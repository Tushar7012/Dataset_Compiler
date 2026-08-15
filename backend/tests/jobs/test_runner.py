import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from tuneforge.generation.specs import GenerationSpec
from tuneforge.jobs.checkpoints import get_latest_checkpoint
from tuneforge.jobs.runner import MAX_ACCEPTED_ROWS, _run_generation_async, run_generation_worker, run_output_path
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import ProviderProfile, RunConsent
from tuneforge.records import SourceRecord
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ModelProfileRecord, ProviderProfileRecord, RunRecord, TrainingPlanRecord
from tuneforge.storage.repositories import ProjectRepository


class _FakeTokenizer:
    def encode(self, text: str) -> list[int]:
        return text.split()


def _provider(handler) -> OpenAICompatibleProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9999")
    profile = ProviderProfile(name="gen", base_url="http://127.0.0.1:9999", model="test-model", endpoint_scope="local")
    return OpenAICompatibleProvider(profile, client)


def _sources(document_id: uuid.UUID, count: int) -> list[SourceRecord]:
    return [
        SourceRecord(
            document_id=document_id,
            chunk_id=f"chunk-{i}",
            text=f"Fact number {i} about the source document.",
            source_name="doc.md",
            source_hash="deadbeef",
            page=None,
            heading=None,
        )
        for i in range(count)
    ]


def _cpt_plan() -> TrainingPlan:
    return TrainingPlan(
        objective="cpt",
        canonical_schema="CPTRecord",
        target_rows=1000,
        examples_per_chunk=1,
        generator_profile_id=None,
        judge_profile_id=None,
        required_validators=["structural", "deduplication"],
        evidence=[],
        confidence=0.9,
        plan_hash="hash1",
    )


@pytest.fixture
def env(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    factory = create_session_factory(engine)
    session = factory()
    artifact_store = ArtifactStore(tmp_path / "data")
    project = ProjectRepository(session, artifact_store).create("proj")

    plan_record = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=project.id, objective="cpt",
        plan_json=json.loads(_cpt_plan().model_dump_json()), plan_hash="hash1",
    )
    provider_record = ProviderProfileRecord(
        id=uuid.uuid4(), project_id=project.id, name="gen", base_url="http://127.0.0.1:9999",
        model="test-model", endpoint_scope="local",
    )
    model_profile_record = ModelProfileRecord(
        id=uuid.uuid4(), project_id=project.id, model_id="gpt2", source="huggingface",
        profile_json={
            "source": "huggingface", "model_id": "gpt2", "architecture": "GPT2LMHeadModel", "model_type": "gpt2",
            "is_causal_lm": True, "is_chat_model": False, "chat_template_found": False, "context_length": 512,
            "modalities": ["text"], "evidence": [], "confidence": 0.9,
        },
        confidence=0.9,
    )
    session.add_all([plan_record, provider_record, model_profile_record])
    session.commit()

    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan_record.id,
        generator_profile_id=provider_record.id, is_preview=False,
    )
    session.add(run)
    session.commit()

    return session, artifact_store, project, run


async def test_cpt_run_processes_every_chunk_with_no_llm_call(env):
    session, artifact_store, project, run = env

    def handler(request):
        raise AssertionError("CPT must not call the provider at all")

    generator = _provider(handler)
    document_id = uuid.uuid4()
    sources = _sources(document_id, 5)

    await _run_generation_async(
        session=session,
        run=run,
        plan=_cpt_plan(),
        sources=sources,
        generator=generator,
        judge=None,
        spec=GenerationSpec(desired_behavior="cpt"),
        tokenizer=_FakeTokenizer(),
        max_tokens=512,
        target_rows=1000,
        resume_from_chunk=0,
        output_path=run_output_path(artifact_store.base_dir, project.id, run.id),
    )

    session.refresh(run)
    assert run.status == "completed"
    assert run.completed_rows == 5

    output_lines = run_output_path(artifact_store.base_dir, project.id, run.id).read_text().strip().splitlines()
    assert len(output_lines) == 5


async def test_run_checkpoints_at_document_boundary_before_hitting_row_interval(env):
    session, artifact_store, project, run = env
    generator = _provider(lambda request: httpx.Response(500))  # never called for CPT
    document_id = uuid.uuid4()
    sources = _sources(document_id, 3)  # fewer than CHECKPOINT_ROW_INTERVAL (100)

    await _run_generation_async(
        session=session, run=run, plan=_cpt_plan(), sources=sources, generator=generator, judge=None,
        spec=GenerationSpec(desired_behavior="cpt"), tokenizer=_FakeTokenizer(), max_tokens=512,
        target_rows=1000, resume_from_chunk=0,
        output_path=run_output_path(artifact_store.base_dir, project.id, run.id),
    )

    checkpoint = get_latest_checkpoint(session, run.id)
    assert checkpoint is not None
    assert checkpoint.sequence == 3
    assert checkpoint.completed_rows == 3


async def test_resume_skips_already_processed_chunks(env):
    session, artifact_store, project, run = env
    generator = _provider(lambda request: httpx.Response(500))
    document_id = uuid.uuid4()
    sources = _sources(document_id, 5)
    output_path = run_output_path(artifact_store.base_dir, project.id, run.id)

    await _run_generation_async(
        session=session, run=run, plan=_cpt_plan(), sources=sources[:2], generator=generator, judge=None,
        spec=GenerationSpec(desired_behavior="cpt"), tokenizer=_FakeTokenizer(), max_tokens=512,
        target_rows=1000, resume_from_chunk=0, output_path=output_path,
    )
    checkpoint = get_latest_checkpoint(session, run.id)

    run.status = "pending"
    session.commit()
    await _run_generation_async(
        session=session, run=run, plan=_cpt_plan(), sources=sources, generator=generator, judge=None,
        spec=GenerationSpec(desired_behavior="cpt"), tokenizer=_FakeTokenizer(), max_tokens=512,
        target_rows=1000, resume_from_chunk=checkpoint.sequence, output_path=output_path,
    )

    session.refresh(run)
    assert run.completed_rows == 5
    output_lines = output_path.read_text().strip().splitlines()
    assert len(output_lines) == 5  # not 7 — resume did not redo the first 2 chunks


async def test_run_stops_at_target_rows(env):
    session, artifact_store, project, run = env
    generator = _provider(lambda request: httpx.Response(500))
    sources = _sources(uuid.uuid4(), 10)

    await _run_generation_async(
        session=session, run=run, plan=_cpt_plan(), sources=sources, generator=generator, judge=None,
        spec=GenerationSpec(desired_behavior="cpt"), tokenizer=_FakeTokenizer(), max_tokens=512,
        target_rows=3, resume_from_chunk=0,
        output_path=run_output_path(artifact_store.base_dir, project.id, run.id),
    )

    session.refresh(run)
    assert run.completed_rows == 3
    assert run.status == "completed"


async def test_cancel_requested_stops_the_run_gracefully(env):
    session, artifact_store, project, run = env
    generator = _provider(lambda request: httpx.Response(500))
    sources = _sources(uuid.uuid4(), 10)
    run.status = "cancel_requested"
    session.commit()

    await _run_generation_async(
        session=session, run=run, plan=_cpt_plan(), sources=sources, generator=generator, judge=None,
        spec=GenerationSpec(desired_behavior="cpt"), tokenizer=_FakeTokenizer(), max_tokens=512,
        target_rows=1000, resume_from_chunk=0,
        output_path=run_output_path(artifact_store.base_dir, project.id, run.id),
    )

    session.refresh(run)
    assert run.status == "cancelled"
    assert run.completed_rows == 0


async def test_run_forwards_consent_to_generate_record(env, monkeypatch):
    session, artifact_store, project, run = env
    granted_at = datetime.now(timezone.utc)
    run.remote_consent_granted_at = granted_at
    session.commit()

    captured = {}

    async def fake_generate_record(*, plan, source, generator, judge, spec, consent=None):
        captured["consent"] = consent
        return None

    monkeypatch.setattr("tuneforge.jobs.runner.generate_record", fake_generate_record)

    await _run_generation_async(
        session=session, run=run, plan=_cpt_plan(), sources=_sources(uuid.uuid4(), 1),
        generator=_provider(lambda request: (_ for _ in ()).throw(AssertionError("not expected"))),
        judge=None, spec=GenerationSpec(desired_behavior="cpt"), tokenizer=_FakeTokenizer(), max_tokens=512,
        target_rows=1000, resume_from_chunk=0,
        output_path=run_output_path(artifact_store.base_dir, project.id, run.id),
        consent=RunConsent(run_id=run.id, granted_at=granted_at),
    )

    assert captured["consent"] is not None
    assert captured["consent"].run_id == run.id
    assert captured["consent"].granted_at.replace(tzinfo=None) == granted_at.replace(tzinfo=None)


def test_worker_builds_consent_from_the_runs_remote_consent_timestamp(env, monkeypatch):
    session, artifact_store, project, run = env
    granted_at = datetime.now(timezone.utc)
    run.remote_consent_granted_at = granted_at
    session.commit()
    db_path = session.get_bind().url.database
    session.close()

    captured = {}

    class _FakeTok:
        tokenizer = object()

    monkeypatch.setattr("tuneforge.ingestion.chunking.build_tokenizer", lambda model_id: _FakeTok())
    monkeypatch.setattr(
        "tuneforge.jobs.runner._load_project_sources", lambda session, artifact_store, project_id, tokenizer: []
    )
    monkeypatch.setattr("tuneforge.jobs.runner._load_provider", lambda session, profile_id: object())

    async def fake_run_generation_async(**kwargs):
        captured["consent"] = kwargs.get("consent")

    monkeypatch.setattr("tuneforge.jobs.runner._run_generation_async", fake_run_generation_async)

    run_generation_worker(db_path=db_path, base_data_dir=str(artifact_store.base_dir), run_id=str(run.id))

    assert captured["consent"] is not None
    assert captured["consent"].run_id == run.id
    assert captured["consent"].granted_at.replace(tzinfo=None) == granted_at.replace(tzinfo=None)


def test_worker_builds_no_consent_when_none_was_granted(env, monkeypatch):
    session, artifact_store, project, run = env
    db_path = session.get_bind().url.database
    session.close()

    captured = {}

    class _FakeTok:
        tokenizer = object()

    monkeypatch.setattr("tuneforge.ingestion.chunking.build_tokenizer", lambda model_id: _FakeTok())
    monkeypatch.setattr(
        "tuneforge.jobs.runner._load_project_sources", lambda session, artifact_store, project_id, tokenizer: []
    )
    monkeypatch.setattr("tuneforge.jobs.runner._load_provider", lambda session, profile_id: object())

    async def fake_run_generation_async(**kwargs):
        captured["consent"] = kwargs.get("consent")

    monkeypatch.setattr("tuneforge.jobs.runner._run_generation_async", fake_run_generation_async)

    run_generation_worker(db_path=db_path, base_data_dir=str(artifact_store.base_dir), run_id=str(run.id))

    assert captured["consent"] is None


def test_worker_marks_run_failed_on_unhandled_exception(env, monkeypatch):
    session, artifact_store, project, run = env
    db_path = session.get_bind().url.database
    session.close()

    class _FakeTok:
        tokenizer = object()

    monkeypatch.setattr("tuneforge.ingestion.chunking.build_tokenizer", lambda model_id: _FakeTok())
    monkeypatch.setattr(
        "tuneforge.jobs.runner._load_project_sources", lambda session, artifact_store, project_id, tokenizer: []
    )
    monkeypatch.setattr("tuneforge.jobs.runner._load_provider", lambda session, profile_id: object())

    async def fake_run_generation_async(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("tuneforge.jobs.runner._run_generation_async", fake_run_generation_async)

    with pytest.raises(RuntimeError):
        run_generation_worker(db_path=db_path, base_data_dir=str(artifact_store.base_dir), run_id=str(run.id))

    check_session = create_session_factory(create_sqlite_engine(Path(db_path)))()
    stored = check_session.get(RunRecord, run.id)
    assert stored.status == "failed"


def test_worker_process_can_be_spawned_and_joins_cleanly(tmp_path):
    # Proves the process-spawning plumbing (module-level target, spawn
    # context, picklable arguments) actually works on this platform —
    # not a full generation run, just the process boundary itself.
    import multiprocessing

    from tuneforge.jobs.runner import _spawn_probe

    ctx = multiprocessing.get_context("spawn")
    marker_path = tmp_path / "marker.txt"
    process = ctx.Process(target=_spawn_probe, args=(str(marker_path),))
    process.start()
    process.join(timeout=15)

    assert process.exitcode == 0
    assert marker_path.read_text() == "ok"


def test_load_project_sources_chunks_every_document_source_in_order(tmp_path):
    from tuneforge.ingestion.chunking import build_tokenizer
    from tuneforge.jobs.runner import _load_project_sources
    from tuneforge.storage.artifacts import ArtifactStore
    from tuneforge.storage.db import create_session_factory, create_sqlite_engine
    from tuneforge.storage.repositories import ProjectRepository, SourceRepository

    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    session = create_session_factory(engine)()
    artifact_store = ArtifactStore(tmp_path / "data")
    project = ProjectRepository(session, artifact_store).create("proj")

    doc_a = tmp_path / "a.md"
    doc_a.write_text("# Doc A\n\nFirst document content.\n")
    doc_b = tmp_path / "b.md"
    doc_b.write_text("# Doc B\n\nSecond document content.\n")
    source_repo = SourceRepository(session, artifact_store)
    source_repo.add_source(project.id, doc_a)
    source_repo.add_source(project.id, doc_b)

    tokenizer = build_tokenizer("gpt2", max_tokens=64)
    sources = _load_project_sources(session, artifact_store, project.id, tokenizer)

    assert len(sources) == 2
    texts = {s.text for s in sources}
    assert any("First document content" in t for t in texts)
    assert any("Second document content" in t for t in texts)

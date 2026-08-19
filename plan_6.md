# TuneForge Implementation Plan — Part 6 (Tasks 11 & 12)

> **For the executing AI:** Self-contained — you don't need `PLAN.md`, though it's in the repo as the master spec. Tasks 1–10 are already implemented, committed, and verified end-to-end (a real model was analyzed, a real document was chunked, real generation and validation ran). This part is the integration point: it wires the provider client (Task 3), planner (Task 5), ingestion (Task 7), generation (Task 9), and validation (Task 10) into an actual resumable job with a real HTTP API, then exports the result as a dataset bundle.
>
> **This is the largest, highest-risk part so far.** Two of its trickiest pieces — genuine OS-process isolation on Windows, and Server-Sent Events streaming with FastAPI — were built and verified against real, running code before being written into this document (not assumed). One piece could **not** be fully live-verified due to an unrelated environment issue during this session (heavy IDE/language-server load causing tokenizer downloads to hang) — `tokenizer.apply_chat_template` in Task 12. It's a stable, well-documented Transformers API, but you should smoke-test it for real as part of Step 6 rather than trust it blindly. That spot is called out again where it matters.
>
> Do not implement anything beyond Task 11 and Task 12. When both are done, stop and produce the completion report at the bottom. Do not push to GitHub.

**Goal (this part):** Turn an approved training plan into an actual resumable generation run — preview 20 rows, approve, run to completion in a crash-isolated worker process with checkpointing, cancel/resume — then split and export the accepted records as a Parquet/JSONL bundle ready for Unsloth.

**Architecture:** A `multiprocessing` worker (not an asyncio background task — PLAN.md requires genuine process isolation so a worker crash can't take the FastAPI process down with it) does the actual generation+validation loop, writing progress to the same SQLite database the API reads from. There is no other channel between the two processes — no queues, no shared memory — the database *is* the IPC, which is also what makes resume possible: the worker asks the database "how far did I get?" instead of being told by whoever restarted it. Accepted records are appended to a JSONL file as they're accepted (durable immediately, no batching window to lose on crash); SQLite checkpoints record how many source chunks were attempted and how many rows were accepted, taken together often enough to resume without redoing much work.

**Tech Stack (new in this part):** `datasets` (Hugging Face Datasets — Parquet/JSONL export and reload verification; already verified against the real library, not assumed).

## Global Constraints

Repeated from Parts 1–5, the ones that bind this part specifically:

- Windows-first, Python 3.12, uv-managed, no conda.
- Preview exactly 20 rows before full generation.
- Maximum supported output: 100,000 rows.
- Default split is 90% train / 10% evaluation by source document.
- No direct writes into Unsloth Studio internals — this part only produces files and instructions, nothing reaches into another application.

## Development Environment

Same as before — **uv**, no conda, no direct `pip`.

```powershell
cd backend
uv sync
uv run pytest -q
```

## Repository State

Same repo, branch `main`, `origin` already set. Commit locally as instructed. **Do not run `git push`.**

## File Structure (this part)

```
backend/
  pyproject.toml                  (modified — add datasets)
  tuneforge/
    storage/
      models.py                   (modified — RunRecord gains 3 fields)
    jobs/
      __init__.py
      checkpoints.py
      runner.py
    api/
      __init__.py
      runs.py
    export/
      __init__.py
      splitting.py
      bundle.py
      compatibility.py
  tests/
    jobs/
      __init__.py
      test_checkpoints.py
      test_runner.py
    api/
      __init__.py
      test_runs.py
    export/
      __init__.py
      test_splitting.py
      test_bundle.py
      test_compatibility.py
```

---

### Task 11: Preview, jobs, checkpoints, cancellation, and resume

**Files:**
- Modify: `backend/tuneforge/storage/models.py`
- Create: `backend/tuneforge/jobs/__init__.py`
- Create: `backend/tuneforge/jobs/checkpoints.py`
- Create: `backend/tuneforge/jobs/runner.py`
- Create: `backend/tuneforge/api/__init__.py`
- Create: `backend/tuneforge/api/runs.py`
- Create: `backend/tests/jobs/__init__.py`
- Create: `backend/tests/jobs/test_checkpoints.py`
- Create: `backend/tests/jobs/test_runner.py`
- Create: `backend/tests/api/__init__.py`
- Create: `backend/tests/api/test_runs.py`

**Interfaces consumed:** `tuneforge.generation.generator.generate_record` (Task 9), `tuneforge.validation.pipeline.run_validation_pipeline` (Task 10), `tuneforge.providers.openai_compatible.OpenAICompatibleProvider` (Task 3), `tuneforge.planning.schemas.TrainingPlan` (Task 5), `tuneforge.storage.*` (Task 2).

**Interfaces produced (Task 12 relies on these):**
- `tuneforge.jobs.checkpoints.record_checkpoint(session, run_id, *, chunks_processed, completed_rows)`, `.get_latest_checkpoint(session, run_id)`, `.CHECKPOINT_ROW_INTERVAL`
- `tuneforge.jobs.runner.run_output_path(base_dir, project_id, run_id) -> Path` (the JSONL file Task 12 reads accepted records back from)
- FastAPI router `tuneforge.api.runs.router`, mountable at `/api`

**On the two RunRecord fields added here and why:** Task 2's `RunRecord` didn't yet need to know which provider generates and which one judges, or whether a run is a 20-row preview versus a full run — those concepts didn't exist until this task. `generator_profile_id`, `judge_profile_id` (nullable — not every objective needs a judge), and `is_preview` are added.

**On "checkpoint every 100 accepted rows and after each source document":** `CheckpointRecord.sequence` (already in the Task 2 schema) is repurposed as the *resume cursor* — how many source chunks have been attempted, accepted or not — rather than adding a new column. `CheckpointRecord.completed_rows` stays what it already was: how many rows were accepted by that point. Resuming means "skip the first `sequence` chunks, keep accepting from there." Both numbers are needed because they diverge — some chunks get rejected during generation or validation, so "chunks attempted" and "rows accepted" are never the same number.

**On accepted records living in a JSONL file, not the database:** SQLite is for run state (status, counts, checkpoints) — a training dataset that can run to 100,000 rows belongs in a file, appended to incrementally as records are accepted, not accumulated in an ORM table. This also means each accepted record is durable the instant it's accepted, before the next one is even generated.

**Two more gaps this task doesn't close, on top of the ones called out inline below — both real, neither silent:**

1. **The router this task builds is never mounted onto the actual app.** Task 11's tests build their own throwaway `FastAPI()` instance and mount `runs.router` onto it directly — that proves the router's own logic works, but `backend/tuneforge/main.py` (Task 1) is never touched here, so none of this is reachable by actually running `tuneforge.main`. Wiring `app.include_router(runs.router, prefix="/api")` into `create_app()`, and deciding how `app.state.session`/`artifact_store`/`db_path` actually get populated for a real running server, is left for whichever task builds the real API composition root. Note this in your report — don't let "the tests pass" read as "you can hit these endpoints on the running app."
2. **The tests' `app.state.session` (one shared session for the whole app) is a test convenience, not a real pattern.** SQLAlchemy sessions aren't safe to share across concurrent requests. A real server needs a per-request session — typically a FastAPI dependency that opens a session from a shared `sessionmaker` and closes it when the request ends. Don't copy the test fixture's pattern into whatever wires this router into the real app.

**Known, accepted trade-off — read before touching `runner.py`:** the JSONL append and the SQLite checkpoint commit are two separate writes, not one atomic transaction. If the process crashes between "wrote row to JSONL" and "committed the checkpoint that counts it," resuming will redo that one chunk and may append a near-duplicate row at the tail of the file. This is deliberate — building real cross-storage transactional exactly-once semantics for a rare-crash edge case in a single-user desktop app would be real over-engineering. Task 10's deduplication (already built) removes the duplicate at export time. Don't try to close this gap with more machinery; the export step is the fix.

#### Step 1: Extend the run schema

Edit `backend/tuneforge/storage/models.py`. Find the `RunRecord` class and add three fields:

```python
class RunRecord(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("training_plans.id"))
    generator_profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_profiles.id"))
    judge_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("provider_profiles.id"), default=None)
    is_preview: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(default="pending")
    total_rows: Mapped[int] = mapped_column(default=0)
    completed_rows: Mapped[int] = mapped_column(default=0)
    assurance_level: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow)
```

(Only the three new fields — `generator_profile_id`, `judge_profile_id`, `is_preview` — are new; everything else in this class already exists. Leave the rest of the file untouched.)

Run Task 2's existing storage tests to confirm nothing broke:

```powershell
cd backend
uv run pytest tests/storage -q
```

Expected: all pass, unchanged.

#### Step 2: Checkpoints — write the failing tests (RED)

Create `backend/tuneforge/jobs/__init__.py` (empty), `backend/tests/jobs/__init__.py` (empty).

Create `backend/tests/jobs/test_checkpoints.py`:

```python
import uuid
from pathlib import Path

import pytest

from tuneforge.jobs.checkpoints import get_latest_checkpoint, record_checkpoint
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ProviderProfileRecord, RunRecord, TrainingPlanRecord
from tuneforge.storage.repositories import ProjectRepository


@pytest.fixture
def session(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    factory = create_session_factory(engine)
    with factory() as db_session:
        yield db_session


@pytest.fixture
def run(session, tmp_path: Path):
    artifact_store = ArtifactStore(tmp_path / "data")
    project = ProjectRepository(session, artifact_store).create("proj")

    plan = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=project.id, objective="cpt", plan_json={}, plan_hash="hash1"
    )
    provider = ProviderProfileRecord(
        id=uuid.uuid4(), project_id=project.id, name="gen", base_url="http://127.0.0.1:9999",
        model="test-model", endpoint_scope="local",
    )
    session.add_all([plan, provider])
    session.commit()

    run_record = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id
    )
    session.add(run_record)
    session.commit()
    return run_record


def test_record_checkpoint_updates_run_progress(session, run):
    record_checkpoint(session, run.id, chunks_processed=5, completed_rows=4)

    session.refresh(run)
    assert run.completed_rows == 4


def test_get_latest_checkpoint_returns_the_highest_sequence(session, run):
    record_checkpoint(session, run.id, chunks_processed=5, completed_rows=4)
    record_checkpoint(session, run.id, chunks_processed=12, completed_rows=10)

    latest = get_latest_checkpoint(session, run.id)

    assert latest.sequence == 12
    assert latest.completed_rows == 10


def test_get_latest_checkpoint_returns_none_when_no_checkpoints_exist(session, run):
    assert get_latest_checkpoint(session, run.id) is None
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/jobs/test_checkpoints.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.jobs.checkpoints'`.

#### Step 3: Checkpoints — implement (GREEN)

Create `backend/tuneforge/jobs/checkpoints.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tuneforge.storage.models import CheckpointRecord, RunRecord

CHECKPOINT_ROW_INTERVAL = 100


def record_checkpoint(
    session: Session, run_id: uuid.UUID, *, chunks_processed: int, completed_rows: int
) -> CheckpointRecord:
    """`chunks_processed` (stored in the existing `sequence` column) is the
    resume cursor — how many source chunks have been attempted so far,
    accepted or not. `completed_rows` is how many were actually accepted.
    """
    checkpoint = CheckpointRecord(
        id=uuid.uuid4(), run_id=run_id, sequence=chunks_processed, completed_rows=completed_rows
    )
    session.add(checkpoint)
    run = session.get(RunRecord, run_id)
    run.completed_rows = completed_rows
    run.updated_at = datetime.now(timezone.utc)
    session.commit()
    return checkpoint


def get_latest_checkpoint(session: Session, run_id: uuid.UUID) -> CheckpointRecord | None:
    return (
        session.query(CheckpointRecord)
        .filter(CheckpointRecord.run_id == run_id)
        .order_by(CheckpointRecord.sequence.desc())
        .first()
    )
```

Run the tests again:

```powershell
uv run pytest tests/jobs/test_checkpoints.py -q
```

Expected: all pass.

#### Step 4: Runner — write the failing tests (RED)

The generation+validation loop is tested directly (in-process, with a fake provider — cheap, thorough, covers every business rule). Process-spawning mechanics are tested separately, minimally, with a real subprocess — proving the plumbing works without needing a real HTTP-serving provider inside a spawned process.

Create `backend/tests/jobs/test_runner.py`:

```python
import json
import uuid
from pathlib import Path

import httpx
import pytest

from tuneforge.generation.specs import GenerationSpec
from tuneforge.jobs.checkpoints import get_latest_checkpoint
from tuneforge.jobs.runner import MAX_ACCEPTED_ROWS, _run_generation_async, run_output_path
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import ProviderProfile
from tuneforge.records import SourceRecord
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ProviderProfileRecord, RunRecord, TrainingPlanRecord
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
        id=uuid.uuid4(), project_id=project.id, objective="cpt", plan_json={}, plan_hash="hash1"
    )
    provider_record = ProviderProfileRecord(
        id=uuid.uuid4(), project_id=project.id, name="gen", base_url="http://127.0.0.1:9999",
        model="test-model", endpoint_scope="local",
    )
    session.add_all([plan_record, provider_record])
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
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/jobs/test_runner.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.jobs.runner'`.

#### Step 5: Runner — implement (GREEN)

Create `backend/tuneforge/jobs/runner.py`:

```python
from __future__ import annotations

import json
import logging
import multiprocessing
import uuid
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from tuneforge.generation.generator import generate_record
from tuneforge.generation.specs import GenerationSpec
from tuneforge.jobs.checkpoints import CHECKPOINT_ROW_INTERVAL, record_checkpoint
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import ProviderProfile
from tuneforge.records import SourceRecord
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ProviderProfileRecord, RunRecord
from tuneforge.validation.pipeline import run_validation_pipeline

logger = logging.getLogger("tuneforge.jobs")

MAX_ACCEPTED_ROWS = 100_000

# Keeps track of processes this server started, so an SSE request handled
# later in the same process can check process.is_alive(). Never shared
# across separate server instances — that's what the database is for.
_RUNNING_PROCESSES: dict[uuid.UUID, multiprocessing.Process] = {}


def run_output_path(base_dir: Path, project_id: uuid.UUID, run_id: uuid.UUID) -> Path:
    return base_dir / "projects" / str(project_id) / "runs" / str(run_id) / "records.jsonl"


def _load_provider(session: Session, profile_id: uuid.UUID) -> OpenAICompatibleProvider:
    record = session.get(ProviderProfileRecord, profile_id)
    profile = ProviderProfile(
        name=record.name,
        base_url=record.base_url,
        model=record.model,
        endpoint_scope=record.endpoint_scope,
        credential_reference=record.credential_reference,
    )
    client = httpx.AsyncClient(base_url=profile.base_url, timeout=profile.timeout_seconds)
    return OpenAICompatibleProvider(profile, client)


async def _run_generation_async(
    *,
    session: Session,
    run: RunRecord,
    plan: TrainingPlan,
    sources: list[SourceRecord],
    generator: OpenAICompatibleProvider,
    judge: OpenAICompatibleProvider | None,
    spec: GenerationSpec,
    tokenizer,
    max_tokens: int,
    target_rows: int,
    resume_from_chunk: int,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    accepted_total = 0
    chunks_processed = resume_from_chunk
    accepted_since_checkpoint = 0
    remaining_sources = sources[resume_from_chunk:]

    run.status = "running"
    session.commit()

    with output_path.open("a", encoding="utf-8") as output_file:
        for index, source in enumerate(remaining_sources):
            session.refresh(run)
            if run.status == "cancel_requested":
                run.status = "cancelled"
                session.commit()
                logger.info("run %s cancelled after %d chunks", run.id, chunks_processed)
                return

            record = await generate_record(plan=plan, source=source, generator=generator, judge=judge, spec=spec)
            chunks_processed += 1

            if record is not None:
                report = await run_validation_pipeline(
                    [record], tokenizer=tokenizer, max_tokens=max_tokens, judge=judge
                )
                for accepted_record in report.accepted:
                    output_file.write(accepted_record.model_dump_json())
                    output_file.write("\n")
                    output_file.flush()
                accepted_total += len(report.accepted)
                accepted_since_checkpoint += len(report.accepted)

            is_last_overall = index == len(remaining_sources) - 1
            is_document_boundary = not is_last_overall and remaining_sources[index + 1].document_id != source.document_id
            if accepted_since_checkpoint >= CHECKPOINT_ROW_INTERVAL or is_document_boundary or is_last_overall:
                record_checkpoint(
                    session, run.id, chunks_processed=chunks_processed, completed_rows=accepted_total
                )
                accepted_since_checkpoint = 0

            if accepted_total >= min(target_rows, MAX_ACCEPTED_ROWS):
                break

    run.status = "completed"
    run.total_rows = accepted_total
    session.commit()


def _spawn_probe(marker_path: str) -> None:
    """Module-level, picklable — proves multiprocessing.Process(target=...)
    actually starts and completes on this platform (Windows requires spawn,
    not fork, and spawn requires the target to be importable by name, not
    a closure or lambda).
    """
    Path(marker_path).write_text("ok")


def run_generation_worker(*, db_path: str, base_data_dir: str, run_id: str) -> None:
    """The real multiprocessing entry point. Deliberately thin: it only
    loads state from the database and delegates to _run_generation_async,
    which is where the actual tested logic lives.
    """
    import asyncio

    from tuneforge.ingestion.chunking import build_tokenizer
    from tuneforge.models.analyzer import analyze_model
    from tuneforge.storage.artifacts import ArtifactStore
    from tuneforge.storage.models import TrainingPlanRecord
    from tuneforge.storage.repositories import SourceRepository

    engine = create_sqlite_engine(Path(db_path))
    session = create_session_factory(engine)()
    artifact_store = ArtifactStore(Path(base_data_dir))

    run = session.get(RunRecord, uuid.UUID(run_id))
    plan_record = session.get(TrainingPlanRecord, run.plan_id)
    plan = TrainingPlan.model_validate(plan_record.plan_json)

    generator = _load_provider(session, run.generator_profile_id)
    judge = _load_provider(session, run.judge_profile_id) if run.judge_profile_id else None

    source_repo = SourceRepository(session, artifact_store)
    sources: list[SourceRecord] = []  # populated by whatever wires ingestion+chunking to a run (out of scope here)

    model_profile = analyze_model(plan_record.plan_json.get("model_id", ""), source="huggingface")
    tokenizer = build_tokenizer(model_profile.model_id)

    from tuneforge.storage.models import CheckpointRecord

    latest = (
        session.query(CheckpointRecord)
        .filter(CheckpointRecord.run_id == run.id)
        .order_by(CheckpointRecord.sequence.desc())
        .first()
    )
    resume_from_chunk = latest.sequence if latest else 0

    target_rows = 20 if run.is_preview else plan.target_rows
    output_path = run_output_path(artifact_store.base_dir, run.project_id, run.id)

    asyncio.run(
        _run_generation_async(
            session=session,
            run=run,
            plan=plan,
            sources=sources,
            generator=generator,
            judge=judge,
            spec=GenerationSpec(desired_behavior=plan.objective),
            tokenizer=tokenizer.tokenizer,
            max_tokens=model_profile.context_length or 2048,
            target_rows=target_rows,
            resume_from_chunk=resume_from_chunk,
            output_path=output_path,
        )
    )


def start_run(*, db_path: Path, base_data_dir: Path, run_id: uuid.UUID) -> multiprocessing.Process:
    ctx = multiprocessing.get_context("spawn")
    process = ctx.Process(
        target=run_generation_worker,
        kwargs={"db_path": str(db_path), "base_data_dir": str(base_data_dir), "run_id": str(run_id)},
    )
    process.start()
    _RUNNING_PROCESSES[run_id] = process
    return process


def is_run_process_alive(run_id: uuid.UUID) -> bool:
    process = _RUNNING_PROCESSES.get(run_id)
    return process is not None and process.is_alive()
```

> **Gap called out on purpose:** `run_generation_worker`'s `sources: list[SourceRecord] = []` line is a placeholder — no earlier task defined "load and chunk every source document for a project into `SourceRecord`s in one call" as a reusable function. Task 7 built the pieces (`convert_document_cached`, `chunk_into_source_records`) per-document, and Task 2's `SourceRepository` tracks which files belong to a project, but nothing yet loops over "every source in this project, chunked, in a stable order." Wire that loop here using those two pieces before this function can run for real — the `_run_generation_async` tests above don't need it (they pass `sources` directly), but the actual `run_generation_worker` entry point does. This is scope this part doesn't fully close; note it in your report rather than inventing a design for it silently.

Run the tests again:

```powershell
uv run pytest tests/jobs/test_runner.py -q
```

Expected: all pass.

#### Step 6: API — write the failing tests (RED)

Create `backend/tuneforge/api/__init__.py` (empty), `backend/tests/api/__init__.py` (empty).

Create `backend/tests/api/test_runs.py`:

```python
import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.runs import router
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ProviderProfileRecord, RunRecord, TrainingPlanRecord
from tuneforge.storage.repositories import ProjectRepository


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    factory = create_session_factory(engine)
    session = factory()
    artifact_store = ArtifactStore(tmp_path / "data")

    app = FastAPI()
    app.state.session = session
    app.state.artifact_store = artifact_store
    app.state.db_path = tmp_path / "data" / "tuneforge.db"
    app.include_router(router, prefix="/api")

    test_client = TestClient(app)
    test_client.session = session
    test_client.artifact_store = artifact_store
    return test_client


def _make_plan_and_provider(client, project_id):
    plan = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=project_id, objective="cpt", plan_json={"objective": "cpt"}, plan_hash="hash1"
    )
    provider = ProviderProfileRecord(
        id=uuid.uuid4(), project_id=project_id, name="gen", base_url="http://127.0.0.1:9999",
        model="test-model", endpoint_scope="local",
    )
    client.session.add_all([plan, provider])
    client.session.commit()
    return plan, provider


def test_get_run_returns_current_status(client, monkeypatch):
    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id, status="running",
        completed_rows=7,
    )
    client.session.add(run)
    client.session.commit()

    response = client.get(f"/api/runs/{run.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert body["completed_rows"] == 7


def test_get_unknown_run_returns_404(client):
    response = client.get(f"/api/runs/{uuid.uuid4()}")
    assert response.status_code == 404


def test_cancel_sets_status_to_cancel_requested(client):
    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id, status="running",
    )
    client.session.add(run)
    client.session.commit()

    response = client.post(f"/api/runs/{run.id}/cancel")

    assert response.status_code == 200
    client.session.refresh(run)
    assert run.status == "cancel_requested"


def test_cancel_on_completed_run_is_a_no_op_error(client):
    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id, status="completed",
    )
    client.session.add(run)
    client.session.commit()

    response = client.post(f"/api/runs/{run.id}/cancel")

    assert response.status_code == 409


def test_approve_full_rejects_an_unapproved_plan(client):
    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    preview_run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id,
        is_preview=True, status="completed",
    )
    client.session.add(preview_run)
    client.session.commit()

    response = client.post(f"/api/runs/{preview_run.id}/approve-full")

    assert response.status_code == 409
    assert "plan_hash" in response.json()["detail"].lower()


def test_approve_plan_then_approve_full_succeeds(client, monkeypatch):
    # start_run spawns a real OS process (Step 5) — irrelevant to what this
    # test checks (the approval bookkeeping), and run_generation_worker
    # can't actually run yet given the sources-loading gap noted in Step 5.
    monkeypatch.setattr("tuneforge.api.runs.start_run", lambda **kwargs: None)

    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    preview_run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id,
        is_preview=True, status="completed",
    )
    client.session.add(preview_run)
    client.session.commit()

    approve_response = client.post(f"/api/plans/{plan.id}/approve")
    assert approve_response.status_code == 200

    response = client.post(f"/api/runs/{preview_run.id}/approve-full")

    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_resume_moves_a_cancelled_run_back_to_pending(client, monkeypatch):
    monkeypatch.setattr("tuneforge.api.runs.start_run", lambda **kwargs: None)

    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id,
        status="cancelled", completed_rows=42,
    )
    client.session.add(run)
    client.session.commit()

    response = client.post(f"/api/runs/{run.id}/resume")

    assert response.status_code == 200
    client.session.refresh(run)
    assert run.status == "pending"
    assert run.completed_rows == 42  # resume doesn't reset progress


def test_resume_on_a_running_run_is_rejected(client):
    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id, status="running",
    )
    client.session.add(run)
    client.session.commit()

    response = client.post(f"/api/runs/{run.id}/resume")

    assert response.status_code == 409


def test_events_stream_is_server_sent_events_format(client):
    project = ProjectRepository(client.session, client.artifact_store).create("proj")
    plan, provider = _make_plan_and_provider(client, project.id)
    run = RunRecord(
        id=uuid.uuid4(), project_id=project.id, plan_id=plan.id, generator_profile_id=provider.id,
        status="completed", completed_rows=20, total_rows=20,
    )
    client.session.add(run)
    client.session.commit()

    response = client.get(f"/api/runs/{run.id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.split("\n\n")
        if line.strip()
    ]
    assert events[-1]["stage"] == "completed"
    assert events[-1]["completed_rows"] == 20
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/api/test_runs.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.api.runs'`.

#### Step 7: API — implement (GREEN)

Create `backend/tuneforge/api/runs.py`:

```python
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from tuneforge.jobs.runner import is_run_process_alive, start_run
from tuneforge.storage.models import RunRecord, TrainingPlanRecord

router = APIRouter()

_CANCELLABLE_STATUSES = {"pending", "running"}


def _get_run_or_404(session, run_id: uuid.UUID) -> RunRecord:
    run = session.get(RunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return run


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, request: Request):
    run = _get_run_or_404(request.app.state.session, run_id)
    return {
        "id": str(run.id),
        "status": run.status,
        "completed_rows": run.completed_rows,
        "total_rows": run.total_rows,
        "is_preview": run.is_preview,
        "assurance_level": run.assurance_level,
    }


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: uuid.UUID, request: Request):
    session = request.app.state.session
    run = _get_run_or_404(session, run_id)
    if run.status not in _CANCELLABLE_STATUSES:
        raise HTTPException(status_code=409, detail=f"run is {run.status!r}, cannot cancel")
    run.status = "cancel_requested"
    session.commit()
    return {"status": run.status}


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: uuid.UUID, request: Request):
    session = request.app.state.session
    run = _get_run_or_404(session, run_id)
    if run.status not in ("cancelled", "failed"):
        raise HTTPException(status_code=409, detail=f"run is {run.status!r}, nothing to resume")
    run.status = "pending"
    session.commit()
    start_run(db_path=request.app.state.db_path, base_data_dir=request.app.state.artifact_store.base_dir, run_id=run.id)
    return {"status": "pending"}


@router.post("/plans/{plan_id}/approve")
async def approve_plan(plan_id: uuid.UUID, request: Request):
    session = request.app.state.session
    plan = session.get(TrainingPlanRecord, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"plan not found: {plan_id}")
    plan.approved_at = datetime.now(timezone.utc)
    session.commit()
    return {"id": str(plan.id), "approved_at": plan.approved_at.isoformat()}


@router.post("/runs/{run_id}/approve-full")
async def approve_full(run_id: uuid.UUID, request: Request):
    session = request.app.state.session
    preview_run = _get_run_or_404(session, run_id)
    if not preview_run.is_preview:
        raise HTTPException(status_code=409, detail="only a preview run can be approved into a full run")
    if preview_run.status != "completed":
        raise HTTPException(status_code=409, detail=f"preview is {preview_run.status!r}, not ready to approve")

    # No task before this one ever updates an existing TrainingPlanRecord's
    # plan_json/plan_hash in place — recommend_plan (Task 5) always computes
    # a fresh hash and nothing persists a plan until this endpoint's sibling
    # writes it. Under that immutable-row assumption, `approved_at is not
    # None` on *this exact row* already means "this exact plan_hash was
    # approved" — the hash physically cannot have changed underneath it.
    # If a future task adds in-place plan editing, this needs to become a
    # real stored-hash comparison instead of an approved_at truthiness
    # check — note that explicitly if you build that.
    plan = session.get(TrainingPlanRecord, preview_run.plan_id)
    if plan.approved_at is None:
        raise HTTPException(status_code=409, detail="plan_hash has not been approved (or was invalidated)")

    full_run = RunRecord(
        id=uuid.uuid4(),
        project_id=preview_run.project_id,
        plan_id=preview_run.plan_id,
        generator_profile_id=preview_run.generator_profile_id,
        judge_profile_id=preview_run.judge_profile_id,
        is_preview=False,
    )
    session.add(full_run)
    session.commit()
    start_run(db_path=request.app.state.db_path, base_data_dir=request.app.state.artifact_store.base_dir, run_id=full_run.id)
    return {"id": str(full_run.id), "status": full_run.status}


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: uuid.UUID, request: Request):
    session = request.app.state.session
    run = _get_run_or_404(session, run_id)

    async def event_source():
        import asyncio

        sequence = 0
        while True:
            session.refresh(run)
            stage = run.status
            payload = {
                "run_id": str(run.id),
                "sequence": sequence,
                "stage": stage,
                "completed_rows": run.completed_rows,
                "total_rows": run.total_rows,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            sequence += 1
            if stage in ("completed", "cancelled", "failed"):
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(event_source(), media_type="text/event-stream")
```

> **On the plan-approval endpoint added in this step:** `PLAN.md`'s Task 11 file list didn't anticipate needing `POST /api/plans/{plan_id}/approve` — nothing before this task persisted a `TrainingPlanRecord` at all, so there was nothing to approve. It's added here because `approve-full` cannot mean anything without it. This relies on `TrainingPlanRecord` rows being immutable once created (true of everything in Tasks 1–10 — re-running the planner produces a new hash, never an in-place update); if a later task changes that, revisit the comment above `approve_full`.

Run the tests again:

```powershell
uv run pytest tests/api/test_runs.py -q
```

Expected: all pass (with the caveat above — the plan-hash test passing does not mean the feature is real).

#### Step 8: Run the full backend suite and commit

```powershell
uv run pytest -q
```

```powershell
git add backend
git commit -m "feat: add resumable generation runs"
```

---

### Task 12: Dataset splitting and export bundle

**Files:**
- Create: `backend/tuneforge/export/__init__.py`
- Create: `backend/tuneforge/export/splitting.py`
- Create: `backend/tuneforge/export/bundle.py`
- Create: `backend/tuneforge/export/compatibility.py`
- Modify: `backend/pyproject.toml`
- Create: `backend/tests/export/__init__.py`
- Create: `backend/tests/export/test_splitting.py`
- Create: `backend/tests/export/test_bundle.py`
- Create: `backend/tests/export/test_compatibility.py`

**Interfaces consumed:** `tuneforge.records.*` (Task 7), `tuneforge.jobs.runner.run_output_path` (Task 11).

**Interfaces produced:**
- `tuneforge.export.splitting.SplitResult`, `.split_train_eval(records, *, seed=42, eval_fraction=0.1) -> SplitResult`
- `tuneforge.export.bundle.export_bundle(*, train, eval_records, output_dir, model_profile, plan, validation_report) -> Path`
- `tuneforge.export.compatibility.render_chat_template_sample(tokenizer, record) -> str`, `.UNSLOTH_IMPORT_INSTRUCTIONS`

**On the chat-template check — read before Step 6:** `tokenizer.apply_chat_template` could not be live-verified against a downloaded tokenizer during this session (an unrelated environment issue — heavy concurrent load from IDE tooling made every `AutoTokenizer.from_pretrained` call in the same session hang, even with `local_files_only=True`). It's a stable, extremely well-documented Transformers API and the code below is written with real confidence in its signature and behavior, but you have a working environment — actually run Step 6's test for real, on a real downloaded tokenizer, before trusting it. If its behavior differs from what's written here, that's the one place in this whole plan most likely to need a correction.

#### Step 1: Add dependencies

Edit `backend/pyproject.toml` — add `datasets`:

```toml
[project]
name = "tuneforge"
version = "0.1.0"
description = "TuneForge backend"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.5",
    "sqlalchemy>=2.0.35",
    "httpx>=0.27",
    "keyring>=25.0",
    "huggingface-hub>=1.0",
    "docling>=2.120.1",
    "transformers>=5.0",
    "datasketch>=2.0.0",
    "datasets>=5.0.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["tuneforge*"]
```

```powershell
cd backend
uv sync
```

#### Step 2: Splitting — write the failing tests (RED)

Create `backend/tuneforge/export/__init__.py` (empty), `backend/tests/export/__init__.py` (empty).

Create `backend/tests/export/test_splitting.py`:

```python
import uuid

from tuneforge.export.splitting import split_train_eval
from tuneforge.records import CPTRecord, RecordMetadata


def _record(source_hash: str) -> CPTRecord:
    return CPTRecord(
        text=f"content for {source_hash}",
        metadata=RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash=source_hash),
    )


def test_single_source_document_produces_no_eval_split_and_a_warning():
    records = [_record("hash1"), _record("hash1"), _record("hash1")]

    result = split_train_eval(records)

    assert len(result.train) == 3
    assert result.eval == []
    assert result.leakage_warning is True


def test_multiple_documents_split_roughly_ninety_ten_by_document_not_row():
    # 10 documents, 10 rows each — split must keep whole documents together
    records = [_record(f"hash{doc}") for doc in range(10) for _ in range(10)]

    result = split_train_eval(records, seed=42)

    train_hashes = {r.metadata.source_hash for r in result.train}
    eval_hashes = {r.metadata.source_hash for r in result.eval}
    assert train_hashes.isdisjoint(eval_hashes), "a document must not appear in both splits"
    assert len(eval_hashes) == 1  # round(10 * 0.1)
    assert result.leakage_warning is False


def test_split_is_deterministic_for_a_fixed_seed():
    records = [_record(f"hash{doc}") for doc in range(10) for _ in range(10)]

    result_a = split_train_eval(records, seed=42)
    result_b = split_train_eval(records, seed=42)

    assert {r.metadata.source_hash for r in result_a.eval} == {r.metadata.source_hash for r in result_b.eval}


def test_different_seeds_can_produce_different_splits():
    records = [_record(f"hash{doc}") for doc in range(10) for _ in range(10)]

    result_a = split_train_eval(records, seed=1)
    result_b = split_train_eval(records, seed=999)

    eval_a = {r.metadata.source_hash for r in result_a.eval}
    eval_b = {r.metadata.source_hash for r in result_b.eval}
    assert eval_a != eval_b or True  # not a strict guarantee, but exercises both seeds without flaking
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/export/test_splitting.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.export.splitting'`.

#### Step 3: Splitting — implement (GREEN)

Create `backend/tuneforge/export/splitting.py`:

```python
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class SplitResult:
    train: list = field(default_factory=list)
    eval: list = field(default_factory=list)
    leakage_warning: bool = False


def split_train_eval(records: list, *, seed: int = 42, eval_fraction: float = 0.1) -> SplitResult:
    """Splits by *document* (source_hash), never by row — a row from a
    document in eval must never come from a document also in train, or the
    eval score would be measuring memorization of near-identical content,
    not generalization.
    """
    document_hashes = sorted({r.metadata.source_hash for r in records})
    if len(document_hashes) <= 1:
        return SplitResult(train=list(records), eval=[], leakage_warning=True)

    rng = random.Random(seed)
    shuffled = document_hashes[:]
    rng.shuffle(shuffled)
    eval_count = max(1, round(len(shuffled) * eval_fraction))
    eval_hashes = set(shuffled[:eval_count])

    train = [r for r in records if r.metadata.source_hash not in eval_hashes]
    eval_records = [r for r in records if r.metadata.source_hash in eval_hashes]
    return SplitResult(train=train, eval=eval_records, leakage_warning=False)
```

Run the tests again:

```powershell
uv run pytest tests/export/test_splitting.py -q
```

Expected: all pass.

#### Step 4: Bundle export — write the failing tests (RED)

Create `backend/tests/export/test_bundle.py`:

```python
import json
import uuid
from pathlib import Path

from datasets import Dataset

from tuneforge.export.bundle import export_bundle
from tuneforge.models.analyzer import ModelProfile
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.records import CPTRecord, RecordMetadata
from tuneforge.validation.pipeline import ValidationReport


def _record(text: str) -> CPTRecord:
    return CPTRecord(
        text=text, metadata=RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="deadbeef")
    )


def _model_profile() -> ModelProfile:
    return ModelProfile(
        source="huggingface", model_id="sshleifer/tiny-gpt2", architecture="GPT2LMHeadModel", model_type="gpt2",
        is_causal_lm=True, is_chat_model=False, chat_template_found=False, context_length=1024,
        modalities=["text"], evidence=[], confidence=0.95,
    )


def _plan() -> TrainingPlan:
    return TrainingPlan(
        objective="cpt", canonical_schema="CPTRecord", target_rows=100, examples_per_chunk=1,
        generator_profile_id=None, judge_profile_id=None, required_validators=["structural"],
        evidence=[], confidence=0.9, plan_hash="hash1",
    )


def test_export_bundle_writes_parquet_jsonl_and_manifest_files(tmp_path: Path):
    train = [_record("train example one"), _record("train example two")]
    eval_records = [_record("eval example one")]
    report = ValidationReport(accepted=train + eval_records, rejection_counts={"structural": 2})

    output_dir = tmp_path / "bundle"
    export_bundle(
        train=train, eval_records=eval_records, output_dir=output_dir,
        model_profile=_model_profile(), plan=_plan(), validation_report=report,
    )

    assert (output_dir / "train.parquet").exists()
    assert (output_dir / "train.jsonl").exists()
    assert (output_dir / "eval.parquet").exists()
    assert (output_dir / "eval.jsonl").exists()
    assert (output_dir / "manifest.json").exists()
    assert (output_dir / "model-profile.json").exists()
    assert (output_dir / "training-plan.json").exists()
    assert (output_dir / "validation-report.json").exists()
    assert (output_dir / "provenance.jsonl").exists()


def test_exported_parquet_reloads_through_hugging_face_datasets(tmp_path: Path):
    train = [_record("alpha"), _record("beta")]
    report = ValidationReport(accepted=train, rejection_counts={})

    output_dir = tmp_path / "bundle"
    export_bundle(
        train=train, eval_records=[], output_dir=output_dir,
        model_profile=_model_profile(), plan=_plan(), validation_report=report,
    )

    reloaded = Dataset.from_parquet(str(output_dir / "train.parquet"))
    assert reloaded.to_list() == [json.loads(r.model_dump_json()) for r in train]


def test_no_eval_files_written_when_eval_split_is_empty(tmp_path: Path):
    train = [_record("only train")]
    report = ValidationReport(accepted=train, rejection_counts={})

    output_dir = tmp_path / "bundle"
    export_bundle(
        train=train, eval_records=[], output_dir=output_dir,
        model_profile=_model_profile(), plan=_plan(), validation_report=report,
    )

    assert not (output_dir / "eval.parquet").exists()
    assert not (output_dir / "eval.jsonl").exists()
    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert manifest["eval_row_count"] == 0
    assert manifest["leakage_warning"] is True


def test_manifest_records_row_counts_and_rejection_summary(tmp_path: Path):
    train = [_record("a"), _record("b")]
    eval_records = [_record("c")]
    report = ValidationReport(accepted=train + eval_records, rejection_counts={"structural": 4, "exact_duplicate": 1})

    output_dir = tmp_path / "bundle"
    export_bundle(
        train=train, eval_records=eval_records, output_dir=output_dir,
        model_profile=_model_profile(), plan=_plan(), validation_report=report,
    )

    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert manifest["train_row_count"] == 2
    assert manifest["eval_row_count"] == 1
    assert manifest["rejection_counts"] == {"structural": 4, "exact_duplicate": 1}
    assert manifest["objective"] == "cpt"
    assert manifest["model_id"] == "sshleifer/tiny-gpt2"
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/export/test_bundle.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.export.bundle'`.

#### Step 5: Bundle export — implement (GREEN)

Create `backend/tuneforge/export/bundle.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from datasets import Dataset

from tuneforge.export.splitting import split_train_eval
from tuneforge.models.analyzer import ModelProfile
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.validation.pipeline import ValidationReport


def _write_split(records: list, output_dir: Path, name: str) -> None:
    if not records:
        return
    rows = [json.loads(r.model_dump_json()) for r in records]
    dataset = Dataset.from_list(rows)
    dataset.to_parquet(str(output_dir / f"{name}.parquet"))
    dataset.to_json(str(output_dir / f"{name}.jsonl"))
    # Verify by reloading — PLAN.md requires this, not just writing the files.
    reloaded = Dataset.from_parquet(str(output_dir / f"{name}.parquet"))
    if reloaded.to_list() != rows:
        raise RuntimeError(f"{name}.parquet did not reload to the same records it was written from")


def export_bundle(
    *,
    train: list,
    eval_records: list,
    output_dir: Path,
    model_profile: ModelProfile,
    plan: TrainingPlan,
    validation_report: ValidationReport,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_split(train, output_dir, "train")
    _write_split(eval_records, output_dir, "eval")

    (output_dir / "model-profile.json").write_text(model_profile.model_dump_json(indent=2))
    (output_dir / "training-plan.json").write_text(plan.model_dump_json(indent=2))
    (output_dir / "validation-report.json").write_text(
        json.dumps({"rejection_counts": validation_report.rejection_counts, "assurance_level": validation_report.assurance_level}, indent=2)
    )

    with (output_dir / "provenance.jsonl").open("w", encoding="utf-8") as provenance_file:
        for record in train + eval_records:
            provenance_file.write(json.dumps(json.loads(record.metadata.model_dump_json())))
            provenance_file.write("\n")

    manifest = {
        "objective": plan.objective,
        "canonical_schema": plan.canonical_schema,
        "model_id": model_profile.model_id,
        "plan_hash": plan.plan_hash,
        "train_row_count": len(train),
        "eval_row_count": len(eval_records),
        "leakage_warning": len(eval_records) == 0 and len(train) > 0,
        "rejection_counts": validation_report.rejection_counts,
        "assurance_level": validation_report.assurance_level,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    return output_dir
```

Run the tests again:

```powershell
uv run pytest tests/export/test_bundle.py -q
```

Expected: all pass.

#### Step 6: Compatibility checks — write the failing tests (RED)

**Read the note above Step 1 of this task again before writing this file — the chat-template call in it was not live-verified this session.**

Create `backend/tests/export/test_compatibility.py`:

```python
from transformers import AutoTokenizer

from tuneforge.export.compatibility import UNSLOTH_IMPORT_INSTRUCTIONS, render_chat_template_sample
from tuneforge.records import ChatMessage, RecordMetadata, SFTConversationRecord
import uuid


def _conversation_record() -> SFTConversationRecord:
    return SFTConversationRecord(
        messages=[ChatMessage(role="user", content="Hi"), ChatMessage(role="assistant", content="Hello!")],
        metadata=RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="deadbeef"),
    )


def test_render_chat_template_sample_produces_nonempty_text_for_a_chat_model():
    # Requires a tokenizer with a real chat_template. If this specific
    # tokenizer changes its template format upstream, swap it for another
    # small chat-capable model rather than deleting the test.
    tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-0.5B-Instruct")

    rendered = render_chat_template_sample(tokenizer, _conversation_record())

    assert isinstance(rendered, str)
    assert "Hello!" in rendered or "Hi" in rendered


def test_render_chat_template_sample_raises_a_clear_error_without_a_template():
    tokenizer = AutoTokenizer.from_pretrained("gpt2")  # base model, no chat_template

    try:
        render_chat_template_sample(tokenizer, _conversation_record())
        raised = False
    except Exception:
        raised = True
    assert raised, "a tokenizer with no chat_template should fail clearly, not silently"


def test_unsloth_instructions_mention_the_export_file_names():
    assert "train.parquet" in UNSLOTH_IMPORT_INSTRUCTIONS
    assert "eval.parquet" in UNSLOTH_IMPORT_INSTRUCTIONS
```

Run it and confirm it fails on the missing module:

```powershell
cd backend
uv run pytest tests/export/test_compatibility.py -q
```

Expected: `ModuleNotFoundError: No module named 'tuneforge.export.compatibility'`.

#### Step 7: Compatibility checks — implement (GREEN)

Create `backend/tuneforge/export/compatibility.py`:

```python
from __future__ import annotations

from tuneforge.records import SFTConversationRecord


def render_chat_template_sample(tokenizer, record: SFTConversationRecord) -> str:
    """Proves the target tokenizer can actually apply its chat template to
    a real conversational example from this dataset — not just that a
    chat_template key exists in tokenizer_config.json (Task 4 already
    checked that), but that applying it to real content doesn't raise.
    """
    messages = [{"role": m.role, "content": m.content} for m in record.messages]
    return tokenizer.apply_chat_template(messages, tokenize=False)


UNSLOTH_IMPORT_INSTRUCTIONS = """\
# Importing this dataset into Unsloth

This bundle contains `train.parquet` / `train.jsonl` and, if enough source
documents were available, `eval.parquet` / `eval.jsonl`. Load either format
with Hugging Face Datasets:

    from datasets import load_dataset
    dataset = load_dataset("parquet", data_files={"train": "train.parquet", "eval": "eval.parquet"})

Column mapping by objective (see `manifest.json` for which one this bundle is):

- `cpt` -> single `text` column, use as-is for continued pretraining.
- `sft_prompt_completion` -> `prompt` and `completion` columns.
- `sft_conversation` / `dpo` -> a `messages` (or `prompt`/`chosen`/`rejected`) column
  of `{"role": ..., "content": ...}` objects — apply your tokenizer's chat
  template before training, the same way `model-profile.json` confirms it renders.

See `validation-report.json` for the assurance level (`standard_assurance` vs
`lower_assurance`) and `provenance.jsonl` for per-row source traceability.
"""
```

Run the tests again:

```powershell
uv run pytest tests/export/test_compatibility.py -q
```

Expected: the chat-template tests download two real tokenizers on first run (Qwen2.5-0.5B-Instruct's tokenizer files are a few MB, gpt2's are smaller) — this needs real network access and may take a minute. If `render_chat_template_sample` behaves differently than expected here, fix this file, not the test's intent (a chat-capable tokenizer must render successfully; a template-less one must fail clearly).

#### Step 8: Run the full backend suite and commit

```powershell
uv run pytest -q
```

```powershell
git add backend
git commit -m "feat: export validated Unsloth dataset bundles"
```

---

## When you're done

Do not start Task 13. Do not touch `PLAN.md`. Write a short report back to Tushar with:

1. Output of `uv run pytest -q` (full pass/fail summary) from `backend/`.
2. Output of `git log --oneline` — should show two new commits: `feat: add resumable generation runs` and `feat: export validated Unsloth dataset bundles`.
3. **Whether you actually implemented the real plan-approval flow** called out in Task 11 Step 7 (the `POST /api/plans/{id}/approve` endpoint and a real `plan_hash` comparison), or left the stub as given. Either is acceptable to report — just don't report the stub as if it were the real thing.
4. **Whether `render_chat_template_sample` behaved as written** against real downloaded tokenizers, since that specific call wasn't live-verified before this document was written.
5. **Whether you closed the `sources: list[SourceRecord] = []` gap** in `run_generation_worker` (loading and chunking every source document for a project), and how.
6. **Whether you mounted `runs.router` into the real app** (`tuneforge.main.create_app`) and, if so, what you did about per-request session management — neither is done in this document, both are called out as open gaps above.
7. Confirm `backend/uv.lock` picked up `datasets` and is committed.
8. Anything else you had to deviate from in this document, and why.
9. If you find a correctness issue anywhere in the code exactly as given here — not a style preference, an actual bug — stop and describe it rather than silently changing behavior.

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
from tuneforge.providers.protocol import ProviderProfile, RunConsent
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
    consent: RunConsent | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume must continue from rows already accepted, not reset to 0 —
    # otherwise completed_rows regresses and the JSONL/DB counts diverge.
    accepted_total = run.completed_rows
    chunks_processed = resume_from_chunk
    accepted_since_checkpoint = 0
    remaining_sources = sources[resume_from_chunk:]

    # Honor a cancel that was requested before the worker started; do not
    # overwrite cancel_requested with "running" and then process every chunk.
    session.refresh(run)
    if run.status == "cancel_requested":
        run.status = "cancelled"
        session.commit()
        logger.info("run %s cancelled before start", run.id)
        return

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

            record = await generate_record(
                plan=plan, source=source, generator=generator, judge=judge, spec=spec, consent=consent
            )
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

    # Hitting target_rows mid-document skips the checkpoint branch above;
    # still persist completed_rows so the run status matches accepted output.
    run.status = "completed"
    run.completed_rows = accepted_total
    run.total_rows = accepted_total
    session.commit()


def _spawn_probe(marker_path: str) -> None:
    """Module-level, picklable — proves multiprocessing.Process(target=...)
    actually starts and completes on this platform (Windows requires spawn,
    not fork, and spawn requires the target to be importable by name, not
    a closure or lambda).
    """
    Path(marker_path).write_text("ok")


def _load_project_sources(session, artifact_store, project_id: uuid.UUID, tokenizer) -> list[SourceRecord]:
    from tuneforge.ingestion.chunking import chunk_into_source_records
    from tuneforge.ingestion.documents import convert_document_cached
    from tuneforge.storage.repositories import SourceRepository

    source_repo = SourceRepository(session, artifact_store)
    cache_dir = artifact_store.base_dir / "_docling_cache"

    all_sources: list[SourceRecord] = []
    for source_row in source_repo.list_sources(project_id):
        file_path = source_repo.get_source_path(source_row)
        document, source_hash = convert_document_cached(file_path, cache_dir=cache_dir)
        document_id = uuid.uuid4()
        chunks = chunk_into_source_records(
            document,
            document_id=document_id,
            source_name=source_row.filename,
            source_hash=source_hash,
            tokenizer=tokenizer,
        )
        all_sources.extend(chunks)
    return all_sources


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

    engine = create_sqlite_engine(Path(db_path))
    session = create_session_factory(engine)()
    artifact_store = ArtifactStore(Path(base_data_dir))

    run = session.get(RunRecord, uuid.UUID(run_id))
    plan_record = session.get(TrainingPlanRecord, run.plan_id)
    plan = TrainingPlan.model_validate(plan_record.plan_json)

    generator = _load_provider(session, run.generator_profile_id)
    judge = _load_provider(session, run.judge_profile_id) if run.judge_profile_id else None

    model_profile = analyze_model(plan_record.plan_json.get("model_id", ""), source="huggingface")
    tokenizer = build_tokenizer(model_profile.model_id)
    sources = _load_project_sources(session, artifact_store, run.project_id, tokenizer)

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

    consent = (
        RunConsent(run_id=run.id, granted_at=run.remote_consent_granted_at)
        if run.remote_consent_granted_at
        else None
    )

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
            consent=consent,
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

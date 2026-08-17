from __future__ import annotations

import json
import logging
import multiprocessing
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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
        # Sources with a confirmed structured mapping are handled by
        # _load_structured_records instead — running them through document
        # conversion here is what used to crash the worker (UnsupportedDocumentError
        # on a .csv/.json source, raised before this function even had a chance
        # to be resumable, let alone caught).
        if source_row.confirmed_schema is not None:
            continue
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


def _load_structured_records(
    session, artifact_store, project_id: uuid.UUID, plan: TrainingPlan
) -> tuple[list, list[dict]]:
    """Normalizes every source with a confirmed column mapping, skipping any
    whose detected schema doesn't produce the plan's canonical record type —
    never silently mixes e.g. CPT generation with SFT-shaped structured rows.
    Returns (records, skipped) where skipped is [{"source_id", "reason"}, ...].
    """
    from tuneforge.ingestion.structured import load_structured_rows
    from tuneforge.normalization.detector import DetectedSchema
    from tuneforge.normalization.mappers import CANONICAL_SCHEMA_BY_DETECTED_SCHEMA, normalize_rows
    from tuneforge.normalization.preview import apply_column_mapping
    from tuneforge.storage.repositories import SourceRepository

    source_repo = SourceRepository(session, artifact_store)

    records: list = []
    skipped: list[dict] = []
    for source_row in source_repo.list_sources(project_id):
        if source_row.confirmed_schema is None:
            continue

        schema = DetectedSchema(source_row.confirmed_schema)
        canonical_schema = CANONICAL_SCHEMA_BY_DETECTED_SCHEMA[schema]
        if canonical_schema != plan.canonical_schema:
            skipped.append(
                {
                    "source_id": str(source_row.id),
                    "reason": (
                        f"detected schema {schema.value!r} ({canonical_schema}) does not match "
                        f"the plan's objective ({plan.canonical_schema})"
                    ),
                }
            )
            continue

        rows = load_structured_rows(source_repo.get_source_path(source_row))
        if source_row.column_mapping:
            rows = apply_column_mapping(rows, json.loads(source_row.column_mapping))
        records.extend(normalize_rows(rows, schema, document_id=source_row.id))

    return records, skipped


@dataclass(frozen=True)
class RowEstimate:
    total_rows: int  # true combined total across every source, uncapped
    truncated: bool  # True when total_rows > capped_at
    capped_at: int  # MAX_ACCEPTED_ROWS, echoed back so callers don't hardcode it


def _count_structured_rows(session, artifact_store, project_id: uuid.UUID) -> int:
    from tuneforge.ingestion.structured import load_structured_rows
    from tuneforge.storage.repositories import SourceRepository

    source_repo = SourceRepository(session, artifact_store)
    total = 0
    for source_row in source_repo.list_sources(project_id):
        if source_row.confirmed_schema is None:
            continue
        total += len(load_structured_rows(source_repo.get_source_path(source_row)))
    return total


def estimate_total_rows(session, artifact_store, project_id: uuid.UUID, tokenizer) -> RowEstimate:
    """Counts exactly what a real run would process: the same document-chunk
    list _load_project_sources produces for the worker, plus confirmed
    structured row counts. No LLM call. Shares _load_project_sources with the
    real run so the two can never drift apart.
    """
    document_chunks = len(_load_project_sources(session, artifact_store, project_id, tokenizer))
    structured_rows = _count_structured_rows(session, artifact_store, project_id)
    total = document_chunks + structured_rows
    return RowEstimate(total_rows=total, truncated=total > MAX_ACCEPTED_ROWS, capped_at=MAX_ACCEPTED_ROWS)


def run_generation_worker(*, db_path: str, base_data_dir: str, run_id: str) -> None:
    """The real multiprocessing entry point. Deliberately thin: it only
    loads state from the database and delegates to _run_generation_async,
    which is where the actual tested logic lives.
    """
    import asyncio

    from tuneforge.ingestion.chunking import build_tokenizer
    from tuneforge.models.analyzer import ModelProfile
    from tuneforge.storage.artifacts import ArtifactStore
    from tuneforge.storage.models import ModelProfileRecord, TrainingPlanRecord

    engine = create_sqlite_engine(Path(db_path))
    session = create_session_factory(engine)()
    artifact_store = ArtifactStore(Path(base_data_dir))

    run = session.get(RunRecord, uuid.UUID(run_id))
    plan_record = session.get(TrainingPlanRecord, run.plan_id)
    plan = TrainingPlan.model_validate(plan_record.plan_json)

    generator = _load_provider(session, run.generator_profile_id)
    judge = _load_provider(session, run.judge_profile_id) if run.judge_profile_id else None

    try:
        # TrainingPlan has no model_id field of its own — the analyzed model
        # profile lives on ModelProfileRecord, keyed by project, not by plan.
        # Reuse the same "most recent analysis for this project" lookup
        # api/exports.py already relies on, rather than re-analyzing from a
        # plan_json key that was never actually populated.
        model_profile_record = (
            session.query(ModelProfileRecord)
            .filter(ModelProfileRecord.project_id == run.project_id)
            .order_by(ModelProfileRecord.created_at.desc())
            .first()
        )
        if model_profile_record is None:
            raise RuntimeError(f"no analyzed model found for project {run.project_id}")
        model_profile = ModelProfile.model_validate(model_profile_record.profile_json)
        tokenizer = build_tokenizer(model_profile.model_id)
        # Everything from here through the structured-record merge below used to
        # sit outside this try block — an UnsupportedDocumentError from a
        # structured source that slipped past _load_project_sources's filter (or
        # any other loading failure) would kill the worker without ever setting
        # run.status to "failed", leaving the run stuck. See CLAUDE.md's known gaps.
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

        # Only merge structured rows once the document phase actually finished —
        # a cancelled/still-running run should not pick up a second row stream.
        # structured_merge_completed_at guards against re-appending the same
        # normalized rows if this run is resumed after already merging once
        # (e.g. a later, unrelated failure triggers a resume). This does not
        # cover the narrow window between the file append below and the commit
        # that sets the flag — a crash exactly there could still double-merge
        # once; a second resume after that would not compound further.
        if run.status == "completed" and run.structured_merge_completed_at is None:
            structured_records, skipped = _load_structured_records(
                session, artifact_store, run.project_id, plan
            )
            remaining_capacity = max(0, min(target_rows, MAX_ACCEPTED_ROWS) - run.completed_rows)
            structured_records = structured_records[:remaining_capacity]

            accepted_normalized = 0
            if structured_records:
                report = asyncio.run(
                    run_validation_pipeline(
                        structured_records,
                        tokenizer=tokenizer.tokenizer,
                        max_tokens=model_profile.context_length or 2048,
                        judge=judge,
                    )
                )
                with output_path.open("a", encoding="utf-8") as output_file:
                    for accepted_record in report.accepted:
                        output_file.write(accepted_record.model_dump_json())
                        output_file.write("\n")
                accepted_normalized = len(report.accepted)

            run.accepted_generated = run.completed_rows
            run.accepted_normalized = accepted_normalized
            run.completed_rows = run.accepted_generated + accepted_normalized
            run.total_rows = run.completed_rows
            run.structured_sources_skipped = json.dumps(skipped) if skipped else None
            run.structured_merge_completed_at = datetime.now(timezone.utc)
            session.commit()
    except Exception:
        logger.exception("run %s failed", run.id)
        run.status = "failed"
        session.commit()
        raise


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

"""100k-row CPT crash-resume stress. Run: uv run pytest tests/stress/test_cpt_100k.py -q -s"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import psutil
import pytest

from tuneforge.generation.specs import GenerationSpec
from tuneforge.jobs.runner import MAX_ACCEPTED_ROWS, _run_generation_async, run_output_path
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.records import CPTRecord, SourceRecord
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import (
    CheckpointRecord,
    Project,
    ProviderProfileRecord,
    RunRecord,
    TrainingPlanRecord,
)
from tuneforge.validation.pipeline import ValidationReport


TARGET = 100_000


def _synthetic_sources(n: int) -> list[SourceRecord]:
    doc_id = uuid.uuid4()
    # Keep texts tiny — CPT is pass-through; we are stress-testing IO/checkpoints.
    return [
        SourceRecord(
            document_id=doc_id,
            chunk_id=f"{doc_id}-{i}",
            text=f"c{i}",
            source_name="synthetic.md",
            source_hash="abc",
            page=None,
            heading=None,
            metadata={},
        )
        for i in range(n)
    ]


@pytest.fixture
def fast_validation(monkeypatch):
    async def _fast(records, **kwargs):
        return ValidationReport(accepted=list(records))

    monkeypatch.setattr("tuneforge.jobs.runner.run_validation_pipeline", _fast)


def test_cpt_100k_crash_resume_memory_bounded(tmp_path: Path, fast_validation):
    """D2: CPT path at 100k with simulated mid-run failure + resume.

    Sources are synthetic (not Docling-chunked documents) so the test measures
    checkpoint/resume/jsonl streaming rather than HybridChunker cost. Validation
    is stubbed to keep wall-clock on Windows CI-scale machines tractable while
    still writing 100k accepted lines through the real runner loop.
    """
    engine = create_sqlite_engine(tmp_path / "tuneforge.db")
    session = create_session_factory(engine)()
    store = ArtifactStore(tmp_path)
    project = Project(id=uuid.uuid4(), name="stress", storage_path=str(tmp_path / "proj"))
    session.add(project)
    session.commit()

    plan = TrainingPlan(
        objective="cpt",
        canonical_schema="CPTRecord",
        target_rows=TARGET,
        examples_per_chunk=1,
        generator_profile_id=None,
        judge_profile_id=None,
        required_validators=["structural", "dedup"],
        evidence=[],
        confidence=1.0,
        plan_hash="stress",
    )
    plan_record = TrainingPlanRecord(
        id=uuid.uuid4(),
        project_id=project.id,
        objective="cpt",
        plan_json=plan.model_dump(mode="json"),
        plan_hash="stress",
    )
    session.add(plan_record)
    provider = ProviderProfileRecord(
        id=uuid.uuid4(),
        project_id=project.id,
        name="unused-for-cpt",
        base_url="http://127.0.0.1:9/v1",
        model="none",
    )
    session.add(provider)
    session.commit()
    run = RunRecord(
        id=uuid.uuid4(),
        project_id=project.id,
        plan_id=plan_record.id,
        generator_profile_id=provider.id,
        status="pending",
        is_preview=False,
        completed_rows=0,
        total_rows=TARGET,
    )
    session.add(run)
    session.commit()

    sources = _synthetic_sources(TARGET)
    output_path = run_output_path(store.base_dir, project.id, run.id)
    tokenizer = MagicMock()
    proc = psutil.Process(os.getpid())
    t0 = time.perf_counter()

    async def run_partial():
        await _run_generation_async(
            session=session,
            run=run,
            plan=plan,
            sources=sources,
            generator=None,  # type: ignore[arg-type]
            judge=None,
            spec=GenerationSpec(desired_behavior="cpt"),
            tokenizer=tokenizer,
            max_tokens=512,
            target_rows=40_000,
            resume_from_chunk=0,
            output_path=output_path,
        )

    asyncio.run(run_partial())
    assert run.completed_rows == 40_000
    mid_rss = proc.memory_info().rss

    # Simulate crash: leave partial jsonl + checkpoint, mark failed, resume.
    run.status = "failed"
    session.commit()
    latest = (
        session.query(CheckpointRecord)
        .filter(CheckpointRecord.run_id == run.id)
        .order_by(CheckpointRecord.sequence.desc())
        .first()
    )
    assert latest is not None
    resume_from = latest.sequence

    run.status = "pending"
    session.commit()

    async def resume_to_cap():
        await _run_generation_async(
            session=session,
            run=run,
            plan=plan,
            sources=sources,
            generator=None,  # type: ignore[arg-type]
            judge=None,
            spec=GenerationSpec(desired_behavior="cpt"),
            tokenizer=tokenizer,
            max_tokens=512,
            target_rows=TARGET,
            resume_from_chunk=resume_from,
            output_path=output_path,
        )

    asyncio.run(resume_to_cap())
    elapsed = time.perf_counter() - t0
    final_rss = proc.memory_info().rss
    growth = final_rss - mid_rss

    assert run.completed_rows == min(TARGET, MAX_ACCEPTED_ROWS)
    line_count = sum(1 for _ in output_path.open(encoding="utf-8"))
    assert line_count == run.completed_rows

    print(
        f"D2 stats: rows={run.completed_rows} elapsed_s={elapsed:.1f} "
        f"mid_rss_mb={mid_rss / 1e6:.1f} final_rss_mb={final_rss / 1e6:.1f} growth_mb={growth / 1e6:.1f}"
    )
    assert growth < 500 * 1024 * 1024, f"RSS grew too much after resume: {growth} bytes"

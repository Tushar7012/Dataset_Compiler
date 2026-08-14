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

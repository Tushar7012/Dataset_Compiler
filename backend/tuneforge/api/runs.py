from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_session
from tuneforge.jobs.runner import is_run_process_alive, start_run
from tuneforge.storage.models import RunRecord, TrainingPlanRecord

router = APIRouter()

_CANCELLABLE_STATUSES = {"pending", "running"}


def _get_run_or_404(session: Session, run_id: uuid.UUID) -> RunRecord:
    run = session.get(RunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return run


@router.post("/runs/preview", status_code=201)
async def create_preview(payload: dict, request: Request, session: Session = Depends(get_session)):
    plan_id = payload.get("plan_id")
    generator_profile_id = payload.get("generator_profile_id")
    if not plan_id or not generator_profile_id:
        raise HTTPException(status_code=422, detail="'plan_id' and 'generator_profile_id' are required")

    plan = session.get(TrainingPlanRecord, uuid.UUID(plan_id))
    if plan is None:
        raise HTTPException(status_code=404, detail=f"plan not found: {plan_id}")

    run = RunRecord(
        id=uuid.uuid4(),
        project_id=plan.project_id,
        plan_id=plan.id,
        generator_profile_id=uuid.UUID(generator_profile_id),
        judge_profile_id=uuid.UUID(payload["judge_profile_id"]) if payload.get("judge_profile_id") else None,
        is_preview=True,
    )
    session.add(run)
    session.commit()
    start_run(db_path=request.app.state.db_path, base_data_dir=request.app.state.artifact_store.base_dir, run_id=run.id)
    return {"id": str(run.id), "status": run.status, "is_preview": run.is_preview}


@router.get("/runs/{run_id}")
async def get_run(run_id: uuid.UUID, session: Session = Depends(get_session)):
    run = _get_run_or_404(session, run_id)
    return {
        "id": str(run.id),
        "status": run.status,
        "completed_rows": run.completed_rows,
        "total_rows": run.total_rows,
        "is_preview": run.is_preview,
        "assurance_level": run.assurance_level,
    }


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: uuid.UUID, session: Session = Depends(get_session)):
    run = _get_run_or_404(session, run_id)
    if run.status not in _CANCELLABLE_STATUSES:
        raise HTTPException(status_code=409, detail=f"run is {run.status!r}, cannot cancel")
    run.status = "cancel_requested"
    session.commit()
    return {"status": run.status}


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: uuid.UUID, request: Request, session: Session = Depends(get_session)):
    run = _get_run_or_404(session, run_id)
    if run.status not in ("cancelled", "failed"):
        raise HTTPException(status_code=409, detail=f"run is {run.status!r}, nothing to resume")
    run.status = "pending"
    session.commit()
    start_run(db_path=request.app.state.db_path, base_data_dir=request.app.state.artifact_store.base_dir, run_id=run.id)
    return {"status": "pending"}


@router.post("/runs/{run_id}/approve-full")
async def approve_full(run_id: uuid.UUID, request: Request, session: Session = Depends(get_session)):
    preview_run = _get_run_or_404(session, run_id)
    if not preview_run.is_preview:
        raise HTTPException(status_code=409, detail="only a preview run can be approved into a full run")
    if preview_run.status != "completed":
        raise HTTPException(status_code=409, detail=f"preview is {preview_run.status!r}, not ready to approve")

    # See the comment in api/plans.py's approve_plan and this same block in
    # the original Task 11 document: this relies on TrainingPlanRecord rows
    # being immutable once created, which is true of everything built so
    # far — approved_at on this exact row already means "this exact
    # plan_hash was approved".
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
async def stream_events(run_id: uuid.UUID, request: Request, session: Session = Depends(get_session)):
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

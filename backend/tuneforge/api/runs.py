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

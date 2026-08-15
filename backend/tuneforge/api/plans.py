from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_session
from tuneforge.models.analyzer import ModelProfile
from tuneforge.planning.intents import TrainingIntent
from tuneforge.planning.planner import ChatTemplateRequiredError, DistinctJudgeRequiredError, recommend_plan
from tuneforge.storage.models import ModelProfileRecord, TrainingPlanRecord

router = APIRouter()


@router.post("/plans/recommend")
async def recommend(payload: dict, session: Session = Depends(get_session)):
    required = ("project_id", "model_profile_id", "goal", "desired_behavior", "language", "target_rows")
    missing = [field for field in required if payload.get(field) is None]
    if missing:
        raise HTTPException(status_code=422, detail=f"missing required field(s): {missing}")

    model_profile_record = session.get(ModelProfileRecord, uuid.UUID(payload["model_profile_id"]))
    if model_profile_record is None:
        raise HTTPException(status_code=404, detail="model profile not found — analyze a model first")
    model_profile = ModelProfile.model_validate(model_profile_record.profile_json)

    intent = TrainingIntent(
        goal=payload["goal"], desired_behavior=payload["desired_behavior"], language=payload["language"]
    )

    try:
        plan = recommend_plan(
            intent,
            model_profile,
            target_rows=payload["target_rows"],
            objective_override=payload.get("objective_override"),
            generator_profile_id=uuid.UUID(payload["generator_profile_id"]) if payload.get("generator_profile_id") else None,
            judge_profile_id=uuid.UUID(payload["judge_profile_id"]) if payload.get("judge_profile_id") else None,
        )
    except (ChatTemplateRequiredError, DistinctJudgeRequiredError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    plan_dict = json.loads(plan.model_dump_json())
    record = TrainingPlanRecord(
        id=uuid.uuid4(),
        project_id=uuid.UUID(payload["project_id"]),
        objective=plan.objective,
        plan_json=plan_dict,
        plan_hash=plan.plan_hash,
    )
    session.add(record)
    session.commit()

    return {"id": str(record.id), **plan_dict}


@router.post("/plans/{plan_id}/approve")
async def approve_plan(plan_id: uuid.UUID, session: Session = Depends(get_session)):
    plan = session.get(TrainingPlanRecord, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"plan not found: {plan_id}")
    plan.approved_at = datetime.now(timezone.utc)
    session.commit()
    return {"id": str(plan.id), "approved_at": plan.approved_at.isoformat()}

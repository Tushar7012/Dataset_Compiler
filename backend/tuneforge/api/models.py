from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_session
from tuneforge.models.analyzer import GatedModelError, ModelNotAccessibleError, analyze_model
from tuneforge.models.compatibility import IncompatibleModelError
from tuneforge.storage.models import ModelProfileRecord

router = APIRouter()


@router.post("/models/analyze")
async def analyze(payload: dict, session: Session = Depends(get_session)):
    model_id = payload.get("model_id")
    project_id = payload.get("project_id")
    source = payload.get("source", "huggingface")
    if not model_id or not project_id:
        raise HTTPException(status_code=422, detail="'model_id' and 'project_id' are required")

    try:
        profile = analyze_model(model_id, source=source)
    except (GatedModelError, ModelNotAccessibleError, IncompatibleModelError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    profile_dict = json.loads(profile.model_dump_json())
    record = ModelProfileRecord(
        id=uuid.uuid4(),
        project_id=uuid.UUID(project_id),
        model_id=profile.model_id,
        source=profile.source,
        profile_json=profile_dict,
        confidence=profile.confidence,
    )
    session.add(record)
    session.commit()

    return {"id": str(record.id), **profile_dict}

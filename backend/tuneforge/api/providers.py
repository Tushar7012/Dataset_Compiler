from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_session
from tuneforge.security.credentials import store_api_key
from tuneforge.storage.models import ProviderProfileRecord

router = APIRouter()

_VALID_SCOPES = {"local", "remote"}
_REQUIRED_FIELDS = ("project_id", "name", "base_url", "model", "endpoint_scope")


@router.post("/providers", status_code=201)
async def create_provider(payload: dict, session: Session = Depends(get_session)):
    missing = [field for field in _REQUIRED_FIELDS if not payload.get(field)]
    if missing:
        raise HTTPException(status_code=422, detail=f"missing required field(s): {missing}")
    if payload["endpoint_scope"] not in _VALID_SCOPES:
        raise HTTPException(status_code=422, detail="endpoint_scope must be 'local' or 'remote'")

    credential_reference = None
    api_key = payload.get("api_key")
    if api_key:
        credential_reference = f"provider-{uuid.uuid4().hex}"
        store_api_key(credential_reference, api_key)

    record = ProviderProfileRecord(
        id=uuid.uuid4(),
        project_id=uuid.UUID(payload["project_id"]),
        name=payload["name"],
        base_url=payload["base_url"],
        model=payload["model"],
        endpoint_scope=payload["endpoint_scope"],
        credential_reference=credential_reference,
    )
    session.add(record)
    session.commit()
    return {"id": str(record.id), "name": record.name, "endpoint_scope": record.endpoint_scope}

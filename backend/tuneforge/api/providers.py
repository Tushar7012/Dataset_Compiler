from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_session
from tuneforge.models.analyzer import HF_TOKEN_CREDENTIAL_NAME
from tuneforge.security.credentials import CredentialNotFoundError, get_api_key, store_api_key
from tuneforge.storage.models import ProviderProfileRecord

router = APIRouter()

_VALID_SCOPES = {"local", "remote"}
_REQUIRED_FIELDS = ("project_id", "name", "base_url", "model", "endpoint_scope")

# Well-known credential name for the pre-configured Gemini key (repo-root .env GEMINI_API_KEY).
# A remote provider created without an explicit api_key falls back to this if it's been seeded,
# so the key never has to be re-typed into the frontend per project.
GEMINI_API_KEY_CREDENTIAL_NAME = "gemini"

# Hugging Face's OpenAI-compatible router — a remote provider pointed at it with no
# explicit api_key falls back to the pre-configured HF_TOKEN credential instead of Gemini's.
HF_ROUTER_BASE_URL_MARKER = "router.huggingface.co"


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
    elif payload["endpoint_scope"] == "remote":
        fallback_credential_name = (
            HF_TOKEN_CREDENTIAL_NAME
            if HF_ROUTER_BASE_URL_MARKER in payload["base_url"]
            else GEMINI_API_KEY_CREDENTIAL_NAME
        )
        try:
            get_api_key(fallback_credential_name)
            credential_reference = fallback_credential_name
        except CredentialNotFoundError:
            pass

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

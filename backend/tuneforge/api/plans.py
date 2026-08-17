from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from tuneforge.api.deps import get_artifact_store, get_session
from tuneforge.api.providers import GEMINI_API_KEY_CREDENTIAL_NAME
from tuneforge.models.analyzer import ModelProfile
from tuneforge.planning.intents import TrainingIntent
from tuneforge.planning.planner import (
    ChatTemplateRequiredError,
    DistinctJudgeRequiredError,
    OBJECTIVE_BY_GOAL,
    recommend_plan,
)
from tuneforge.providers.openai_compatible import OpenAICompatibleProvider, ProviderAuthError, ProviderResponseError
from tuneforge.providers.protocol import GenerationRequest, ProviderProfile, RunConsent
from tuneforge.research.official_sources import fetch_model_card_readme, fetch_source, model_card_url
from tuneforge.research.resolver import resolve_rejected_recommendation
from tuneforge.security.credentials import CredentialNotFoundError
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.models import ModelProfileRecord, TrainingPlanRecord

router = APIRouter()

_SUGGEST_GOAL_CONSENT_ERROR = "remote provider requires explicit consent — set 'remote_consent': true"
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
_GEMINI_GOAL_SUGGESTION_MODEL = "gemini-2.5-flash"
# ~2k tokens — enough for a coarse 1-of-4 classification from a document's
# opening content, without transmitting the whole document to a remote API.
_GOAL_SUGGESTION_CHAR_BUDGET = 8_000
_VALID_GOALS = frozenset(OBJECTIVE_BY_GOAL)


class GoalSuggestionError(RuntimeError):
    pass


def _sample_project_text(session, artifact_store, project_id: uuid.UUID) -> str:
    from tuneforge.ingestion.documents import convert_document_cached
    from tuneforge.storage.repositories import SourceRepository

    source_repo = SourceRepository(session, artifact_store)
    cache_dir = artifact_store.base_dir / "_docling_cache"  # same cache _load_project_sources uses
    chunks: list[str] = []
    budget = _GOAL_SUGGESTION_CHAR_BUDGET
    for source_row in source_repo.list_sources(project_id):
        if source_row.confirmed_schema is not None or budget <= 0:
            continue
        document, _ = convert_document_cached(source_repo.get_source_path(source_row), cache_dir=cache_dir)
        text = document.export_to_markdown()[:budget]
        if not text.strip():
            continue  # e.g. an image-only PDF Docling parsed but extracted no text from (do_ocr=False)
        chunks.append(text)
        budget -= len(text)
    return "\n\n---\n\n".join(chunks)


def _gemini_provider() -> OpenAICompatibleProvider:
    profile = ProviderProfile(
        name="gemini-goal-suggestion",
        base_url=_GEMINI_BASE_URL,
        model=_GEMINI_GOAL_SUGGESTION_MODEL,
        endpoint_scope="remote",
        credential_reference=GEMINI_API_KEY_CREDENTIAL_NAME,
    )
    client = httpx.AsyncClient(base_url=profile.base_url, timeout=profile.timeout_seconds)
    return OpenAICompatibleProvider(profile, client)


async def _suggest_goal_from_text(provider: OpenAICompatibleProvider, text: str, consent: RunConsent) -> dict:
    prompt = (
        "You are classifying a document to choose the best fine-tuning goal.\n"
        f"Pick exactly one goal from this list: {sorted(_VALID_GOALS)}.\n\n"
        f"DOCUMENT SAMPLE:\n{text}\n\n"
        'Respond with only a JSON object: {"goal": "<one of the list above>", '
        '"rationale": "<one sentence>", "desired_behavior": "<one sentence>"}'
    )
    response = await provider.generate(
        GenerationRequest(messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}),
        consent=consent,
    )
    try:
        data = json.loads(response.content)
        goal = data["goal"]
        rationale = str(data["rationale"])
        desired_behavior = str(data["desired_behavior"])
        if not isinstance(goal, str) or goal not in _VALID_GOALS:
            raise GoalSuggestionError(f"Gemini suggested an unrecognized goal: {goal!r}")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise GoalSuggestionError(f"Gemini response was not valid JSON with the expected fields: {exc}") from exc
    return {"goal": goal, "rationale": rationale, "desired_behavior": desired_behavior}


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


@router.get("/plans/estimated-rows")
async def estimated_rows(
    project_id: uuid.UUID,
    model_profile_id: uuid.UUID,
    session: Session = Depends(get_session),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
):
    model_profile_record = session.get(ModelProfileRecord, model_profile_id)
    if model_profile_record is None:
        raise HTTPException(status_code=404, detail="model profile not found — analyze a model first")
    model_profile = ModelProfile.model_validate(model_profile_record.profile_json)

    from tuneforge.ingestion.chunking import build_tokenizer
    from tuneforge.ingestion.documents import (
        CorruptDocumentError,
        EmptyDocumentError,
        EncryptedDocumentError,
        OversizedDocumentError,
        UnsupportedDocumentError,
    )
    from tuneforge.jobs.runner import estimate_total_rows

    tokenizer = build_tokenizer(model_profile.model_id)
    try:
        estimate = estimate_total_rows(session, artifact_store, project_id, tokenizer)
    except (
        UnsupportedDocumentError,
        EmptyDocumentError,
        OversizedDocumentError,
        EncryptedDocumentError,
        CorruptDocumentError,
    ) as exc:
        raise HTTPException(status_code=422, detail=f"could not read project document source(s): {exc}") from exc
    return {"total_rows": estimate.total_rows, "truncated": estimate.truncated, "capped_at": estimate.capped_at}


@router.post("/plans/suggest-goal")
async def suggest_goal(
    payload: dict,
    session: Session = Depends(get_session),
    artifact_store: ArtifactStore = Depends(get_artifact_store),
):
    if not payload.get("remote_consent"):
        raise HTTPException(status_code=422, detail=_SUGGEST_GOAL_CONSENT_ERROR)
    if not payload.get("project_id"):
        raise HTTPException(status_code=422, detail="'project_id' is required")

    project_id = uuid.UUID(payload["project_id"])

    from tuneforge.ingestion.documents import (
        CorruptDocumentError,
        EmptyDocumentError,
        EncryptedDocumentError,
        OversizedDocumentError,
        UnsupportedDocumentError,
    )

    try:
        text_sample = _sample_project_text(session, artifact_store, project_id)
    except (
        UnsupportedDocumentError,
        EmptyDocumentError,
        OversizedDocumentError,
        EncryptedDocumentError,
        CorruptDocumentError,
    ) as exc:
        raise HTTPException(status_code=422, detail=f"could not read project document source(s): {exc}") from exc

    if not text_sample:
        raise HTTPException(
            status_code=422,
            detail="no document source with extractable text available — upload a document source first"
        )

    consent = RunConsent(run_id=uuid.uuid4(), granted_at=datetime.now(timezone.utc))
    provider = _gemini_provider()
    try:
        return await _suggest_goal_from_text(provider, text_sample, consent)
    except CredentialNotFoundError as exc:
        raise HTTPException(status_code=422, detail=f"Gemini credential not configured: {exc}") from exc
    except (ProviderAuthError, ProviderResponseError, GoalSuggestionError) as exc:
        raise HTTPException(status_code=502, detail=f"goal suggestion failed: {exc}") from exc
    finally:
        # Unlike runner.py's providers (built in a short-lived subprocess that
        # exits right after), this one is built fresh per request inside the
        # long-lived main server process — never leave its client open.
        await provider.aclose()


@router.post("/plans/{plan_id}/approve")
async def approve_plan(plan_id: uuid.UUID, session: Session = Depends(get_session)):
    plan = session.get(TrainingPlanRecord, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"plan not found: {plan_id}")
    plan.approved_at = datetime.now(timezone.utc)
    session.commit()
    return {"id": str(plan.id), "approved_at": plan.approved_at.isoformat()}


def _parse_uuid_field(payload: dict, key: str) -> uuid.UUID | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"'{key}' is not a valid UUID: {value!r}") from exc


@router.post("/plans/{plan_id}/research")
async def research(plan_id: uuid.UUID, payload: dict, session: Session = Depends(get_session)):
    rejected_plan = session.get(TrainingPlanRecord, plan_id)
    if rejected_plan is None:
        raise HTTPException(status_code=404, detail=f"plan not found: {plan_id}")

    required = ("project_id", "model_profile_id", "goal", "desired_behavior", "language", "target_rows")
    missing = [field for field in required if payload.get(field) is None]
    if missing:
        raise HTTPException(status_code=422, detail=f"missing required field(s): {missing}")

    model_profile_record = session.get(ModelProfileRecord, _parse_uuid_field(payload, "model_profile_id"))
    if model_profile_record is None:
        raise HTTPException(status_code=404, detail="model profile not found — analyze a model first")
    model_profile = ModelProfile.model_validate(model_profile_record.profile_json)

    intent = TrainingIntent(
        goal=payload["goal"], desired_behavior=payload["desired_behavior"], language=payload["language"]
    )

    async with httpx.AsyncClient() as client:
        try:
            result = await resolve_rejected_recommendation(
                intent,
                model_profile,
                client=client,
                target_rows=payload["target_rows"],
                objective_override=payload.get("objective_override"),
                generator_profile_id=_parse_uuid_field(payload, "generator_profile_id"),
                judge_profile_id=_parse_uuid_field(payload, "judge_profile_id"),
            )
        except (ChatTemplateRequiredError, DistinctJudgeRequiredError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    if result.plan is None:
        return {
            "plan": None,
            "citations": [json.loads(c.model_dump_json()) for c in result.citations],
            "confidence": result.confidence,
            "requires_manual_selection": result.requires_manual_selection,
        }

    plan_dict = json.loads(result.plan.model_dump_json())
    record = TrainingPlanRecord(
        id=uuid.uuid4(), project_id=_parse_uuid_field(payload, "project_id"),
        objective=result.plan.objective, plan_json=plan_dict, plan_hash=result.plan.plan_hash,
    )
    session.add(record)
    session.commit()
    return {"id": str(record.id), **plan_dict, "citations": [], "requires_manual_selection": False}

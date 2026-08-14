from __future__ import annotations

import httpx
from pydantic import BaseModel

from tuneforge.models.analyzer import ModelProfile, analyze_model
from tuneforge.planning.intents import TrainingIntent
from tuneforge.planning.planner import ChatTemplateRequiredError, recommend_plan
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.research.official_sources import (
    FetchedSource,
    fetch_model_card_readme,
    fetch_source,
    model_card_url,
)


class ResearchResult(BaseModel):
    plan: TrainingPlan | None
    citations: list[FetchedSource]
    confidence: float
    requires_manual_selection: bool


async def resolve_rejected_recommendation(
    intent: TrainingIntent,
    model_profile: ModelProfile,
    *,
    client: httpx.AsyncClient,
    target_rows: int,
    **plan_kwargs,
) -> ResearchResult:
    """Only call this after the user has rejected `recommend_plan`'s result.

    Order matters here: local metadata is always rechecked before any
    network call, and a Hugging Face model card is only fetched for
    `source="huggingface"` profiles that are still inconclusive after that
    recheck — a local model has no HF model card to fetch at all.
    """
    if model_profile.source == "huggingface":
        refreshed_profile = analyze_model(model_profile.model_id, source=model_profile.source)
    else:
        refreshed_profile = model_profile

    try:
        plan = recommend_plan(intent, refreshed_profile, target_rows=target_rows, **plan_kwargs)
        return ResearchResult(plan=plan, citations=[], confidence=plan.confidence, requires_manual_selection=False)
    except ChatTemplateRequiredError:
        pass

    if refreshed_profile.source != "huggingface":
        return ResearchResult(plan=None, citations=[], confidence=0.0, requires_manual_selection=True)

    card = fetch_model_card_readme(refreshed_profile.model_id)
    if card is None:
        card = await fetch_source(model_card_url(refreshed_profile.model_id), client)
    return ResearchResult(plan=None, citations=[card], confidence=0.0, requires_manual_selection=True)

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Literal

from tuneforge.models.analyzer import ModelProfile
from tuneforge.models.evidence import Evidence
from tuneforge.planning.intents import TrainingIntent
from tuneforge.planning.schemas import TrainingPlan

OBJECTIVE_BY_GOAL: dict[str, str] = {
    "domain_adaptation": "cpt",
    "single_turn_instruction": "sft_prompt_completion",
    "multi_turn_conversation": "sft_conversation",
    "preference_alignment": "dpo",
}

CANONICAL_SCHEMA_BY_OBJECTIVE: dict[str, str] = {
    "cpt": "CPTRecord",
    "sft_prompt_completion": "SFTPromptCompletionRecord",
    "sft_conversation": "SFTConversationRecord",
    "dpo": "DPORecord",
}

_BASE_VALIDATORS = ["structural", "deduplication", "source_grounding"]

REQUIRED_VALIDATORS_BY_OBJECTIVE: dict[str, list[str]] = {
    "cpt": [*_BASE_VALIDATORS],
    "sft_prompt_completion": [*_BASE_VALIDATORS],
    "sft_conversation": [*_BASE_VALIDATORS, "chat_role_order"],
    "dpo": [*_BASE_VALIDATORS, "chat_role_order", "judge_required"],
}

CHAT_TEMPLATE_REQUIRED_OBJECTIVES = {"sft_conversation", "dpo"}


class ChatTemplateRequiredError(RuntimeError):
    pass


class DistinctJudgeRequiredError(RuntimeError):
    pass


def _compute_plan_hash(
    *,
    objective: str,
    canonical_schema: str,
    target_rows: int,
    examples_per_chunk: int,
    generator_profile_id: uuid.UUID | None,
    judge_profile_id: uuid.UUID | None,
    required_validators: list[str],
) -> str:
    payload = {
        "objective": objective,
        "canonical_schema": canonical_schema,
        "target_rows": target_rows,
        "examples_per_chunk": examples_per_chunk,
        "generator_profile_id": str(generator_profile_id) if generator_profile_id else None,
        "judge_profile_id": str(judge_profile_id) if judge_profile_id else None,
        "required_validators": sorted(required_validators),
    }
    canonical = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def recommend_plan(
    intent: TrainingIntent,
    model_profile: ModelProfile,
    *,
    target_rows: int,
    examples_per_chunk: int = 1,
    generator_profile_id: uuid.UUID | None = None,
    judge_profile_id: uuid.UUID | None = None,
    objective_override: Literal["cpt", "sft_prompt_completion", "sft_conversation", "dpo"] | None = None,
) -> TrainingPlan:
    """Deterministically recommend a training plan.

    `objective_override` is how a caller implements "Change Objective": call
    again with an explicit objective instead of the one the intent maps to.
    "Approve" and "Cancel" have no dedicated methods here — the caller either
    persists the returned TrainingPlan (approve) or discards it (cancel);
    "Inspect Evidence" is just reading `.evidence` off the result.
    """
    objective = objective_override or OBJECTIVE_BY_GOAL[intent.goal]

    # cpt's generation step is a deterministic passthrough of the source
    # chunk (no LLM call) — N copies of the same chunk would just be
    # duplicate rows the dedup validator strips right back out.
    if objective == "cpt":
        examples_per_chunk = 1

    if objective in CHAT_TEMPLATE_REQUIRED_OBJECTIVES and not model_profile.chat_template_found:
        raise ChatTemplateRequiredError(
            f"{model_profile.model_id} has no chat template, which {objective!r} requires"
        )

    if objective == "dpo":
        if generator_profile_id is None:
            raise DistinctJudgeRequiredError("dpo requires a generator_profile_id")
        if judge_profile_id is None:
            raise DistinctJudgeRequiredError("dpo requires a judge_profile_id")
        if judge_profile_id == generator_profile_id:
            raise DistinctJudgeRequiredError("dpo requires a judge model different from the generator model")

    canonical_schema = CANONICAL_SCHEMA_BY_OBJECTIVE[objective]
    required_validators = REQUIRED_VALIDATORS_BY_OBJECTIVE[objective]

    evidence = [
        *model_profile.evidence,
        Evidence(
            field="objective",
            value=objective,
            source="objective_matrix",
            detail=f"goal={intent.goal!r} mapped to objective={objective!r}"
            + (" (overridden)" if objective_override else ""),
        ),
    ]

    plan_hash = _compute_plan_hash(
        objective=objective,
        canonical_schema=canonical_schema,
        target_rows=target_rows,
        examples_per_chunk=examples_per_chunk,
        generator_profile_id=generator_profile_id,
        judge_profile_id=judge_profile_id,
        required_validators=required_validators,
    )

    return TrainingPlan(
        objective=objective,
        canonical_schema=canonical_schema,
        target_rows=target_rows,
        examples_per_chunk=examples_per_chunk,
        generator_profile_id=generator_profile_id,
        judge_profile_id=judge_profile_id,
        required_validators=required_validators,
        evidence=evidence,
        confidence=model_profile.confidence,
        plan_hash=plan_hash,
    )

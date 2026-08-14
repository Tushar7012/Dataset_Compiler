from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel

from tuneforge.models.evidence import Evidence


class TrainingPlan(BaseModel):
    objective: Literal["cpt", "sft_prompt_completion", "sft_conversation", "dpo"]
    canonical_schema: str
    target_rows: int
    examples_per_chunk: int
    generator_profile_id: uuid.UUID | None
    judge_profile_id: uuid.UUID | None
    required_validators: list[str]
    evidence: list[Evidence]
    confidence: float
    plan_hash: str

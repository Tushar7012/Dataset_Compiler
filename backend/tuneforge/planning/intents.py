from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class TrainingIntent(BaseModel):
    goal: Literal[
        "domain_adaptation",
        "single_turn_instruction",
        "multi_turn_conversation",
        "preference_alignment",
    ]
    output_style: str | None = None

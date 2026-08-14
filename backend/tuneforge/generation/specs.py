from __future__ import annotations

from pydantic import BaseModel


class GenerationSpec(BaseModel):
    """Provider-independent description of what to generate — no provider
    or transport detail here, just the knobs that affect the output.
    """

    desired_behavior: str
    language: str = "en"
    max_candidates: int = 4  # DPO only: how many candidate answers to score
    score_margin: float = 2.0  # DPO only: min score gap to accept a pair (0-10 scale)
    max_retries: int = 2

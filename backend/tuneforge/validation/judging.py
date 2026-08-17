from __future__ import annotations

import json

from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import GenerationRequest, RunConsent
from tuneforge.records import DPORecord
from tuneforge.validation.structural import render_record_text


class JudgingError(RuntimeError):
    pass


async def judge_quality(
    judge: OpenAICompatibleProvider,
    record,
    *,
    pass_threshold: float = 6.0,
    consent: RunConsent | None = None,
) -> bool:
    """A general quality gate: does this training example look coherent and
    useful? Used as an optional pass for SFT/CPT (PLAN.md: judging is
    optional for those) and as one half of the mandatory DPO gate below.
    """
    text = render_record_text(record)
    prompt = (
        "Rate the quality of this training example from 0 (incoherent or "
        "useless) to 10 (clear, coherent, and useful for fine-tuning).\n\n"
        f"{text}\n\n"
        'Respond with only a JSON object: {"score": <number 0-10>}'
    )
    response = await judge.generate(
        GenerationRequest(messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}),
        consent=consent,
    )
    try:
        data = json.loads(response.content)
        score = float(data["score"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise JudgingError(f"judge response was not a valid score: {exc}") from exc
    return score >= pass_threshold


async def judge_dpo_preference(
    judge: OpenAICompatibleProvider,
    record: DPORecord,
    *,
    margin: float = 1.0,
    consent: RunConsent | None = None,
) -> bool:
    """DPO-specific and mandatory (PLAN.md): an *independent* re-check that
    chosen is actually better than rejected. Separate from whatever judging
    happened during generation (Task 9) — a normalized/imported DPO dataset
    never went through that at all, so this is the only judging it gets.
    """
    prompt_text = "\n".join(m.content for m in record.prompt)
    chosen_text = "\n".join(m.content for m in record.chosen)
    rejected_text = "\n".join(m.content for m in record.rejected)
    prompt = (
        "Given the PROMPT below, rate answer A and answer B independently from "
        "0 (bad) to 10 (excellent).\n\n"
        f"PROMPT: {prompt_text}\n\nANSWER A: {chosen_text}\n\nANSWER B: {rejected_text}\n\n"
        'Respond with only a JSON object: {"score_a": <0-10>, "score_b": <0-10>}'
    )
    response = await judge.generate(
        GenerationRequest(messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}),
        consent=consent,
    )
    try:
        data = json.loads(response.content)
        score_a = float(data["score_a"])
        score_b = float(data["score_b"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise JudgingError(f"judge response was not valid: {exc}") from exc
    return (score_a - score_b) >= margin

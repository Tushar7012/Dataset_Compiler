from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import RunConsent
from tuneforge.records import DPORecord
from tuneforge.validation.deduplication import deduplicate
from tuneforge.validation.judging import JudgingError, judge_dpo_preference, judge_quality
from tuneforge.validation.structural import StructuralValidationError, validate_structure, validate_token_length


@dataclass
class ValidationReport:
    accepted: list = field(default_factory=list)
    rejection_counts: dict[str, int] = field(default_factory=dict)
    assurance_level: Literal["standard_assurance", "lower_assurance"] = "lower_assurance"

    def record_rejection(self, reason: str) -> None:
        self.rejection_counts[reason] = self.rejection_counts.get(reason, 0) + 1


async def run_validation_pipeline(
    records: list,
    *,
    tokenizer,
    max_tokens: int,
    judge: OpenAICompatibleProvider | None = None,
    consent: RunConsent | None = None,
    apply_sft_judging: bool = False,
    dpo_judge_margin: float = 1.0,
) -> ValidationReport:
    """Order: structural + length checks (cheap, no I/O) -> deduplication
    (cheap, no I/O) -> judging (expensive, real LLM calls) — so the priciest
    step only ever runs on rows everything else has already accepted.

    Source-grounding is enforced upstream, at generation time (Task 9's
    generator rejects an ungrounded candidate before a record is ever
    produced) — it is not re-checked here. By the time a record reaches
    this pipeline, either it came from generation (already grounded) or
    from normalization (Task 8, no source chunk to ground against at all),
    and this pipeline only ever sees canonical records, not the original
    source text, so there is nothing here to re-verify against.
    """
    report = ValidationReport()
    structurally_valid = []

    for record in records:
        try:
            validate_structure(record)
            validate_token_length(record, tokenizer=tokenizer, max_tokens=max_tokens)
        except StructuralValidationError:
            report.record_rejection("structural")
            continue
        structurally_valid.append(record)

    dedup_result = deduplicate(structurally_valid)
    if dedup_result.exact_duplicates:
        report.rejection_counts["exact_duplicate"] = dedup_result.exact_duplicates
    if dedup_result.near_duplicates:
        report.rejection_counts["near_duplicate"] = dedup_result.near_duplicates

    judged_any = False
    accepted = []
    for record in dedup_result.kept:
        if isinstance(record, DPORecord):
            if judge is None:
                raise ValueError("DPO records require a judge provider — judging is mandatory, not optional")
            judged_any = True
            try:
                if not await judge_dpo_preference(judge, record, margin=dpo_judge_margin, consent=consent):
                    report.record_rejection("dpo_preference_not_confirmed")
                    continue
            except JudgingError:
                report.record_rejection("judging_error")
                continue
        elif apply_sft_judging and judge is not None:
            judged_any = True
            try:
                if not await judge_quality(judge, record, consent=consent):
                    report.record_rejection("quality_judged_insufficient")
                    continue
            except JudgingError:
                report.record_rejection("judging_error")
                continue
        accepted.append(record)

    report.accepted = accepted
    report.assurance_level = "standard_assurance" if judged_any else "lower_assurance"
    return report

from __future__ import annotations

import asyncio
import json
import logging

from tuneforge.generation.specs import GenerationSpec
from tuneforge.planning.schemas import TrainingPlan
from tuneforge.providers.openai_compatible import OpenAICompatibleProvider, extract_json_object
from tuneforge.providers.protocol import GenerationRequest, RunConsent
from tuneforge.records import (
    ChatMessage,
    CPTRecord,
    DPORecord,
    RecordMetadata,
    SFTConversationRecord,
    SFTPromptCompletionRecord,
    SourceRecord,
)

logger = logging.getLogger("tuneforge.generation")


class MalformedGenerationError(RuntimeError):
    pass


class GroundingError(RuntimeError):
    pass


def _metadata(source: SourceRecord, *, extra: dict | None = None) -> RecordMetadata:
    return RecordMetadata(
        document_id=source.document_id,
        source_name=source.source_name,
        source_hash=source.source_hash,
        chunk_id=source.chunk_id,
        extra=extra or {},
    )


def build_cpt_record(source: SourceRecord) -> CPTRecord:
    """CPT needs no generation at all — the training data *is* the source
    text. Calling an LLM here would be rewriting text PLAN.md says should
    pass through unmodified.
    """
    return CPTRecord(text=source.text, metadata=_metadata(source))


async def _generate_qa_candidate(
    provider: OpenAICompatibleProvider, source: SourceRecord, consent: RunConsent | None = None
) -> dict:
    prompt = (
        "You are generating a training example strictly grounded in the source text "
        "below. Ask one clear question a reader could answer using only this text, "
        "answer it accurately, and quote the exact sentence(s) from the source that "
        "support your answer — the quote must appear verbatim in the source.\n\n"
        f"Source text:\n{source.text}\n\n"
        'Respond with only a JSON object: {"question": "...", "answer": "...", '
        '"supporting_quote": "..."}'
    )
    response = await provider.generate(
        GenerationRequest(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        ),
        consent=consent,
    )
    try:
        candidate = json.loads(response.content)
    except json.JSONDecodeError as exc:
        raise MalformedGenerationError(f"response was not valid JSON: {exc}") from exc
    for field in ("question", "answer", "supporting_quote"):
        if not isinstance(candidate.get(field), str) or not candidate[field].strip():
            raise MalformedGenerationError(f"missing or empty field: {field!r}")
    if candidate["supporting_quote"] not in source.text:
        raise GroundingError(f"supporting_quote not found verbatim in source chunk {source.chunk_id}")
    return candidate


async def generate_sft_prompt_completion_record(
    provider: OpenAICompatibleProvider, source: SourceRecord, spec: GenerationSpec, consent: RunConsent | None = None
) -> SFTPromptCompletionRecord | None:
    last_error: Exception | None = None
    for _ in range(spec.max_retries + 1):
        try:
            candidate = await _generate_qa_candidate(provider, source, consent)
        except (MalformedGenerationError, GroundingError) as exc:
            last_error = exc
            continue
        return SFTPromptCompletionRecord(
            prompt=candidate["question"],
            completion=candidate["answer"],
            metadata=_metadata(source, extra={"supporting_quote": candidate["supporting_quote"]}),
        )
    logger.warning("rejected chunk %s after %d attempts: %s", source.chunk_id, spec.max_retries + 1, last_error)
    return None


async def generate_sft_conversation_record(
    provider: OpenAICompatibleProvider, source: SourceRecord, spec: GenerationSpec, consent: RunConsent | None = None
) -> SFTConversationRecord | None:
    last_error: Exception | None = None
    for _ in range(spec.max_retries + 1):
        try:
            candidate = await _generate_qa_candidate(provider, source, consent)
        except (MalformedGenerationError, GroundingError) as exc:
            last_error = exc
            continue
        return SFTConversationRecord(
            messages=[
                ChatMessage(role="user", content=candidate["question"]),
                ChatMessage(role="assistant", content=candidate["answer"]),
            ],
            metadata=_metadata(source, extra={"supporting_quote": candidate["supporting_quote"]}),
        )
    logger.warning("rejected chunk %s after %d attempts: %s", source.chunk_id, spec.max_retries + 1, last_error)
    return None


async def _score_candidate(
    judge: OpenAICompatibleProvider,
    *,
    question: str,
    answer: str,
    source: SourceRecord,
    consent: RunConsent | None = None,
) -> float:
    prompt = (
        "Rate how well the ANSWER responds to the QUESTION using only the SOURCE "
        "text below, on a scale from 0 (useless or wrong) to 10 (excellent, fully "
        "grounded in the source).\n\n"
        f"SOURCE:\n{source.text}\n\nQUESTION: {question}\n\nANSWER: {answer}\n\n"
        'Respond with only a JSON object: {"score": <number 0-10>}'
    )
    response = await judge.generate(
        GenerationRequest(messages=[{"role": "user", "content": prompt}]),
        consent=consent,
    )
    try:
        data = extract_json_object(response.content)
        return float(data["score"])
    except (ValueError, KeyError, TypeError) as exc:
        raise MalformedGenerationError(f"judge response was not a valid score: {exc}") from exc


async def _generate_and_score_candidate(
    generator: OpenAICompatibleProvider,
    judge: OpenAICompatibleProvider,
    *,
    question: str,
    source: SourceRecord,
    consent: RunConsent | None,
) -> tuple[float, str]:
    candidate = await _generate_qa_candidate(generator, source, consent)
    score = await _score_candidate(judge, question=question, answer=candidate["answer"], source=source, consent=consent)
    return score, candidate["answer"]


async def generate_dpo_record(
    generator: OpenAICompatibleProvider,
    judge: OpenAICompatibleProvider,
    source: SourceRecord,
    spec: GenerationSpec,
    consent: RunConsent | None = None,
) -> DPORecord | None:
    last_error: Exception | None = None
    for _ in range(spec.max_retries + 1):
        try:
            question_candidate = await _generate_qa_candidate(generator, source, consent)
            question = question_candidate["question"]

            # ponytail: the 4 candidates are independent draws — gather them
            # instead of a sequential loop. A candidate that errors mid-flight
            # still lets its siblings' already-issued requests run to
            # completion in the background (gather doesn't cancel them), so a
            # failing attempt can cost a few extra provider calls versus the
            # old fail-fast loop. Acceptable: it's the rare path (retries
            # already exist for it) and never affects a successful attempt.
            scored = list(
                await asyncio.gather(
                    *(
                        _generate_and_score_candidate(generator, judge, question=question, source=source, consent=consent)
                        for _ in range(spec.max_candidates)
                    )
                )
            )

            scored.sort(key=lambda pair: pair[0])
            worst_score, worst_answer = scored[0]
            best_score, best_answer = scored[-1]
            if best_score - worst_score < spec.score_margin:
                raise MalformedGenerationError(
                    f"candidate scores too close ({best_score} vs {worst_score}) — no clear preference"
                )
        except (MalformedGenerationError, GroundingError) as exc:
            last_error = exc
            continue

        return DPORecord(
            prompt=[ChatMessage(role="user", content=question)],
            chosen=[ChatMessage(role="assistant", content=best_answer)],
            rejected=[ChatMessage(role="assistant", content=worst_answer)],
            metadata=_metadata(source),
        )
    logger.warning("rejected DPO candidate for chunk %s after %d attempts: %s", source.chunk_id, spec.max_retries + 1, last_error)
    return None


async def generate_record(
    *,
    plan: TrainingPlan,
    source: SourceRecord,
    generator: OpenAICompatibleProvider,
    judge: OpenAICompatibleProvider | None,
    spec: GenerationSpec,
    consent: RunConsent | None = None,
):
    if plan.objective == "cpt":
        return build_cpt_record(source)
    if plan.objective == "sft_prompt_completion":
        return await generate_sft_prompt_completion_record(generator, source, spec, consent)
    if plan.objective == "sft_conversation":
        return await generate_sft_conversation_record(generator, source, spec, consent)
    if plan.objective == "dpo":
        if judge is None:
            raise ValueError("dpo generation requires a judge provider")
        return await generate_dpo_record(generator, judge, source, spec, consent)
    raise ValueError(f"unknown objective: {plan.objective}")

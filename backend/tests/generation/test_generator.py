import json
import uuid

import httpx

from tuneforge.generation.generator import (
    build_cpt_record,
    generate_dpo_record,
    generate_sft_conversation_record,
    generate_sft_prompt_completion_record,
)
from tuneforge.generation.specs import GenerationSpec
from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import ProviderProfile
from tuneforge.records import SourceRecord

SOURCE_TEXT = "Employees get 20 days of paid vacation per year."


def _source() -> SourceRecord:
    return SourceRecord(
        document_id=uuid.uuid4(),
        chunk_id="doc-0",
        text=SOURCE_TEXT,
        source_name="policy.md",
        source_hash="deadbeef",
        page=None,
        heading="Vacation Policy",
    )


def _provider(handler) -> OpenAICompatibleProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9999")
    profile = ProviderProfile(name="test", base_url="http://127.0.0.1:9999", model="test-model", endpoint_scope="local")
    return OpenAICompatibleProvider(profile, client)


def _chat_response(content: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


def test_cpt_record_is_a_passthrough_with_no_generation():
    source = _source()
    record = build_cpt_record(source)
    assert record.text == SOURCE_TEXT
    assert record.metadata.chunk_id == "doc-0"


async def test_sft_prompt_completion_accepts_grounded_candidate():
    def handler(request):
        return _chat_response(
            {"question": "How many vacation days?", "answer": "20 days.", "supporting_quote": "20 days of paid vacation"}
        )

    provider = _provider(handler)
    record = await generate_sft_prompt_completion_record(provider, _source(), GenerationSpec(desired_behavior="qa"))

    assert record is not None
    assert record.prompt == "How many vacation days?"
    assert record.completion == "20 days."
    assert record.metadata.extra["supporting_quote"] == "20 days of paid vacation"


async def test_sft_prompt_completion_rejects_ungrounded_quote_after_retries():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return _chat_response(
            {"question": "How many days?", "answer": "20", "supporting_quote": "this text is not in the source"}
        )

    provider = _provider(handler)
    record = await generate_sft_prompt_completion_record(
        provider, _source(), GenerationSpec(desired_behavior="qa", max_retries=2)
    )

    assert record is None
    assert calls["count"] == 3  # initial attempt + 2 retries


async def test_sft_prompt_completion_recovers_after_one_malformed_attempt():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
        return _chat_response(
            {"question": "How many days?", "answer": "20 days.", "supporting_quote": "20 days of paid vacation"}
        )

    provider = _provider(handler)
    record = await generate_sft_prompt_completion_record(
        provider, _source(), GenerationSpec(desired_behavior="qa", max_retries=2)
    )

    assert record is not None
    assert calls["count"] == 2


async def test_sft_conversation_produces_user_assistant_pair():
    def handler(request):
        return _chat_response(
            {"question": "How many vacation days?", "answer": "20 days.", "supporting_quote": "20 days of paid vacation"}
        )

    provider = _provider(handler)
    record = await generate_sft_conversation_record(provider, _source(), GenerationSpec(desired_behavior="chat"))

    assert record is not None
    assert [m.role for m in record.messages] == ["user", "assistant"]
    assert record.messages[0].content == "How many vacation days?"


async def test_dpo_record_picks_highest_and_lowest_scored_candidates():
    # generate_dpo_record makes one generator call to settle on a *question*
    # (its answer is discarded), then max_candidates more generator calls
    # each immediately followed by one judge call scoring that candidate's
    # answer. Matching on the answer text embedded in the judge prompt is
    # more robust here than counting call order.
    answer_scores = {"bad answer": 2.0, "ok answer": 5.0, "best answer": 9.0}
    candidate_answers = iter(["throwaway", "bad answer", "ok answer", "best answer"])

    def handler(request):
        payload = json.loads(request.content)
        prompt = payload["messages"][0]["content"]
        if "QUESTION:" in prompt:
            for answer, score in answer_scores.items():
                if f"ANSWER: {answer}" in prompt:
                    return _chat_response({"score": score})
            raise AssertionError(f"unscored answer in judge prompt: {prompt}")
        return _chat_response(
            {
                "question": "How many vacation days?",
                "answer": next(candidate_answers),
                "supporting_quote": "20 days of paid vacation",
            }
        )

    generator = _provider(handler)
    judge = _provider(handler)
    record = await generate_dpo_record(
        generator, judge, _source(), GenerationSpec(desired_behavior="dpo", max_candidates=3, score_margin=2.0)
    )

    assert record is not None
    assert record.chosen[0].content == "best answer"
    assert record.rejected[0].content == "bad answer"
    assert record.prompt[0].content == "How many vacation days?"


async def test_dpo_rejects_when_candidate_scores_are_too_close():
    answer_scores = {"answer-a": 5.0, "answer-b": 5.5, "answer-c": 5.2}
    candidate_answers = iter(["throwaway", "answer-a", "answer-b", "answer-c"])

    def handler(request):
        payload = json.loads(request.content)
        prompt = payload["messages"][0]["content"]
        if "QUESTION:" in prompt:
            for answer, score in answer_scores.items():
                if f"ANSWER: {answer}" in prompt:
                    return _chat_response({"score": score})
            raise AssertionError(f"unscored answer in judge prompt: {prompt}")
        return _chat_response(
            {
                "question": "How many days?",
                "answer": next(candidate_answers),
                "supporting_quote": "20 days of paid vacation",
            }
        )

    generator = _provider(handler)
    judge = _provider(handler)
    record = await generate_dpo_record(
        generator,
        judge,
        _source(),
        GenerationSpec(desired_behavior="dpo", max_candidates=3, score_margin=2.0, max_retries=0),
    )

    assert record is None

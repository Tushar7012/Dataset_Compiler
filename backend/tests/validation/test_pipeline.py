import json
import uuid

import httpx
import pytest

from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import ProviderProfile
from tuneforge.records import ChatMessage, CPTRecord, DPORecord, RecordMetadata, SFTPromptCompletionRecord
from tuneforge.validation.pipeline import run_validation_pipeline


class _FakeTokenizer:
    def encode(self, text: str) -> list[int]:
        return text.split()


def _metadata() -> RecordMetadata:
    return RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="deadbeef")


def _provider(handler) -> OpenAICompatibleProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9999")
    profile = ProviderProfile(name="judge", base_url="http://127.0.0.1:9999", model="judge-model", endpoint_scope="local")
    return OpenAICompatibleProvider(profile, client)


def _chat_response(content: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


async def test_pipeline_without_judging_marks_lower_assurance():
    records = [
        CPTRecord(text="Employees get 20 days of vacation.", metadata=_metadata()),
        CPTRecord(text="The office closes at 5pm on Fridays.", metadata=_metadata()),
    ]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100)

    assert len(report.accepted) == 2
    assert report.assurance_level == "lower_assurance"
    assert report.rejection_counts == {}


async def test_pipeline_drops_structurally_invalid_records():
    records = [
        CPTRecord(text="valid content here", metadata=_metadata()),
        SFTPromptCompletionRecord(prompt="hi", completion="   ", metadata=_metadata()),
    ]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100)

    assert len(report.accepted) == 1
    assert report.rejection_counts["structural"] == 1


async def test_pipeline_drops_records_over_token_limit():
    records = [CPTRecord(text="one two three four five six seven", metadata=_metadata())]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=3)

    assert len(report.accepted) == 0
    assert report.rejection_counts["structural"] == 1


async def test_pipeline_dedups_before_accepting():
    records = [
        CPTRecord(text="Employees get 20 days of vacation.", metadata=_metadata()),
        CPTRecord(text="Employees get 20 days of vacation.", metadata=_metadata()),
    ]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100)

    assert len(report.accepted) == 1
    assert report.rejection_counts["exact_duplicate"] == 1


async def test_pipeline_requires_judge_for_dpo_records():
    records = [
        DPORecord(
            prompt=[ChatMessage(role="user", content="q")],
            chosen=[ChatMessage(role="assistant", content="good")],
            rejected=[ChatMessage(role="assistant", content="bad")],
            metadata=_metadata(),
        )
    ]
    with pytest.raises(ValueError, match="judge"):
        await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100, judge=None)


async def test_pipeline_accepts_dpo_record_confirmed_by_judge_and_marks_standard_assurance():
    def handler(request):
        return _chat_response({"score_a": 9, "score_b": 2})

    judge = _provider(handler)
    records = [
        DPORecord(
            prompt=[ChatMessage(role="user", content="q")],
            chosen=[ChatMessage(role="assistant", content="good")],
            rejected=[ChatMessage(role="assistant", content="bad")],
            metadata=_metadata(),
        )
    ]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100, judge=judge)

    assert len(report.accepted) == 1
    assert report.assurance_level == "standard_assurance"


async def test_pipeline_rejects_dpo_record_when_judge_disagrees():
    def handler(request):
        return _chat_response({"score_a": 5, "score_b": 5.2})

    judge = _provider(handler)
    records = [
        DPORecord(
            prompt=[ChatMessage(role="user", content="q")],
            chosen=[ChatMessage(role="assistant", content="good")],
            rejected=[ChatMessage(role="assistant", content="bad")],
            metadata=_metadata(),
        )
    ]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100, judge=judge)

    assert len(report.accepted) == 0
    assert report.rejection_counts["dpo_preference_not_confirmed"] == 1


async def test_pipeline_applies_optional_sft_judging_when_requested():
    def handler(request):
        return _chat_response({"score": 2})

    judge = _provider(handler)
    records = [SFTPromptCompletionRecord(prompt="hi", completion="hello", metadata=_metadata())]
    report = await run_validation_pipeline(
        records, tokenizer=_FakeTokenizer(), max_tokens=100, judge=judge, apply_sft_judging=True
    )

    assert len(report.accepted) == 0
    assert report.rejection_counts["quality_judged_insufficient"] == 1
    assert report.assurance_level == "standard_assurance"


async def test_pipeline_skips_sft_judging_by_default():
    records = [SFTPromptCompletionRecord(prompt="hi", completion="hello", metadata=_metadata())]
    report = await run_validation_pipeline(records, tokenizer=_FakeTokenizer(), max_tokens=100, judge=None)

    assert len(report.accepted) == 1
    assert report.assurance_level == "lower_assurance"

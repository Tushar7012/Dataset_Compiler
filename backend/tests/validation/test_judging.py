import json
import uuid

import httpx
import pytest

from tuneforge.providers.openai_compatible import OpenAICompatibleProvider
from tuneforge.providers.protocol import ProviderProfile
from tuneforge.records import ChatMessage, CPTRecord, DPORecord, RecordMetadata
from tuneforge.validation.judging import JudgingError, judge_dpo_preference, judge_quality


def _metadata() -> RecordMetadata:
    return RecordMetadata(document_id=uuid.uuid4(), source_name="doc.md", source_hash="deadbeef")


def _provider(handler) -> OpenAICompatibleProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9999")
    profile = ProviderProfile(name="judge", base_url="http://127.0.0.1:9999", model="judge-model", endpoint_scope="local")
    return OpenAICompatibleProvider(profile, client)


def _chat_response(content: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


async def test_judge_quality_passes_above_threshold():
    def handler(request):
        return _chat_response({"score": 8})

    judge = _provider(handler)
    record = CPTRecord(text="Employees get 20 days of paid vacation.", metadata=_metadata())
    assert await judge_quality(judge, record, pass_threshold=6.0) is True


async def test_judge_quality_fails_below_threshold():
    def handler(request):
        return _chat_response({"score": 3})

    judge = _provider(handler)
    record = CPTRecord(text="garbled nonsense", metadata=_metadata())
    assert await judge_quality(judge, record, pass_threshold=6.0) is False


async def test_judge_quality_raises_on_malformed_response():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    judge = _provider(handler)
    record = CPTRecord(text="text", metadata=_metadata())
    with pytest.raises(JudgingError):
        await judge_quality(judge, record)


async def test_judge_dpo_preference_confirms_clear_winner():
    def handler(request):
        return _chat_response({"score_a": 9, "score_b": 3})

    judge = _provider(handler)
    record = DPORecord(
        prompt=[ChatMessage(role="user", content="q")],
        chosen=[ChatMessage(role="assistant", content="good")],
        rejected=[ChatMessage(role="assistant", content="bad")],
        metadata=_metadata(),
    )
    assert await judge_dpo_preference(judge, record, margin=1.0) is True


async def test_judge_dpo_preference_rejects_when_too_close():
    def handler(request):
        return _chat_response({"score_a": 5, "score_b": 4.8})

    judge = _provider(handler)
    record = DPORecord(
        prompt=[ChatMessage(role="user", content="q")],
        chosen=[ChatMessage(role="assistant", content="good")],
        rejected=[ChatMessage(role="assistant", content="bad")],
        metadata=_metadata(),
    )
    assert await judge_dpo_preference(judge, record, margin=1.0) is False

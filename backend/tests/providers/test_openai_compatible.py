import logging
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from tuneforge.providers.openai_compatible import (
    OpenAICompatibleProvider,
    ProviderAuthError,
    ProviderResponseError,
    RemoteConsentRequiredError,
)
from tuneforge.providers.protocol import GenerationRequest, ProviderProfile, RunConsent


def make_provider(handler, *, endpoint_scope="local", credential_reference=None):
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9999")
    profile = ProviderProfile(
        name="test",
        base_url="http://127.0.0.1:9999",
        model="test-model",
        endpoint_scope=endpoint_scope,
        credential_reference=credential_reference,
    )
    return OpenAICompatibleProvider(profile, client)


async def test_health_reports_ok_on_200():
    def handler(request):
        return httpx.Response(200, json={"data": []})

    provider = make_provider(handler)
    health = await provider.health()
    assert health.healthy is True


async def test_health_reports_unhealthy_on_error():
    def handler(request):
        return httpx.Response(500)

    provider = make_provider(handler)
    health = await provider.health()
    assert health.healthy is False


async def test_generate_returns_content_on_success():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    provider = make_provider(handler)
    result = await provider.generate(GenerationRequest(messages=[{"role": "user", "content": "hi"}]))
    assert result.content == "hello"


async def test_generate_retries_on_503_then_succeeds():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = make_provider(handler)
    result = await provider.generate(GenerationRequest(messages=[{"role": "user", "content": "hi"}]))
    assert result.content == "ok"
    assert calls["count"] == 3


async def test_generate_gives_up_after_max_retries():
    def handler(request):
        return httpx.Response(503)

    provider = make_provider(handler)
    with pytest.raises(ProviderResponseError):
        await provider.generate(GenerationRequest(messages=[{"role": "user", "content": "hi"}]))


async def test_generate_does_not_retry_auth_errors():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return httpx.Response(401)

    provider = make_provider(handler)
    with pytest.raises(ProviderAuthError):
        await provider.generate(GenerationRequest(messages=[{"role": "user", "content": "hi"}]))
    assert calls["count"] == 1


async def test_remote_provider_refuses_generation_without_consent():
    def handler(request):
        raise AssertionError("should not reach the network without consent")

    provider = make_provider(handler, endpoint_scope="remote")

    with pytest.raises(RemoteConsentRequiredError):
        await provider.generate(GenerationRequest(messages=[{"role": "user", "content": "hi"}]))


async def test_remote_provider_allows_generation_with_consent():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = make_provider(handler, endpoint_scope="remote")
    consent = RunConsent(run_id=uuid.uuid4(), granted_at=datetime.now(timezone.utc))

    result = await provider.generate(
        GenerationRequest(messages=[{"role": "user", "content": "hi"}]), consent=consent
    )
    assert result.content == "ok"


async def test_generate_logs_do_not_contain_prompt_or_credentials(caplog, monkeypatch):
    monkeypatch.setattr(
        "tuneforge.providers.openai_compatible.get_api_key", lambda ref: "super-secret-key"
    )

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = make_provider(handler, credential_reference="test-provider")
    secret_prompt = "the confidential document says XYZZY-SECRET"

    with caplog.at_level(logging.INFO, logger="tuneforge.providers"):
        await provider.generate(GenerationRequest(messages=[{"role": "user", "content": secret_prompt}]))

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "super-secret-key" not in log_text
    assert "XYZZY-SECRET" not in log_text

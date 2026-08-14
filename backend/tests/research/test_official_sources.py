import httpx
import pytest

from tuneforge.research.official_sources import SourceNotAllowedError, fetch_source, model_card_url


def test_model_card_url_points_at_huggingface():
    assert model_card_url("Qwen/Qwen2.5-7B-Instruct") == "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct"


async def test_fetch_source_rejects_non_allowlisted_host():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")))
    with pytest.raises(SourceNotAllowedError):
        await fetch_source("https://evil.example.com/page", client)


async def test_fetch_source_rejects_lookalike_host():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")))
    with pytest.raises(SourceNotAllowedError):
        await fetch_source("https://huggingface.co.attacker.com/page", client)


async def test_fetch_source_rejects_prefixed_lookalike_host():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")))
    with pytest.raises(SourceNotAllowedError):
        await fetch_source("https://evil-huggingface.co/page", client)


async def test_fetch_source_rejects_disallowed_github_repo():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")))
    with pytest.raises(SourceNotAllowedError):
        await fetch_source("https://github.com/some-random/repo", client)


async def test_fetch_source_rejects_non_https():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x")))
    with pytest.raises(SourceNotAllowedError):
        await fetch_source("http://huggingface.co/org/model", client)


async def test_fetch_source_allows_huggingface_model_card():
    def handler(request):
        return httpx.Response(200, text="This model uses a chat template for conversations.")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await fetch_source("https://huggingface.co/Qwen/Qwen2.5-7B-Instruct", client)

    assert result.url == "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct"
    assert result.sha256
    assert "chat template" in result.excerpt


async def test_fetch_source_allows_official_transformers_repo():
    def handler(request):
        return httpx.Response(200, text="docs")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await fetch_source("https://github.com/huggingface/transformers/blob/main/README.md", client)
    assert result.sha256


async def test_fetch_source_raises_on_http_error(monkeypatch):
    def handler(request):
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_source("https://huggingface.co/org/missing-model", client)

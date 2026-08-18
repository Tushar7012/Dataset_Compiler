import httpx
import pytest

from tuneforge.ingestion.documents import CorruptDocumentError, EncryptedDocumentError, convert_document
from tuneforge.ingestion.remote_parser import RemoteParsingUnavailableError, convert_document_remote


def _real_document_json(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("# Title\n\nReal remote content.\n")
    document = convert_document(path)
    return document, document.model_dump(mode="json")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_sends_bytes_filename_header_and_returns_the_document(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("# Title\n\nReal remote content.\n")
    _, document_json = _real_document_json(tmp_path)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["filename_header"] = request.headers.get("X-Document-Filename")
        captured["body"] = request.content
        return httpx.Response(200, json=document_json)

    document = convert_document_remote(path, base_url="http://dgx:9000", client=_client(handler))

    assert captured["url"] == "http://dgx:9000/convert"
    assert captured["filename_header"] == "policy.md"
    assert captured["body"] == path.read_bytes()
    assert "Real remote content." in document.export_to_markdown()


def test_forwards_bearer_token_when_provided(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("hi")
    _, document_json = _real_document_json(tmp_path)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=document_json)

    convert_document_remote(path, base_url="http://dgx:9000", token="tok-abc", client=_client(handler))

    assert captured["auth"] == "Bearer tok-abc"


def test_no_authorization_header_when_no_token_given(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("hi")
    _, document_json = _real_document_json(tmp_path)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=document_json)

    convert_document_remote(path, base_url="http://dgx:9000", client=_client(handler))

    assert captured["auth"] is None


def test_translates_422_encrypted_to_encrypted_document_error(tmp_path):
    path = tmp_path / "locked.pdf"
    path.write_bytes(b"fake pdf bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "encrypted"})

    with pytest.raises(EncryptedDocumentError):
        convert_document_remote(path, base_url="http://dgx:9000", client=_client(handler))


def test_translates_422_corrupt_to_corrupt_document_error(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"fake pdf bytes")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "corrupt", "detail": "bad stream"})

    with pytest.raises(CorruptDocumentError):
        convert_document_remote(path, base_url="http://dgx:9000", client=_client(handler))


def test_retries_on_503_then_succeeds(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("hi")
    _, document_json = _real_document_json(tmp_path)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=document_json)

    document = convert_document_remote(path, base_url="http://dgx:9000", client=_client(handler))

    assert calls["count"] == 3
    assert document is not None


def test_raises_remote_parsing_unavailable_after_exhausting_retries_on_5xx(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("hi")
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(503)

    with pytest.raises(RemoteParsingUnavailableError):
        convert_document_remote(path, base_url="http://dgx:9000", client=_client(handler))

    assert calls["count"] == 4  # initial attempt + 3 retries, then give up


def test_raises_remote_parsing_unavailable_on_connection_error(tmp_path):
    path = tmp_path / "policy.md"
    path.write_text("hi")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(RemoteParsingUnavailableError):
        convert_document_remote(path, base_url="http://dgx:9000", client=_client(handler))

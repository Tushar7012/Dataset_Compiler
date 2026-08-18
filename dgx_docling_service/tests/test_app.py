from io import BytesIO

import pytest
from docling.exceptions import ConversionError, SecurityError
from docling_core.types.doc.document import DoclingDocument
from fastapi.testclient import TestClient

from app import app, get_converter

MARKDOWN_BYTES = b"# Title\n\nSome real content here.\n"


class _FakeConverter:
    def __init__(self, *, raises: Exception | None = None, document=None):
        self._raises = raises
        self._document = document

    def convert(self, source):
        if self._raises is not None:
            raise self._raises
        return type("Result", (), {"document": self._document})()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_health_check_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_convert_rejects_missing_bearer_token(client, monkeypatch):
    monkeypatch.setattr("app._AUTH_TOKEN", "secret-token")
    response = client.post(
        "/convert", content=MARKDOWN_BYTES, headers={"X-Document-Filename": "doc.md"}
    )
    assert response.status_code == 401


def test_convert_rejects_wrong_bearer_token(client, monkeypatch):
    monkeypatch.setattr("app._AUTH_TOKEN", "secret-token")
    response = client.post(
        "/convert",
        content=MARKDOWN_BYTES,
        headers={"X-Document-Filename": "doc.md", "Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_convert_accepts_correct_bearer_token(client, monkeypatch):
    monkeypatch.setattr("app._AUTH_TOKEN", "secret-token")
    app.dependency_overrides[get_converter] = lambda: _FakeConverter(document=DoclingDocument(name="doc"))
    response = client.post(
        "/convert",
        content=MARKDOWN_BYTES,
        headers={"X-Document-Filename": "doc.md", "Authorization": "Bearer secret-token"},
    )
    assert response.status_code == 200


def test_convert_allows_any_request_when_no_token_configured(client, monkeypatch):
    monkeypatch.setattr("app._AUTH_TOKEN", None)
    app.dependency_overrides[get_converter] = lambda: _FakeConverter(document=DoclingDocument(name="doc"))
    response = client.post(
        "/convert", content=MARKDOWN_BYTES, headers={"X-Document-Filename": "doc.md"}
    )
    assert response.status_code == 200


def test_convert_returns_a_reconstructable_docling_document(client, monkeypatch):
    monkeypatch.setattr("app._AUTH_TOKEN", None)
    response = client.post(
        "/convert", content=MARKDOWN_BYTES, headers={"X-Document-Filename": "doc.md"}
    )

    assert response.status_code == 200
    document = DoclingDocument.model_validate(response.json())
    assert "Some real content here." in document.export_to_markdown()


def test_convert_translates_security_error_to_422_encrypted(client, monkeypatch):
    monkeypatch.setattr("app._AUTH_TOKEN", None)
    app.dependency_overrides[get_converter] = lambda: _FakeConverter(raises=SecurityError("locked"))
    response = client.post(
        "/convert", content=b"fake pdf bytes", headers={"X-Document-Filename": "locked.pdf"}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "encrypted"


def test_convert_translates_conversion_error_to_422_corrupt(client, monkeypatch):
    monkeypatch.setattr("app._AUTH_TOKEN", None)
    app.dependency_overrides[get_converter] = lambda: _FakeConverter(raises=ConversionError("broken"))
    response = client.post(
        "/convert", content=b"fake pdf bytes", headers={"X-Document-Filename": "broken.pdf"}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "corrupt"


def test_convert_requires_filename_header(client, monkeypatch):
    monkeypatch.setattr("app._AUTH_TOKEN", None)
    response = client.post("/convert", content=MARKDOWN_BYTES)
    assert response.status_code == 422

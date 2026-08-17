import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.providers import GEMINI_API_KEY_CREDENTIAL_NAME, router
from tuneforge.models.analyzer import HF_TOKEN_CREDENTIAL_NAME
from tuneforge.security.credentials import CredentialNotFoundError
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ProviderProfileRecord
from tuneforge.storage.repositories import ProjectRepository


@pytest.fixture
def client(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)
    app.state.artifact_store = ArtifactStore(tmp_path / "data")
    app.include_router(router, prefix="/api")
    test_client = TestClient(app)
    test_client.session_factory = app.state.session_factory
    test_client.artifact_store = app.state.artifact_store
    return test_client


def _project_id(client) -> uuid.UUID:
    session = client.session_factory()
    return ProjectRepository(session, client.artifact_store).create("proj").id


def test_create_local_provider_without_api_key_stores_no_credential_reference(client):
    response = client.post(
        "/api/providers",
        json={
            "project_id": str(_project_id(client)), "name": "ollama", "base_url": "http://127.0.0.1:11434",
            "model": "llama3", "endpoint_scope": "local",
        },
    )

    assert response.status_code == 201
    session = client.session_factory()
    stored = session.query(ProviderProfileRecord).one()
    assert stored.credential_reference is None


def test_create_remote_provider_with_api_key_stores_a_credential_reference_not_the_key(client, monkeypatch):
    stored_keys = {}
    monkeypatch.setattr(
        "tuneforge.api.providers.store_api_key", lambda ref, key: stored_keys.__setitem__(ref, key)
    )

    response = client.post(
        "/api/providers",
        json={
            "project_id": str(_project_id(client)), "name": "openai", "base_url": "https://api.openai.com/v1",
            "model": "gpt-4", "endpoint_scope": "remote", "api_key": "sk-super-secret",
        },
    )

    assert response.status_code == 201
    session = client.session_factory()
    stored = session.query(ProviderProfileRecord).one()
    assert stored.credential_reference is not None
    assert stored.credential_reference != "sk-super-secret"
    assert stored_keys[stored.credential_reference] == "sk-super-secret"


def test_remote_provider_without_api_key_falls_back_to_preconfigured_credential(client, monkeypatch):
    monkeypatch.setattr("tuneforge.api.providers.get_api_key", lambda name: "preconfigured-key")

    response = client.post(
        "/api/providers",
        json={
            "project_id": str(_project_id(client)), "name": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model": "gemini-2.5-flash", "endpoint_scope": "remote",
        },
    )

    assert response.status_code == 201
    session = client.session_factory()
    stored = session.query(ProviderProfileRecord).one()
    assert stored.credential_reference == GEMINI_API_KEY_CREDENTIAL_NAME


def test_hf_router_provider_without_api_key_falls_back_to_hf_token_credential(client, monkeypatch):
    monkeypatch.setattr("tuneforge.api.providers.get_api_key", lambda name: "preconfigured-key")

    response = client.post(
        "/api/providers",
        json={
            "project_id": str(_project_id(client)), "name": "hf-router-judge",
            "base_url": "https://router.huggingface.co/v1",
            "model": "Qwen/Qwen3-235B-A22B-Thinking-2507", "endpoint_scope": "remote",
        },
    )

    assert response.status_code == 201
    session = client.session_factory()
    stored = session.query(ProviderProfileRecord).one()
    assert stored.credential_reference == HF_TOKEN_CREDENTIAL_NAME


def test_remote_provider_without_api_key_or_preconfigured_credential_stores_none(client, monkeypatch):
    def _raise(name):
        raise CredentialNotFoundError(name)

    monkeypatch.setattr("tuneforge.api.providers.get_api_key", _raise)

    response = client.post(
        "/api/providers",
        json={
            "project_id": str(_project_id(client)), "name": "gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
            "model": "gemini-2.5-flash", "endpoint_scope": "remote",
        },
    )

    assert response.status_code == 201
    session = client.session_factory()
    stored = session.query(ProviderProfileRecord).one()
    assert stored.credential_reference is None


def test_invalid_endpoint_scope_is_rejected(client):
    response = client.post(
        "/api/providers",
        json={
            "project_id": str(_project_id(client)), "name": "x", "base_url": "http://x", "model": "x",
            "endpoint_scope": "not-a-real-scope",
        },
    )
    assert response.status_code == 422

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.models import router
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine
from tuneforge.storage.models import ModelProfileRecord
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


def test_analyze_persists_a_model_profile_record(client, monkeypatch):
    from tuneforge.models.analyzer import ModelProfile

    fake_profile = ModelProfile(
        source="huggingface", model_id="sshleifer/tiny-gpt2", architecture="GPT2LMHeadModel", model_type="gpt2",
        is_causal_lm=True, is_chat_model=False, chat_template_found=False, context_length=1024,
        modalities=["text"], evidence=[], confidence=0.95,
    )
    monkeypatch.setattr("tuneforge.api.models.analyze_model", lambda model_id, *, source: fake_profile)

    response = client.post(
        "/api/models/analyze", json={"model_id": "sshleifer/tiny-gpt2", "project_id": str(_project_id(client))}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model_id"] == "sshleifer/tiny-gpt2"
    assert body["is_causal_lm"] is True

    session = client.session_factory()
    stored = session.query(ModelProfileRecord).one()
    assert stored.model_id == "sshleifer/tiny-gpt2"
    assert stored.confidence == 0.95


def test_analyze_translates_incompatible_model_error_to_422(client, monkeypatch):
    from tuneforge.models.compatibility import IncompatibleModelError

    def raise_incompatible(model_id, *, source):
        raise IncompatibleModelError("not a causal LM")

    monkeypatch.setattr("tuneforge.api.models.analyze_model", raise_incompatible)

    response = client.post(
        "/api/models/analyze", json={"model_id": "bert-base-uncased", "project_id": str(_project_id(client))}
    )

    assert response.status_code == 422


def test_analyze_requires_model_id_and_project_id(client):
    response = client.post("/api/models/analyze", json={})
    assert response.status_code == 422

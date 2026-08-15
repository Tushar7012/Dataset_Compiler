from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.projects import router
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine


@pytest.fixture
def client(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "data" / "tuneforge.db")
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)
    app.state.artifact_store = ArtifactStore(tmp_path / "data")
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_create_project_returns_the_new_project(client):
    response = client.post("/api/projects", json={"name": "HR Policy Bot"})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "HR Policy Bot"
    assert "id" in body


def test_create_project_without_name_is_rejected(client):
    response = client.post("/api/projects", json={})
    assert response.status_code == 422


def test_delete_unknown_project_returns_404(client):
    import uuid

    response = client.delete(f"/api/projects/{uuid.uuid4()}")
    assert response.status_code == 404


def test_upload_source_stores_the_original_filename(client):
    create_response = client.post("/api/projects", json={"name": "proj"})
    project_id = create_response.json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": ("policy.md", b"# Policy\n\nContent here.", "text/markdown")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "policy.md"
    assert "source_hash" in body


def test_upload_source_to_unknown_project_returns_404(client):
    import uuid

    response = client.post(
        f"/api/projects/{uuid.uuid4()}/sources",
        files={"file": ("policy.md", b"content", "text/markdown")},
    )
    assert response.status_code == 404

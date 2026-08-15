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


def test_upload_source_rejects_path_traversal_in_filename(client, tmp_path):
    create_response = client.post("/api/projects", json={"name": "proj"})
    project_id = create_response.json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": ("../../../../../../outside_marker.txt", b"payload", "text/plain")},
    )

    assert response.status_code == 201
    assert response.json()["filename"] == "outside_marker.txt"
    assert not list(tmp_path.rglob("outside_marker.txt"))
    assert not any(
        (parent / "outside_marker.txt").exists() for parent in [tmp_path.parent, tmp_path.parent.parent]
    )


def _upload_csv(client, project_id, content: str, filename: str = "data.csv"):
    return client.post(
        f"/api/projects/{project_id}/sources",
        files={"file": (filename, content.encode(), "text/csv")},
    )


def test_get_schema_detects_prompt_completion_csv(client):
    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    source_id = _upload_csv(client, project_id, "prompt,completion\nHi,Hello there\nBye,Goodbye\n").json()["id"]

    response = client.get(f"/api/projects/{project_id}/sources/{source_id}/schema")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_name"] == "prompt_completion"
    assert body["confidence"] == 1.0
    assert set(body["columns"]) == {"prompt", "completion"}


def test_get_schema_returns_null_when_inconclusive(client):
    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    source_id = _upload_csv(client, project_id, "col_a,col_b\nfoo,bar\n").json()["id"]

    response = client.get(f"/api/projects/{project_id}/sources/{source_id}/schema")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_name"] is None
    assert set(body["columns"]) == {"col_a", "col_b"}


def test_get_schema_for_unknown_source_returns_404(client):
    import uuid

    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    response = client.get(f"/api/projects/{project_id}/sources/{uuid.uuid4()}/schema")
    assert response.status_code == 404


def test_normalize_preview_with_detected_schema(client):
    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    source_id = _upload_csv(client, project_id, "prompt,completion\nHi,Hello there\nBye,Goodbye\n").json()["id"]

    response = client.post(f"/api/projects/{project_id}/sources/{source_id}/normalize-preview", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["schema_name"] == "prompt_completion"
    assert body["total_rows"] == 2
    assert len(body["preview"]) == 2
    assert body["preview"][0]["prompt"] == "Hi"
    assert body["preview"][0]["completion"] == "Hello there"


def test_normalize_preview_with_manual_column_mapping(client):
    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    source_id = _upload_csv(client, project_id, "question,answer\nHi,Hello there\n").json()["id"]

    response = client.post(
        f"/api/projects/{project_id}/sources/{source_id}/normalize-preview",
        json={"mapping": {"question": "prompt", "answer": "completion"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_name"] == "prompt_completion"
    assert body["preview"][0]["prompt"] == "Hi"


def test_normalize_preview_without_mapping_when_inconclusive_returns_422(client):
    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    source_id = _upload_csv(client, project_id, "col_a,col_b\nfoo,bar\n").json()["id"]

    response = client.post(f"/api/projects/{project_id}/sources/{source_id}/normalize-preview", json={})

    assert response.status_code == 422


def test_normalize_preview_caps_at_20_rows_but_reports_the_real_total(client):
    lines = ["prompt,completion"] + [f"p{i},c{i}" for i in range(30)]
    project_id = client.post("/api/projects", json={"name": "proj"}).json()["id"]
    source_id = _upload_csv(client, project_id, "\n".join(lines) + "\n").json()["id"]

    response = client.post(f"/api/projects/{project_id}/sources/{source_id}/normalize-preview", json={})

    assert response.status_code == 200
    body = response.json()
    assert len(body["preview"]) == 20
    assert body["total_rows"] == 30

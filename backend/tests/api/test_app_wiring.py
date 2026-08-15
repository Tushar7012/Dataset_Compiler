from tuneforge.main import create_app
from tuneforge.settings import Settings


def test_all_routers_are_mounted(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = create_app(Settings())

    # Prefer OpenAPI paths — app.routes can include non-path wrappers
    # (_IncludedRouter) depending on FastAPI/Starlette version.
    paths = set(app.openapi()["paths"])
    assert "/api/projects" in paths
    assert "/api/models/analyze" in paths
    assert "/api/plans/recommend" in paths
    assert "/api/providers" in paths
    assert "/api/runs/preview" in paths
    assert "/api/runs/{run_id}/export" in paths
    assert "/api/exports/{run_id}/download" in paths


def test_project_endpoints_require_bearer_auth(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = create_app(Settings())
    client = TestClient(app)

    response = client.post("/api/projects", json={"name": "test"})

    assert response.status_code == 401

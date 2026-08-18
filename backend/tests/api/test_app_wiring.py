from tuneforge.main import create_app
from tuneforge.settings import Settings


def test_all_routers_are_mounted(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # docling_remote_url explicitly None — Settings() reads real process/dotenv
    # env vars same as production, so this must not depend on whatever the
    # developer's real .env currently has TUNEFORGE_DOCLING_REMOTE_URL set to.
    app = create_app(Settings(docling_remote_url=None))

    # Prefer OpenAPI paths — app.routes can include non-path wrappers
    # (_IncludedRouter) depending on FastAPI/Starlette version.
    paths = set(app.openapi()["paths"])
    assert "/api/projects" in paths
    assert "/api/models/analyze" in paths
    assert "/api/plans/recommend" in paths
    assert "/api/plans/estimated-rows" in paths
    assert "/api/plans/suggest-goal" in paths
    assert "/api/plans/{plan_id}/approve" in paths
    assert "/api/plans/{plan_id}/research" in paths
    assert "/api/providers" in paths
    assert "/api/runs/preview" in paths
    assert "/api/runs/{run_id}/export" in paths
    assert "/api/exports/{run_id}/download" in paths


def test_project_endpoints_require_bearer_auth(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # docling_remote_url explicitly None — Settings() reads real process/dotenv
    # env vars same as production, so this must not depend on whatever the
    # developer's real .env currently has TUNEFORGE_DOCLING_REMOTE_URL set to.
    app = create_app(Settings(docling_remote_url=None))
    client = TestClient(app)

    response = client.post("/api/projects", json={"name": "test"})

    assert response.status_code == 401

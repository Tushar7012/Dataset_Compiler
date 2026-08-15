import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tuneforge.main import create_app
from tuneforge.settings import Settings


def make_client(tmp_path: Path):
    app = create_app(Settings(data_dir=tmp_path))
    return app, TestClient(app)


def test_host_cannot_be_overridden_from_env(monkeypatch):
    monkeypatch.setenv("TUNEFORGE_HOST", "0.0.0.0")
    with pytest.raises(Exception):
        Settings()


def test_health_is_public(tmp_path):
    _, client = make_client(tmp_path)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_session_bootstrap_returns_token_without_auth_header(tmp_path):
    app, client = make_client(tmp_path)
    resp = client.get("/api/session")
    assert resp.status_code == 200
    assert resp.json() == {"token": app.state.session_token}


def test_session_bootstrap_rejects_mismatched_origin(tmp_path):
    _, client = make_client(tmp_path)
    resp = client.get("/api/session", headers={"Origin": "http://evil.example.com"})
    assert resp.status_code == 403


def test_session_bootstrap_allows_matching_origin(tmp_path):
    app, client = make_client(tmp_path)
    origin = f"http://127.0.0.1:{app.state.settings.port}"
    resp = client.get("/api/session", headers={"Origin": origin})
    assert resp.status_code == 200
    assert resp.json() == {"token": app.state.session_token}


def test_version_reports_configured_version(tmp_path):
    app, client = make_client(tmp_path)
    resp = client.get("/api/version")
    assert resp.status_code == 200
    assert resp.json() == {"version": app.state.settings.app_version}


def test_protected_endpoint_requires_bearer_token(tmp_path):
    _, client = make_client(tmp_path)
    resp = client.get("/api/echo-session")
    assert resp.status_code == 401


def test_protected_endpoint_accepts_correct_token(tmp_path):
    app, client = make_client(tmp_path)
    token = app.state.session_token
    resp = client.get("/api/echo-session", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_protected_endpoint_rejects_wrong_token(tmp_path):
    _, client = make_client(tmp_path)
    resp = client.get("/api/echo-session", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_mismatched_origin_is_rejected(tmp_path):
    app, client = make_client(tmp_path)
    token = app.state.session_token
    resp = client.get(
        "/api/echo-session",
        headers={"Authorization": f"Bearer {token}", "Origin": "http://evil.example.com"},
    )
    assert resp.status_code == 403


def test_matching_origin_is_allowed(tmp_path):
    app, client = make_client(tmp_path)
    token = app.state.session_token
    origin = f"http://127.0.0.1:{app.state.settings.port}"
    resp = client.get(
        "/api/echo-session",
        headers={"Authorization": f"Bearer {token}", "Origin": origin},
    )
    assert resp.status_code == 200


def test_session_token_never_appears_in_logs(caplog, tmp_path):
    app, _ = make_client(tmp_path)
    token = app.state.session_token
    with caplog.at_level(logging.INFO, logger="tuneforge"):
        logging.getLogger("tuneforge").info("session token is %s", token)
    for record in caplog.records:
        assert token not in record.getMessage()


def test_session_token_is_redacted_from_any_logger(caplog, tmp_path):
    # Redaction must not depend on which logger emits the record — uvicorn's
    # own loggers (uvicorn.access, uvicorn.error) never propagate through
    # "tuneforge", so this has to work at the record-factory level.
    app, _ = make_client(tmp_path)
    token = app.state.session_token
    other_logger = logging.getLogger("uvicorn.error")
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        other_logger.info("session token is %s", token)
    for record in caplog.records:
        assert token not in record.getMessage()

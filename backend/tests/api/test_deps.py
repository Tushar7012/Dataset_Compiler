from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from tuneforge.api.deps import get_session
from tuneforge.storage.db import create_session_factory, create_sqlite_engine


def _build_app(tmp_path: Path) -> FastAPI:
    engine = create_sqlite_engine(tmp_path / "tuneforge.db")
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)

    @app.get("/probe")
    def probe(session=Depends(get_session)):
        return {"is_active": session.is_active}

    return app


def test_get_session_provides_a_working_session(tmp_path):
    client = TestClient(_build_app(tmp_path))
    response = client.get("/probe")
    assert response.status_code == 200
    assert response.json()["is_active"] is True


def test_get_session_opens_a_fresh_session_per_request(tmp_path, monkeypatch):
    app = _build_app(tmp_path)
    seen_ids = []
    original_factory = app.state.session_factory

    def tracking_factory():
        session = original_factory()
        seen_ids.append(id(session))
        return session

    app.state.session_factory = tracking_factory
    client = TestClient(app)

    client.get("/probe")
    client.get("/probe")

    assert len(set(seen_ids)) == 2, "each request must get its own session, not a shared one"

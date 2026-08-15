from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from tuneforge.storage.artifacts import ArtifactStore


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_artifact_store(request: Request) -> ArtifactStore:
    return request.app.state.artifact_store

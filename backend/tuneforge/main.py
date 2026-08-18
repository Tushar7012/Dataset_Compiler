from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from tuneforge.api import exports, models, plans, projects, providers, runs
from tuneforge.security.log_redaction import install_log_redaction, register_redaction_token
from tuneforge.settings import Settings, generate_session_token
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine

logger = logging.getLogger("tuneforge")


def require_session(request: Request) -> None:
    auth_header = request.headers.get("authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or token != request.app.state.session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="TuneForge")
    app.state.settings = settings
    app.state.session_token = generate_session_token()
    register_redaction_token(lambda: getattr(app.state, "session_token", None))
    # Well-known .env credentials — redact whatever is currently in the process
    # environment (load_dotenv already ran at credentials import time), even
    # before any provider has resolved them via get_api_key.
    register_redaction_token(lambda: os.environ.get("GEMINI_API_KEY"))
    register_redaction_token(lambda: os.environ.get("HF_TOKEN"))
    register_redaction_token(lambda: os.environ.get("DGX_PARSER_TOKEN"))
    install_log_redaction()

    db_path = settings.data_dir / "tuneforge.db"
    engine = create_sqlite_engine(db_path)
    app.state.db_path = db_path
    app.state.session_factory = create_session_factory(engine)
    app.state.artifact_store = ArtifactStore(settings.data_dir)

    @app.middleware("http")
    async def enforce_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin is not None:
            expected = f"http://{settings.host}:{settings.port}"
            if origin != expected:
                return JSONResponse(status_code=403, content={"detail": "origin not allowed"})
        return await call_next(request)

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/version")
    async def version():
        return {"version": settings.app_version}

    @app.get("/api/session")
    async def session_bootstrap():
        """Let the SPA learn the process-generated session token.

        Unauthenticated by design — there is no other way for the browser to
        ever obtain the token before making its first authenticated request.
        Safe because the enforce_origin middleware above already rejects any
        request whose Origin doesn't match this app's own origin, and the
        app only ever binds to 127.0.0.1: only this machine's browser, on
        this exact origin, can reach it.
        """
        return {"token": app.state.session_token}

    @app.get("/api/echo-session", dependencies=[Depends(require_session)])
    async def echo_session():
        return {"status": "ok"}

    protected = [Depends(require_session)]
    app.include_router(projects.router, prefix="/api", dependencies=protected)
    app.include_router(models.router, prefix="/api", dependencies=protected)
    app.include_router(plans.router, prefix="/api", dependencies=protected)
    app.include_router(providers.router, prefix="/api", dependencies=protected)
    app.include_router(runs.router, prefix="/api", dependencies=protected)
    app.include_router(exports.router, prefix="/api", dependencies=protected)

    dist_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist_dir.exists():
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")

    return app


def main() -> None:
    import uvicorn

    settings = Settings()
    app = create_app(settings)
    logger.info("starting TuneForge on %s:%s", settings.host, settings.port)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from tuneforge.api import exports, models, plans, projects, providers, runs
from tuneforge.settings import Settings, generate_session_token
from tuneforge.storage.artifacts import ArtifactStore
from tuneforge.storage.db import create_session_factory, create_sqlite_engine

logger = logging.getLogger("tuneforge")


def require_session(request: Request) -> None:
    auth_header = request.headers.get("authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or token != request.app.state.session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")


_redaction_tokens: list = []
_redaction_installed = False


def _install_global_log_redaction() -> None:
    """Strip live session tokens from every log record, process-wide.

    A logging.Filter attached to one logger (e.g. "tuneforge") only runs for
    records created through that exact logger — it does not re-run for
    ancestors during propagation, and uvicorn's own loggers set
    propagate=False anyway. Wrapping the record factory instead catches
    every record regardless of which logger emitted it.
    """
    global _redaction_installed
    if _redaction_installed:
        return
    _redaction_installed = True
    original_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = original_factory(*args, **kwargs)
        message = record.getMessage()
        redacted = message
        for get_token in _redaction_tokens:
            token = get_token()
            if token and token in redacted:
                redacted = redacted.replace(token, "***REDACTED***")
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return record

    logging.setLogRecordFactory(factory)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="TuneForge")
    app.state.settings = settings
    app.state.session_token = generate_session_token()
    _redaction_tokens.append(lambda: getattr(app.state, "session_token", None))
    _install_global_log_redaction()

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

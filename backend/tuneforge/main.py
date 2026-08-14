from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from tuneforge.settings import Settings, generate_session_token

logger = logging.getLogger("tuneforge")


def require_session(request: Request) -> None:
    auth_header = request.headers.get("authorization", "")
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or token != request.app.state.session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")


class RedactTokenFilter(logging.Filter):
    """Strip live session token from log records before emission."""

    def __init__(self, app: FastAPI):
        super().__init__()
        self._app = app

    def filter(self, record: logging.LogRecord) -> bool:
        token = getattr(self._app.state, "session_token", None)
        if token:
            message = record.getMessage()
            if token in message:
                record.msg = message.replace(token, "***REDACTED***")
                record.args = ()
        return True


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="TuneForge")
    app.state.settings = settings
    app.state.session_token = generate_session_token()
    logger.addFilter(RedactTokenFilter(app))

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

    @app.get("/api/echo-session", dependencies=[Depends(require_session)])
    async def echo_session():
        return {"status": "ok"}

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

"""FastAPI application entry point: ``uvicorn app.main:app``."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import OperationalError

from app.api import channels, exports, ideas, jobs, reports, search, system, videos
from app.core.config import REPO_ROOT, get_env
from app.core.errors import StudioError
from app.core.logging import setup_logging

log = logging.getLogger(__name__)


def create_app(*, init: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        env = get_env()
        setup_logging(env.log_dir, "api", env.log_level)
        if init:
            from app.database.init_db import init_db

            init_db()
        yield

    app = FastAPI(title="YouTube Content Intelligence Studio", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(StudioError)
    async def _studio(_req: Request, exc: StudioError):
        return JSONResponse(status_code=400, content={"detail": exc.user_message, "kind": exc.kind})

    @app.exception_handler(OperationalError)
    async def _db(_req: Request, exc: OperationalError):
        msg = "The database is busy; please retry." if "locked" in str(exc).lower() else f"Database error: {exc.orig}"
        return JSONResponse(status_code=503, content={"detail": msg})

    for r in (system.router, channels.router, videos.router, ideas.router, jobs.router, search.router,
              reports.router, exports.router):
        app.include_router(r)

    dist = REPO_ROOT / "frontend" / "dist"
    if dist.exists():
        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            target = (dist / full_path).resolve()
            if full_path and target.is_file() and dist.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(dist / "index.html")

    return app


app = create_app()

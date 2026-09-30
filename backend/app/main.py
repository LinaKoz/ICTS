"""FastAPI application entrypoint.

Startup (§2): `alembic upgrade head`, then an idempotent seed, then
uvicorn. This module implements the lifespan that does the first two
steps and warms up the engine pool (§2 "Generation execution").
"""
from __future__ import annotations

import logging
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.auth.router import router as auth_router
from app.config import settings
from app.csrf import OriginCheckMiddleware
from app.db import async_session_factory, dispose_engine
from app.engine_pool import engine_pool
from app.errors import register_exception_handlers
from app.csvio.router import router as csv_router
from app.routers.meta import router as meta_router
from app.rosters.approval import router as approval_router
from app.rosters.edits import router as edits_router
from app.rosters.router import router as rosters_router
from app.workers.router import router as workers_router
from app.seed import seed

logger = logging.getLogger(__name__)
logging.basicConfig(level=settings.log_level)


def _run_migrations() -> None:
    """Runs `alembic upgrade head`."""
    subprocess.run(["alembic", "upgrade", "head"], check=True, cwd="/app")


async def _seed() -> None:
    """Idempotent seed: creates demo users, and if `workers` is empty,
    a small sample of workers and contracts (§2, §8 T2)."""
    async with async_session_factory() as session:
        await seed(session)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not settings.session_secret:
        logger.warning(
            "SESSION_SECRET is empty; generating a random secret for this process. "
            "Sessions will reset on restart."
        )
    _run_migrations()
    await _seed()
    await engine_pool.start()
    try:
        yield
    finally:
        await engine_pool.shutdown()
        await dispose_engine()


app = FastAPI(title="ICTS Rostering API", version="0.1.0", lifespan=lifespan)
register_exception_handlers(app)
app.add_middleware(OriginCheckMiddleware)
app.include_router(meta_router)
app.include_router(auth_router)
app.include_router(rosters_router)
app.include_router(workers_router)
app.include_router(edits_router)
app.include_router(approval_router)
app.include_router(csv_router)


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "engine": "ready" if engine_pool.ready else "not_ready",
    }


def export_openapi(path: str = "openapi.json") -> None:
    """Writes the current app's OpenAPI schema to `path`. Used by
    `scripts/export_openapi.py` (§8 T0 "OpenAPI export... a script")."""
    import json

    with open(path, "w") as f:
        json.dump(app.openapi(), f, indent=2)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)

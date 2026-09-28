"""Async SQLAlchemy 2 engine/session setup.

Table models (`app/*/models.py`) and Alembic migrations are added in T2
(§8). This module only wires up the engine, session factory and the
FastAPI dependency used to obtain a session.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models (added in T2)."""


engine = create_async_engine(settings.database_url, pool_pre_ping=True)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped async session."""
    async with async_session_factory() as session:
        yield session


async def dispose_engine() -> None:
    """Disposes the engine's connection pool. Called from the lifespan on shutdown."""
    await engine.dispose()

"""SQLAlchemy async engine, session factory, and FastAPI dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings


def _normalize_async_url(url: str) -> str:
    """Coerce common Postgres URL forms to the asyncpg driver.

    ``DATABASE_URL`` in ``.env`` is often written as
    ``postgresql://...`` for portability (psql, alembic sync), but the
    async engine requires ``postgresql+asyncpg://...``. We normalize so
    operators don't have to remember a separate URL.
    """
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


_settings = get_settings()

# Use NullPool so connections are not retained across event loops. This is
# crucial for the pytest-asyncio harness, where each test may run on a fresh
# loop and reusing a pooled asyncpg connection from a prior loop raises
# "got Future ... attached to a different loop". The performance cost is
# negligible for a single-host v0 deployment.
engine = create_async_engine(
    _normalize_async_url(_settings.database_url),
    poolclass=NullPool,
    future=True,
)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an ``AsyncSession``.

    The session is closed after the request. In the test harness,
    ``app.dependency_overrides[get_db]`` is replaced with a transactional
    session bound to a rollback-only outer transaction.
    """
    async with async_session_maker() as session:
        yield session

"""Async SQLAlchemy engine, session factory, and raw asyncpg connection pool.

Two database handles are provided:
- ``async_sessionmaker`` — used by FastAPI routes and services via SQLAlchemy ORM.
- ``asyncpg`` pool — used by ``TickBuffer`` for high-throughput COPY bulk inserts.
"""

from __future__ import annotations

import asyncpg
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import get_settings

# ── Module-level singletons (initialised lazily via init_db / get_*) ──────────

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_asyncpg_pool: asyncpg.Pool | None = None  # type: ignore[type-arg]


def _build_engine() -> AsyncEngine:
    """Create the SQLAlchemy async engine from application settings.

    Returns:
        A configured :class:`AsyncEngine` instance.
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


def get_engine() -> AsyncEngine:
    """Return the module-level :class:`AsyncEngine`, creating it on first call.

    Returns:
        The singleton :class:`AsyncEngine`.
    """
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the module-level ``async_sessionmaker``, creating it on first call.

    The factory is configured with ``expire_on_commit=False`` so that ORM
    objects remain usable after a ``session.commit()`` call without issuing
    extra SELECT queries.

    Returns:
        The singleton :class:`async_sessionmaker`.
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autobegin=True,
            autoflush=False,
        )
    return _session_factory


async def get_async_session() -> AsyncSession:
    """Async generator that yields a single :class:`AsyncSession` per request.

    Intended for use as a FastAPI dependency (via :mod:`src.dependencies`).
    The session is automatically closed when the context exits; callers are
    responsible for committing or rolling back.

    Yields:
        An open :class:`AsyncSession`.

    Example::

        async with get_async_session() as session:
            result = await session.execute(select(TradingPair))
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def get_asyncpg_pool() -> asyncpg.Pool:  # type: ignore[type-arg]
    """Return the module-level ``asyncpg`` connection pool for raw COPY operations.

    The pool is shared across the process lifetime and supports the
    ``copy_records_to_table`` bulk-insert path used by :class:`TickBuffer`.

    Returns:
        An open :class:`asyncpg.Pool`.

    Raises:
        RuntimeError: If the pool has not been initialised via :func:`init_db`.
    """
    global _asyncpg_pool
    if _asyncpg_pool is None:
        raise RuntimeError(
            "asyncpg pool is not initialised. Call init_db() at application startup."
        )
    return _asyncpg_pool


async def init_db() -> None:
    """Initialise both the SQLAlchemy engine and the raw asyncpg pool.

    Call this once at application startup (e.g. in the FastAPI lifespan handler
    or at the top of the ingestion service's ``main()``).

    Example::

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await init_db()
            yield
            await close_db()
    """
    global _asyncpg_pool
    settings = get_settings()

    # Ensure the SQLAlchemy engine is ready.
    get_engine()

    # Build raw asyncpg pool used for COPY bulk inserts.
    # Strip the SQLAlchemy driver prefix so asyncpg receives a plain DSN.
    raw_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    _asyncpg_pool = await asyncpg.create_pool(
        dsn=raw_dsn,
        min_size=2,
        max_size=10,
        command_timeout=60,
    )


async def close_db() -> None:
    """Close all database connections gracefully.

    Call this on application shutdown to ensure in-flight queries complete
    before the process exits.

    Example::

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await init_db()
            yield
            await close_db()
    """
    global _engine, _asyncpg_pool

    if _asyncpg_pool is not None:
        await _asyncpg_pool.close()
        _asyncpg_pool = None

    if _engine is not None:
        await _engine.dispose()
        _engine = None

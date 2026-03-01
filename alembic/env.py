"""Alembic environment for async SQLAlchemy migrations.

This module wires Alembic's ``MigrationContext`` to the async SQLAlchemy engine
built from ``src.config.Settings``.  TimescaleDB-specific DDL (hypertables,
continuous aggregates, compression/retention policies) is executed via raw SQL
in the migration scripts using ``op.execute()``.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from src.config import get_settings
from src.database.models import Base

# ── Alembic Config object (gives access to alembic.ini values) ───────────────
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Provide the ORM metadata so Alembic can detect model diffs automatically.
target_metadata = Base.metadata


def _get_url() -> str:
    """Return the database URL from application settings.

    Uses :func:`src.config.get_settings` so the ``DATABASE_URL`` environment
    variable (or ``.env`` file) is the single source of truth.

    Returns:
        The asyncpg-compatible connection string.
    """
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Generate migration SQL without connecting to the database.

    This mode is useful for producing SQL scripts that can be reviewed or
    applied manually (e.g. by a DBA).  Note that TimescaleDB-specific
    ``op.execute()`` calls will be included verbatim in the output.
    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Include all schemas in autogenerate comparisons
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_migrations_sync(connection: object) -> None:
    """Configure the migration context and run migrations synchronously.

    This helper is called inside ``asyncio.run()`` via
    :func:`run_migrations_online`.

    Args:
        connection: An open SQLAlchemy connection handed off from the async
            engine.
    """
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        include_schemas=True,
        # Compare server_defaults so Alembic detects DEFAULT changes
        compare_server_default=True,
        # Render ``AS IDENTITY`` for autoincrements where supported
        render_as_batch=False,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live database using an async engine.

    Creates a short-lived :class:`AsyncEngine` (``NullPool`` to avoid keeping
    idle connections), acquires a synchronous connection via
    ``run_sync``, and delegates to :func:`_run_migrations_sync`.
    """
    connectable = create_async_engine(
        _get_url(),
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as conn:
        await conn.run_sync(_run_migrations_sync)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

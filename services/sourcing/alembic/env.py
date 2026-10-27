"""
Alembic async environment configuration — AHP Sourcing Engine.

This module is executed by Alembic's ``alembic`` CLI and programmatic API.
It configures the migration context to use the async SQLAlchemy engine from
:mod:`app.db.session` and discovers all models via :mod:`app.db.base`.

Key points:
* Uses ``run_async_migrations()`` for online (connected) migrations.
* ``run_migrations_offline()`` emits raw SQL without a live connection.
* The ``target_metadata`` is sourced from ``Base.metadata`` which contains
  every table registered through :class:`app.db.base.Base`.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings

# Import Base *after* all models so that Base.metadata is fully populated.
# The models/__init__.py re-exports everything, which triggers registration.
from app.models import Candidate, CandidateSource, IngestionLog  # noqa: F401
from app.db.base import Base

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to alembic.ini values.
# ---------------------------------------------------------------------------
config = context.config

# Interpret the config file for Python logging (unless running from CLI
# with its own logging already configured).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the sqlalchemy.url with the value from application settings.
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# The MetaData object for 'autogenerate' support.
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline migrations — emit SQL to stdout, no DB connection required.
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL and not an ``Engine``. Calls to
    ``context.execute()`` emit the given SQL string to stdout.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online (async) migrations — connect to a live database.
# ---------------------------------------------------------------------------


def do_run_migrations(connection: Connection) -> None:
    """Execute migrations against the provided sync connection wrapper."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine, connect, and run migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — delegates to the async runner."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Entry point — Alembic calls this automatically.
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

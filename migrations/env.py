import asyncio

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.core.config import get_settings
from app.core.db import BASELINE_REVISION, LEGACY_TABLES, Base, include_in_autogenerate

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def _stamp_legacy_database(connection: Connection) -> None:
    """Databases created by create_all() before Alembic have tables but no version row.

    Mark them as already at the baseline revision so 0001 is not re-applied.
    Runs for both the app-startup path and the ``alembic`` CLI.
    """
    inspector = inspect(connection)
    if inspector.has_table("alembic_version"):
        return
    if not any(inspector.has_table(table) for table in LEGACY_TABLES):
        return
    script = ScriptDirectory.from_config(config)
    context.get_context().stamp(script, BASELINE_REVISION)


def _run_migrations(connection: Connection) -> None:
    # render_as_batch: SQLite cannot ALTER most things, batch mode recreates the table
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        include_name=include_in_autogenerate,
    )
    with context.begin_transaction():
        _stamp_legacy_database(connection)
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_async() -> None:
    engine = create_async_engine(_database_url())
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    # The app passes its own (sync-adapted) connection at startup; the CLI opens one.
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_migrations(connection)
    else:
        asyncio.run(_run_migrations_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

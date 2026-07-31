import os
import subprocess
import sys

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.db import BASELINE_REVISION, PROJECT_ROOT, Base, create_fts_objects, run_migrations


def _table_names(sync_conn) -> set[str]:
    return set(inspect(sync_conn).get_table_names())


async def test_migrations_build_schema_from_scratch(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations)
        tables = await conn.run_sync(_table_names)
        version = await conn.scalar(text("SELECT version_num FROM alembic_version"))
    await engine.dispose()
    assert {"publishers", "books", "book_sources", "fetch_runs", "book_fts"} <= tables
    assert version == BASELINE_REVISION


async def test_migrations_stamp_pre_alembic_database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(create_fts_objects)
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations)  # must not try to re-create existing tables
        version = await conn.scalar(text("SELECT version_num FROM alembic_version"))
    await engine.dispose()
    assert version == BASELINE_REVISION


async def test_migrations_are_idempotent_on_stamped_database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'twice.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations)
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations)
        version = await conn.scalar(text("SELECT version_num FROM alembic_version"))
    await engine.dispose()
    assert version == BASELINE_REVISION


async def test_alembic_cli_stamps_pre_alembic_database(tmp_path):
    db_path = tmp_path / "cli.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(create_fts_objects)
    await engine.dispose()

    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}"}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.connect() as conn:
        version = await conn.scalar(text("SELECT version_num FROM alembic_version"))
    await engine.dispose()
    assert version == BASELINE_REVISION

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.db import BASELINE_REVISION, Base, create_fts_objects, run_migrations


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

import os
import subprocess
import sys

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.db import ALEMBIC_INI, PROJECT_ROOT, Base, create_fts_objects, run_migrations


def _head_revision() -> str:
    cfg = AlembicConfig(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def _insert(sync_conn, table: str, **values) -> None:
    values.setdefault("created_at", "2026-01-01 00:00:00")
    values.setdefault("updated_at", "2026-01-01 00:00:00")
    columns = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    sync_conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params})"), values)


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
    assert version == _head_revision()


async def test_migrations_stamp_pre_alembic_database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(create_fts_objects)
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations)  # must not try to re-create existing tables
        version = await conn.scalar(text("SELECT version_num FROM alembic_version"))
    await engine.dispose()
    assert version == _head_revision()


async def test_migrations_are_idempotent_on_stamped_database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'twice.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations)
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations)
        version = await conn.scalar(text("SELECT version_num FROM alembic_version"))
    await engine.dispose()
    assert version == _head_revision()


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
    assert version == _head_revision()


async def test_migration_0002_keeps_newest_book_source_per_key(tmp_path):
    def seed(sync_conn):
        _insert(sync_conn, "publishers", id="pub", name="Pub")
        _insert(sync_conn, "books", id="b1", title="T", publisher_id="pub")
        for row_id, key, fetched_at in [
            ("old", "k1", "2026-01-01 00:00:00"),
            ("newest", "k1", "2026-03-01 00:00:00"),
            ("middle", "k1", "2026-02-01 00:00:00"),
            ("other", "k2", "2026-01-01 00:00:00"),
        ]:
            _insert(
                sync_conn,
                "book_sources",
                id=row_id,
                book_id="b1",
                source="dmk_html",
                source_key=key,
                fetched_at=fetched_at,
            )

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'dupes.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations, "0001")
        await conn.run_sync(seed)
        await conn.run_sync(run_migrations)
        ids = set((await conn.scalars(text("SELECT id FROM book_sources"))).all())
        indexes = await conn.run_sync(lambda c: inspect(c).get_indexes("book_sources"))
    await engine.dispose()
    assert ids == {"newest", "other"}
    assert {"name": "ux_book_sources_book_source_key", "unique": 1} in [
        {"name": ix["name"], "unique": ix["unique"]} for ix in indexes
    ]


async def test_migration_0003_recomputes_dedupe_keys(tmp_path):
    import hashlib

    def seed(sync_conn):
        _insert(sync_conn, "publishers", id="pub", name="Pub")
        _insert(
            sync_conn,
            "books",
            id="b1",
            title="Swift Recipes.",
            publisher_id="pub",
            authors='["Nathan B. Crocker", "Other"]',
            dedupe_key="old",
        )
        _insert(sync_conn, "books", id="b2", title="No Authors", publisher_id="pub")

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'keys.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations, "0002")
        await conn.run_sync(seed)
        await conn.run_sync(run_migrations)
        keys = dict((await conn.execute(text("SELECT id, dedupe_key FROM books"))).all())
    await engine.dispose()
    assert keys == {
        "b1": hashlib.sha1(b"swift recipes|pub|crocker").hexdigest(),
        "b2": hashlib.sha1(b"no authors|pub|").hexdigest(),
    }


async def test_migration_0004_scrubs_query_strings_from_fetch_run_errors(tmp_path):
    def seed(sync_conn):
        _insert(
            sync_conn,
            "fetch_runs",
            id="leaky",
            status="error",
            new_count=0,
            updated_count=0,
            error="for url 'https://example.com/v1?q=x&key=SECRET'",
        )
        _insert(sync_conn, "fetch_runs", id="clean", status="success", new_count=0, updated_count=0)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations, "0003")
        await conn.run_sync(seed)
        await conn.run_sync(run_migrations)
        errors = dict((await conn.execute(text("SELECT id, error FROM fetch_runs"))).all())
    await engine.dispose()
    assert errors == {"leaky": "for url 'https://example.com/v1?<redacted>'", "clean": None}


async def test_migration_0005_normalizes_languages(tmp_path):
    codes = {"b1": "eng", "b2": "en-US", "b3": "ru", "b4": None, "b5": "XX"}

    def seed(sync_conn):
        _insert(sync_conn, "publishers", id="pub", name="Pub")
        for book_id, code in codes.items():
            _insert(
                sync_conn, "books", id=book_id, title=book_id, publisher_id="pub", language=code
            )

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'langs.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations, "0004")
        await conn.run_sync(seed)
        await conn.run_sync(run_migrations)
        langs = dict((await conn.execute(text("SELECT id, language FROM books"))).all())
    await engine.dispose()
    assert langs == {"b1": "en", "b2": "en", "b3": "ru", "b4": None, "b5": "xx"}


async def test_migrated_fts_index_follows_book_writes(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fts.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(run_migrations)
        await conn.run_sync(lambda c: _insert(c, "publishers", id="pub", name="Pub"))
        await conn.run_sync(
            lambda c: _insert(c, "books", id="b1", title="Rust in Action", publisher_id="pub")
        )
        await conn.execute(text("UPDATE books SET title = 'Go in Action' WHERE id = 'b1'"))
        found = (
            await conn.scalars(text("SELECT rowid FROM book_fts WHERE book_fts MATCH 'go'"))
        ).all()
        stale = (
            await conn.scalars(text("SELECT rowid FROM book_fts WHERE book_fts MATCH 'rust'"))
        ).all()
        triggers = set(
            (
                await conn.scalars(text("SELECT name FROM sqlite_master WHERE type = 'trigger'"))
            ).all()
        )
    await engine.dispose()
    assert (len(found), stale) == (1, [])
    assert triggers == {"books_ai", "books_au", "books_ad"}

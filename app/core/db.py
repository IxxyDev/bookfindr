import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Connection, String, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import PROJECT_ROOT, get_settings

logger = logging.getLogger(__name__)

ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
# Revision that matches the schema create_all() produced before Alembic was introduced;
# migrations/env.py stamps databases that already have these tables but no version row.
BASELINE_REVISION = "0001"
LEGACY_TABLES = ("publishers", "books", "book_sources", "fetch_runs")

_engine: AsyncEngine | None = None
_async_session: async_sessionmaker[AsyncSession] | None = None


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


def enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """SQLite ignores FOREIGN KEY constraints unless the pragma is set per connection."""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _json_dumps(value) -> str:
    # Readable non-ASCII: escaped JSON ("\\u0417...") hides Cyrillic from FTS and LIKE
    return json.dumps(value, ensure_ascii=False)


def make_engine(url: str) -> AsyncEngine:
    """The app's engine setup; tests build theirs with it too."""
    is_sqlite = url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_async_engine(
        url, echo=False, connect_args=connect_args, json_serializer=_json_dumps
    )
    if is_sqlite:
        enable_sqlite_foreign_keys(engine)
    return engine


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
    return _engine


def get_async_session() -> async_sessionmaker[AsyncSession]:
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _async_session


async def get_session() -> AsyncGenerator[AsyncSession]:
    async with get_async_session()() as session:
        yield session


async def rebuild_fts_index() -> None:
    async with get_engine().begin() as conn:
        await conn.exec_driver_sql("INSERT INTO book_fts(book_fts) VALUES('rebuild')")


def include_in_autogenerate(name: str | None, type_: str, _parent_names) -> bool:
    """Alembic include_name hook: book_fts and its shadow tables are not ORM models,
    so autogenerate must not propose dropping them."""
    return not (type_ == "table" and name and name.startswith("book_fts"))


def create_fts_objects(conn) -> None:
    """Create FTS5 virtual table and triggers (idempotent; tests build schemas with it).

    Migration 0001 holds its own frozen copy of this SQL.
    """
    conn.exec_driver_sql(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS book_fts
        USING fts5(title, description, authors, content='books', content_rowid='rowid');
        """
    )
    conn.exec_driver_sql(
        """
        CREATE TRIGGER IF NOT EXISTS books_ai AFTER INSERT ON books BEGIN
            INSERT INTO book_fts(rowid, title, description, authors)
            VALUES (
                new.rowid,
                coalesce(new.title,''),
                coalesce(new.description,''),
                coalesce(new.authors,'')
            );
        END;
        """
    )
    conn.exec_driver_sql(
        """
        CREATE TRIGGER IF NOT EXISTS books_au AFTER UPDATE ON books BEGIN
            INSERT INTO book_fts(book_fts, rowid, title, description, authors)
            VALUES('delete', old.rowid, old.title, old.description, old.authors);
            INSERT INTO book_fts(rowid, title, description, authors)
            VALUES (
                new.rowid,
                coalesce(new.title,''),
                coalesce(new.description,''),
                coalesce(new.authors,'')
            );
        END;
        """
    )
    conn.exec_driver_sql(
        """
        CREATE TRIGGER IF NOT EXISTS books_ad AFTER DELETE ON books BEGIN
            INSERT INTO book_fts(book_fts, rowid, title, description, authors)
            VALUES(
                'delete',
                old.rowid,
                old.title,
                old.description,
                old.authors
            );
        END;
        """
    )


def _alembic_config(connection: Connection) -> AlembicConfig:
    cfg = AlembicConfig(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.attributes["connection"] = connection
    return cfg


def run_migrations(connection: Connection, revision: str = "head") -> None:
    """Upgrade the schema to ``revision`` (sync; call via ``conn.run_sync``)."""
    command.upgrade(_alembic_config(connection), revision)


async def init_db() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(run_migrations)
    await rebuild_fts_index()


def run_migrations_blocking() -> None:
    asyncio.run(init_db())

import asyncio
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


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        is_sqlite = settings.database_url.startswith("sqlite")
        connect_args = {"check_same_thread": False} if is_sqlite else {}
        _engine = create_async_engine(settings.database_url, echo=False, connect_args=connect_args)
        if is_sqlite:
            enable_sqlite_foreign_keys(_engine)
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


FTS_OBJECTS_DROP_SQL = (
    "DROP TRIGGER IF EXISTS books_ai",
    "DROP TRIGGER IF EXISTS books_au",
    "DROP TRIGGER IF EXISTS books_ad",
    "DROP TABLE IF EXISTS book_fts",
)


def create_fts_objects(conn) -> None:
    """Create FTS5 virtual table and triggers (idempotent; used by migration 0001 and tests)."""
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

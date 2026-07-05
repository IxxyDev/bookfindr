import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from sqlalchemy import String
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_async_session: async_sessionmaker[AsyncSession] | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = (
            {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
        )
        _engine = create_async_engine(settings.database_url, echo=False, connect_args=connect_args)
    return _engine


def get_async_session() -> async_sessionmaker[AsyncSession]:
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _async_session


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_async_session()() as session:
        yield session


async def rebuild_fts_index() -> None:
    async with get_engine().begin() as conn:
        await conn.exec_driver_sql("INSERT INTO book_fts(book_fts) VALUES('rebuild')")


def create_fts_objects(conn) -> None:
    """Create FTS5 virtual table and triggers (used in sync context)."""
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


async def init_db() -> None:
    # Import models for metadata
    from app import models  # noqa: F401

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(create_fts_objects)
    await rebuild_fts_index()


def run_migrations_blocking() -> None:
    asyncio.run(init_db())

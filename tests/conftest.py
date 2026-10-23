from datetime import date
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import Base, create_fts_objects, make_engine
from app.models.book import Book
from app.models.publisher import Publisher


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture()
async def db_engine():
    engine = make_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(create_fts_objects)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture()
async def client(db_engine, monkeypatch):
    from app.core import db
    from app.core.db import get_session
    from app.main import app

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    # Background syncs open their own session via get_async_session(): keep them on the test DB
    monkeypatch.setattr(db, "_async_session", session_factory)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture()
async def sample_publisher(db_session: AsyncSession) -> Publisher:
    pub = Publisher(
        id="oreilly",
        name="O'Reilly Media",
        aliases=["OReilly"],
        languages=["en"],
    )
    db_session.add(pub)
    await db_session.commit()
    return pub


@pytest.fixture()
async def sample_book(db_session: AsyncSession, sample_publisher: Publisher) -> Book:
    book = Book(
        id=str(uuid4()),
        title="Learning Python",
        subtitle="Powerful Object-Oriented Programming",
        authors=["Mark Lutz"],
        publisher_id=sample_publisher.id,
        language="en",
        subjects=["computers", "programming"],
        topics=["python"],
        description="A comprehensive guide to the Python programming language.",
        isbn_13="9781449355739",
        isbn_10="1449355730",
        dedupe_key="test-dedupe-key",
        page_count=1648,
        print_type="BOOK",
        published_date=date(2024, 6, 15),
        cover_url="https://example.com/cover.jpg",
        info_url="https://example.com/book",
        source_primary="google_books",
        source_keys={"google_books": "abc123"},
    )
    db_session.add(book)
    await db_session.commit()
    return book

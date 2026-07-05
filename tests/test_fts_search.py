from datetime import date
from uuid import uuid4

import pytest

from app.models.book import Book
from app.models.publisher import Publisher
from app.repositories.books import BookFilters, BookRepository


@pytest.fixture()
async def fts_publisher(db_session) -> Publisher:
    pub = Publisher(id="ftspub", name="FTS Publisher")
    db_session.add(pub)
    await db_session.flush()
    return pub


@pytest.fixture()
async def fts_books(db_session, fts_publisher) -> list[Book]:
    books_data = [
        {
            "title": "Advanced Python Programming",
            "description": "Deep dive into Python internals and advanced techniques",
        },
        {
            "title": "Kubernetes in Action",
            "description": "Deploying containerized applications at scale",
        },
        {
            "title": "Database Internals",
            "description": "A deep dive into how distributed data systems work",
        },
    ]
    created = []
    for data in books_data:
        book = Book(
            id=str(uuid4()),
            title=data["title"],
            publisher_id=fts_publisher.id,
            description=data["description"],
            language="en",
            published_date=date(2024, 6, 15),
            dedupe_key=f"fts-{uuid4().hex[:8]}",
            source_primary="google_books",
            source_keys={},
        )
        db_session.add(book)
        created.append(book)
    await db_session.flush()
    return created


async def test_fts_search_by_title(db_session, fts_books):
    repo = BookRepository(db_session)
    result = await repo.list(BookFilters(query="Python"), limit=50, offset=0)
    titles = [b.title for b in result]
    assert "Advanced Python Programming" in titles


async def test_fts_search_by_description(db_session, fts_books):
    repo = BookRepository(db_session)
    result = await repo.list(BookFilters(query="containerized"), limit=50, offset=0)
    titles = [b.title for b in result]
    assert "Kubernetes in Action" in titles


async def test_fts_search_no_results(db_session, fts_books):
    repo = BookRepository(db_session)
    result = await repo.list(BookFilters(query="nonexistentterm12345"), limit=50, offset=0)
    assert len(result) == 0


async def test_fts_count(db_session, fts_books):
    repo = BookRepository(db_session)
    count = await repo.count(BookFilters(query="Python"))
    assert count >= 1


async def test_fts_search_multiple_terms(db_session, fts_books):
    repo = BookRepository(db_session)
    result = await repo.list(BookFilters(query="deep dive"), limit=50, offset=0)
    assert len(result) >= 1

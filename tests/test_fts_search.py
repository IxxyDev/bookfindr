from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text

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
    result, _ = await repo.list_with_count(BookFilters(query="Python"), limit=50, offset=0)
    titles = [b.title for b in result]
    assert "Advanced Python Programming" in titles


async def test_fts_search_by_description(db_session, fts_books):
    repo = BookRepository(db_session)
    result, _ = await repo.list_with_count(BookFilters(query="containerized"), limit=50, offset=0)
    titles = [b.title for b in result]
    assert "Kubernetes in Action" in titles


async def test_fts_search_no_results(db_session, fts_books):
    repo = BookRepository(db_session)
    result, _ = await repo.list_with_count(
        BookFilters(query="nonexistentterm12345"), limit=50, offset=0
    )
    assert len(result) == 0


async def test_fts_count(db_session, fts_books):
    repo = BookRepository(db_session)
    _, count = await repo.list_with_count(BookFilters(query="Python"), limit=1, offset=0)
    assert count >= 1


async def test_fts_search_multiple_terms(db_session, fts_books):
    repo = BookRepository(db_session)
    result, _ = await repo.list_with_count(BookFilters(query="deep dive"), limit=50, offset=0)
    assert len(result) >= 1


async def test_fts_query_with_quotes_does_not_error(db_session, fts_books, caplog):
    repo = BookRepository(db_session)
    filters = BookFilters(query='python "internals')
    with caplog.at_level("WARNING"):
        books, total = await repo.list_with_count(filters, limit=10, offset=0)
    assert "FTS5 search failed" not in caplog.text
    assert total == 1
    assert books[0].title == "Advanced Python Programming"


async def test_like_fallback_escapes_wildcards(db_session, fts_books):
    repo = BookRepository(db_session)
    assert repo._escape_like("100%_sure") == r"100\%\_sure"
    assert repo._escape_like(r"50\_off") == r"50\\\_off"


async def test_whitespace_only_query_is_ignored(db_session, fts_books):
    repo = BookRepository(db_session)
    _, total = await repo.list_with_count(BookFilters(query="   "), limit=10, offset=0)
    assert total == len(fts_books)


async def test_last_token_matches_as_prefix(db_session, fts_books):
    repo = BookRepository(db_session)
    books, total = await repo.list_with_count(BookFilters(query="Pyth"), limit=10, offset=0)
    assert (total, [b.title for b in books]) == (1, ["Advanced Python Programming"])

    _, total = await repo.list_with_count(BookFilters(query="deep di"), limit=10, offset=0)
    assert total == 2


async def test_only_the_last_token_is_a_prefix(db_session, fts_books):
    repo = BookRepository(db_session)
    _, total = await repo.list_with_count(BookFilters(query="Pyth internals"), limit=10, offset=0)
    assert total == 0


async def test_like_fallback_when_fts_index_is_missing(db_session, fts_books, caplog):
    await db_session.execute(text("DROP TABLE book_fts"))
    repo = BookRepository(db_session)
    with caplog.at_level("WARNING"):
        books, total = await repo.list_with_count(
            BookFilters(query="kubernetes", language="en"), limit=10, offset=0
        )
    assert "FTS5 search failed" in caplog.text
    assert (total, [b.title for b in books]) == (1, ["Kubernetes in Action"])


async def test_fts_search_combines_with_filters_and_paginates(db_session, fts_books):
    repo = BookRepository(db_session)
    filters = BookFilters(query="deep", publisher_id="ftspub", date_from=date(2024, 1, 1))
    page, total = await repo.list_with_count(filters, limit=1, offset=1)
    assert total == 2
    assert len(page) == 1


async def test_like_fallback_searches_authors(db_session, fts_books, fts_publisher):
    db_session.add(
        Book(
            id=str(uuid4()),
            title="Python Crash Course",
            authors=["Eric Matthes"],
            publisher_id=fts_publisher.id,
            published_date=date(2024, 6, 15),
        )
    )
    await db_session.flush()
    await db_session.execute(text("DROP TABLE book_fts"))

    repo = BookRepository(db_session)
    books, total = await repo.list_with_count(BookFilters(query="matthes"), limit=10, offset=0)
    assert (total, [b.title for b in books]) == (1, ["Python Crash Course"])

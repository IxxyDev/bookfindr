from datetime import date
from uuid import uuid4

import pytest

from app.models.book import Book
from app.models.publisher import Publisher
from app.repositories.books import BookFilters, BookRepository


@pytest.fixture()
async def repo(db_session):
    return BookRepository(db_session)


@pytest.fixture()
async def publisher(db_session) -> Publisher:
    pub = Publisher(id="testpub", name="Test Publisher")
    db_session.add(pub)
    await db_session.flush()
    return pub


@pytest.fixture()
async def books(db_session, publisher) -> list[Book]:
    items = []
    for i in range(5):
        book = Book(
            id=str(uuid4()),
            title=f"Book Title {i}",
            publisher_id=publisher.id,
            language="en" if i % 2 == 0 else "ru",
            subjects=["computers"],
            description=f"Description for book {i}",
            published_date=date(2024, 6, i + 1),
            dedupe_key=f"dk-{i}",
            source_primary="google_books",
            source_keys={},
        )
        items.append(book)
        db_session.add(book)
    await db_session.flush()
    return items


async def test_list_no_filters(repo, books):
    result, _ = await repo.list_with_count(BookFilters(), limit=50, offset=0)
    assert len(result) == 5


async def test_list_filter_by_publisher(repo, books):
    result, _ = await repo.list_with_count(BookFilters(publisher_id="testpub"), limit=50, offset=0)
    assert len(result) == 5

    result, _ = await repo.list_with_count(
        BookFilters(publisher_id="nonexistent"), limit=50, offset=0
    )
    assert len(result) == 0


async def test_list_filter_by_language(repo, books):
    result, _ = await repo.list_with_count(BookFilters(language="en"), limit=50, offset=0)
    assert len(result) == 3  # indices 0, 2, 4


async def test_list_pagination(repo, books):
    page1, _ = await repo.list_with_count(BookFilters(), limit=2, offset=0)
    assert len(page1) == 2

    page2, _ = await repo.list_with_count(BookFilters(), limit=2, offset=2)
    assert len(page2) == 2

    page3, _ = await repo.list_with_count(BookFilters(), limit=2, offset=4)
    assert len(page3) == 1


async def test_list_date_range(repo, books):
    result, _ = await repo.list_with_count(
        BookFilters(date_from=date(2024, 6, 3), date_to=date(2024, 6, 5)),
        limit=50,
        offset=0,
    )
    assert len(result) == 3  # days 3, 4, 5


async def test_get_existing(repo, books):
    book = await repo.get(books[0].id)
    assert book is not None
    assert book.title == "Book Title 0"


async def test_get_nonexistent(repo, books):
    book = await repo.get("nonexistent-id")
    assert book is None


async def test_find_existing_by_isbn(db_session, repo, publisher):
    book = Book(
        id=str(uuid4()),
        title="ISBN Book",
        publisher_id=publisher.id,
        isbn_13="9999999999999",
        dedupe_key="isbn-dk",
        source_keys={},
    )
    db_session.add(book)
    await db_session.flush()

    found = await repo.find_existing("9999999999999", None, "other-dk")
    assert found is not None
    assert found.title == "ISBN Book"


async def test_find_existing_by_dedupe_key(db_session, repo, publisher):
    book = Book(
        id=str(uuid4()),
        title="Dedupe Book",
        publisher_id=publisher.id,
        dedupe_key="unique-dk-123",
        source_keys={},
    )
    db_session.add(book)
    await db_session.flush()

    found = await repo.find_existing(None, None, "unique-dk-123")
    assert found is not None
    assert found.title == "Dedupe Book"


async def test_find_existing_prefers_isbn_over_dedupe_key(db_session, repo, publisher):
    by_key = Book(id="by-key", title="Key", publisher_id=publisher.id, dedupe_key="dk-shared")
    by_isbn = Book(id="by-isbn", title="Isbn", publisher_id=publisher.id, isbn_13="9780000000002")
    db_session.add_all([by_key, by_isbn])
    await db_session.flush()

    found = await repo.find_existing("9780000000002", None, "dk-shared")
    assert found is not None
    assert found.id == "by-isbn"


async def test_find_existing_falls_back_to_isbn_10(db_session, repo, publisher):
    db_session.add(Book(id="ten", title="Ten", publisher_id=publisher.id, isbn_10="0000000001"))
    await db_session.flush()

    found = await repo.find_existing("9780000000009", "0000000001", "dk-none")
    assert found is not None
    assert found.id == "ten"


async def test_find_existing_ignores_dedupe_key_when_record_has_isbn(db_session, repo, publisher):
    db_session.add(
        Book(
            id="first-edition",
            title="Same Title",
            publisher_id=publisher.id,
            isbn_13="9780000000001",
            dedupe_key="dk-same",
        )
    )
    await db_session.flush()

    assert await repo.find_existing("9780000000002", None, "dk-same") is None


async def test_list_breaks_ties_by_id_so_pages_do_not_overlap(db_session, repo, publisher):
    from datetime import datetime

    created = datetime(2026, 1, 1)
    for book_id in ["c", "a", "b"]:
        db_session.add(
            Book(
                id=book_id,
                title=book_id,
                publisher_id=publisher.id,
                published_date=date(2026, 1, 1),
                created_at=created,
            )
        )
    await db_session.flush()

    pages = [await repo.list_with_count(BookFilters(), limit=1, offset=i) for i in range(3)]
    assert [books[0].id for books, _ in pages] == ["a", "b", "c"]

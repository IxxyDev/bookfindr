from uuid import uuid4

from app.models.book import Book
from app.services.books import build_dedupe_key, merge_book
from app.services.types import BookRecord


def _make_record(**overrides) -> BookRecord:
    defaults = dict(
        source="google_books",
        source_key="gb-123",
        publisher_id="oreilly",
        title="Test Book",
        authors=["Author One"],
    )
    defaults.update(overrides)
    return BookRecord(**defaults)


def test_build_dedupe_key_consistent():
    r1 = _make_record(title="Python Crash Course", publisher_id="nostarch", authors=["Eric"])
    r2 = _make_record(title="Python Crash Course", publisher_id="nostarch", authors=["Eric"])
    assert build_dedupe_key(r1) == build_dedupe_key(r2)


def test_build_dedupe_key_case_insensitive():
    r1 = _make_record(title="Python Crash Course", authors=["Eric Matthes"])
    r2 = _make_record(title="python crash course", authors=["eric matthes"])
    assert build_dedupe_key(r1) == build_dedupe_key(r2)


def test_build_dedupe_key_different_titles():
    r1 = _make_record(title="Book A")
    r2 = _make_record(title="Book B")
    assert build_dedupe_key(r1) != build_dedupe_key(r2)


def test_merge_book_fills_none_fields():
    book = Book(
        id=str(uuid4()),
        title="Old Title",
        publisher_id="oreilly",
        source_primary="open_library",
        source_keys={},
    )
    record = _make_record(
        source="google_books",
        description="A great book",
        page_count=300,
        isbn_13="9781234567890",
    )
    merged, changed = merge_book(book, record)
    assert changed is True
    assert merged.description == "A great book"
    assert merged.page_count == 300
    assert merged.isbn_13 == "9781234567890"


def test_merge_book_higher_priority_overwrites():
    book = Book(
        id=str(uuid4()),
        title="Old Title",
        description="Old description",
        publisher_id="oreilly",
        source_primary="open_library",
        source_keys={},
    )
    record = _make_record(
        source="connector",
        title="New Title",
        description="New description",
    )
    merged, changed = merge_book(book, record)
    assert changed is True
    assert merged.title == "New Title"
    assert merged.description == "New description"
    assert merged.source_primary == "connector"


def test_merge_book_lower_priority_no_overwrite():
    book = Book(
        id=str(uuid4()),
        title="Existing Title",
        description="Existing desc",
        publisher_id="oreilly",
        source_primary="connector",
        source_keys={},
    )
    record = _make_record(
        source="open_library",
        title="New Title",
        description="New desc",
    )
    merged, changed = merge_book(book, record)
    assert merged.title == "Existing Title"
    assert merged.description == "Existing desc"
    assert merged.description == "Existing desc"


async def test_upsert_second_source_persists_source_keys(db_session, sample_publisher):
    from sqlalchemy import select

    from app.services.books import upsert_records

    first = _make_record(source="google_books", source_key="g1", title="Persist Me")
    await upsert_records(db_session, [first])
    await db_session.commit()
    db_session.expunge_all()

    second = _make_record(source="open_library", source_key="o1", title="Persist Me")
    _, updated = await upsert_records(db_session, [second])
    await db_session.commit()
    db_session.expunge_all()

    assert updated == 1
    book = (await db_session.scalars(select(Book).where(Book.title == "Persist Me"))).one()
    assert book.source_keys == {"google_books": "g1", "open_library": "o1"}


async def test_upsert_same_record_twice_keeps_one_source_row(db_session, sample_publisher):
    from sqlalchemy import select

    from app.models.book_source import BookSource
    from app.services.books import upsert_records

    first = _make_record(source="dmk_html", source_key="d1", title="Refetch Me", raw={"v": 1})
    await upsert_records(db_session, [first])
    await db_session.commit()

    again = _make_record(source="dmk_html", source_key="d1", title="Refetch Me", raw={"v": 2})
    await upsert_records(db_session, [again])
    await db_session.commit()
    db_session.expunge_all()

    rows = (await db_session.scalars(select(BookSource))).all()
    assert len(rows) == 1
    assert rows[0].raw == {"v": 2}


def test_merge_book_empty_values_do_not_wipe_fields():
    book = Book(
        id=str(uuid4()),
        title="Existing Title",
        authors=["Author One"],
        subjects=["computers"],
        description="Existing desc",
        publisher_id="oreilly",
        source_primary="google_books",
        source_keys={},
    )
    record = _make_record(source="dmk_html", title="Existing Title", authors=[], description="")
    merged, _ = merge_book(book, record)
    assert merged.authors == ["Author One"]
    assert merged.subjects == ["computers"]
    assert merged.description == "Existing desc"


def test_merge_book_fills_empty_values_from_lower_priority():
    book = Book(
        id=str(uuid4()),
        title="Existing Title",
        authors=[],
        description="",
        publisher_id="oreilly",
        source_primary="dmk_html",
        source_keys={},
    )
    record = _make_record(source="open_library", authors=["Author One"], description="Desc")
    merged, changed = merge_book(book, record)
    assert changed is True
    assert merged.authors == ["Author One"]
    assert merged.description == "Desc"
    assert merged.title == "Existing Title"

import hashlib
import logging
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book
from app.models.book_source import BookSource
from app.repositories.books import BookRepository
from app.services.types import BookRecord, source_priority
from app.utils.lang import normalize_language

logger = logging.getLogger(__name__)


_PUNCTUATION = re.compile(r"[^\w\s]")


def _normalize_words(text: str) -> str:
    return " ".join(_PUNCTUATION.sub(" ", text.lower()).split())


def build_dedupe_key(book: BookRecord | Book) -> str:
    """Hash of normalized title, publisher and the first author's surname.

    Only the surname: sources disagree on middle initials ("Nathan B. Crocker").
    Migration 0003 holds a frozen copy of this function; change both together
    and add a migration that recomputes stored keys.
    """
    first_author = (book.authors or [""])[0]
    surname = (_normalize_words(first_author).split() or [""])[-1]
    key_base = f"{_normalize_words(book.title)}|{book.publisher_id}|{surname}"
    return hashlib.sha1(key_base.encode("utf-8")).hexdigest()


async def find_existing_book(
    repo: BookRepository, record: BookRecord, dedupe_key: str | None = None
) -> Book | None:
    key = dedupe_key or record.dedupe_key or build_dedupe_key(record)
    return await repo.find_existing(record.isbn_13, record.isbn_10, key)


def _should_replace(current_source: str | None, incoming_source: str) -> bool:
    return source_priority(incoming_source) > source_priority(current_source)


def _is_missing(value) -> bool:
    return value is None or value == "" or value == []


def merge_book(existing: Book, record: BookRecord) -> tuple[Book, bool]:
    updated = False
    source_update = _should_replace(existing.source_primary, record.source)

    def set_if_better(attr: str, new_value):
        nonlocal updated
        current = getattr(existing, attr)
        if _is_missing(new_value):
            return
        if _is_missing(current) or source_update:
            if current != new_value:
                setattr(existing, attr, new_value)
                updated = True

    set_if_better("title", record.title)
    set_if_better("subtitle", record.subtitle)
    set_if_better("authors", record.authors)
    set_if_better("language", record.language)
    set_if_better("subjects", record.subjects)
    set_if_better("topics", record.topics)
    set_if_better("description", record.description)
    set_if_better("isbn_10", record.isbn_10)
    set_if_better("isbn_13", record.isbn_13)
    set_if_better("page_count", record.page_count)
    set_if_better("print_type", record.print_type)
    if record.published_date is not None:
        if record.published_date_is_sighting:
            # A "first seen" date only fills a gap: it is no evidence against a date already known
            if existing.published_date is None:
                existing.published_date = record.published_date
                existing.published_date_is_sighting = True
                updated = True
        elif existing.published_date_is_sighting:
            # A real date beats a "first seen" one whatever the source priority
            existing.published_date = record.published_date
            existing.published_date_is_sighting = False
            updated = True
        else:
            set_if_better("published_date", record.published_date)
    set_if_better("cover_url", record.cover_url)
    set_if_better("info_url", record.info_url)

    if source_update:
        existing.source_primary = record.source
        updated = True

    # Copy: mutating the tracked dict in place is invisible to SQLAlchemy change detection
    keys = dict(existing.source_keys or {})
    if record.source not in keys or keys.get(record.source) != record.source_key:
        keys[record.source] = record.source_key
        existing.source_keys = keys
        updated = True

    return existing, updated


async def attach_source(repo: BookRepository, book_id: str, record: BookRecord) -> None:
    fetched_at = datetime.now(UTC)
    existing = await repo.find_source(book_id, record.source, record.source_key)
    if existing:
        existing.raw = record.raw
        existing.fetched_at = fetched_at
        return
    source = BookSource(
        id=str(uuid4()),
        book_id=book_id,
        source=record.source,
        source_key=record.source_key,
        raw=record.raw,
        fetched_at=fetched_at,
    )
    await repo.add_source(source)


async def _upsert_one(
    session: AsyncSession, repo: BookRepository, record: BookRecord
) -> str | None:
    """Upsert a single record inside a savepoint; returns 'new', 'updated' or None."""
    async with session.begin_nested():
        existing = await find_existing_book(repo, record, dedupe_key=record.dedupe_key)
        if existing:
            merged, changed = merge_book(existing, record)
            if changed:
                merged.dedupe_key = build_dedupe_key(merged)
            await attach_source(repo, merged.id, record)
            return "updated" if changed else None
        book_id = str(uuid4())
        book = Book(
            id=book_id,
            title=record.title,
            subtitle=record.subtitle,
            authors=record.authors or [],
            publisher_id=record.publisher_id,
            language=record.language,
            subjects=record.subjects or [],
            topics=record.topics or [],
            description=record.description,
            isbn_10=record.isbn_10,
            isbn_13=record.isbn_13,
            dedupe_key=record.dedupe_key,
            page_count=record.page_count,
            print_type=record.print_type,
            published_date=record.published_date,
            published_date_is_sighting=record.published_date_is_sighting,
            cover_url=record.cover_url,
            info_url=record.info_url,
            source_primary=record.source,
            source_keys={record.source: record.source_key},
        )
        await repo.add_book(book)
        await attach_source(repo, book_id, record)
        return "new"


async def upsert_records(session: AsyncSession, records: Iterable[BookRecord]) -> tuple[int, int]:
    repo = BookRepository(session)
    new_count = 0
    updated_count = 0
    for record in records:
        record.language = normalize_language(record.language)
        record.dedupe_key = build_dedupe_key(record)
        try:
            outcome = await _upsert_one(session, repo, record)
        except IntegrityError:
            # e.g. record matched book A by dedupe_key while its ISBN belongs to book B
            logger.warning(
                "Skipping conflicting record %r (source=%s, isbn13=%s)",
                record.title,
                record.source,
                record.isbn_13,
            )
            continue
        if outcome == "new":
            new_count += 1
        elif outcome == "updated":
            updated_count += 1
    return new_count, updated_count


async def purge_outdated_books(session: AsyncSession, cutoff: date) -> int:
    repo = BookRepository(session)
    return await repo.delete_before_date(cutoff)


async def purge_future_books(session: AsyncSession, today: date) -> int:
    repo = BookRepository(session)
    return await repo.delete_after_date(today)

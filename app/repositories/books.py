import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, and_, delete, func, or_, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book
from app.models.book_source import BookSource

logger = logging.getLogger(__name__)


@dataclass
class BookFilters:
    publisher_id: str | None = None
    language: str | None = None
    subject: str | None = None
    query: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class BookRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        # FTS5 string syntax: wrap each token in quotes, doubling embedded quotes
        tokens = query.replace('"', '""').split()
        return " ".join(f'"{token}"' for token in tokens if token)

    async def _fts_search(self, query: str, limit: int) -> list[str]:
        sanitized = self._sanitize_fts_query(query)
        if not sanitized:
            return []
        sql = text(
            "SELECT b.id FROM books b "
            "JOIN book_fts ON book_fts.rowid = b.rowid "
            "WHERE book_fts MATCH :query "
            "ORDER BY bm25(book_fts) "
            "LIMIT :limit"
        )
        result = await self._session.execute(sql, {"query": sanitized, "limit": limit})
        return [row[0] for row in result.fetchall()]

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")

    def _build_conditions(self, filters: BookFilters) -> list:
        conditions = []
        if filters.publisher_id:
            conditions.append(Book.publisher_id == filters.publisher_id)
        if filters.language:
            conditions.append(Book.language == filters.language)
        if filters.subject:
            escaped = self._escape_like(filters.subject)
            conditions.append(Book.subjects.like(f"%{escaped}%", escape="\\"))
        if filters.date_from:
            conditions.append(Book.published_date >= filters.date_from)
        if filters.date_to:
            conditions.append(Book.published_date <= filters.date_to)
        return conditions

    async def _resolve_fts_ids(self, query: str, limit: int) -> tuple[list[str] | None, bool]:
        """Return (fts_ids | None, is_empty). None signals LIKE fallback."""
        try:
            fts_ids = await self._fts_search(query, limit)
            if fts_ids:
                return fts_ids, False
            return None, True
        except OperationalError:
            logger.warning("FTS5 search failed, falling back to LIKE", exc_info=True)
            return None, False

    async def list_with_count(
        self, filters: BookFilters, limit: int, offset: int
    ) -> tuple[list[Book], int]:
        conditions = self._build_conditions(filters)
        query = (filters.query or "").strip()
        if query:
            fts_ids, is_empty = await self._resolve_fts_ids(query, 10000)
            if is_empty:
                return [], 0
            if fts_ids is not None:
                conditions.append(Book.id.in_(fts_ids))
            else:
                pattern = f"%{self._escape_like(query)}%"
                conditions.append(
                    or_(
                        Book.title.ilike(pattern, escape="\\"),
                        Book.description.ilike(pattern, escape="\\"),
                    )
                )

        count_stmt = select(func.count()).select_from(Book)
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total = (await self._session.scalar(count_stmt)) or 0

        list_stmt: Select[Book] = select(Book)
        if conditions:
            list_stmt = list_stmt.where(and_(*conditions))
        list_stmt = (
            list_stmt.order_by(Book.published_date.desc(), Book.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        books = (await self._session.scalars(list_stmt)).all()
        return books, total

    async def list(self, filters: BookFilters, limit: int, offset: int) -> list[Book]:
        books, _ = await self.list_with_count(filters, limit, offset)
        return books

    async def count(self, filters: BookFilters) -> int:
        _, total = await self.list_with_count(filters, limit=1, offset=0)
        return total

    async def get(self, book_id: str) -> Book | None:
        return await self._session.get(Book, book_id)

    async def list_sources(self, book_id: str) -> list[BookSource]:
        stmt: Select[BookSource] = select(BookSource).where(BookSource.book_id == book_id)
        return (await self._session.scalars(stmt)).all()

    async def find_existing(
        self, isbn_13: str | None, isbn_10: str | None, dedupe_key: str
    ) -> Book | None:
        """ISBN-13, then ISBN-10; the dedupe key only for a record without any ISBN.

        A record with its own ISBN that matches by title/author is another edition.
        """
        if isbn_13:
            book = await self._session.scalar(select(Book).where(Book.isbn_13 == isbn_13))
            if book:
                return book
        if isbn_10:
            book = await self._session.scalar(select(Book).where(Book.isbn_10 == isbn_10))
            if book:
                return book
        if isbn_13 or isbn_10:
            return None
        stmt = select(Book).where(Book.dedupe_key == dedupe_key).order_by(Book.created_at)
        return await self._session.scalar(stmt.limit(1))

    async def add_book(self, book: Book) -> None:
        self._session.add(book)

    async def find_source(
        self, book_id: str, source: str, source_key: str | None
    ) -> BookSource | None:
        stmt = select(BookSource).where(
            BookSource.book_id == book_id,
            BookSource.source == source,
            BookSource.source_key.is_not_distinct_from(source_key),
        )
        return await self._session.scalar(stmt)

    async def add_source(self, book_source: BookSource) -> None:
        self._session.add(book_source)

    async def delete_before_date(self, cutoff: date) -> int:
        ids = (
            await self._session.scalars(select(Book.id).where(Book.published_date < cutoff))
        ).all()
        return await self._delete_by_ids(ids)

    async def delete_after_date(self, target: date) -> int:
        ids = (
            await self._session.scalars(select(Book.id).where(Book.published_date > target))
        ).all()
        return await self._delete_by_ids(ids)

    async def _delete_by_ids(self, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        await self._session.execute(delete(BookSource).where(BookSource.book_id.in_(ids)))
        await self._session.execute(delete(Book).where(Book.id.in_(ids)))
        return len(ids)

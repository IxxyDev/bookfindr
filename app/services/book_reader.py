from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book
from app.models.book_source import BookSource
from app.repositories import BookFilters, BookRepository


@dataclass
class BookDetail:
    book: Book
    sources: list[BookSource]


@dataclass
class BookListResult:
    books: list[Book]
    total: int


async def list_books(
    session: AsyncSession, filters: BookFilters, limit: int, offset: int
) -> BookListResult:
    repo = BookRepository(session)
    books, total = await repo.list_with_count(filters, limit, offset)
    return BookListResult(books=books, total=total)


async def get_book_detail(session: AsyncSession, book_id: str) -> BookDetail | None:
    repo = BookRepository(session)
    book = await repo.get(book_id)
    if not book:
        return None
    sources = await repo.list_sources(book_id)
    return BookDetail(book=book, sources=sources)

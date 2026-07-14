from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.repositories import BookFilters
from app.schemas.book import BookDetailSchema, BookSchema, BookSourceSchema
from app.services.book_reader import get_book_detail
from app.services.book_reader import list_books as list_books_service

router = APIRouter(prefix="/books", tags=["books"])


@router.get("")
async def list_books(
    publisher_id: str | None = None,
    language: str | None = None,
    subject: str | None = None,
    q: str | None = None,
    date_from: date | None = Query(None, description="Published after (inclusive)"),
    date_to: date | None = Query(None, description="Published before (inclusive)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    settings = get_settings()
    default_from = date.today() - timedelta(days=settings.window_days)
    filters = BookFilters(
        publisher_id=publisher_id,
        language=language,
        subject=subject,
        query=q,
        date_from=date_from or default_from,
        date_to=date_to,
    )
    result = await list_books_service(session, filters, limit=limit, offset=offset)
    data = [
        BookSchema.model_validate(b, from_attributes=True).model_dump(mode="json")
        for b in result.books
    ]
    return JSONResponse(content=data, headers={"X-Total-Count": str(result.total)})


@router.get("/{book_id}", response_model=BookDetailSchema)
async def book_detail(
    book_id: str, session: AsyncSession = Depends(get_session)
) -> BookDetailSchema:
    detail = await get_book_detail(session, book_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Book not found")
    source_models = [
        BookSourceSchema.model_validate(src, from_attributes=True) for src in detail.sources
    ]
    schema = BookDetailSchema.model_validate(detail.book, from_attributes=True)
    schema.sources = source_models
    return schema

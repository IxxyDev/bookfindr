from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BookSource(Base):
    __tablename__ = "book_sources"
    # One row per source item of a book; a re-fetch refreshes raw/fetched_at in place
    __table_args__ = (
        Index("ux_book_sources_book_source_key", "book_id", "source", "source_key", unique=True),
    )

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(255))
    raw: Mapped[dict | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime)

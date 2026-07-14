from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class BookSource(Base):
    __tablename__ = "book_sources"

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(255))
    raw: Mapped[dict | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime)

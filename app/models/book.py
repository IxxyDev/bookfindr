from datetime import date

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Book(Base):
    __tablename__ = "books"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(500))
    authors: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    publisher_id: Mapped[str] = mapped_column(ForeignKey("publishers.id"), index=True)
    language: Mapped[str | None] = mapped_column(String(16), index=True)
    subjects: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    topics: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(Text)
    isbn_10: Mapped[str | None] = mapped_column(String(20), unique=True)
    isbn_13: Mapped[str | None] = mapped_column(String(32), unique=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    print_type: Mapped[str | None] = mapped_column(String(50))
    published_date: Mapped[date | None] = mapped_column(Date, index=True)
    # published_date is the day the book was first seen, not a publication date
    published_date_is_sighting: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    cover_url: Mapped[str | None] = mapped_column(String(500))
    info_url: Mapped[str | None] = mapped_column(String(500))
    source_primary: Mapped[str | None] = mapped_column(String(50))
    source_keys: Mapped[dict | None] = mapped_column(JSON, default=dict)

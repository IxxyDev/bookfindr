from datetime import date
from typing import List, Optional

from sqlalchemy import JSON, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Book(Base):
    __tablename__ = "books"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    subtitle: Mapped[Optional[str]] = mapped_column(String(500))
    authors: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    publisher_id: Mapped[str] = mapped_column(ForeignKey("publishers.id"), index=True)
    language: Mapped[Optional[str]] = mapped_column(String(16), index=True)
    subjects: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    topics: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    description: Mapped[Optional[str]] = mapped_column(Text)
    isbn_10: Mapped[Optional[str]] = mapped_column(String(20), unique=True)
    isbn_13: Mapped[Optional[str]] = mapped_column(String(32), unique=True)
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    print_type: Mapped[Optional[str]] = mapped_column(String(50))
    published_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    cover_url: Mapped[Optional[str]] = mapped_column(String(500))
    info_url: Mapped[Optional[str]] = mapped_column(String(500))
    source_primary: Mapped[Optional[str]] = mapped_column(String(50))
    source_keys: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

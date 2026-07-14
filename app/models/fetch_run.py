from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class FetchRun(Base):
    __tablename__ = "fetch_runs"

    source: Mapped[str | None] = mapped_column(String(50))
    publisher_id: Mapped[str | None] = mapped_column(ForeignKey("publishers.id"))
    started_at: Mapped[DateTime | None] = mapped_column(DateTime)
    finished_at: Mapped[DateTime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)

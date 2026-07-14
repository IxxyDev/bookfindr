from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Publisher(Base):
    __tablename__ = "publishers"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    languages: Mapped[list[str] | None] = mapped_column(JSON, default=list)

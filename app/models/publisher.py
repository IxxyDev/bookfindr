from typing import List, Optional

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Publisher(Base):
    __tablename__ = "publishers"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    languages: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)

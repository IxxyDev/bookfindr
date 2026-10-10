from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.time import UtcDateTime


class BookSourceSchema(BaseModel):
    id: str
    source: str
    source_key: str | None
    fetched_at: UtcDateTime | None
    raw: dict | None

    model_config = ConfigDict(from_attributes=True)


class BookSchema(BaseModel):
    id: str
    title: str
    subtitle: str | None
    authors: list[str] = Field(default_factory=list)
    publisher_id: str
    language: str | None
    subjects: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    description: str | None
    isbn_10: str | None
    isbn_13: str | None
    page_count: int | None
    print_type: str | None
    published_date: date | None
    cover_url: str | None
    info_url: str | None
    source_primary: str | None
    source_keys: dict = Field(default_factory=dict)
    created_at: UtcDateTime
    updated_at: UtcDateTime

    model_config = ConfigDict(from_attributes=True)


class BookDetailSchema(BookSchema):
    sources: list[BookSourceSchema] = Field(default_factory=list)

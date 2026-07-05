from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class BookSourceSchema(BaseModel):
    id: str
    source: str
    source_key: Optional[str]
    fetched_at: Optional[str]
    raw: Optional[dict]

    model_config = ConfigDict(from_attributes=True)


class BookSchema(BaseModel):
    id: str
    title: str
    subtitle: Optional[str]
    authors: List[str] = Field(default_factory=list)
    publisher_id: str
    language: Optional[str]
    subjects: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    description: Optional[str]
    isbn_10: Optional[str]
    isbn_13: Optional[str]
    page_count: Optional[int]
    print_type: Optional[str]
    published_date: Optional[date]
    cover_url: Optional[str]
    info_url: Optional[str]
    source_primary: Optional[str]
    source_keys: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BookDetailSchema(BookSchema):
    sources: List[BookSourceSchema] = Field(default_factory=list)

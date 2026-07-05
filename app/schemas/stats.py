from typing import List, Optional

from pydantic import BaseModel

from app.schemas.sync import FetchRunSchema


class PublisherCount(BaseModel):
    publisher_id: Optional[str] = None
    count: int


class SourceCount(BaseModel):
    source: Optional[str] = None
    count: int


class StatsResponse(BaseModel):
    total_books: int
    by_publisher: List[PublisherCount]
    by_source: List[SourceCount]
    last_runs: List[FetchRunSchema]

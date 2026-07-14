from pydantic import BaseModel

from app.schemas.sync import FetchRunSchema


class PublisherCount(BaseModel):
    publisher_id: str | None = None
    count: int


class SourceCount(BaseModel):
    source: str | None = None
    count: int


class StatsResponse(BaseModel):
    total_books: int
    by_publisher: list[PublisherCount]
    by_source: list[SourceCount]
    last_runs: list[FetchRunSchema]

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

SyncSource = Literal["google_books", "open_library", "connectors"]


class SyncRequest(BaseModel):
    publisher_id: str | None = None
    sources: list[SyncSource] | None = None
    dry_run: bool = False


class SyncStartResponse(BaseModel):
    status: str
    publisher_id: str | None = None
    sources: list[SyncSource]


class FetchRunSchema(BaseModel):
    id: str
    source: str | None = None
    publisher_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: str
    error: str | None = None
    new_count: int = 0
    updated_count: int = 0


class SyncStatusResponse(BaseModel):
    running: bool
    last_runs: list[FetchRunSchema]

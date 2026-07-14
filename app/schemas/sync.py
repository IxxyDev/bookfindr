from datetime import datetime

from pydantic import BaseModel


class SyncRequest(BaseModel):
    publisher_id: str | None = None
    sources: list[str] | None = None
    dry_run: bool = False


class SyncStartResponse(BaseModel):
    status: str
    publisher_id: str | None = None
    sources: list[str]


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

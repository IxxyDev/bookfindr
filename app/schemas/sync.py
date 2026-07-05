from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class SyncRequest(BaseModel):
    publisher_id: Optional[str] = None
    sources: Optional[List[str]] = None
    dry_run: bool = False


class SyncStartResponse(BaseModel):
    status: str
    publisher_id: Optional[str] = None
    sources: List[str]


class FetchRunSchema(BaseModel):
    id: str
    source: Optional[str] = None
    publisher_id: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    status: str
    error: Optional[str] = None
    new_count: int = 0
    updated_count: int = 0


class SyncStatusResponse(BaseModel):
    running: bool
    last_runs: List[FetchRunSchema]

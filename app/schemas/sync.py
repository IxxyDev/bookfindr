from typing import List, Optional

from pydantic import BaseModel


class SyncRequest(BaseModel):
    publisher_id: Optional[str] = None
    sources: Optional[List[str]] = None
    dry_run: bool = False


class SyncStats(BaseModel):
    new_count: int
    updated_count: int
    source: str
    publisher_id: str


class SyncResponse(BaseModel):
    runs: List[SyncStats]

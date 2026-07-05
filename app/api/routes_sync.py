from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings, load_publishers
from app.core.db import get_session
from app.schemas.sync import SyncRequest, SyncResponse, SyncStats
from app.services.sync import run_sync

router = APIRouter(prefix="/sync", tags=["sync"])


async def _check_sync_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    settings = get_settings()
    if settings.sync_api_key and x_api_key != settings.sync_api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


@router.post("/run", response_model=SyncResponse, dependencies=[Depends(_check_sync_api_key)])
async def sync_run(
    payload: SyncRequest, session: AsyncSession = Depends(get_session)
) -> SyncResponse:
    config = load_publishers()
    runs = await run_sync(
        session,
        config,
        publisher_id=payload.publisher_id,
        sources=payload.sources,
        dry_run=payload.dry_run,
    )
    stats: List[SyncStats] = [
        SyncStats(
            new_count=run.new_count,
            updated_count=run.updated_count,
            source=run.source or "",
            publisher_id=run.publisher_id or "",
        )
        for run in runs
    ]
    return SyncResponse(runs=stats)

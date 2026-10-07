import asyncio
import logging
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import PublishersFile, get_publishers_config, get_settings
from app.core.db import get_session
from app.models.fetch_run import FetchRun
from app.schemas.sync import (
    FetchRunSchema,
    SyncRequest,
    SyncStartResponse,
    SyncStatusResponse,
)
from app.services.sync import run_locked_sync, sync_lock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["sync"])

# Keep strong references so background tasks are not garbage-collected mid-run.
_background_tasks: set[asyncio.Task] = set()


async def _check_sync_api_key(x_api_key: str | None = Header(None)) -> None:
    settings = get_settings()
    if not settings.sync_api_key:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.sync_api_key):
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


async def _run_sync_in_background(payload: SyncRequest) -> None:
    try:
        await run_locked_sync(
            publisher_id=payload.publisher_id, sources=payload.sources, dry_run=payload.dry_run
        )
    except Exception:
        logger.exception("Background sync failed")


@router.post(
    "/run",
    response_model=SyncStartResponse,
    status_code=202,
    dependencies=[Depends(_check_sync_api_key)],
)
async def sync_run(
    payload: SyncRequest, config: PublishersFile = Depends(get_publishers_config)
) -> SyncStartResponse:
    if payload.publisher_id and payload.publisher_id not in {p.id for p in config.publishers}:
        raise HTTPException(status_code=404, detail="Unknown publisher")
    if sync_lock.locked():
        raise HTTPException(status_code=409, detail="Sync is already running")
    # Take the lock here, not in the task: a second request arriving before the task
    # starts must already see it held
    await sync_lock.acquire()
    task = asyncio.create_task(_run_sync_in_background(payload))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return SyncStartResponse(
        status="started",
        publisher_id=payload.publisher_id,
        sources=payload.sources or ["connectors"],
    )


@router.get("/status", response_model=SyncStatusResponse)
async def sync_status(session: AsyncSession = Depends(get_session)) -> SyncStatusResponse:
    stmt = select(FetchRun).order_by(desc(FetchRun.started_at)).limit(20)
    runs = (await session.scalars(stmt)).all()
    return SyncStatusResponse(
        running=sync_lock.locked(),
        last_runs=[FetchRunSchema.model_validate(r, from_attributes=True) for r in runs],
    )

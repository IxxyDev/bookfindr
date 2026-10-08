from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fetch_run import FetchRun


async def list_recent_runs(session: AsyncSession, limit: int) -> Sequence[FetchRun]:
    stmt = select(FetchRun).order_by(FetchRun.started_at.desc()).limit(limit)
    return (await session.scalars(stmt)).all()


async def delete_runs_started_before(session: AsyncSession, cutoff: datetime) -> int:
    # "fetch": in-session runs hold naive (loaded) and aware (new) datetimes, which the
    # default Python-side evaluation cannot compare
    stmt = delete(FetchRun).where(FetchRun.started_at < cutoff)
    result = await session.execute(stmt.execution_options(synchronize_session="fetch"))
    return result.rowcount

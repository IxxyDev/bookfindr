from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fetch_run import FetchRun


async def delete_runs_started_before(session: AsyncSession, cutoff: datetime) -> int:
    # "fetch": in-session runs hold naive (loaded) and aware (new) datetimes, which the
    # default Python-side evaluation cannot compare
    stmt = delete(FetchRun).where(FetchRun.started_at < cutoff)
    result = await session.execute(stmt.execution_options(synchronize_session="fetch"))
    return result.rowcount

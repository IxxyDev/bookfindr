from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book
from app.models.fetch_run import FetchRun
from app.schemas.stats import PublisherCount, SourceCount, StatsResponse
from app.schemas.sync import FetchRunSchema


async def get_stats(session: AsyncSession, last_runs_limit: int = 20) -> StatsResponse:
    total = (await session.scalar(select(func.count()).select_from(Book))) or 0

    by_publisher_rows = (
        await session.execute(
            select(Book.publisher_id, func.count())
            .group_by(Book.publisher_id)
            .order_by(func.count().desc())
        )
    ).all()

    by_source_rows = (
        await session.execute(
            select(Book.source_primary, func.count())
            .group_by(Book.source_primary)
            .order_by(func.count().desc())
        )
    ).all()

    runs = (
        await session.scalars(
            select(FetchRun).order_by(desc(FetchRun.started_at)).limit(last_runs_limit)
        )
    ).all()

    return StatsResponse(
        total_books=total,
        by_publisher=[PublisherCount(publisher_id=p, count=c) for p, c in by_publisher_rows],
        by_source=[SourceCount(source=s, count=c) for s, c in by_source_rows],
        last_runs=[FetchRunSchema.model_validate(r, from_attributes=True) for r in runs],
    )

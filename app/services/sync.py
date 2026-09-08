import argparse
import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.connectors import ConnectorResult, failure_line, fetch_connectors
from app.clients.google_books import fetch_google_books
from app.clients.open_library import fetch_open_library
from app.core.config import PublisherConfig, PublishersFile, Settings, get_settings, load_publishers
from app.core.db import get_async_session, init_db
from app.models.fetch_run import FetchRun
from app.repositories.fetch_runs import delete_runs_started_before
from app.services.books import purge_future_books, purge_outdated_books, upsert_records
from app.services.publishers import sync_publishers
from app.services.types import BookRecord

logger = logging.getLogger(__name__)

# fetch_runs is a log for /sync/status and /stats, not an archive
FETCH_RUN_RETENTION_DAYS = 30

# Guards against concurrent syncs (manual trigger vs scheduled job).
sync_lock = asyncio.Lock()

# Query strings carry API keys; migration 0004 holds a frozen copy of this pattern
_URL_QUERY = re.compile(r"(https?://[^\s?#'\"<>]+)\?[^\s#'\"<>]*")


def redact_url_query(text: str) -> str:
    return _URL_QUERY.sub(r"\1?<redacted>", text)


def _filter_recent_records(records: list[BookRecord], window_days: int) -> list[BookRecord]:
    today = date.today()
    cutoff = today - timedelta(days=window_days)
    filtered: list[BookRecord] = []
    for record in records:
        published = record.published_date
        if not published:
            continue
        if published > today:
            continue
        if published < cutoff:
            continue
        filtered.append(record)
    return filtered


async def _fetch_aggregator(
    name: str,
    fetch: Callable[[PublisherConfig, Settings, int], Awaitable[list[BookRecord]]],
    publisher: PublisherConfig,
    settings: Settings,
    window_days: int,
) -> ConnectorResult:
    """Run one aggregator; its failure must not end the publisher's run."""
    try:
        return ConnectorResult(records=await fetch(publisher, settings, window_days))
    except Exception as exc:
        logger.exception("%s failed for %s", name, publisher.id)
        return ConnectorResult(errors=[failure_line(name, exc)])


async def _purge(session: AsyncSession, window_days: int) -> None:
    # Same local clock as connectors/_filter_recent_records: a UTC date
    # here would purge books scraped "today" local time as future-dated
    today = date.today()
    await purge_outdated_books(session, today - timedelta(days=window_days))
    await purge_future_books(session, today)
    await delete_runs_started_before(
        session, datetime.now(UTC) - timedelta(days=FETCH_RUN_RETENTION_DAYS)
    )
    await session.commit()


async def _sync_publisher(
    session: AsyncSession,
    config: PublishersFile,
    pub: PublisherConfig,
    sources: list[str],
    dry_run: bool,
) -> FetchRun:
    settings = get_settings()
    run = FetchRun(
        id=str(uuid4()),
        publisher_id=pub.id,
        source=",".join(sources),
        started_at=datetime.now(UTC),
        status="running",
        new_count=0,
        updated_count=0,
    )
    session.add(run)
    # Commit now: /sync/status sees the run, and no write transaction stays open while fetching
    await session.commit()
    try:
        results: list[ConnectorResult] = []
        if "google_books" in sources:
            results.append(
                await _fetch_aggregator(
                    "google_books", fetch_google_books, pub, settings, config.window_days
                )
            )
        if "open_library" in sources:
            results.append(
                await _fetch_aggregator(
                    "open_library", fetch_open_library, pub, settings, config.window_days
                )
            )
        if "connectors" in sources:
            results.append(await fetch_connectors(pub, config.window_days))
        records = [record for result in results for record in result.records]
        errors = [error for result in results for error in result.errors]

        records = _filter_recent_records(records, config.window_days)

        if not dry_run:
            new_count, updated_count = await upsert_records(session, records)
            run.new_count = new_count
            run.updated_count = updated_count
        else:
            run.new_count = 0
            run.updated_count = 0

        # some sources failed: the records of the others are still stored
        run.status = "partial" if errors else "success"
        run.error = redact_url_query("; ".join(errors)) or None
        run.finished_at = datetime.now(UTC)
        await session.commit()
    except Exception as exc:
        logger.exception("Sync failed for %s", pub.id)
        # A failed flush leaves the session unusable until rolled back; the run row
        # itself was committed above and is updated below
        await session.rollback()
        run.status = "error"
        run.error = redact_url_query(str(exc))
        run.finished_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(run)
    return run


async def run_sync(
    session: AsyncSession,
    config: PublishersFile,
    publisher_id: str | None = None,
    sources: list[str] | None = None,
    dry_run: bool = False,
) -> list[FetchRun]:
    use_sources = sources or ["connectors"]
    await sync_publishers(session, config)
    runs: list[FetchRun] = []
    for pub in config.publishers:
        if publisher_id and pub.id != publisher_id:
            continue
        runs.append(await _sync_publisher(session, config, pub, use_sources, dry_run))
    if not dry_run:
        await _purge(session, config.window_days)
    return runs


async def run_once_from_cli(publisher_id: str | None = None, dry_run: bool = False) -> None:
    await init_db()
    config = load_publishers()
    async with sync_lock:
        async with get_async_session()() as session:
            await run_sync(session, config, publisher_id=publisher_id, dry_run=dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bookfindr sync runner")
    parser.add_argument(
        "--publisher",
        dest="publisher_id",
        help="Run only for a specific publisher",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(run_once_from_cli(publisher_id=args.publisher_id, dry_run=args.dry_run))


if __name__ == "__main__":
    main()

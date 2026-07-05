import argparse
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.connectors import fetch_connectors
from app.clients.google_books import fetch_google_books
from app.clients.open_library import fetch_open_library
from app.core.config import PublishersFile, get_settings, load_publishers
from app.core.db import get_async_session, init_db
from app.models.fetch_run import FetchRun
from app.services.books import purge_future_books, purge_outdated_books, upsert_records
from app.services.publishers import sync_publishers
from app.services.types import BookRecord

logger = logging.getLogger(__name__)

# Guards against concurrent syncs (manual trigger vs scheduled job).
sync_lock = asyncio.Lock()


def _filter_recent_records(records: List[BookRecord], window_days: int) -> List[BookRecord]:
    today = date.today()
    cutoff = today - timedelta(days=window_days)
    filtered: List[BookRecord] = []
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


async def run_sync(
    session: AsyncSession,
    config: PublishersFile,
    publisher_id: Optional[str] = None,
    sources: Optional[List[str]] = None,
    dry_run: bool = False,
) -> List[FetchRun]:
    runs: List[FetchRun] = []
    use_sources = sources or ["connectors"]

    await sync_publishers(session, config)
    settings = get_settings()

    for pub in config.publishers:
        if publisher_id and pub.id != publisher_id:
            continue
        run = FetchRun(
            id=str(uuid4()),
            publisher_id=pub.id,
            source=",".join(use_sources),
            started_at=datetime.now(timezone.utc),
            status="running",
            new_count=0,
            updated_count=0,
        )
        session.add(run)
        await session.flush()
        try:
            records: List[BookRecord] = []
            if "google_books" in use_sources:
                records.extend(await fetch_google_books(pub, settings, config.window_days))
            if "open_library" in use_sources:
                records.extend(await fetch_open_library(pub, settings, config.window_days))
            if "connectors" in use_sources:
                records.extend(await fetch_connectors(pub))

            records = _filter_recent_records(records, config.window_days)

            if not dry_run:
                today = datetime.now(timezone.utc).date()
                new_count, updated_count = await upsert_records(session, records)
                cutoff = today - timedelta(days=config.window_days)
                await purge_outdated_books(session, cutoff)
                await purge_future_books(session, today)
                run.new_count = new_count
                run.updated_count = updated_count
            else:
                run.new_count = 0
                run.updated_count = 0

            run.status = "success"
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Sync failed for %s", pub.id)
            run.status = "error"
            run.error = str(exc)
        finally:
            run.finished_at = datetime.now(timezone.utc)
            await session.commit()
            runs.append(run)
    return runs


async def run_once_from_cli(publisher_id: Optional[str] = None, dry_run: bool = False) -> None:
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

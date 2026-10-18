from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clients.connectors import ConnectorResult
from app.core.config import PublisherConfig, PublishersFile
from app.core.db import Base, create_fts_objects
from app.models.book import Book
from app.models.fetch_run import FetchRun
from app.services import sync
from app.services.sync import redact_url_query, run_sync
from app.services.types import BookRecord

LEAKY_ERROR = (
    "Client error '403 Forbidden' for url "
    "'https://www.googleapis.com/books/v1/volumes?q=subject%3Acomputers&key=SECRET'"
)


def _config(*publisher_ids: str) -> PublishersFile:
    return PublishersFile(
        publishers=[PublisherConfig(id=pid, name=pid.upper()) for pid in publisher_ids]
    )


def test_redact_url_query_drops_query_strings():
    assert redact_url_query(LEAKY_ERROR) == (
        "Client error '403 Forbidden' for url "
        "'https://www.googleapis.com/books/v1/volumes?<redacted>'"
    )
    assert redact_url_query("no url here") == "no url here"


async def test_run_sync_stores_redacted_error(db_session, monkeypatch):
    async def failing_fetch(*_args):
        raise RuntimeError(LEAKY_ERROR)

    monkeypatch.setattr(sync, "fetch_connectors", failing_fetch)
    runs = await run_sync(db_session, _config("pub"))

    assert runs[0].status == "error"
    assert "SECRET" not in runs[0].error
    assert "volumes?<redacted>" in runs[0].error


@pytest.fixture()
async def file_session_factory(tmp_path):
    """A file database: unlike the shared in-memory one, a second connection only sees commits."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sync.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(create_fts_objects)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_running_fetch_run_is_committed_before_fetching(file_session_factory, monkeypatch):
    seen_statuses: list[str] = []

    async def observing_fetch(*_args):
        async with file_session_factory() as observer:
            seen_statuses.extend((await observer.scalars(select(FetchRun.status))).all())
        return ConnectorResult()

    monkeypatch.setattr(sync, "fetch_connectors", observing_fetch)
    async with file_session_factory() as session:
        await run_sync(session, _config("pub"))

    assert seen_statuses == ["running"]


def _record(publisher_id: str, title: str, published: date | None = None) -> BookRecord:
    return BookRecord(
        source="dmk_html",
        source_key=f"{publisher_id}-{title}",
        publisher_id=publisher_id,
        title=title,
        published_date=published or date.today(),
    )


def _connectors_returning(*records: BookRecord, errors: list[str] | None = None):
    async def fetch(publisher, _window_days):
        own = [r for r in records if r.publisher_id == publisher.id]
        return ConnectorResult(records=own, errors=list(errors or []))

    return fetch


async def test_db_error_in_one_publisher_does_not_abort_the_rest(db_session, monkeypatch):
    real_upsert = sync.upsert_records

    async def upsert(session, records):
        if records and records[0].publisher_id == "broken":
            session.add(Book(id="orphan", title="Orphan", publisher_id="no-such-publisher"))
            await session.flush()  # FK violation: the session now needs a rollback
        return await real_upsert(session, records)

    monkeypatch.setattr(sync, "upsert_records", upsert)
    monkeypatch.setattr(
        sync,
        "fetch_connectors",
        _connectors_returning(_record("broken", "A"), _record("fine", "B")),
    )

    runs = await run_sync(db_session, _config("broken", "fine"))

    assert {r.publisher_id: r.status for r in runs} == {"broken": "error", "fine": "success"}
    assert "FOREIGN KEY" in runs[0].error
    assert (await db_session.scalars(select(Book.title))).all() == ["B"]


async def test_purge_runs_once_after_all_publishers(db_session, monkeypatch):
    calls: list[str] = []

    def fake_purge(name):
        async def purge(_session, _day):
            calls.append(name)
            return 0

        return purge

    monkeypatch.setattr(sync, "fetch_connectors", _connectors_returning())
    monkeypatch.setattr(sync, "purge_outdated_books", fake_purge("outdated"))
    monkeypatch.setattr(sync, "purge_future_books", fake_purge("future"))

    await run_sync(db_session, _config("one", "two", "three"))

    assert calls == ["outdated", "future"]


async def test_purge_drops_fetch_runs_past_retention(db_session):
    now = datetime.now(UTC)
    for run_id, age_days in [("old", sync.FETCH_RUN_RETENTION_DAYS + 1), ("recent", 1)]:
        db_session.add(
            FetchRun(id=run_id, status="success", started_at=now - timedelta(days=age_days))
        )
    await db_session.commit()

    await run_sync(db_session, _config())

    assert (await db_session.scalars(select(FetchRun.id))).all() == ["recent"]


async def test_dry_run_reports_real_counts_and_writes_no_books(db_session, monkeypatch):
    monkeypatch.setattr(
        sync, "fetch_connectors", _connectors_returning(_record("pub", "A"), _record("pub", "B"))
    )

    runs = await run_sync(db_session, _config("pub"), dry_run=True)

    assert (runs[0].status, runs[0].new_count, runs[0].updated_count) == ("success", 2, 0)
    assert (await db_session.scalars(select(Book))).all() == []
    assert (await db_session.scalars(select(FetchRun.new_count))).all() == [2]


async def test_failed_connectors_mark_the_run_partial(db_session, monkeypatch):
    errors = ["dmk_catalog: ValueError: bad page", f"bhv_store: HTTPStatusError: {LEAKY_ERROR}"]
    monkeypatch.setattr(
        sync, "fetch_connectors", _connectors_returning(_record("pub", "Kept"), errors=errors)
    )

    runs = await run_sync(db_session, _config("pub"))

    assert (runs[0].status, runs[0].new_count) == ("partial", 1)
    assert runs[0].error.startswith("dmk_catalog: ValueError: bad page; bhv_store: ")
    assert "SECRET" not in runs[0].error


def test_cli_passes_sources_publisher_and_dry_run(monkeypatch):
    calls: list[dict] = []

    async def fake_run_once(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(sync, "run_once_from_cli", fake_run_once)
    argv = ["sync", "--publisher", "dmk", "--sources", "google_books", "connectors", "--dry-run"]
    monkeypatch.setattr("sys.argv", argv)
    sync.main()
    monkeypatch.setattr("sys.argv", ["sync"])
    sync.main()

    assert calls == [
        {"publisher_id": "dmk", "sources": ["google_books", "connectors"], "dry_run": True},
        {"publisher_id": None, "sources": None, "dry_run": False},
    ]


def test_cli_rejects_unknown_source(monkeypatch):
    monkeypatch.setattr("sys.argv", ["sync", "--sources", "google"])
    with pytest.raises(SystemExit):
        sync.main()

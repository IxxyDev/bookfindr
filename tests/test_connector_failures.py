from datetime import date, timedelta

import httpx
import pytest

from app.clients import connectors
from app.core.config import PublisherConfig, PublishersFile
from app.services import sync
from app.services.types import BookRecord

PUBLISHER = PublisherConfig(id="acme", name="Acme", connectors=["fake_ok", "fake_broken"])


def _record(source: str, title: str) -> BookRecord:
    return BookRecord(
        source=source,
        source_key=title,
        publisher_id=PUBLISHER.id,
        title=title,
        published_date=date.today() - timedelta(days=1),
    )


async def _fake_ok(publisher: PublisherConfig) -> list[BookRecord]:
    return [_record("fake_ok", "Linux for everyone")]


async def _fake_broken(publisher: PublisherConfig) -> list[BookRecord]:
    raise ValueError("layout changed")


@pytest.fixture
def fake_connectors(monkeypatch):
    monkeypatch.setitem(connectors.CONNECTOR_MAP, "fake_ok", _fake_ok)
    monkeypatch.setitem(connectors.CONNECTOR_MAP, "fake_broken", _fake_broken)


async def test_failed_connector_is_reported_and_the_rest_still_count(fake_connectors):
    result = await connectors.fetch_connectors(PUBLISHER)

    assert [r.title for r in result.records] == ["Linux for everyone"]
    assert result.errors == ["fake_broken: ValueError: layout changed"]


async def test_run_is_partial_when_a_connector_failed(db_session, fake_connectors):
    config = PublishersFile(publishers=[PUBLISHER])

    [run] = await sync.run_sync(db_session, config)

    assert run.status == "partial"
    assert run.error == "fake_broken: ValueError: layout changed"
    assert run.new_count == 1


async def test_failed_aggregator_does_not_stop_the_connectors(
    db_session, fake_connectors, monkeypatch
):
    async def unavailable(publisher, settings, window_days):
        request = httpx.Request("GET", "https://www.googleapis.com/books/v1/volumes")
        raise httpx.HTTPStatusError(
            "503 Service Unavailable", request=request, response=httpx.Response(503)
        )

    monkeypatch.setattr(sync, "fetch_google_books", unavailable)
    config = PublishersFile(publishers=[PUBLISHER.model_copy(update={"connectors": ["fake_ok"]})])

    [run] = await sync.run_sync(db_session, config, sources=["google_books", "connectors"])

    assert run.status == "partial"
    assert run.error == "google_books: HTTPStatusError: 503 Service Unavailable"
    assert run.new_count == 1


async def test_run_without_failures_is_a_success(db_session, fake_connectors):
    config = PublishersFile(publishers=[PUBLISHER.model_copy(update={"connectors": ["fake_ok"]})])

    [run] = await sync.run_sync(db_session, config)

    assert (run.status, run.error) == ("success", None)


async def test_storage_failure_marks_the_run_as_error(db_session, fake_connectors, monkeypatch):
    async def broken_upsert(session, records):
        raise RuntimeError("disk full")

    monkeypatch.setattr(sync, "upsert_records", broken_upsert)
    config = PublishersFile(publishers=[PUBLISHER.model_copy(update={"connectors": ["fake_ok"]})])

    [run] = await sync.run_sync(db_session, config)

    assert (run.status, run.error) == ("error", "disk full")

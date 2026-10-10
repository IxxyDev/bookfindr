import asyncio
from datetime import date
from uuid import uuid4

import pytest

from app.models.book import Book
from app.models.publisher import Publisher


@pytest.fixture()
async def api_publisher(db_session) -> Publisher:
    pub = Publisher(id="apipub", name="API Publisher")
    db_session.add(pub)
    await db_session.commit()
    return pub


@pytest.fixture()
async def api_book(db_session, api_publisher) -> Book:
    book = Book(
        id=str(uuid4()),
        title="API Test Book",
        publisher_id=api_publisher.id,
        language="en",
        subjects=["computers"],
        description="A book for testing the API",
        published_date=date.today(),
        dedupe_key="api-dk",
        source_primary="google_books",
        source_keys={},
    )
    db_session.add(book)
    await db_session.commit()
    return book


async def test_health(client):
    res = await client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


async def test_books_empty(client):
    res = await client.get("/books")
    assert res.status_code == 200
    assert res.json() == []


async def test_books_with_data(client, api_book):
    res = await client.get("/books")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    titles = [b["title"] for b in data]
    assert "API Test Book" in titles


async def test_books_total_count_header(client, api_book):
    res = await client.get("/books")
    assert res.status_code == 200
    assert "x-total-count" in res.headers
    total = int(res.headers["x-total-count"])
    assert total >= 1


async def test_book_detail_found(client, api_book):
    res = await client.get(f"/books/{api_book.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "API Test Book"
    assert "sources" in data


async def test_book_detail_not_found(client):
    res = await client.get("/books/nonexistent-id-12345")
    assert res.status_code == 404


async def test_publishers_lists_configured_ids_in_config_order(client, db_session):
    from app.core.config import PublisherConfig, PublishersFile, get_publishers_config
    from app.main import app

    for pid in ["alpha", "removed", "zeta"]:
        db_session.add(Publisher(id=pid, name=pid.title()))
    await db_session.commit()
    app.dependency_overrides[get_publishers_config] = lambda: PublishersFile(
        publishers=[
            PublisherConfig(id="zeta", name="Zeta"),
            PublisherConfig(id="not_synced_yet", name="New"),
            PublisherConfig(id="alpha", name="Alpha"),
        ]
    )

    res = await client.get("/publishers")
    assert res.status_code == 200
    assert [p["id"] for p in res.json()] == ["zeta", "alpha"]


async def test_stats(client, api_book):
    res = await client.get("/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total_books"] >= 1
    publisher_ids = [row["publisher_id"] for row in data["by_publisher"]]
    assert api_book.publisher_id in publisher_ids
    sources = [row["source"] for row in data["by_source"]]
    assert "google_books" in sources
    assert "last_runs" in data


async def test_sync_status_idle(client):
    res = await client.get("/sync/status")
    assert res.status_code == 200
    data = res.json()
    assert data["running"] is False
    assert data["last_runs"] == []


async def test_root_page_renders(client):
    res = await client.get("/")
    assert res.status_code == 200
    assert "Bookfindr" in res.text


@pytest.fixture()
async def api_book_with_source(db_session, api_book) -> Book:
    from datetime import UTC, datetime

    from app.models.book_source import BookSource

    db_session.add(
        BookSource(
            id=str(uuid4()),
            book_id=api_book.id,
            source="google_books",
            source_key="gb-1",
            raw={"id": "gb-1"},
            fetched_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    return api_book


async def test_book_detail_with_sources(client, api_book_with_source):
    res = await client.get(f"/books/{api_book_with_source.id}")
    assert res.status_code == 200
    sources = res.json()["sources"]
    assert len(sources) == 1
    assert sources[0]["source"] == "google_books"
    assert sources[0]["fetched_at"]


async def test_sync_run_requires_api_key(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "sync_api_key", "secret")
    res = await client.post("/sync/run", json={"dry_run": True})
    assert res.status_code == 403
    res = await client.post("/sync/run", json={"dry_run": True}, headers={"X-Api-Key": "nope"})
    assert res.status_code == 403


@pytest.fixture()
def ten_day_window():
    from app.core.config import PublishersFile, get_publishers_config
    from app.main import app

    app.dependency_overrides[get_publishers_config] = lambda: PublishersFile(
        publishers=[], window_days=10
    )
    yield
    app.dependency_overrides.pop(get_publishers_config, None)


async def test_books_default_window_comes_from_publishers_config(
    client, db_session, api_publisher, ten_day_window
):
    from datetime import timedelta

    for title, age in [("Fresh", 5), ("Stale", 20)]:
        db_session.add(
            Book(
                id=str(uuid4()),
                title=title,
                publisher_id=api_publisher.id,
                published_date=date.today() - timedelta(days=age),
            )
        )
    await db_session.commit()

    res = await client.get("/books")
    assert [b["title"] for b in res.json()] == ["Fresh"]
    assert res.headers["x-total-count"] == "1"


async def test_root_page_shows_configured_window(client, ten_day_window):
    res = await client.get("/")
    assert "Последние 10 дней" in res.text


@pytest.fixture()
async def blocked_sync(monkeypatch):
    """Replace run_sync with one that holds the lock until the test ends."""
    from app.api import routes_sync
    from app.services import sync

    gate = asyncio.Event()
    calls: list[dict] = []

    async def fake_run_sync(_session, _config, **kwargs):
        calls.append(kwargs)
        await gate.wait()
        return []

    monkeypatch.setattr(sync, "run_sync", fake_run_sync)
    yield calls
    gate.set()
    await asyncio.gather(*routes_sync._background_tasks)


async def test_sync_run_starts_once_and_reports_running(client, blocked_sync):
    first, second = await asyncio.gather(
        client.post("/sync/run", json={}), client.post("/sync/run", json={})
    )
    assert sorted([first.status_code, second.status_code]) == [202, 409]

    status = await client.get("/sync/status")
    assert status.json()["running"] is True


async def test_sync_run_with_valid_api_key(client, blocked_sync, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "sync_api_key", "secret")
    res = await client.post(
        "/sync/run",
        json={"dry_run": True, "sources": ["google_books"]},
        headers={"X-Api-Key": "secret"},
    )
    assert res.status_code == 202
    assert res.json() == {"status": "started", "publisher_id": None, "sources": ["google_books"]}
    await asyncio.sleep(0)
    assert blocked_sync == [{"publisher_id": None, "sources": ["google_books"], "dry_run": True}]


async def test_sync_run_rejects_unknown_source(client, blocked_sync):
    res = await client.post("/sync/run", json={"sources": ["google"]})
    assert res.status_code == 422
    assert blocked_sync == []


async def test_sync_run_unknown_publisher_is_404(client, blocked_sync):
    from app.core.config import PublisherConfig, PublishersFile, get_publishers_config
    from app.main import app

    app.dependency_overrides[get_publishers_config] = lambda: PublishersFile(
        publishers=[PublisherConfig(id="known", name="Known")]
    )
    res = await client.post("/sync/run", json={"publisher_id": "nope"})
    assert res.status_code == 404
    assert blocked_sync == []

    res = await client.post("/sync/run", json={"publisher_id": "known"})
    assert res.status_code == 202


async def test_books_language_filter_is_normalized(client, api_book):
    for code in ["en", "ENG", "en-GB"]:
        res = await client.get("/books", params={"language": code})
        assert [b["title"] for b in res.json()] == ["API Test Book"], code


async def test_timestamps_are_utc_with_offset(client, api_book_with_source, db_session):
    from datetime import datetime, timedelta

    from app.models.fetch_run import FetchRun

    db_session.add(FetchRun(id="run", status="success", started_at=datetime(2026, 1, 1, 3)))
    await db_session.commit()

    book = (await client.get("/books")).json()[0]
    detail = (await client.get(f"/books/{api_book_with_source.id}")).json()
    run = (await client.get("/sync/status")).json()["last_runs"][0]
    stamps = [
        book["created_at"],
        book["updated_at"],
        detail["sources"][0]["fetched_at"],
        run["started_at"],
    ]
    assert all(datetime.fromisoformat(s).utcoffset() == timedelta(0) for s in stamps), stamps
    assert datetime.fromisoformat(run["started_at"]).hour == 3

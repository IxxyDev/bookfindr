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


async def test_publishers(client, api_publisher):
    res = await client.get("/publishers")
    assert res.status_code == 200
    data = res.json()
    ids = [p["id"] for p in data]
    assert "apipub" in ids


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

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

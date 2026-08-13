from datetime import date, timedelta

import httpx
import pytest

from app.clients.google_books import fetch_google_books
from app.core.config import GoogleBooksConfig, PublisherConfig, Settings
from tests.mock_http import install_mock_transport

API_KEY = "test-google-key"


def _publisher() -> PublisherConfig:
    return PublisherConfig(
        id="apress",
        name="Apress",
        google_books=GoogleBooksConfig(inpublishers=["Apress"], subjects=["computers"]),
    )


def _settings(**overrides) -> Settings:
    return Settings(google_books_api_key=API_KEY, **overrides)


def _first_page_only(items: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        first_page = request.url.params["startIndex"] == "0"
        return httpx.Response(200, json={"items": items} if first_page else {})

    return handler


def _volume(volume_id: str, published: date, title: str = "Programming Rust") -> dict:
    return {
        "id": volume_id,
        "volumeInfo": {
            "title": title,
            "publishedDate": published.isoformat(),
            "categories": ["Computers"],
        },
    }


async def test_query_terms_are_joined_with_a_space(monkeypatch):
    sent = install_mock_transport(monkeypatch, lambda request: httpx.Response(200, json={}))

    await fetch_google_books(_publisher(), _settings())

    assert sent[0].url.params["q"] == 'subject:computers inpublisher:"Apress"'
    assert b"%2B" not in sent[0].url.raw_path


async def test_api_key_goes_in_a_header_not_the_url(monkeypatch):
    sent = install_mock_transport(monkeypatch, lambda request: httpx.Response(200, json={}))

    await fetch_google_books(_publisher(), _settings())

    assert sent[0].headers["X-Goog-Api-Key"] == API_KEY
    assert API_KEY not in str(sent[0].url)


async def test_http_error_message_does_not_carry_the_api_key(monkeypatch):
    install_mock_transport(monkeypatch, lambda request: httpx.Response(403))

    with pytest.raises(httpx.HTTPStatusError) as raised:
        await fetch_google_books(_publisher(), _settings())

    assert API_KEY not in str(raised.value)


async def test_no_key_header_without_a_configured_key(monkeypatch):
    sent = install_mock_transport(monkeypatch, lambda request: httpx.Response(200, json={}))

    await fetch_google_books(_publisher(), Settings(google_books_api_key=None))

    assert "X-Goog-Api-Key" not in sent[0].headers


async def test_items_become_records(monkeypatch):
    published = date.today() - timedelta(days=3)
    install_mock_transport(monkeypatch, _first_page_only([_volume("v1", published)]))

    records = await fetch_google_books(_publisher(), _settings())

    assert [(r.source_key, r.published_date) for r in records] == [("v1", published)]


async def test_isbns_are_normalized(monkeypatch):
    volume = _volume("v2", date.today() - timedelta(days=3))
    volume["volumeInfo"]["industryIdentifiers"] = [
        {"type": "ISBN_13", "identifier": "978-1-4842-1234-5"},
        {"type": "ISBN_10", "identifier": "not-an-isbn"},
    ]
    install_mock_transport(monkeypatch, _first_page_only([volume]))

    records = await fetch_google_books(_publisher(), _settings())

    assert (records[0].isbn_13, records[0].isbn_10) == ("9781484212345", None)

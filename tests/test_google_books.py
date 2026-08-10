from datetime import date, timedelta

import httpx

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


async def test_items_become_records(monkeypatch):
    published = date.today() - timedelta(days=3)
    install_mock_transport(monkeypatch, _first_page_only([_volume("v1", published)]))

    records = await fetch_google_books(_publisher(), _settings())

    assert [(r.source_key, r.published_date) for r in records] == [("v1", published)]

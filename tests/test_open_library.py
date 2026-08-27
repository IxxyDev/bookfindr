from datetime import date, timedelta

import httpx

from app.clients.open_library import fetch_open_library
from app.core.config import OpenLibraryConfig, PublisherConfig, Settings
from tests.mock_http import install_mock_transport


def _publisher() -> PublisherConfig:
    return PublisherConfig(
        id="apress",
        name="Apress",
        open_library=OpenLibraryConfig(publishers=["Apress"], languages=["eng"]),
    )


def _first_page_only(docs: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        first_page = request.url.params["page"] == "1"
        return httpx.Response(200, json={"docs": docs if first_page else []})

    return handler


def _doc(key: str, **fields) -> dict:
    return {"key": key, "title": "Programming Rust", "subject": ["Computer programming"], **fields}


async def test_requests_the_fields_it_reads(monkeypatch):
    sent = install_mock_transport(monkeypatch, _first_page_only([]))

    await fetch_open_library(_publisher(), Settings())

    fields = sent[0].url.params["fields"].split(",")
    assert {"key", "title", "publish_date", "first_publish_year", "language", "isbn"} <= set(fields)


async def test_does_not_narrow_the_search_by_subject(monkeypatch):
    sent = install_mock_transport(monkeypatch, _first_page_only([]))

    await fetch_open_library(_publisher(), Settings())

    assert "subject" not in sent[0].url.params


async def test_publish_date_becomes_the_record_date(monkeypatch):
    published = date.today() - timedelta(days=5)
    doc = _doc("/works/OL1W", publish_date=[published.isoformat(), "2001"], language=["eng"])
    install_mock_transport(monkeypatch, _first_page_only([doc]))

    records = await fetch_open_library(_publisher(), Settings())

    assert [(r.source_key, r.published_date, r.language) for r in records] == [
        ("/works/OL1W", published, "en")
    ]


async def test_first_publish_year_is_the_fallback_date(monkeypatch):
    doc = _doc("/works/OL2W", first_publish_year=date.today().year)
    install_mock_transport(monkeypatch, _first_page_only([doc]))

    [record] = await fetch_open_library(_publisher(), Settings())

    assert record.published_date == date.today()
    assert record.published_date_is_sighting is True


async def test_doc_without_any_date_is_skipped(monkeypatch):
    install_mock_transport(monkeypatch, _first_page_only([_doc("/works/OL3W")]))

    assert await fetch_open_library(_publisher(), Settings()) == []


async def test_isbns_are_validated_not_picked_by_length(monkeypatch):
    published = date.today() - timedelta(days=5)
    doc = _doc(
        "/works/OL4W",
        publish_date=[published.isoformat()],
        isbn=["1234567890123", "978-1-4842-1234-5", "abcdefghij", "1-4842-1234-X"],
    )
    install_mock_transport(monkeypatch, _first_page_only([doc]))

    records = await fetch_open_library(_publisher(), Settings())

    assert (records[0].isbn_13, records[0].isbn_10) == ("9781484212345", "148421234X")


async def test_year_only_publish_date_of_the_current_year_is_a_sighting(monkeypatch):
    doc = _doc("/works/OL5W", publish_date=[str(date.today().year)])
    install_mock_transport(monkeypatch, _first_page_only([doc]))

    [record] = await fetch_open_library(_publisher(), Settings())

    assert record.published_date == date.today()
    assert record.published_date_is_sighting is True

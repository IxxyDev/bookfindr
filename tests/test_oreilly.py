from datetime import date, timedelta

import httpx
import pytest

from app.clients.connectors import oreilly
from app.core.config import PublisherConfig
from tests.mock_http import cap_results, install_mock_transport

WINDOW_DAYS = 90

RECENT = (date.today() - timedelta(days=3)).isoformat()


def _publisher(*names: str) -> PublisherConfig:
    return PublisherConfig(id="oreilly", name="O'Reilly Media", oreilly_publishers=list(names))


def _item(archive_id: str, *publishers: str) -> dict:
    return {
        "archive_id": archive_id,
        "title": f"Book {archive_id}",
        "issued": RECENT,
        "publishers": list(publishers),
    }


def _serve(items: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": items, "next": None})

    return handler


async def test_asks_the_api_for_the_configured_publisher(monkeypatch):
    sent = install_mock_transport(monkeypatch, _serve([]))

    await oreilly.fetch_oreilly_api(_publisher("O'Reilly Media, Inc."), WINDOW_DAYS)

    assert sent[0].url.params["publishers"] == "O'Reilly Media, Inc."


async def test_items_of_other_publishers_are_dropped(monkeypatch):
    items = [
        _item("1", "O'Reilly Media, Inc."),
        _item("2", "Packt Publishing"),
        _item("3"),
    ]
    install_mock_transport(monkeypatch, _serve(items))

    records = await oreilly.fetch_oreilly_api(_publisher("O'Reilly Media, Inc."), WINDOW_DAYS)

    assert [r.source_key for r in records] == ["1"]


async def test_publisher_without_api_names_fetches_nothing(monkeypatch):
    sent = install_mock_transport(monkeypatch, _serve([_item("1", "O'Reilly Media, Inc.")]))

    assert await oreilly.fetch_oreilly_api(_publisher(), WINDOW_DAYS) == []
    assert sent == []


def test_publishers_yml_names_the_api_publishers():
    from app.core.config import load_publishers

    config = {p.id: p for p in load_publishers("publishers.yml").publishers}
    assert config["oreilly"].oreilly_publishers == ["O'Reilly Media, Inc."]
    assert config["addison_wesley"].oreilly_publishers == ["Addison-Wesley Professional"]
    assert config["pearson"].oreilly_publishers == ["Pearson"]
    assert config["wrox"].oreilly_publishers == ["Wrox"]


async def test_future_dated_items_are_left_to_the_sync(monkeypatch):
    item = _item("1", "O'Reilly Media, Inc.")
    item["issued"] = (date.today() + timedelta(days=30)).isoformat()
    install_mock_transport(monkeypatch, _serve([item]))

    records = await oreilly.fetch_oreilly_api(_publisher("O'Reilly Media, Inc."), WINDOW_DAYS)

    assert [r.source_key for r in records] == ["1"]


def _pages(*pages: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        has_next = page < len(pages)
        items = pages[page - 1] if page <= len(pages) else []
        return httpx.Response(200, json={"results": items, "next": "more" if has_next else None})

    return handler


NAME = "O'Reilly Media, Inc."


async def test_follows_next_pages(monkeypatch):
    sent = install_mock_transport(monkeypatch, _pages([_item("1", NAME)], [_item("2", NAME)]))

    records = await oreilly.fetch_oreilly_api(_publisher(NAME), WINDOW_DAYS)

    assert [r.source_key for r in records] == ["1", "2"]
    assert [r.url.params["page"] for r in sent] == ["1", "2"]


async def test_a_page_reaching_past_the_window_is_the_last(monkeypatch):
    old = _item("old", NAME)
    old["issued"] = "2001-01-01"
    sent = install_mock_transport(monkeypatch, _pages([_item("1", NAME), old], [_item("2", NAME)]))

    records = await oreilly.fetch_oreilly_api(_publisher(NAME), WINDOW_DAYS)

    assert [r.source_key for r in records] == ["1", "old"]  # the sync drops "old"
    assert len(sent) == 1


async def test_results_are_capped(monkeypatch):
    cap_results(monkeypatch, oreilly, 1)
    install_mock_transport(monkeypatch, _pages([_item("1", NAME), _item("2", NAME)]))

    records = await oreilly.fetch_oreilly_api(_publisher(NAME), WINDOW_DAYS)

    assert [r.source_key for r in records] == ["1"]


async def test_http_error_propagates(monkeypatch):
    install_mock_transport(monkeypatch, lambda request: httpx.Response(403))

    with pytest.raises(httpx.HTTPStatusError):
        await oreilly.fetch_oreilly_api(_publisher(NAME), WINDOW_DAYS)


def test_published_date_prefers_issued_then_date_added_then_timestamp():
    assert oreilly._oreilly_published({"issued": "2026-05-01", "date_added": "2026-06-01"}) == date(
        2026, 5, 1
    )
    assert oreilly._oreilly_published(
        {"date_added": "2026-06-01T10:00:00Z", "timestamp": "2026-07-01"}
    ) == date(2026, 6, 1)
    assert oreilly._oreilly_published({"timestamp": "2026-07-01T00:00:00+03:00"}) == date(
        2026, 7, 1
    )
    assert oreilly._oreilly_published({}) is None


def test_record_fixes_relative_urls_and_normalizes_isbn():
    item = {
        "archive_id": "9781098100000",
        "title": "Fluent Python",
        "url": "/library/view/fluent-python/9781098100000/",
        "isbn": "978-1-0981-0000-0",
        "authors": "Luciano Ramalho",
        "description": "<p>Clear, <b>concise</b></p>",
    }
    record = oreilly._oreilly_record(item, _publisher(NAME), date(2026, 5, 1))

    assert (
        record.info_url == "https://learning.oreilly.com/library/view/fluent-python/9781098100000/"
    )
    assert record.isbn_13 == "9781098100000"
    assert record.authors == ["Luciano Ramalho"]
    assert record.description == "Clear, concise"


def test_record_keeps_absolute_urls():
    item = {"title": "T", "web_url": "https://www.oreilly.com/library/view/t/1/"}
    record = oreilly._oreilly_record(item, _publisher(NAME), date(2026, 5, 1))
    assert record.info_url == "https://www.oreilly.com/library/view/t/1/"
    assert record.source_key == "https://www.oreilly.com/library/view/t/1/"

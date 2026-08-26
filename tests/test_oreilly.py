from datetime import date, timedelta

import httpx

from app.clients.connectors import oreilly
from app.core.config import PublisherConfig
from tests.mock_http import install_mock_transport

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

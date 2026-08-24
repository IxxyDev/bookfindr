from datetime import date

import httpx

from app.clients.connectors import fetch_dmk_catalog
from app.core.config import PublisherConfig
from tests.mock_http import install_mock_transport
from tests.test_connectors import DMK_SAMPLE

WINDOW_DAYS = 90

PUBLISHER = PublisherConfig(id="dmk", name="ДМК Пресс")


def _first_page_only(request: httpx.Request) -> httpx.Response:
    first_page = "PAGEN_1" not in request.url.params
    return httpx.Response(200, text=DMK_SAMPLE if first_page else "<html></html>")


async def test_new_cards_are_dated_by_first_sighting(monkeypatch):
    install_mock_transport(monkeypatch, _first_page_only)

    [record] = await fetch_dmk_catalog(PUBLISHER, WINDOW_DAYS)

    assert record.title == "Увлекательная геометрия"
    assert record.published_date == date.today()
    assert record.published_date_is_sighting is True

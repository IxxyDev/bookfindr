from datetime import date

import httpx
import pytest

from app.clients.connectors import dmk
from app.clients.connectors.dmk import fetch_dmk_catalog
from app.core.config import PublisherConfig
from tests.mock_http import cap_results, install_mock_transport
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


OLD_ONLY = DMK_SAMPLE.split('<div class="cell">')[2]


def _pages(*pages: str):
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("PAGEN_1", "1"))
        return httpx.Response(200, text=pages[page - 1] if page <= len(pages) else "")

    return handler


async def test_pages_while_new_badges_last(monkeypatch):
    sent = install_mock_transport(monkeypatch, _pages(DMK_SAMPLE, DMK_SAMPLE, OLD_ONLY))

    records = await fetch_dmk_catalog(PUBLISHER, WINDOW_DAYS)

    assert len(records) == 2
    assert len(sent) == 3  # the page without badges ends the scan


async def test_paging_is_bounded(monkeypatch):
    sent = install_mock_transport(monkeypatch, lambda request: httpx.Response(200, text=DMK_SAMPLE))

    await fetch_dmk_catalog(PUBLISHER, WINDOW_DAYS)

    assert len(sent) == dmk.DMK_MAX_PAGES


async def test_results_are_capped(monkeypatch):
    cap_results(monkeypatch, dmk, 1)
    sent = install_mock_transport(monkeypatch, lambda request: httpx.Response(200, text=DMK_SAMPLE))

    records = await fetch_dmk_catalog(PUBLISHER, WINDOW_DAYS)

    assert len(records) == 1
    assert len(sent) == 1


async def test_http_error_propagates(monkeypatch):
    install_mock_transport(monkeypatch, lambda request: httpx.Response(404))

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_dmk_catalog(PUBLISHER, WINDOW_DAYS)

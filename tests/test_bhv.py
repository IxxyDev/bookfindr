from datetime import date

import httpx
import pytest

from app.clients.connectors import bhv
from app.clients.connectors.bhv import fetch_bhv_store
from app.core.config import PublisherConfig
from tests.mock_http import cap_results, install_mock_transport

WINDOW_DAYS = 90

PUBLISHER = PublisherConfig(id="bhv", name="БХВ-Петербург")


def _product(product_id: int, name: str, *categories: str) -> dict:
    return {"id": product_id, "name": name, "categories": [{"name": c} for c in categories]}


def _serve(products: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=products if request.url.params["page"] == "1" else [])

    return handler


async def test_computing_category_or_computing_title_is_kept(monkeypatch):
    products = [
        _product(1, "Самоучитель", "Компьютеры и программы"),
        _product(2, "Linux для всех", "Разное"),
        _product(3, "Роман о любви", "Художественная литература"),
    ]
    install_mock_transport(monkeypatch, _serve(products))

    records = await fetch_bhv_store(PUBLISHER, WINDOW_DAYS)

    assert [r.source_key for r in records] == ["1", "2"]


async def test_records_are_dated_by_first_sighting(monkeypatch):
    product = _product(1, "Самоучитель", "Компьютеры и программы")
    product["description"] = "<p>ISBN 978-5-9775-1234-5</p>"
    install_mock_transport(monkeypatch, _serve([product]))

    [record] = await fetch_bhv_store(PUBLISHER, WINDOW_DAYS)

    assert record.published_date == date.today()
    assert record.published_date_is_sighting is True
    assert record.isbn_13 == "9785977512345"


def _computing_page(first_id: int, size: int = bhv.BHV_PER_PAGE) -> list[dict]:
    return [_product(first_id + i, "Linux", "Компьютеры и программы") for i in range(size)]


async def test_a_short_page_is_the_last(monkeypatch):
    pages = {"1": _computing_page(0), "2": _computing_page(100, size=3)}
    sent = install_mock_transport(
        monkeypatch,
        lambda request: httpx.Response(200, json=pages.get(request.url.params["page"], [])),
    )

    records = await fetch_bhv_store(PUBLISHER, WINDOW_DAYS)

    assert len(records) == bhv.BHV_PER_PAGE + 3
    assert len(sent) == 2


async def test_paging_stops_at_max_pages(monkeypatch):
    sent = install_mock_transport(
        monkeypatch, lambda request: httpx.Response(200, json=_computing_page(0))
    )

    await fetch_bhv_store(PUBLISHER, WINDOW_DAYS)

    assert len(sent) == bhv.BHV_MAX_PAGES


async def test_results_are_capped(monkeypatch):
    cap_results(monkeypatch, bhv, 2)
    install_mock_transport(
        monkeypatch, lambda request: httpx.Response(200, json=_computing_page(0))
    )

    assert len(await fetch_bhv_store(PUBLISHER, WINDOW_DAYS)) == 2


async def test_error_object_instead_of_a_list_ends_the_feed(monkeypatch):
    install_mock_transport(
        monkeypatch, lambda request: httpx.Response(200, json={"code": "rest_invalid_param"})
    )

    assert await fetch_bhv_store(PUBLISHER, WINDOW_DAYS) == []


async def test_server_error_on_a_later_page_keeps_earlier_records(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["page"] == "1":
            return httpx.Response(200, json=_computing_page(0))
        return httpx.Response(501)  # not retried, so no backoff sleep in the test

    install_mock_transport(monkeypatch, handler)

    assert len(await fetch_bhv_store(PUBLISHER, WINDOW_DAYS)) == bhv.BHV_PER_PAGE


async def test_client_error_propagates(monkeypatch):
    install_mock_transport(monkeypatch, lambda request: httpx.Response(403))

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_bhv_store(PUBLISHER, WINDOW_DAYS)


def test_cover_comes_from_images_keyed_by_id():
    item = {"images": {"17": {"src": "https://bhv.ru/cover.jpg"}}}
    assert bhv._bhv_cover(item) == "https://bhv.ru/cover.jpg"


def test_cover_from_a_list_and_missing_images():
    assert bhv._bhv_cover({"images": [{"src": "https://bhv.ru/a.jpg"}]}) == "https://bhv.ru/a.jpg"
    assert bhv._bhv_cover({"images": []}) is None
    assert bhv._bhv_cover({}) is None

from datetime import date, timedelta

import httpx
import pytest

from app.clients.connectors.nit import fetch_nit_catalog
from app.core.config import PublisherConfig
from tests.mock_http import install_mock_transport

WINDOW_DAYS = 90

PUBLISHER = PublisherConfig(id="nauka_technika", name="Наука и техника")
UPDATED_AT = date.today() - timedelta(days=4)
PROPERTIES = [
    {"id": 1, "title": "Автор"},
    {"id": 2, "title": "ISBN"},
    {"id": 3, "title": "Год издания"},
    {"id": 4, "title": "Количество страниц"},
]


def _product(product_id: int, year: int) -> dict:
    return {
        "id": product_id,
        "title": f"Сети и Linux, том {product_id}",
        "url": f"/product/{product_id}",
        "updated_at": UPDATED_AT.isoformat() + "T08:00:00+03:00",
        "first_image": {"large_url": "https://static.insales.ru/cover.jpg"},
        "properties": PROPERTIES,
        "characteristics": [
            {"property_id": 1, "title": "Иванов И., Петров П."},
            {"property_id": 2, "title": "978-5-94387-123-4"},
            {"property_id": 3, "title": str(year)},
            {"property_id": 4, "title": "320"},
        ],
    }


def _serve(products: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        first_page = request.url.params["page"] == "1"
        return httpx.Response(200, json={"products": products if first_page else []})

    return handler


async def test_characteristics_fill_the_record(monkeypatch):
    install_mock_transport(monkeypatch, _serve([_product(1, date.today().year)]))

    [record] = await fetch_nit_catalog(PUBLISHER, WINDOW_DAYS)

    assert record.authors == ["Иванов И.", "Петров П."]
    assert record.isbn_13 == "9785943871234"
    assert record.page_count == 320
    assert record.published_date == UPDATED_AT
    assert record.info_url == "https://nit.com.ru/product/1"
    assert record.cover_url == "https://static.insales.ru/cover.jpg"


async def test_publication_year_dates_the_product_not_updated_at(monkeypatch):
    install_mock_transport(monkeypatch, _serve([_product(1, 2015)]))

    [record] = await fetch_nit_catalog(PUBLISHER, WINDOW_DAYS)

    assert record.published_date == date(2015, 1, 1)  # the sync drops it, not the connector


async def test_http_error_is_raised_not_swallowed(monkeypatch):
    install_mock_transport(monkeypatch, lambda request: httpx.Response(404))

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_nit_catalog(PUBLISHER, WINDOW_DAYS)

from datetime import date, timedelta

import httpx

from app.clients import connectors
from app.core.config import PublisherConfig
from tests.mock_http import install_mock_transport

PUBLISHER = PublisherConfig(id="piter", name="Питер")
YEAR_PROPERTY = 1
PRINT_YEAR_PROPERTY = 2


def _product(product_id: int, *, year: int | None = None, print_year: int | None = None) -> dict:
    characteristics = []
    if year is not None:
        characteristics.append({"property_id": YEAR_PROPERTY, "title": str(year)})
    if print_year is not None:
        characteristics.append({"property_id": PRINT_YEAR_PROPERTY, "title": str(print_year)})
    return {
        "id": product_id,
        "title": f"Книга {product_id}",
        "url": f"/product/{product_id}",
        "updated_at": (date.today() - timedelta(days=2)).isoformat() + "T10:00:00Z",
        "properties": [
            {"id": YEAR_PROPERTY, "title": "Год"},
            {"id": PRINT_YEAR_PROPERTY, "title": "Год тиража"},
        ],
        "characteristics": characteristics,
    }


def _full_page(**year_fields) -> list[dict]:
    return [_product(i, **year_fields) for i in range(100)]


def _serve(page_products):
    def handler(request: httpx.Request) -> httpx.Response:
        products = page_products(int(request.url.params["page"]))
        return httpx.Response(200, json={"count": 10_000, "products": products})

    return handler


def test_print_year_dates_a_product_without_a_publication_year():
    assert connectors._piter_published_date(_product(1, print_year=2015)) == date(2015, 1, 1)


def test_publication_year_wins_over_print_year():
    assert connectors._piter_published_date(_product(1, year=2014, print_year=2015)) == date(
        2014, 1, 1
    )


async def test_paging_stops_at_a_page_of_only_old_years(monkeypatch):
    sent = install_mock_transport(monkeypatch, _serve(lambda page: _full_page(print_year=2015)))

    assert await connectors.fetch_piter_catalog(PUBLISHER) == []
    assert len(sent) == 1


async def test_paging_stops_after_max_pages(monkeypatch):
    monkeypatch.setattr(connectors, "PITER_MAX_PAGES", 1)
    sent = install_mock_transport(
        monkeypatch, _serve(lambda page: _full_page(year=date.today().year))
    )

    records = await connectors.fetch_piter_catalog(PUBLISHER)

    assert len(sent) == 1
    assert len(records) == 100

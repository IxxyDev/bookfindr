import json
from datetime import date, timedelta

import httpx
import pytest

from app.clients.connectors import manning
from app.clients.connectors.manning import fetch_manning_catalog
from app.core.config import PublisherConfig
from tests.mock_http import cap_results, install_mock_transport

WINDOW_DAYS = 90

PUBLISHER = PublisherConfig(id="manning", name="Manning Publications")
RECENT = (date.today() - timedelta(days=3)).isoformat() + "T00:00:00"


def _serve(products: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        pagination = {"page": 1, "pages": 1, "hasNextPage": False}
        return httpx.Response(200, json={"products": products, "pagination": pagination})

    return handler


async def test_product_without_any_identifier_is_skipped(monkeypatch):
    products = [
        {"id": 42, "title": "Kubernetes in Action", "date": RECENT},
        {"title": "Mystery product", "date": RECENT},
    ]
    install_mock_transport(monkeypatch, _serve(products))

    records = await fetch_manning_catalog(PUBLISHER, WINDOW_DAYS)

    assert [r.source_key for r in records] == ["42"]


def _product(product_id: int, published: str = RECENT) -> dict:
    return {"id": product_id, "title": f"Book {product_id}", "date": published}


def _pages(*pages: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        page = json.loads(request.content)["page"]
        pagination = {"page": page, "pages": len(pages), "hasNextPage": page < len(pages)}
        products = pages[page - 1] if page <= len(pages) else []
        return httpx.Response(200, json={"products": products, "pagination": pagination})

    return handler


async def test_follows_pages_while_the_catalog_says_there_are_more(monkeypatch):
    sent = install_mock_transport(monkeypatch, _pages([_product(1)], [_product(2)]))

    records = await fetch_manning_catalog(PUBLISHER, WINDOW_DAYS)

    assert [r.source_key for r in records] == ["1", "2"]
    assert len(sent) == 2
    body = json.loads(sent[0].content)
    assert body["selectedCategoryIds"] == [manning.MANNING_COMPUTING_CATEGORY_ID]
    assert body["sort"] == "newest"


async def test_a_page_reaching_past_the_window_is_the_last(monkeypatch):
    sent = install_mock_transport(
        monkeypatch, _pages([_product(1), _product(2, "2001-01-01T00:00:00")], [_product(3)])
    )

    records = await fetch_manning_catalog(PUBLISHER, WINDOW_DAYS)

    assert [r.source_key for r in records] == ["1", "2"]  # the sync drops the old one
    assert len(sent) == 1


async def test_results_are_capped(monkeypatch):
    cap_results(monkeypatch, manning, 1)
    install_mock_transport(monkeypatch, _pages([_product(1), _product(2)]))

    assert len(await fetch_manning_catalog(PUBLISHER, WINDOW_DAYS)) == 1


async def test_http_error_propagates(monkeypatch):
    install_mock_transport(monkeypatch, lambda request: httpx.Response(400))

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_manning_catalog(PUBLISHER, WINDOW_DAYS)


def test_manning_date_reads_the_date_part():
    assert manning._manning_date("2026-05-04T00:00:00") == date(2026, 5, 4)
    assert manning._manning_date("2026-05-04") == date(2026, 5, 4)
    assert manning._manning_date("May 2026") == date(2026, 5, 1)
    assert manning._manning_date("soon") is None
    assert manning._manning_date(None) is None


def test_cover_url_depends_on_the_cover_shape():
    assert manning._manning_cover_url({"imageUrl": "a.png", "wideCover": True}) == (
        "https://images.manning.com/264/149/resize/a.png"
    )
    assert manning._manning_cover_url({"imageUrl": "a.png"}) == (
        "https://images.manning.com/320/400/resize/a.png"
    )
    assert manning._manning_cover_url({}) is None

from datetime import date, timedelta

import httpx

from app.clients.connectors.manning import fetch_manning_catalog
from app.core.config import PublisherConfig
from tests.mock_http import install_mock_transport

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

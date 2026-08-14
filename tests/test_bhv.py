import httpx

from app.clients.connectors import fetch_bhv_store
from app.core.config import PublisherConfig
from tests.mock_http import install_mock_transport

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

    records = await fetch_bhv_store(PUBLISHER)

    assert [r.source_key for r in records] == ["1", "2"]

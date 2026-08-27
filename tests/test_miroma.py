import httpx
import pytest

from app.clients.connectors import miroma
from app.core.config import PublisherConfig
from tests.mock_http import cap_results, install_mock_transport
from tests.test_connectors import MIROMA_ROWS, _xlsx_bytes

WINDOW_DAYS = 90

PUBLISHER = PublisherConfig(id="bhv", name="БХВ-Петербург", aliases=["БХВ"])
LISTING_URL = "https://miromabook.ru/prays-listy/"


def test_sheet_without_publisher_column_is_skipped_when_names_are_wanted():
    assert miroma._parse_miroma_workbook(_xlsx_bytes(MIROMA_ROWS), ["БХВ"]) == []


def test_source_key_without_isbn_survives_rows_moving():
    rows = [["Наименование", "Автор"], ["Сети для всех", "Иванов И."]]
    shifted = [rows[0], ["Linux с нуля", ""], rows[1]]

    [before] = miroma._parse_miroma_workbook(_xlsx_bytes(rows), file_name="price.xlsx")
    after = miroma._parse_miroma_workbook(_xlsx_bytes(shifted), file_name="price.xlsx")

    assert before.source_key == after[1].source_key
    assert before.source_key.startswith("price.xlsx:")
    other_file = miroma._parse_miroma_workbook(_xlsx_bytes(rows), file_name="other.xlsx")
    assert other_file[0].source_key != before.source_key


def test_price_links_resolve_relative_to_the_page_dedupe_and_accept_single_quotes():
    html = (
        '<a href="/files/price.xls">a</a>'
        "<a href='files/new.xlsx'>b</a>"
        '<a href="/files/price.xls">again</a>'
        '<a href="https://cdn.example.com/all.zip">c</a>'
    )
    assert miroma._extract_price_links(html, LISTING_URL) == [
        "https://miromabook.ru/files/price.xls",
        "https://miromabook.ru/prays-listy/files/new.xlsx",
        "https://cdn.example.com/all.zip",
    ]


def _site(price_list: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == LISTING_URL:
            return httpx.Response(200, text='<a href="/files/price.xlsx">price</a>')
        return httpx.Response(200, content=price_list)

    return handler


async def test_price_list_is_downloaded_and_parsed(monkeypatch):
    rows = [["Наименование", "Издательство"], ["Linux для всех", "БХВ"]]
    install_mock_transport(monkeypatch, _site(_xlsx_bytes(rows)))

    [record] = await miroma.fetch_miroma_price(PUBLISHER, WINDOW_DAYS)

    assert (record.title, record.publisher_id, record.source) == (
        "Linux для всех",
        "bhv",
        "miroma_price",
    )
    assert record.source_key.startswith("price.xlsx:")


async def test_price_list_over_the_download_budget_is_skipped(monkeypatch):
    monkeypatch.setattr(miroma, "MIROMA_MAX_DOWNLOAD_BYTES", 100)
    rows = [["Наименование", "Издательство"], ["Linux для всех", "БХВ"]]
    install_mock_transport(monkeypatch, _site(_xlsx_bytes(rows)))

    assert await miroma.fetch_miroma_price(PUBLISHER, WINDOW_DAYS) == []


BHV_ROWS = [["Наименование", "Издательство"], ["Linux для всех", "БХВ"], ["Сети", "БХВ"]]


async def test_a_broken_price_list_does_not_stop_the_others(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == LISTING_URL:
            links = '<a href="/files/broken.xlsx">x</a><a href="/files/good.xlsx">y</a>'
            return httpx.Response(200, text=links)
        if request.url.path.endswith("broken.xlsx"):
            return httpx.Response(404)
        return httpx.Response(200, content=_xlsx_bytes(BHV_ROWS))

    install_mock_transport(monkeypatch, handler)

    records = await miroma.fetch_miroma_price(PUBLISHER, WINDOW_DAYS)

    assert [r.title for r in records] == ["Linux для всех", "Сети"]


async def test_results_are_capped(monkeypatch):
    cap_results(monkeypatch, miroma, 1)
    install_mock_transport(monkeypatch, _site(_xlsx_bytes(BHV_ROWS)))

    assert len(await miroma.fetch_miroma_price(PUBLISHER, WINDOW_DAYS)) == 1


async def test_unreachable_listing_propagates(monkeypatch):
    install_mock_transport(monkeypatch, lambda request: httpx.Response(403))

    with pytest.raises(httpx.HTTPStatusError):
        await miroma.fetch_miroma_price(PUBLISHER, WINDOW_DAYS)

import httpx

from app.clients import connectors
from app.core.config import PublisherConfig
from tests.mock_http import install_mock_transport
from tests.test_connectors import MIROMA_ROWS, _xlsx_bytes

PUBLISHER = PublisherConfig(id="bhv", name="БХВ-Петербург", aliases=["БХВ"])
LISTING_URL = "https://miromabook.ru/prays-listy/"


def test_sheet_without_publisher_column_is_skipped_when_names_are_wanted():
    assert connectors._parse_miroma_workbook(_xlsx_bytes(MIROMA_ROWS), ["БХВ"]) == []


def test_source_key_without_isbn_survives_rows_moving():
    rows = [["Наименование", "Автор"], ["Сети для всех", "Иванов И."]]
    shifted = [rows[0], ["Linux с нуля", ""], rows[1]]

    [before] = connectors._parse_miroma_workbook(_xlsx_bytes(rows), file_name="price.xlsx")
    after = connectors._parse_miroma_workbook(_xlsx_bytes(shifted), file_name="price.xlsx")

    assert before.source_key == after[1].source_key
    assert before.source_key.startswith("price.xlsx:")
    other_file = connectors._parse_miroma_workbook(_xlsx_bytes(rows), file_name="other.xlsx")
    assert other_file[0].source_key != before.source_key


def test_price_links_resolve_relative_to_the_page_dedupe_and_accept_single_quotes():
    html = (
        '<a href="/files/price.xls">a</a>'
        "<a href='files/new.xlsx'>b</a>"
        '<a href="/files/price.xls">again</a>'
        '<a href="https://cdn.example.com/all.zip">c</a>'
    )
    assert connectors._extract_price_links(html, LISTING_URL) == [
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

    [record] = await connectors.fetch_miroma_price(PUBLISHER)

    assert (record.title, record.publisher_id, record.source) == (
        "Linux для всех",
        "bhv",
        "miroma_price",
    )
    assert record.source_key.startswith("price.xlsx:")


async def test_price_list_over_the_download_budget_is_skipped(monkeypatch):
    monkeypatch.setattr(connectors, "MIROMA_MAX_DOWNLOAD_BYTES", 100)
    rows = [["Наименование", "Издательство"], ["Linux для всех", "БХВ"]]
    install_mock_transport(monkeypatch, _site(_xlsx_bytes(rows)))

    assert await connectors.fetch_miroma_price(PUBLISHER) == []

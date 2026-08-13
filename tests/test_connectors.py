from datetime import date

from selectolax.lexbor import LexborHTMLParser

from app.clients.connectors import (
    _extract_price_links,
    _find_isbn_in_text,
    _manning_authors,
    _packt_isbn,
    _packt_pages,
    _parse_dmk_page,
    _parse_packt_date,
)


def test_parse_packt_date_ordinal():
    assert _parse_packt_date("Jan 21st, 2025") == date(2025, 1, 21)
    assert _parse_packt_date("February 3rd, 2025") == date(2025, 2, 3)
    assert _parse_packt_date("Mar 22nd 2024") == date(2024, 3, 22)


def test_parse_packt_date_month_year():
    assert _parse_packt_date("Mar 2025") == date(2025, 3, 1)


def test_parse_packt_date_invalid():
    assert _parse_packt_date("") is None
    assert _parse_packt_date("not a date") is None


def test_packt_pages():
    assert _packt_pages("Paperback, 350 pages, English") == 350
    assert _packt_pages("no page info here") is None


def test_packt_isbn_from_data_attr():
    html = LexborHTMLParser(
        '<div class="card"><span data-default-selected-isbn="9781803239349"></span></div>'
    )
    card = html.css_first(".card")
    assert _packt_isbn(card) == "9781803239349"


def test_packt_isbn_missing():
    card = LexborHTMLParser('<div class="card"><span>no isbn</span></div>').css_first(".card")
    assert _packt_isbn(card) is None


def test_find_isbn_in_text_hyphenated():
    assert _find_isbn_in_text("ISBN 978-5-9775-1234-5, 2025") == "9785977512345"


def test_find_isbn_in_text_spaced():
    assert _find_isbn_in_text("ISBN: 978 5 9775 1234 5") == "9785977512345"


def test_find_isbn_in_text_absent():
    assert _find_isbn_in_text("никакого ISBN тут нет") is None
    assert _find_isbn_in_text("") is None


def test_manning_authors_html_and_separators():
    assert _manning_authors("<i>John  Doe and Jane Roe</i>") == ["John Doe", "Jane Roe"]
    assert _manning_authors("Alice Smith, Bob Jones") == ["Alice Smith", "Bob Jones"]
    assert _manning_authors(None) == []
    assert _manning_authors("") == []


# Trimmed real markup from dmkpress.com/catalog/computer/
DMK_SAMPLE = """
<div class="cell">
  <div class="book-card" data-product data-product-id="13974">
    <a class="book-card__pic" href="/catalog/computer/978-5-93700-473-4/">
      <picture><img src="/upload/resize_cache/iblock/50e/cover.jpg"
        alt="Увлекательная геометрия"/></picture>
      <div class="book-card__novel">Новинка</div>
    </a>
    <div class="book-card__main">
      <a class="book-card__title"
        href="/catalog/computer/978-5-93700-473-4/">Увлекательная геометрия</a>
      <div class="book-card__autor"><a href="/author/7420/">Златопольский Д.</a></div>
    </div>
  </div>
</div>
<div class="cell">
  <div class="book-card" data-product data-product-id="13975">
    <a class="book-card__pic" href="/catalog/computer/978-5-93700-001-9/">
      <picture><img src="https://cdn.example.com/old.jpg" alt="Старая книга"/></picture>
    </a>
    <div class="book-card__main">
      <a class="book-card__title" href="/catalog/computer/978-5-93700-001-9/">Старая книга</a>
      <div class="book-card__autor"><a href="/author/1/">Автор А.</a><a
        href="/author/2/">Автор Б.</a></div>
    </div>
  </div>
</div>
"""


def test_parse_dmk_page():
    cards = _parse_dmk_page(DMK_SAMPLE)
    assert len(cards) == 2

    new = cards[0]
    assert new["title"] == "Увлекательная геометрия"
    assert new["is_new"] is True
    assert new["isbn_13"] == "9785937004734"
    assert new["info_url"] == "https://www.dmkpress.com/catalog/computer/978-5-93700-473-4/"
    assert new["cover_url"] == "https://www.dmkpress.com/upload/resize_cache/iblock/50e/cover.jpg"
    assert new["authors"] == ["Златопольский Д."]

    old = cards[1]
    assert old["is_new"] is False
    assert old["cover_url"] == "https://cdn.example.com/old.jpg"
    assert old["authors"] == ["Автор А.", "Автор Б."]


def test_parse_dmk_page_drops_isbn_of_wrong_length():
    html = DMK_SAMPLE.replace("978-5-93700-473-4", "978-5-93700-473-4-99")
    assert _parse_dmk_page(html)[0]["isbn_13"] is None


def test_parse_dmk_page_empty():
    assert _parse_dmk_page("<html><body>nothing here</body></html>") == []


def test_extract_price_links():
    html = (
        '<a href="/files/price.xls">xls</a>'
        '<a href="https://miromabook.ru/files/full.XLSX">abs</a>'
        '<a href="/about.html">not a price</a>'
    )
    links = _extract_price_links(html, "https://miromabook.ru")
    assert links == [
        "https://miromabook.ru/files/price.xls",
        "https://miromabook.ru/files/full.XLSX",
    ]


def _xlsx_bytes(rows: list[list[object]]) -> bytes:
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Прайс"
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


MIROMA_ROWS = [
    ["Наименование", "Автор", "Год", "ISBN"],
    ["Linux для всех", "Иванов И., Петров П.", 2025, 9785000000001],
    ["", "пусто", 2025, ""],
    ["Без года", "", "", "978-5-0000-0002-8"],
]


def test_parse_miroma_workbook_xlsx():
    from app.clients.connectors import _parse_miroma_workbook

    records = _parse_miroma_workbook(_xlsx_bytes(MIROMA_ROWS))
    assert [r.title for r in records] == ["Linux для всех", "Без года"]
    first = records[0]
    assert first.authors == ["Иванов И.", "Петров П."]
    assert first.published_date == date(2025, 1, 1)
    assert first.isbn_13 == "9785000000001"
    assert first.source_key == "Прайс-1"
    assert records[1].published_date is None
    assert records[1].isbn_13 == "9785000000028"  # hyphens stripped


MIROMA_DISTRIBUTOR_ROWS = [
    ["Тел.: 8 (812) 251-03-05", "", "", "", "", "Сумма заказа:"],
    ["", "ЗАКАЗАТЬ АКТУАЛЬНЫЙ ПРАЙС", "www.miromabook.ru/", "", "", ""],
    ["", "Название", "Автор", "Издательство", "Год издания", "Кол-во страниц", "ISBN"],
    ["", "Linux для всех", "Иванов И.", "БХВ (г. Санкт-Петербург)", 2026, 320, "9785000000001"],
    ["", "Сказки", "Пушкин А.С.", "Эксмо (г. Москва)", 2026, 100, "9785000000002"],
    ["", "Старая книга по сетям", "Петров П.", "БХВ (г. Санкт-Петербург)", 2020, "", ""],
]


def test_parse_miroma_workbook_finds_header_after_preamble_and_filters_publisher():
    from app.clients.connectors import _parse_miroma_workbook

    everything = _parse_miroma_workbook(_xlsx_bytes(MIROMA_DISTRIBUTOR_ROWS))
    assert [r.title for r in everything] == ["Linux для всех", "Сказки", "Старая книга по сетям"]

    bhv_only = _parse_miroma_workbook(
        _xlsx_bytes(MIROMA_DISTRIBUTOR_ROWS), publisher_names=["БХВ-Петербург", "BHV", "БХВ"]
    )
    assert [r.title for r in bhv_only] == ["Linux для всех", "Старая книга по сетям"]
    assert bhv_only[0].page_count == 320
    assert bhv_only[0].isbn_13 == "9785000000001"
    assert bhv_only[0].published_date == date.today()  # current year: first sighting
    assert bhv_only[1].published_date == date(2020, 1, 1)
    assert bhv_only[0].raw["publisher"] == "БХВ (г. Санкт-Петербург)"

    nothing = _parse_miroma_workbook(
        _xlsx_bytes(MIROMA_DISTRIBUTOR_ROWS), publisher_names=["Miroma Book"]
    )
    assert nothing == []


def test_parse_miroma_workbook_sorts_isbn_cells_into_13_and_10():
    from app.clients.connectors import _parse_miroma_workbook

    rows = [
        ["Наименование", "ISBN"],
        ["Два ISBN", "978-5-9775-1234-5, 978-5-9775-1234-6"],
        ["Только десятизначный", "5-9775-1234-X"],
        ["Мусор", "12345"],
    ]
    records = _parse_miroma_workbook(_xlsx_bytes(rows))
    assert [(r.isbn_13, r.isbn_10) for r in records] == [
        ("9785977512345", None),
        (None, "597751234X"),
        (None, None),
    ]


def test_parse_miroma_workbook_zip_with_xlsx():
    import io
    import zipfile

    from app.clients.connectors import _parse_miroma_workbook

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("readme.txt", "ignored")
        archive.writestr("price/full.xlsx", _xlsx_bytes(MIROMA_ROWS))
    records = _parse_miroma_workbook(buf.getvalue())
    assert len(records) == 2


def test_parse_miroma_workbook_garbage_is_empty():
    from app.clients.connectors import _parse_miroma_workbook

    assert _parse_miroma_workbook(b"not a spreadsheet") == []
    assert _parse_miroma_workbook(b"PK\x03\x04broken") == []


def test_cell_text_normalizes_numeric_cells():
    from app.clients.connectors import _cell_text

    assert _cell_text(None) == ""
    assert _cell_text(2025.0) == "2025"  # xlrd returns every number as float
    assert _cell_text(9785000000001.0) == "9785000000001"
    assert _cell_text(3.5) == "3.5"
    assert _cell_text(2025) == "2025"


def test_parse_miroma_workbook_xls_via_xlrd(monkeypatch):
    from app.clients import connectors

    grid = [["Название", "Год", "ISBN"], ["Книга про сети", 2025.0, 9785000000001.0]]

    class _Sheet:
        name = "Лист1"
        nrows = len(grid)
        ncols = len(grid[0])

        def cell_value(self, r, c):
            return grid[r][c]

    class _Book:
        def sheets(self):
            return [_Sheet()]

    monkeypatch.setattr(connectors.xlrd, "open_workbook", lambda file_contents: _Book())
    records = connectors._parse_miroma_workbook(b"\xd0\xcf\x11\xe0 legacy xls")
    assert len(records) == 1
    assert records[0].title == "Книга про сети"
    assert records[0].published_date == date(2025, 1, 1)
    assert records[0].isbn_13 == "9785000000001"
    assert records[0].source_key == "Лист1-1"


def test_parse_miroma_workbook_rejects_nested_archives():
    import io
    import zipfile

    from app.clients.connectors import _parse_miroma_workbook

    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("price.xlsx", _xlsx_bytes(MIROMA_ROWS))
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("inner.xlsx", inner.getvalue())  # a zip masquerading as a workbook
    assert _parse_miroma_workbook(outer.getvalue()) == []


def test_parse_miroma_workbook_enforces_size_budget(monkeypatch):
    from app.clients import connectors

    payload = _xlsx_bytes(MIROMA_ROWS)
    monkeypatch.setattr(connectors, "ZIP_MAX_UNCOMPRESSED_BYTES", 100)
    assert connectors._parse_miroma_workbook(payload) == []
    monkeypatch.setattr(connectors, "ZIP_MAX_UNCOMPRESSED_BYTES", 50 * 1024 * 1024)
    monkeypatch.setattr(connectors, "ZIP_MAX_MEMBERS", 1)
    assert connectors._parse_miroma_workbook(payload) == []


def test_date_from_year_current_year_uses_fallback_or_today():
    from app.clients.connectors import _date_from_year

    today = date(2026, 9, 20)
    assert _date_from_year(2026, today) == today
    assert _date_from_year(2026, today, fallback=date(2026, 8, 1)) == date(2026, 8, 1)
    assert _date_from_year(2025, today) == date(2025, 1, 1)
    assert _date_from_year(2027, today, fallback=date(2026, 8, 1)) == date(2027, 1, 1)


def test_piter_isbn_is_stored_without_hyphens():
    from app.clients.connectors import _piter_isbn

    prod = {
        "properties": [{"id": 7, "title": "ISBN"}],
        "characteristics": [{"property_id": 7, "title": "978-5-4461-2345-6"}],
    }
    assert _piter_isbn(prod) == "9785446123456"


def _piter_product(year: str | None, updated_at: str | None) -> dict:
    prod = {"properties": [{"id": 1, "title": "Год"}], "characteristics": []}
    if year is not None:
        prod["characteristics"].append({"property_id": 1, "title": year})
    if updated_at is not None:
        prod["updated_at"] = updated_at
    return prod


def test_piter_published_date(monkeypatch):
    from app.clients import connectors

    class _Today(date):
        @classmethod
        def today(cls):
            return date(2026, 9, 20)

    monkeypatch.setattr(connectors, "date", _Today)
    current_year = connectors._piter_published_date(_piter_product("2026", "2026-09-01T10:00:00Z"))
    assert current_year == date(2026, 9, 1)
    assert connectors._piter_published_date(_piter_product("2026", None)) == date(2026, 9, 20)
    assert connectors._piter_published_date(_piter_product("2024", "2026-09-01T10:00:00Z")) == date(
        2024, 1, 1
    )
    assert connectors._piter_published_date(_piter_product("2027", None)) == date(2027, 1, 1)
    assert connectors._piter_published_date(_piter_product(None, "2026-09-01T10:00:00Z")) == date(
        2026, 9, 1
    )
    assert connectors._piter_published_date(_piter_product(None, None)) is None

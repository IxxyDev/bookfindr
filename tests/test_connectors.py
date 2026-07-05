from datetime import date

from selectolax.parser import HTMLParser

from app.clients.connectors import (
    _extract_price_links,
    _find_isbn_in_text,
    _manning_authors,
    _packt_isbn,
    _packt_pages,
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
    html = HTMLParser(
        '<div class="card"><span data-default-selected-isbn="9781803239349"></span></div>'
    )
    card = html.css_first(".card")
    assert _packt_isbn(card) == "9781803239349"


def test_packt_isbn_missing():
    card = HTMLParser('<div class="card"><span>no isbn</span></div>').css_first(".card")
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

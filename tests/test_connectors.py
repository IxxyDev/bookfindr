from datetime import date

from selectolax.parser import HTMLParser

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

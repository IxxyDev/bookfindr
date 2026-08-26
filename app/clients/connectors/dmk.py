import re
from datetime import date

from selectolax.lexbor import LexborHTMLParser

from app.clients.connectors._http import Collector, source_client
from app.core.config import PublisherConfig, get_settings
from app.services.types import BookRecord
from app.utils.http import get_with_retries
from app.utils.isbn import normalize_isbn13

# DMK Press computer-literature catalog (Bitrix HTML)
DMK_BASE = "https://www.dmkpress.com"
DMK_COMPUTER_URL = DMK_BASE + "/catalog/computer/"
# "Новинка" badges sit on the first page or two; five pages is a generous bound
DMK_MAX_PAGES = 5
# the whole hyphenated run: normalize_isbn13 rejects it unless it holds exactly 13 digits
DMK_ISBN_RE = re.compile(r"97[89][-0-9]+")


async def fetch_dmk_catalog(publisher: PublisherConfig, window_days: int) -> list[BookRecord]:
    """Cards badged "Новинка"; paging stops with the badges, the window plays no part."""
    settings = get_settings()
    collector = Collector(settings.max_results_per_source)

    async with source_client(settings, follow_redirects=True) as client:
        for page in range(1, DMK_MAX_PAGES + 1):
            params = {"PAGEN_1": page} if page > 1 else None
            resp = await get_with_retries(client, DMK_COMPUTER_URL, params=params)
            cards = _parse_dmk_page(resp.text)
            if not cards:
                break
            new_cards = [c for c in cards if c["is_new"]]
            for c in new_cards:
                if collector.add(_dmk_record(c, publisher)):
                    return collector.records
            if not new_cards:
                # "Новинка" badges are gone: older pages only from here on
                break
    return collector.records


def _dmk_record(card: dict, publisher: PublisherConfig) -> BookRecord:
    return BookRecord(
        source="dmk_html",
        source_key=card["isbn_13"] or card["info_url"],
        publisher_id=publisher.id,
        title=card["title"],
        authors=card["authors"],
        language="ru",
        subjects=["computers"],
        isbn_13=card["isbn_13"],
        # cards carry no publish date; record first sighting
        published_date=date.today(),
        published_date_is_sighting=True,
        cover_url=card["cover_url"],
        info_url=card["info_url"],
        raw={"href": card["info_url"]},
    )


def _parse_dmk_page(html_text: str) -> list[dict]:
    html = LexborHTMLParser(html_text)
    cards = []
    for card in html.css(".book-card"):
        title_el = card.css_first("a.book-card__title")
        if not title_el:
            continue
        href = title_el.attributes.get("href") or ""
        info_url = href if href.startswith("http") else DMK_BASE + href
        m = DMK_ISBN_RE.search(href)
        isbn_13 = normalize_isbn13(m.group(0)) if m else None
        cover_el = card.css_first(".book-card__pic img")
        cover_url = cover_el.attributes.get("src") if cover_el else None
        if cover_url and cover_url.startswith("/"):
            cover_url = DMK_BASE + cover_url
        cards.append(
            {
                "title": title_el.text(strip=True),
                "authors": [a.text(strip=True) for a in card.css(".book-card__autor a")],
                "info_url": info_url,
                "isbn_13": isbn_13,
                "cover_url": cover_url,
                "is_new": card.css_first(".book-card__novel") is not None,
            }
        )
    return cards

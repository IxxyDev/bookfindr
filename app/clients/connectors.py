import io
import logging
import re
import zipfile
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta

import httpx
import openpyxl
import xlrd
from selectolax.parser import HTMLParser

from app.core.config import PublisherConfig, get_settings
from app.services.types import BookRecord
from app.utils.dates import parse_date
from app.utils.http import get_with_retries, request_with_retries

logger = logging.getLogger(__name__)


async def fetch_connectors(publisher: PublisherConfig) -> list[BookRecord]:
    connectors = publisher.connectors or []
    results: list[BookRecord] = []
    for name in connectors:
        fetcher = CONNECTOR_MAP.get(name)
        if not fetcher:
            logger.warning("Unknown connector %s for %s", name, publisher.id)
            continue
        try:
            records = await fetcher(publisher)
            results.extend(records)
        except Exception as exc:  # pragma: no cover - best-effort
            logger.exception("Connector %s failed for %s: %s", name, publisher.id, exc)
    return results


# ---- O'Reilly new & upcoming (JSON API) ----
OREILLY_SEARCH_URL = "https://learning.oreilly.com/api/v2/search/"


def _oreilly_authors(obj: dict) -> list[str]:
    authors = obj.get("authors") or []
    if isinstance(authors, str):
        return [authors]
    return [a for a in authors if a]


def _oreilly_published(obj: dict) -> date | None:
    for key in ["issued", "date_added", "timestamp"]:
        published = parse_date(obj.get(key))
        if published:
            return published
    return None


async def _fetch_oreilly_api(
    publisher: PublisherConfig, publishers_filter: str | None = None
) -> list[BookRecord]:
    settings = get_settings()
    cutoff = date.today() - timedelta(days=settings.window_days)
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    params = {"query": "*", "formats": "book", "sort": "publication_date", "page": 1}
    if publishers_filter:
        params["publishers"] = publishers_filter

    results: list[BookRecord] = []
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        while True:
            resp = await get_with_retries(client, OREILLY_SEARCH_URL, params=params)
            data = resp.json()
            items = data.get("results") or []
            if not items:
                break
            page_too_old = False
            for item in items:
                published = _oreilly_published(item)
                if not published:
                    continue
                today = date.today()
                if published > today:
                    continue
                if published < cutoff:
                    page_too_old = True
                    continue
                title = item.get("title") or "Untitled"
                info_url = item.get("web_url") or item.get("url")
                if info_url and info_url.startswith("/"):
                    info_url = "https://learning.oreilly.com" + info_url
                cover_url = item.get("cover_url")
                description = _strip_html(item.get("description")) or None
                pages = item.get("virtual_pages")
                source_key = item.get("archive_id") or info_url or title
                results.append(
                    BookRecord(
                        source="oreilly_api",
                        source_key=source_key,
                        publisher_id=publisher.id,
                        title=title,
                        subtitle=None,
                        authors=_oreilly_authors(item),
                        language="en",
                        subjects=["computers"],
                        topics=[],
                        description=description,
                        isbn_10=None,
                        isbn_13=item.get("isbn"),
                        page_count=pages,
                        print_type="book",
                        published_date=published,
                        cover_url=cover_url,
                        info_url=info_url,
                        raw=item,
                    )
                )
                if len(results) >= settings.max_results_per_source:
                    return results
            if page_too_old:
                break
            next_url = data.get("next")
            if not next_url:
                break
            params["page"] += 1
    return results


async def fetch_oreilly_new_upcoming(publisher: PublisherConfig) -> list[BookRecord]:
    return await _fetch_oreilly_api(publisher)


async def fetch_addison_wesley(publisher: PublisherConfig) -> list[BookRecord]:
    return await _fetch_oreilly_api(publisher, publishers_filter="Addison-Wesley Professional")


async def fetch_pearson(publisher: PublisherConfig) -> list[BookRecord]:
    return await _fetch_oreilly_api(publisher, publishers_filter="Pearson")


async def fetch_wrox(publisher: PublisherConfig) -> list[BookRecord]:
    return await _fetch_oreilly_api(publisher, publishers_filter="Wrox Press")


# ---- DMK Press computer-literature catalog (Bitrix HTML) ----
DMK_BASE = "https://www.dmkpress.com"
DMK_COMPUTER_URL = DMK_BASE + "/catalog/computer/"
DMK_MAX_PAGES = 5
DMK_ISBN_RE = re.compile(r"97[89][-0-9]{10,14}")


def _parse_dmk_page(html_text: str) -> list[dict]:
    html = HTMLParser(html_text)
    cards = []
    for card in html.css(".book-card"):
        title_el = card.css_first("a.book-card__title")
        if not title_el:
            continue
        href = title_el.attributes.get("href") or ""
        info_url = href if href.startswith("http") else DMK_BASE + href
        m = DMK_ISBN_RE.search(href)
        isbn_13 = m.group(0).replace("-", "") if m else None
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


async def fetch_dmk_catalog(publisher: PublisherConfig) -> list[BookRecord]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    results: list[BookRecord] = []

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        for page in range(1, DMK_MAX_PAGES + 1):
            params = {"PAGEN_1": page} if page > 1 else None
            resp = await get_with_retries(client, DMK_COMPUTER_URL, params=params)
            cards = _parse_dmk_page(resp.text)
            if not cards:
                break
            new_cards = [c for c in cards if c["is_new"]]
            for c in new_cards:
                results.append(
                    BookRecord(
                        source="dmk_html",
                        source_key=c["isbn_13"] or c["info_url"],
                        publisher_id=publisher.id,
                        title=c["title"],
                        authors=c["authors"],
                        language="ru",
                        subjects=["computers"],
                        isbn_13=c["isbn_13"],
                        # cards carry no publish date; record first sighting
                        published_date=date.today(),
                        cover_url=c["cover_url"],
                        info_url=c["info_url"],
                        raw={"href": c["info_url"]},
                    )
                )
                if len(results) >= settings.max_results_per_source:
                    return results
            if not new_cards:
                # "Новинка" badges are gone: older pages only from here on
                break
    return results


# ---- Piter (collection JSON) ----
PITER_URL = "https://www.piter.com/collection/kompyutery-i-internet.json"


async def fetch_piter_catalog(publisher: PublisherConfig) -> list[BookRecord]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    cutoff = date.today() - timedelta(days=settings.window_days)

    results: list[BookRecord] = []
    page = 1
    per = 100
    total = None

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        while True:
            params = {"page": page, "per": per, "sort": "created_at_desc"}
            resp = await get_with_retries(client, PITER_URL, params=params)
            data = resp.json()
            if total is None:
                total = data.get("count", 0)
            products = data.get("products") or []
            if not products:
                break
            for prod in products:
                published = _piter_published_date(prod)
                if not published:
                    continue
                if published < cutoff:
                    continue
                record = BookRecord(
                    source="piter_json",
                    source_key=str(prod.get("id")),
                    publisher_id=publisher.id,
                    title=prod.get("title") or "Untitled",
                    subtitle=None,
                    authors=_piter_authors(prod),
                    language="ru",
                    subjects=["computers"],
                    topics=[],
                    description=prod.get("short_description"),
                    isbn_10=None,
                    isbn_13=_piter_isbn(prod),
                    page_count=_piter_pages(prod),
                    print_type="book",
                    published_date=published,
                    cover_url=_piter_cover(prod),
                    info_url="https://www.piter.com" + prod.get("url", ""),
                    raw=prod,
                )
                results.append(record)
                if len(results) >= settings.max_results_per_source:
                    return results
            if len(products) < per or (total and page * per >= total):
                break
            page += 1
    return results


def _piter_prop_map(prod: dict) -> dict[int, str]:
    return {p["id"]: p.get("title") for p in prod.get("properties", [])}


def _piter_char_values(prod: dict) -> dict[str, list[str]]:
    prop_map = _piter_prop_map(prod)
    values: dict[str, list[str]] = {}
    for ch in prod.get("characteristics") or []:
        name = prop_map.get(ch.get("property_id"))
        if not name:
            continue
        values.setdefault(name.lower(), []).append(ch.get("title") or "")
    return values


def _piter_published_date(prod: dict) -> date | None:
    values = _piter_char_values(prod)
    if "год" in values:
        try:
            year = int(values["год"][0][:4])
            return date(year, 1, 1)
        except Exception:
            pass
    updated_at = prod.get("updated_at")
    if updated_at:
        try:
            return datetime.fromisoformat(updated_at.replace("Z", "+00:00")).date()
        except Exception:
            return None
    return None


def _piter_authors(prod: dict) -> list[str]:
    values = _piter_char_values(prod)
    authors = values.get("автор(ы)") or values.get("автор") or []
    if authors:
        return [a.strip() for val in authors for a in val.split(",") if a.strip()]
    return []


def _piter_isbn(prod: dict) -> str | None:
    values = _piter_char_values(prod)
    isbn_vals = values.get("isbn") or []
    if isbn_vals:
        return isbn_vals[0]
    return None


def _piter_pages(prod: dict) -> int | None:
    values = _piter_char_values(prod)
    if "страниц" in values:
        for val in values["страниц"]:
            try:
                return int(val)
            except ValueError:
                continue
    return None


def _piter_cover(prod: dict) -> str | None:
    img = prod.get("first_image") or {}
    return img.get("large_url") or img.get("original_url") or img.get("url")


async def fetch_bhv_store(publisher: PublisherConfig) -> list[BookRecord]:
    """WooCommerce store feed."""
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    cutoff = date.today() - timedelta(days=settings.window_days)
    page = 1
    per_page = 50
    max_pages = 3
    results: list[BookRecord] = []
    base = "https://bhv.ru/wp-json/wc/store/products"

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        while True:
            params = {"per_page": per_page, "page": page, "orderby": "date", "order": "desc"}
            try:
                resp = await get_with_retries(client, base, params=params)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500:
                    break
                raise
            items = resp.json()
            if not isinstance(items, list) or not items:
                # WooCommerce returns an error object instead of a list on failure
                break
            for item in items:
                published = parse_date(item.get("date_created")) or date.today()
                if published < cutoff:
                    continue
                if not _bhv_is_computing(item):
                    continue
                desc = item.get("short_description") or item.get("description") or ""
                images = item.get("images") or []
                if isinstance(images, dict):
                    # the store API sometimes keys images by id instead of a list
                    images = list(images.values())
                cover_url = None
                if images and isinstance(images[0], dict):
                    cover_url = images[0].get("src")
                record = BookRecord(
                    source="bhv_store",
                    source_key=str(item.get("id")),
                    publisher_id=publisher.id,
                    title=item.get("name") or "Untitled",
                    subtitle=None,
                    authors=[],
                    language="ru",
                    subjects=["computers"],
                    topics=[],
                    description=_strip_html(desc),
                    isbn_10=None,
                    isbn_13=_find_isbn_in_text(desc),
                    page_count=None,
                    print_type="book",
                    published_date=published,
                    cover_url=cover_url,
                    info_url=item.get("permalink"),
                    raw=item,
                )
                results.append(record)
                if len(results) >= settings.max_results_per_source:
                    return results
            if len(items) < per_page or page >= max_pages:
                break
            page += 1
    return results


def _strip_html(text: str) -> str:
    return HTMLParser(text).text() if text else ""


ISBN13_IN_TEXT_RE = re.compile(r"97[89][-\s]?[0-9][-\s]?[0-9]{2,}[-\s]?[0-9]{2,}[-\s]?[0-9]")


def _find_isbn_in_text(text: str) -> str | None:
    if not text:
        return None
    m = ISBN13_IN_TEXT_RE.search(text)
    if m:
        return m.group(0).replace(" ", "").replace("-", "")
    return None


def _bhv_is_computing(item: dict) -> bool:
    categories = " ".join(cat.get("name", "") for cat in item.get("categories", []))
    text = (item.get("name", "") + " " + categories).lower()
    keywords = ["комп", "ит", "информ", "програм", "linux", "windows", "сет", "data", "security"]
    return any(k in text for k in keywords)


# ---- Miroma (price-list XLS) ----
MIROMA_BASE = "https://miromabook.ru"

PRICE_LINK_RE = re.compile(r'href="([^"]+\.(?:xls|xlsx|zip))"', re.I)


def _extract_price_links(html_text: str, base: str) -> list[str]:
    links = PRICE_LINK_RE.findall(html_text)
    return [link if link.startswith("http") else base + link for link in links]


async def fetch_miroma_price(publisher: PublisherConfig) -> list[BookRecord]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    results: list[BookRecord] = []
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        listing = await get_with_retries(client, f"{MIROMA_BASE}/prays-listy/")
        for url in _extract_price_links(listing.text, MIROMA_BASE):
            try:
                resp = await get_with_retries(client, url)
                book_list = _parse_miroma_workbook(resp.content)
                for rec in book_list:
                    rec.publisher_id = publisher.id
                    rec.source = "miroma_price"
                    results.append(rec)
            except Exception:
                logger.warning("Failed to fetch/parse Miroma price list %s", url, exc_info=True)
                continue
            if len(results) >= settings.max_results_per_source:
                break
    return results


ZIP_MAGIC = b"PK\x03\x04"


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))  # xlrd/openpyxl hand numeric ISBNs and years back as floats
    return str(value)


def _sheets_from_xls(content: bytes) -> list[tuple[str, list[list[str]]]]:
    book = xlrd.open_workbook(file_contents=content)
    return [
        (
            sheet.name,
            [
                [_cell_text(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
                for r in range(sheet.nrows)
            ],
        )
        for sheet in book.sheets()
    ]


def _sheets_from_xlsx(content: bytes) -> list[tuple[str, list[list[str]]]]:
    workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        return [
            (ws.title, [[_cell_text(v) for v in row] for row in ws.iter_rows(values_only=True)])
            for ws in workbook.worksheets
        ]
    finally:
        workbook.close()


def _workbook_sheets(content: bytes) -> list[tuple[str, list[list[str]]]]:
    """Return (sheet name, rows) for an .xls, an .xlsx, or a .zip holding either."""
    if not content.startswith(ZIP_MAGIC):
        return _sheets_from_xls(content)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        if "xl/workbook.xml" in names:
            return _sheets_from_xlsx(content)
        sheets: list[tuple[str, list[list[str]]]] = []
        for name in names:
            if name.lower().endswith((".xls", ".xlsx")):
                sheets.extend(_workbook_sheets(archive.read(name)))
        return sheets


def _parse_miroma_workbook(content: bytes) -> list[BookRecord]:
    records: list[BookRecord] = []
    try:
        sheets = _workbook_sheets(content)
    except Exception:
        logger.warning("Unreadable Miroma price list", exc_info=True)
        return records
    for sheet_name, rows in sheets:
        if not rows:
            continue
        headers = [h.strip().lower() for h in rows[0]]
        col_title = _find_col(headers, ["назв", "наименование", "title"])
        if col_title is None:
            continue
        col_author = _find_col(headers, ["автор", "authors"])
        col_year = _find_col(headers, ["год", "year"])
        col_isbn = _find_col(headers, ["isbn"])
        for r, row in enumerate(rows[1:], start=1):

            def cell(col: int | None) -> str:
                return row[col].strip() if col is not None and col < len(row) else ""

            title = cell(col_title)
            if not title:
                continue
            authors = [a.strip() for a in cell(col_author).split(",") if a.strip()]
            published = None
            year_text = cell(col_year)[:4]
            if year_text.isdigit():
                published = date(int(year_text), 1, 1)
            records.append(
                BookRecord(
                    source="miroma_price",
                    source_key=f"{sheet_name}-{r}",
                    publisher_id="",
                    title=title,
                    authors=authors,
                    language="ru",
                    subjects=["computers"],
                    published_date=published,
                    isbn_13=cell(col_isbn) or None,
                    raw={"sheet": sheet_name, "row": r},
                )
            )
    return records


# ---- NiT (Insales JSON) ----
async def fetch_nit_catalog(publisher: PublisherConfig) -> list[BookRecord]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    base = "https://nit.com.ru/collection/komp_lit.json"
    page = 1
    per = 100
    results: list[BookRecord] = []
    cutoff = date.today() - timedelta(days=settings.window_days)
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        while True:
            try:
                resp = await get_with_retries(client, base, params={"page": page, "per": per})
            except httpx.HTTPStatusError:
                break
            data = resp.json()
            products = data.get("products") or []
            if not products:
                break
            for prod in products:
                published = parse_date(prod.get("updated_at")) or date.today()
                if published < cutoff:
                    continue
                record = BookRecord(
                    source="nit_json",
                    source_key=str(prod.get("id")),
                    publisher_id=publisher.id,
                    title=prod.get("title") or "Untitled",
                    authors=[],
                    language="ru",
                    subjects=["computers"],
                    description=prod.get("short_description"),
                    isbn_13=None,
                    published_date=published,
                    cover_url=(prod.get("first_image") or {}).get("large_url"),
                    info_url="https://nit.com.ru" + prod.get("url", ""),
                    raw=prod,
                )
                results.append(record)
                if len(results) >= settings.max_results_per_source:
                    return results
            if len(products) < per:
                break
            page += 1
    return results


def _find_col(headers: list[str], keys: list[str]) -> int | None:
    for idx, h in enumerate(headers):
        for key in keys:
            if key in h:
                return idx
    return None


PACKT_SEARCH_URL = (
    "https://www.packtpub.com/en-us/search?q=&product-type=book&sort=publication-newest"
)

PACKT_ORDINAL_RE = re.compile(r"(\d+)(st|nd|rd|th)", re.IGNORECASE)
PACKT_PAGES_RE = re.compile(r"(\d{2,4})\s+pages")
PACKT_ISBN_RE = re.compile(r"97[89]\d{10}")


def _parse_packt_date(value: str) -> date | None:
    if not value:
        return None
    cleaned = value.replace(",", "")
    cleaned = PACKT_ORDINAL_RE.sub(r"\1", cleaned)
    for fmt in ["%b %d %Y", "%B %d %Y", "%b %Y", "%B %Y"]:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return parse_date(cleaned)


def _packt_pages(text: str) -> int | None:
    m = PACKT_PAGES_RE.search(text.lower())
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _packt_isbn(card) -> str | None:
    values: list[str] = []
    for attr in [
        "data-default-selected-isbn",
        "data-default-isbn",
        "data-selected-isbn",
        "data-price-id",
        "data-analytics-item-id",
    ]:
        for el in card.css(f"[{attr}]"):
            val = el.attributes.get(attr)
            if val:
                values.append(val)
    if values:
        joined = " ".join(values)
        m = PACKT_ISBN_RE.search(joined)
        if m:
            return m.group(0)
    return None


def _packt_authors(card) -> list[str]:
    authors = []
    for span in card.css(".product-info-authors-container .product-info-authors-item span"):
        text = span.text(strip=True)
        if text:
            authors.append(text)
    return authors


def _packt_published(card) -> date | None:
    attr_holder = card.css_first("[data-publication-date]")
    if attr_holder:
        published = _parse_packt_date(attr_holder.attributes.get("data-publication-date"))
        if published:
            return published
    meta_date = card.css_first(".product-card-v2-meta-info-text span")
    if meta_date:
        parsed = _parse_packt_date(meta_date.text(strip=True))
        if parsed:
            return parsed
    year_attr = card.attributes.get("data-analytics-item-publication-year")
    if year_attr and year_attr.isdigit():
        try:
            return date(int(year_attr), 1, 1)
        except ValueError:
            return None
    return None


BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


async def fetch_packt_search(publisher: PublisherConfig) -> list[BookRecord]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    # Packt returns 403 for non-browser user agents
    headers = {"User-Agent": BROWSER_USER_AGENT, "Accept-Language": "en"}
    cutoff = date.today() - timedelta(days=settings.window_days)

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        resp = await get_with_retries(client, PACKT_SEARCH_URL)
    html = HTMLParser(resp.text)
    cards = html.css(".product-card-v2") or []
    results: list[BookRecord] = []
    for card in cards:
        title_el = card.css_first(".product-card-v2-content-info-text .ellipsis")
        title = title_el.text(strip=True) if title_el else None
        if not title:
            continue
        info_el = card.css_first(".product-card-v2-content-info")
        href = info_el.attributes.get("href") if info_el else None
        if href and href.startswith("/"):
            href = "https://www.packtpub.com" + href
        published = _packt_published(card)
        if published and published < cutoff:
            continue
        description_el = card.css_first(".product-card-v2-content-info-description .ellipsis")
        description = description_el.text(strip=True) if description_el else None
        cover_el = card.css_first(".product-card-v2-content-info-header img")
        cover_url = cover_el.attributes.get("src") if cover_el else None
        text_blob = card.text()
        page_count = _packt_pages(text_blob)
        isbn = _packt_isbn(card)
        authors = _packt_authors(card)
        source_key = isbn or href or title
        results.append(
            BookRecord(
                source="packt_search",
                source_key=source_key,
                publisher_id=publisher.id,
                title=title,
                authors=authors,
                language="en",
                subjects=["computers"],
                description=description,
                isbn_13=isbn,
                page_count=page_count,
                print_type="book",
                published_date=published,
                cover_url=cover_url,
                info_url=href,
                raw={"html": card.html},
            )
        )
        if len(results) >= settings.max_results_per_source:
            break
    return results


MANNING_CATALOG_URL = "https://www.manning.com/search/getCatalogData"

WHITESPACE_RE = re.compile(r"\s+")


def _manning_cover_url(obj: dict) -> str | None:
    image = obj.get("imageUrl")
    if not image:
        return None
    base = "https://images.manning.com/264/149/resize/"
    if not obj.get("wideCover"):
        base = "https://images.manning.com/320/400/resize/"
    return base + image


def _manning_authors(authorship: str | None) -> list[str]:
    if not authorship:
        return []
    clean = HTMLParser(authorship).text(separator=" ")
    clean = WHITESPACE_RE.sub(" ", clean).strip()
    if not clean:
        return []
    parts = re.split(r",| and | with ", clean, flags=re.IGNORECASE)
    return [p.strip(" ,") for p in parts if p.strip()]


def _manning_date(value: str | None) -> date | None:
    if not value:
        return None
    date_part = value.split("T")[0]
    try:
        return date.fromisoformat(date_part)
    except ValueError:
        return parse_date(date_part)


async def fetch_manning_catalog(publisher: PublisherConfig) -> list[BookRecord]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent, "Content-Type": "application/json"}
    cutoff = date.today() - timedelta(days=settings.window_days)
    payload = {
        "accessType": [],
        "keywords": [],
        "level": [],
        "meapFilter": "",
        "productType": [],
        "programmingLanguages": [],
        "selectedCategoryIds": [1],
        "sort": "newest",
        "includePrices": True,
    }

    page = 1
    results: list[BookRecord] = []
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        while True:
            payload["page"] = page
            resp = await request_with_retries(client, "POST", MANNING_CATALOG_URL, json=payload)
            data = resp.json()
            products = data.get("products") or []
            page_dates: list[date] = []
            for prod in products:
                published = _manning_date(prod.get("date"))
                if published:
                    page_dates.append(published)
                if published and published < cutoff:
                    continue
                authors = _manning_authors(prod.get("authorshipDisplay"))
                record = BookRecord(
                    source="manning_catalog",
                    source_key=str(prod.get("id") or prod.get("slug") or prod.get("link")),
                    publisher_id=publisher.id,
                    title=prod.get("title") or "Untitled",
                    subtitle=prod.get("subtitle") or None,
                    authors=authors,
                    language="en",
                    subjects=["computers"],
                    description=None,
                    isbn_13=None,
                    published_date=published,
                    cover_url=_manning_cover_url(prod),
                    info_url=prod.get("link"),
                    raw=prod,
                )
                results.append(record)
                if len(results) >= settings.max_results_per_source:
                    return results
            pagination = data.get("pagination") or {}
            current_page = pagination.get("page") or 0
            total_pages = pagination.get("pages") or 0
            has_next = bool(pagination.get("hasNextPage") and current_page < total_pages)
            if page_dates and min(page_dates) < cutoff:
                break
            if not has_next:
                break
            page += 1
    return results


# Naive HTML scrapers for dialektika/williams/eksmo/fizmatlit/gelios/ast/knorus/
# eunivers/apress/nostarch/informit/binom were removed: they collected every <a>
# on the page as a "book" with published_date=today. Re-add per-site connectors
# here once proper selectors are written and tested against saved fixtures.
CONNECTOR_MAP: dict[str, Callable[[PublisherConfig], Awaitable[list[BookRecord]]]] = {
    "oreilly_new_upcoming": fetch_oreilly_new_upcoming,
    "dmk_catalog": fetch_dmk_catalog,
    "piter_catalog": fetch_piter_catalog,
    "bhv_store": fetch_bhv_store,
    "miroma_price": fetch_miroma_price,
    "nit_catalog": fetch_nit_catalog,
    "addison_wesley_api": fetch_addison_wesley,
    "pearson_api": fetch_pearson,
    "wrox_api": fetch_wrox,
    "packt_search": fetch_packt_search,
    "manning_catalog": fetch_manning_catalog,
}

import asyncio
import hashlib
import io
import logging
import re
import zipfile
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

import httpx
import openpyxl
import xlrd
from selectolax.lexbor import LexborHTMLParser

from app.core.config import PublisherConfig, get_settings
from app.services.types import BookRecord
from app.utils.dates import date_from_year, parse_date
from app.utils.filters import is_computing
from app.utils.http import get_with_retries, request_with_retries
from app.utils.isbn import normalize_isbn10, normalize_isbn13

logger = logging.getLogger(__name__)


@dataclass
class ConnectorResult:
    records: list[BookRecord] = field(default_factory=list)
    # one line per failed source: "<name>: <ExcType>: <message>"
    errors: list[str] = field(default_factory=list)


def failure_line(source: str, exc: Exception) -> str:
    return f"{source}: {type(exc).__name__}: {exc}"


async def fetch_connectors(publisher: PublisherConfig) -> ConnectorResult:
    result = ConnectorResult()
    for name in publisher.connectors or []:
        fetcher = CONNECTOR_MAP.get(name)
        if not fetcher:
            logger.warning("Unknown connector %s for %s", name, publisher.id)
            continue
        try:
            result.records.extend(await fetcher(publisher))
        except Exception as exc:
            logger.exception("Connector %s failed for %s", name, publisher.id)
            result.errors.append(failure_line(name, exc))
    return result


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


async def fetch_oreilly_api(publisher: PublisherConfig) -> list[BookRecord]:
    """New titles of each ``publisher.oreilly_publishers`` name in the O'Reilly API.

    The API's ``publishers`` parameter alone let other imprints through, so items are
    also checked against the name client-side.
    """
    if not publisher.oreilly_publishers:
        logger.warning("oreilly_api: no oreilly_publishers configured for %s", publisher.id)
        return []
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    results: list[BookRecord] = []
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        for api_name in publisher.oreilly_publishers:
            budget = settings.max_results_per_source - len(results)
            results.extend(await _fetch_oreilly_publisher(client, publisher, api_name, budget))
            if len(results) >= settings.max_results_per_source:
                break
    return results


async def _fetch_oreilly_publisher(
    client: httpx.AsyncClient, publisher: PublisherConfig, api_name: str, limit: int
) -> list[BookRecord]:
    settings = get_settings()
    cutoff = date.today() - timedelta(days=settings.window_days)
    # sort direction is assumed newest first (the early stop relies on it); unverified
    # since the API began answering 401/403 to anonymous clients
    params = {
        "query": "*",
        "formats": "book",
        "sort": "publication_date",
        "publishers": api_name,
        "page": 1,
    }
    results: list[BookRecord] = []
    while True:
        resp = await get_with_retries(client, OREILLY_SEARCH_URL, params=params)
        data = resp.json()
        items = data.get("results") or []
        if not items:
            break
        page_too_old = False
        for item in items:
            if api_name not in (item.get("publishers") or []):
                continue
            published = _oreilly_published(item)
            if not published:
                continue
            today = date.today()
            if published > today:
                continue
            if published < cutoff:
                page_too_old = True
                continue
            results.append(_oreilly_record(item, publisher, published))
            if len(results) >= limit:
                return results
        if page_too_old:
            break
        if not data.get("next"):
            break
        params["page"] += 1
    return results


def _oreilly_record(item: dict, publisher: PublisherConfig, published: date) -> BookRecord:
    title = item.get("title") or "Untitled"
    info_url = item.get("web_url") or item.get("url")
    if info_url and info_url.startswith("/"):
        info_url = "https://learning.oreilly.com" + info_url
    return BookRecord(
        source="oreilly_api",
        source_key=item.get("archive_id") or info_url or title,
        publisher_id=publisher.id,
        title=title,
        authors=_oreilly_authors(item),
        language="en",
        subjects=["computers"],
        description=_strip_html(item.get("description")) or None,
        isbn_13=normalize_isbn13(item.get("isbn")),
        page_count=item.get("virtual_pages"),
        print_type="book",
        published_date=published,
        cover_url=item.get("cover_url"),
        info_url=info_url,
        raw=item,
    )


# ---- DMK Press computer-literature catalog (Bitrix HTML) ----
DMK_BASE = "https://www.dmkpress.com"
DMK_COMPUTER_URL = DMK_BASE + "/catalog/computer/"
DMK_MAX_PAGES = 5
# the whole hyphenated run: normalize_isbn13 rejects it unless it holds exactly 13 digits
DMK_ISBN_RE = re.compile(r"97[89][-0-9]+")


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
                        published_date_is_sighting=True,
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


# ---- InSales collection JSON (Piter, NiT) ----
INSALES_PER_PAGE = 100  # the largest page InSales serves
PITER_SITE = "https://www.piter.com"
PITER_URL = PITER_SITE + "/collection/kompyutery-i-internet.json"
# the whole computing collection is ~11 pages of 100; a bound keeps a broken
# "count" from paging forever
PITER_MAX_PAGES = 20
NIT_SITE = "https://nit.com.ru"
NIT_URL = NIT_SITE + "/collection/komp_lit.json"
NIT_MAX_PAGES = 20
# characteristic names (lowercased) differ between the two shops
INSALES_AUTHOR_KEYS = ["автор(ы)", "автор"]
INSALES_YEAR_KEYS = ["год", "год издания", "год тиража"]
INSALES_PAGES_KEYS = ["страниц", "количество страниц"]


async def fetch_piter_catalog(publisher: PublisherConfig) -> list[BookRecord]:
    return await fetch_insales_collection(
        PITER_URL,
        publisher,
        source="piter_json",
        site=PITER_SITE,
        max_pages=PITER_MAX_PAGES,
        newest_first=True,
    )


async def fetch_nit_catalog(publisher: PublisherConfig) -> list[BookRecord]:
    return await fetch_insales_collection(
        NIT_URL, publisher, source="nit_json", site=NIT_SITE, max_pages=NIT_MAX_PAGES
    )


async def fetch_insales_collection(
    url: str,
    publisher: PublisherConfig,
    source: str,
    site: str,
    max_pages: int,
    newest_first: bool = False,
) -> list[BookRecord]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    cutoff = date.today() - timedelta(days=settings.window_days)
    results: list[BookRecord] = []

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        for page in range(1, max_pages + 1):
            page_params = {"page": page, "per": INSALES_PER_PAGE}
            if newest_first:
                page_params["sort"] = "created_at_desc"
            resp = await get_with_retries(client, url, params=page_params)
            data = resp.json()
            products = data.get("products") or []
            if not products:
                break
            records = [_insales_record(prod, publisher, source, site) for prod in products]
            for record in records:
                if not record.published_date or record.published_date < cutoff:
                    continue
                results.append(record)
                if len(results) >= settings.max_results_per_source:
                    return results
            total = data.get("count") or 0
            if len(products) < INSALES_PER_PAGE or (total and page * INSALES_PER_PAGE >= total):
                break
            # only a newest-first listing lets a page dated before the window end it
            if newest_first and all(
                r.published_date and r.published_date < cutoff for r in records
            ):
                break
    return results


def _insales_record(prod: dict, publisher: PublisherConfig, source: str, site: str) -> BookRecord:
    values = _insales_char_values(prod)
    published = _insales_published_date(prod, values)
    today = date.today()
    # dated today though the feed did not say so: date_from_year fell back to first sighting
    is_sighting = published == today and _insales_updated_at(prod) != today
    return BookRecord(
        source=source,
        source_key=str(prod.get("id")),
        publisher_id=publisher.id,
        title=prod.get("title") or "Untitled",
        authors=_insales_authors(values),
        language="ru",
        subjects=["computers"],
        description=prod.get("short_description"),
        isbn_13=_insales_isbn(values),
        page_count=_insales_pages(values),
        print_type="book",
        published_date=published,
        published_date_is_sighting=is_sighting,
        cover_url=_insales_cover(prod),
        # the feed sends "url": null for some products
        info_url=site + prod["url"] if prod.get("url") else None,
        raw=prod,
    )


def _insales_char_values(prod: dict) -> dict[str, list[str]]:
    """Characteristic values keyed by lowercased property title."""
    property_titles = {p["id"]: p.get("title") for p in prod.get("properties", [])}
    values: dict[str, list[str]] = {}
    for ch in prod.get("characteristics") or []:
        name = property_titles.get(ch.get("property_id"))
        if not name:
            continue
        values.setdefault(name.lower(), []).append(ch.get("title") or "")
    return values


def _first_values(values: dict[str, list[str]], keys: list[str]) -> list[str]:
    return next((values[key] for key in keys if values.get(key)), [])


def _insales_updated_at(prod: dict) -> date | None:
    updated_at = prod.get("updated_at")
    if not updated_at:
        return None
    try:
        return datetime.fromisoformat(updated_at.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _insales_published_date(prod: dict, values: dict[str, list[str]]) -> date | None:
    updated = _insales_updated_at(prod)
    # most Piter products carry only "год тиража" (print-run year), not "год"
    year_text = (_first_values(values, INSALES_YEAR_KEYS) or [""])[0][:4]
    if year_text.isdigit():
        return date_from_year(int(year_text), date.today(), fallback=updated)
    return updated


def _insales_authors(values: dict[str, list[str]]) -> list[str]:
    authors = _first_values(values, INSALES_AUTHOR_KEYS)
    return [a.strip() for val in authors for a in val.split(",") if a.strip()]


def _insales_isbn(values: dict[str, list[str]]) -> str | None:
    return next((i for i in map(normalize_isbn13, values.get("isbn") or []) if i), None)


def _insales_pages(values: dict[str, list[str]]) -> int | None:
    pages = _first_values(values, INSALES_PAGES_KEYS)
    return next((int(val) for val in pages if val.isdigit()), None)


def _insales_cover(prod: dict) -> str | None:
    img = prod.get("first_image") or {}
    return img.get("large_url") or img.get("original_url") or img.get("url")


BHV_COMPUTING_CATEGORY = "Компьютеры и программы"


async def fetch_bhv_store(publisher: PublisherConfig) -> list[BookRecord]:
    """WooCommerce Store API feed, newest first.

    The Store API exposes no product date, so records are dated by first sighting.
    """
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
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
                categories = [cat.get("name") or "" for cat in item.get("categories") or []]
                if BHV_COMPUTING_CATEGORY not in categories and not is_computing(
                    [item.get("name") or "", *categories]
                ):
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
                    published_date=date.today(),
                    published_date_is_sighting=True,
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
    return LexborHTMLParser(text).text() if text else ""


ISBN13_IN_TEXT_RE = re.compile(r"97[89][-\s]?[0-9][-\s]?[0-9]{2,}[-\s]?[0-9]{2,}[-\s]?[0-9]")


def _find_isbn_in_text(text: str) -> str | None:
    if not text:
        return None
    m = ISBN13_IN_TEXT_RE.search(text)
    return normalize_isbn13(m.group(0)) if m else None


# ---- Miroma (price-list XLS) ----
MIROMA_LISTING_URL = "https://miromabook.ru/prays-listy/"
# the full price list is a few MB; anything far larger is not a price list
MIROMA_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024

PRICE_LINK_RE = re.compile(r"""href=["']([^"']+\.(?:xls|xlsx|zip))["']""", re.I)


def _extract_price_links(html_text: str, page_url: str) -> list[str]:
    links = (urljoin(page_url, link) for link in PRICE_LINK_RE.findall(html_text))
    return list(dict.fromkeys(links))


async def _download_capped(client: httpx.AsyncClient, url: str, max_bytes: int) -> bytes:
    """GET ``url`` but stop reading once it exceeds ``max_bytes``."""
    async with client.stream("GET", url) as resp:
        resp.raise_for_status()
        chunks: list[bytes] = []
        received = 0
        async for chunk in resp.aiter_bytes():
            received += len(chunk)
            if received > max_bytes:
                raise ValueError(f"{url} is larger than {max_bytes} bytes")
            chunks.append(chunk)
    return b"".join(chunks)


async def fetch_miroma_price(publisher: PublisherConfig) -> list[BookRecord]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    results: list[BookRecord] = []
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        listing = await get_with_retries(client, MIROMA_LISTING_URL)
        for url in _extract_price_links(listing.text, MIROMA_LISTING_URL):
            try:
                content = await _download_capped(client, url, MIROMA_MAX_DOWNLOAD_BYTES)
                # CPU-bound parsing of a third-party file: keep it off the event loop
                book_list = await asyncio.to_thread(
                    _parse_miroma_workbook,
                    content,
                    [publisher.name, *publisher.aliases],
                    PurePosixPath(urlparse(url).path).name,
                )
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
# Price lists come from a third-party site: bound what a crafted archive can make us do.
ZIP_MAX_MEMBERS = 50
ZIP_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
ZIP_MAX_DEPTH = 1


def _check_zip_budget(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if len(infos) > ZIP_MAX_MEMBERS:
        raise ValueError(f"archive has {len(infos)} members (limit {ZIP_MAX_MEMBERS})")
    total = sum(info.file_size for info in infos)
    if total > ZIP_MAX_UNCOMPRESSED_BYTES:
        raise ValueError(f"archive expands to {total} bytes (limit {ZIP_MAX_UNCOMPRESSED_BYTES})")


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


def _workbook_sheets(content: bytes, depth: int = 0) -> list[tuple[str, list[list[str]]]]:
    """Return (sheet name, rows) for an .xls, an .xlsx, or a .zip holding either."""
    if not content.startswith(ZIP_MAGIC):
        return _sheets_from_xls(content)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        _check_zip_budget(archive)
        names = archive.namelist()
        if "xl/workbook.xml" in names:
            return _sheets_from_xlsx(content)
        if depth >= ZIP_MAX_DEPTH:
            raise ValueError("nested archives are not supported")
        sheets: list[tuple[str, list[list[str]]]] = []
        for name in names:
            if name.lower().endswith((".xls", ".xlsx")):
                sheets.extend(_workbook_sheets(archive.read(name), depth + 1))
        return sheets


ISBN_LIST_SEPARATORS_RE = re.compile(r"[,;/]")


def _isbns_from_cell(value: str) -> tuple[str | None, str | None]:
    """(ISBN-13, ISBN-10) from a price-list cell that may hold one, both or several."""
    parts = ISBN_LIST_SEPARATORS_RE.split(value)
    isbn_13 = next((i for i in map(normalize_isbn13, parts) if i), None)
    isbn_10 = next((i for i in map(normalize_isbn10, parts) if i), None)
    return isbn_13, isbn_10


MIROMA_HEADER_SCAN_ROWS = 30
MIROMA_TITLE_KEYS = ["назв", "наименование", "title"]


def _find_header_row(rows: list[list[str]]) -> int | None:
    """Skip the ordering preamble: the header is the first row that has a title column."""
    for index, row in enumerate(rows[:MIROMA_HEADER_SCAN_ROWS]):
        headers = [h.strip().lower() for h in row]
        if _find_col(headers, MIROMA_TITLE_KEYS) is not None:
            return index
    return None


def _parse_miroma_workbook(
    content: bytes, publisher_names: Sequence[str] = (), file_name: str = ""
) -> list[BookRecord]:
    """Parse a distributor price list into records.

    ``publisher_names`` (name + aliases) narrows the "Издательство" column: a
    distributor lists dozens of publishers, we only want the configured one.
    """
    try:
        sheets = _workbook_sheets(content)
    except Exception:
        logger.warning("Unreadable Miroma price list %s", file_name, exc_info=True)
        return []
    wanted = [name.lower() for name in publisher_names if name]
    records: list[BookRecord] = []
    for sheet_name, rows in sheets:
        records.extend(_parse_miroma_sheet(sheet_name, rows, wanted, file_name))
    return records


def _parse_miroma_sheet(
    sheet_name: str, rows: list[list[str]], wanted: list[str], file_name: str
) -> list[BookRecord]:
    header_index = _find_header_row(rows)
    if header_index is None:
        return []
    headers = [h.strip().lower() for h in rows[header_index]]
    col_title = _find_col(headers, MIROMA_TITLE_KEYS)
    col_author = _find_col(headers, ["автор", "authors"])
    col_year = _find_col(headers, ["год", "year"])
    col_isbn = _find_col(headers, ["isbn"])
    col_pages = _find_col(headers, ["страниц", "pages"])
    col_publisher = _find_col(headers, ["издательств", "publisher"])
    if wanted and col_publisher is None:
        # without the column every distributor row would be credited to this publisher
        logger.warning("Miroma %s sheet %s has no publisher column, skipped", file_name, sheet_name)
        return []
    today = date.today()
    records: list[BookRecord] = []
    for r, row in enumerate(rows[header_index + 1 :], start=header_index + 1):

        def cell(col: int | None) -> str:
            return row[col].strip() if col is not None and col < len(row) else ""

        title = cell(col_title)
        if not title or not is_computing([title]):
            continue
        if wanted and not any(name in cell(col_publisher).lower() for name in wanted):
            continue
        authors = [a.strip() for a in cell(col_author).split(",") if a.strip()]
        published = None
        year_text = cell(col_year)[:4]
        if year_text.isdigit():
            published = date_from_year(int(year_text), today)
        pages_text = cell(col_pages)
        isbn_13, isbn_10 = _isbns_from_cell(cell(col_isbn))
        records.append(
            BookRecord(
                source="miroma_price",
                source_key=isbn_13 or isbn_10 or _miroma_row_key(file_name, title, authors),
                publisher_id="",
                title=title,
                authors=authors,
                language="ru",
                subjects=["computers"],
                published_date=published,
                # a current-year row has no fallback date: it is dated today
                published_date_is_sighting=published == today,
                isbn_13=isbn_13,
                isbn_10=isbn_10,
                page_count=int(pages_text) if pages_text.isdigit() else None,
                raw={"sheet": sheet_name, "row": r, "publisher": cell(col_publisher)},
            )
        )
    return records


def _miroma_row_key(file_name: str, title: str, authors: list[str]) -> str:
    """Stable key for a row without ISBN: row indexes shift whenever the list changes."""
    digest = hashlib.sha1("|".join([title, *authors]).encode()).hexdigest()
    return f"{file_name}:{digest}"


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
        return date_from_year(int(year_attr), date.today())
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
    html = LexborHTMLParser(resp.text)
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
    clean = LexborHTMLParser(authorship).text(separator=" ")
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
                product_key = prod.get("id") or prod.get("slug") or prod.get("link")
                if not product_key:
                    continue  # nothing to dedupe on; str() turned it into the key "None"
                authors = _manning_authors(prod.get("authorshipDisplay"))
                record = BookRecord(
                    source="manning_catalog",
                    source_key=str(product_key),
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
    "oreilly_api": fetch_oreilly_api,
    "dmk_catalog": fetch_dmk_catalog,
    "piter_catalog": fetch_piter_catalog,
    "bhv_store": fetch_bhv_store,
    "miroma_price": fetch_miroma_price,
    "nit_catalog": fetch_nit_catalog,
    "packt_search": fetch_packt_search,
    "manning_catalog": fetch_manning_catalog,
}

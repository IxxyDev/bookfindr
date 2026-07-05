import logging
import re
from datetime import date, datetime, timedelta
from typing import Awaitable, Callable, Dict, List, Optional

import httpx
import xlrd
from selectolax.parser import HTMLParser

from app.core.config import PublisherConfig, get_settings
from app.services.types import BookRecord
from app.utils.dates import parse_date
from app.utils.http import get_with_retries, request_with_retries

logger = logging.getLogger(__name__)


async def fetch_connectors(publisher: PublisherConfig) -> List[BookRecord]:
    connectors = publisher.connectors or []
    results: List[BookRecord] = []
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


def _oreilly_authors(obj: dict) -> List[str]:
    authors = obj.get("authors") or []
    if isinstance(authors, str):
        return [authors]
    return [a for a in authors if a]


def _oreilly_published(obj: dict) -> Optional[date]:
    for key in ["issued", "date_added", "timestamp"]:
        published = parse_date(obj.get(key))
        if published:
            return published
    return None


async def _fetch_oreilly_api(
    publisher: PublisherConfig, publishers_filter: Optional[str] = None
) -> List[BookRecord]:
    settings = get_settings()
    cutoff = date.today() - timedelta(days=settings.window_days)
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    params = {"query": "*", "formats": "book", "sort": "publication_date", "page": 1}
    if publishers_filter:
        params["publishers"] = publishers_filter

    results: List[BookRecord] = []
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


async def fetch_oreilly_new_upcoming(publisher: PublisherConfig) -> List[BookRecord]:
    return await _fetch_oreilly_api(publisher)


async def fetch_addison_wesley(publisher: PublisherConfig) -> List[BookRecord]:
    return await _fetch_oreilly_api(publisher, publishers_filter="Addison-Wesley Professional")


async def fetch_pearson(publisher: PublisherConfig) -> List[BookRecord]:
    return await _fetch_oreilly_api(publisher, publishers_filter="Pearson")


async def fetch_wrox(publisher: PublisherConfig) -> List[BookRecord]:
    return await _fetch_oreilly_api(publisher, publishers_filter="Wrox Press")


# ---- DMK Press catalog (HTML) ----
DMK_URL = "https://dmkpress.com/catalog/"


async def fetch_dmk_catalog(publisher: PublisherConfig) -> List[BookRecord]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    cutoff = date.today() - timedelta(days=settings.window_days)

    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        resp = await get_with_retries(client, DMK_URL)
    html = HTMLParser(resp.text)
    items = html.css(".book-item")
    results: List[BookRecord] = []
    for item in items:
        title_el = item.css_first(".book-title a")
        info_url = None
        if title_el and title_el.attributes.get("href"):
            info_url = "https://dmkpress.com" + title_el.attributes["href"]
        authors = [a.text(strip=True) for a in item.css(".book-authors a")]
        date_el = item.css_first(".book-date")
        published = parse_date(date_el.text(strip=True) if date_el else None)
        if published and published < cutoff:
            continue
        cover_el = item.css_first("img")
        cover_url = cover_el.attributes.get("src") if cover_el else None
        results.append(
            BookRecord(
                source="dmk_html",
                source_key=info_url,
                publisher_id=publisher.id,
                title=title_el.text(strip=True) if title_el else "Untitled",
                authors=authors,
                language="ru",
                subjects=["computers"],
                description=None,
                published_date=published,
                cover_url=cover_url,
                info_url=info_url,
                raw={"html": item.html},
            )
        )
    return results


# ---- Piter (collection JSON) ----
PITER_URL = "https://www.piter.com/collection/kompyutery-i-internet.json"


async def fetch_piter_catalog(publisher: PublisherConfig) -> List[BookRecord]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    cutoff = date.today() - timedelta(days=settings.window_days)

    results: List[BookRecord] = []
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


def _piter_prop_map(prod: dict) -> Dict[int, str]:
    return {p["id"]: p.get("title") for p in prod.get("properties", [])}


def _piter_char_values(prod: dict) -> Dict[str, List[str]]:
    prop_map = _piter_prop_map(prod)
    values: Dict[str, List[str]] = {}
    for ch in prod.get("characteristics") or []:
        name = prop_map.get(ch.get("property_id"))
        if not name:
            continue
        values.setdefault(name.lower(), []).append(ch.get("title") or "")
    return values


def _piter_published_date(prod: dict) -> Optional[date]:
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


def _piter_authors(prod: dict) -> List[str]:
    values = _piter_char_values(prod)
    authors = values.get("автор(ы)") or values.get("автор") or []
    if authors:
        return [a.strip() for val in authors for a in val.split(",") if a.strip()]
    return []


def _piter_isbn(prod: dict) -> Optional[str]:
    values = _piter_char_values(prod)
    isbn_vals = values.get("isbn") or []
    if isbn_vals:
        return isbn_vals[0]
    return None


def _piter_pages(prod: dict) -> Optional[int]:
    values = _piter_char_values(prod)
    if "страниц" in values:
        for val in values["страниц"]:
            try:
                return int(val)
            except ValueError:
                continue
    return None


def _piter_cover(prod: dict) -> Optional[str]:
    img = prod.get("first_image") or {}
    return img.get("large_url") or img.get("original_url") or img.get("url")


async def fetch_bhv_store(publisher: PublisherConfig) -> List[BookRecord]:
    """WooCommerce store feed."""
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    cutoff = date.today() - timedelta(days=settings.window_days)
    page = 1
    per_page = 50
    max_pages = 3
    results: List[BookRecord] = []
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
            if not items:
                break
            for item in items:
                published = parse_date(item.get("date_created")) or date.today()
                if published < cutoff:
                    continue
                if not _bhv_is_computing(item):
                    continue
                desc = item.get("short_description") or item.get("description") or ""
                images = item.get("images") or []
                cover_url = images[0].get("src") if images else None
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


def _find_isbn_in_text(text: str) -> Optional[str]:
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


def _extract_price_links(html_text: str, base: str) -> List[str]:
    links = PRICE_LINK_RE.findall(html_text)
    return [link if link.startswith("http") else base + link for link in links]


async def fetch_miroma_price(publisher: PublisherConfig) -> List[BookRecord]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    results: List[BookRecord] = []
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        listing = await get_with_retries(client, f"{MIROMA_BASE}/prays-listy/")
        for url in _extract_price_links(listing.text, MIROMA_BASE):
            try:
                resp = await get_with_retries(client, url)
                book_list = _parse_miroma_xls(resp.content)
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


def _parse_miroma_xls(content: bytes) -> List[BookRecord]:
    records: List[BookRecord] = []
    try:
        book = xlrd.open_workbook(file_contents=content)
    except Exception:
        return records
    for sheet in book.sheets():
        headers = [str(sheet.cell_value(0, c)).strip().lower() for c in range(sheet.ncols)]
        col_title = _find_col(headers, ["назв", "наименование", "title"])
        if col_title is None:
            continue
        col_author = _find_col(headers, ["автор", "authors"])
        col_year = _find_col(headers, ["год", "year"])
        col_isbn = _find_col(headers, ["isbn"])
        for r in range(1, sheet.nrows):
            title = str(sheet.cell_value(r, col_title)).strip()
            if not title:
                continue
            authors = []
            if col_author is not None:
                val = str(sheet.cell_value(r, col_author)).strip()
                if val:
                    authors = [a.strip() for a in val.split(",") if a.strip()]
            published = None
            if col_year is not None:
                try:
                    year = int(str(sheet.cell_value(r, col_year)).strip()[:4])
                    published = date(year, 1, 1)
                except Exception:
                    published = None
            isbn = None
            if col_isbn is not None:
                isbn = str(sheet.cell_value(r, col_isbn)).strip()
            records.append(
                BookRecord(
                    source="miroma_price",
                    source_key=f"{sheet.name}-{r}",
                    publisher_id="",
                    title=title,
                    authors=authors,
                    language="ru",
                    subjects=["computers"],
                    published_date=published,
                    isbn_13=isbn,
                    raw={"sheet": sheet.name, "row": r},
                )
            )
    return records


# ---- NiT (Insales JSON) ----
async def fetch_nit_catalog(publisher: PublisherConfig) -> List[BookRecord]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    base = "https://nit.com.ru/collection/komp_lit.json"
    page = 1
    per = 100
    results: List[BookRecord] = []
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


def _find_col(headers: List[str], keys: List[str]) -> Optional[int]:
    for idx, h in enumerate(headers):
        for key in keys:
            if key in h:
                return idx
    return None


PACKT_SEARCH_URL = (
    "https://www.packtpub.com/en-us/search?"
    "q=&product-type=book&sort=publication-newest"
)

PACKT_ORDINAL_RE = re.compile(r"(\d+)(st|nd|rd|th)", re.IGNORECASE)
PACKT_PAGES_RE = re.compile(r"(\d{2,4})\s+pages")
PACKT_ISBN_RE = re.compile(r"97[89]\d{10}")


def _parse_packt_date(value: str) -> Optional[date]:
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


def _packt_pages(text: str) -> Optional[int]:
    m = PACKT_PAGES_RE.search(text.lower())
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _packt_isbn(card) -> Optional[str]:
    values: List[str] = []
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


def _packt_authors(card) -> List[str]:
    authors = []
    for span in card.css(".product-info-authors-container .product-info-authors-item span"):
        text = span.text(strip=True)
        if text:
            authors.append(text)
    return authors


def _packt_published(card) -> Optional[date]:
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


async def fetch_packt_search(publisher: PublisherConfig) -> List[BookRecord]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.request_timeout, connect=settings.request_timeout)
    headers = {"User-Agent": settings.user_agent}
    cutoff = date.today() - timedelta(days=settings.window_days)

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        resp = await get_with_retries(client, PACKT_SEARCH_URL)
    html = HTMLParser(resp.text)
    cards = html.css(".product-card-v2") or []
    results: List[BookRecord] = []
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


def _manning_cover_url(obj: dict) -> Optional[str]:
    image = obj.get("imageUrl")
    if not image:
        return None
    base = "https://images.manning.com/264/149/resize/"
    if not obj.get("wideCover"):
        base = "https://images.manning.com/320/400/resize/"
    return base + image


def _manning_authors(authorship: Optional[str]) -> List[str]:
    if not authorship:
        return []
    clean = HTMLParser(authorship).text(separator=" ")
    clean = WHITESPACE_RE.sub(" ", clean).strip()
    if not clean:
        return []
    parts = re.split(r",| and | with ", clean, flags=re.IGNORECASE)
    return [p.strip(" ,") for p in parts if p.strip()]


def _manning_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    date_part = value.split("T")[0]
    try:
        return date.fromisoformat(date_part)
    except ValueError:
        return parse_date(date_part)


async def fetch_manning_catalog(publisher: PublisherConfig) -> List[BookRecord]:
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
    results: List[BookRecord] = []
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        while True:
            payload["page"] = page
            resp = await request_with_retries(client, "POST", MANNING_CATALOG_URL, json=payload)
            data = resp.json()
            products = data.get("products") or []
            page_dates: List[date] = []
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
CONNECTOR_MAP: Dict[str, Callable[[PublisherConfig], Awaitable[List[BookRecord]]]] = {
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

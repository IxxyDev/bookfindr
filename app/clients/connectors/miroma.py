"""Distributor price lists (miromabook.ru): .xls, .xlsx or a .zip holding them."""

import asyncio
import hashlib
import io
import logging
import re
import zipfile
from collections.abc import Sequence
from datetime import date
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

import httpx
import openpyxl
import xlrd

from app.clients.connectors._http import Collector, source_client
from app.core.config import PublisherConfig, get_settings
from app.services.types import BookRecord
from app.utils.dates import date_from_year
from app.utils.filters import is_computing
from app.utils.http import get_with_retries
from app.utils.isbn import normalize_isbn10, normalize_isbn13

logger = logging.getLogger(__name__)

MIROMA_LISTING_URL = "https://miromabook.ru/prays-listy/"
# the full price list is a few MB; anything far larger is not a price list
MIROMA_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024

PRICE_LINK_RE = re.compile(r"""href=["']([^"']+\.(?:xls|xlsx|zip))["']""", re.I)


async def fetch_miroma_price(publisher: PublisherConfig, window_days: int) -> list[BookRecord]:
    """Every price-list row of the publisher; a price list has no order to page by."""
    settings = get_settings()
    collector = Collector(settings.max_results_per_source)
    async with source_client(settings) as client:
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
            except Exception:
                logger.warning("Failed to fetch/parse Miroma price list %s", url, exc_info=True)
                continue
            for rec in book_list:
                rec.publisher_id = publisher.id
                if collector.add(rec):
                    return collector.records
    return collector.records


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


# the ordering preamble above the header row is about a dozen rows
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

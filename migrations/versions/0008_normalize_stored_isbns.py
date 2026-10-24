"""books.isbn_13 / isbn_10: compact digits, invalid values to NULL.

Piter stored hyphenated ISBN-13s ("978-5-459-01330-6"), so a sync with normalized
ISBNs no longer matched them and created a second row per book. Uses a frozen copy
of app.utils.isbn. When two rows normalize to the same ISBN, the older row (by
created_at) keeps it and the newer one gets NULL; nothing else is merged.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-24 11:00:00
"""

import logging
import re
from collections.abc import Callable

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

logger = logging.getLogger(f"alembic.migration.{revision}")

SEPARATORS_RE = re.compile(r"[-\s]")
ISBN13_RE = re.compile(r"97[89]\d{10}")
ISBN10_RE = re.compile(r"\d{9}[\dX]")


def _compact(value: str | None) -> str:
    return SEPARATORS_RE.sub("", value or "").upper()


def _normalize_isbn13(value: str | None) -> str | None:
    compact = _compact(value)
    return compact if ISBN13_RE.fullmatch(compact) else None


def _normalize_isbn10(value: str | None) -> str | None:
    compact = _compact(value)
    return compact if ISBN10_RE.fullmatch(compact) else None


def _normalize_column(column: str, normalize: Callable[[str | None], str | None]) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            f"SELECT id, {column} FROM books WHERE {column} IS NOT NULL ORDER BY created_at, id"
        )
    ).all()
    owners: dict[str, str] = {}
    targets: dict[str, str | None] = {}
    for book_id, stored in rows:
        normalized = normalize(stored)
        if normalized is not None and normalized in owners:
            logger.warning(
                "%s %s of book %s already belongs to older book %s; set to NULL",
                column,
                normalized,
                book_id,
                owners[normalized],
            )
            normalized = None
        elif normalized is not None:
            owners[normalized] = book_id
        if normalized != stored:
            targets[book_id] = normalized

    # Clear first, then write: a compact value may still sit on a row that loses it
    for book_id in targets:
        bind.execute(sa.text(f"UPDATE books SET {column} = NULL WHERE id = :id"), {"id": book_id})
    for book_id, normalized in targets.items():
        if normalized is not None:
            bind.execute(
                sa.text(f"UPDATE books SET {column} = :value WHERE id = :id"),
                {"value": normalized, "id": book_id},
            )


def upgrade() -> None:
    _normalize_column("isbn_13", _normalize_isbn13)
    _normalize_column("isbn_10", _normalize_isbn10)


def downgrade() -> None:
    # Original spellings and dropped duplicates are not kept
    pass

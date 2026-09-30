"""books.language: two-letter codes (sources stored en/eng and ru/rus side by side).

Uses a frozen copy of app.utils.lang.normalize_language.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23 12:30:00
"""

import re

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

ISO_639_2_TO_1 = {
    "ara": "ar",
    "bel": "be",
    "chi": "zh",
    "zho": "zh",
    "cze": "cs",
    "ces": "cs",
    "dut": "nl",
    "nld": "nl",
    "eng": "en",
    "fre": "fr",
    "fra": "fr",
    "ger": "de",
    "deu": "de",
    "heb": "he",
    "hin": "hi",
    "ita": "it",
    "jpn": "ja",
    "kaz": "kk",
    "kor": "ko",
    "pol": "pl",
    "por": "pt",
    "rus": "ru",
    "spa": "es",
    "swe": "sv",
    "tur": "tr",
    "ukr": "uk",
}

REGION_SUFFIX_RE = re.compile(r"[-_].*$")


def _normalize_language(code: str) -> str | None:
    if not code.strip():
        return None
    base = REGION_SUFFIX_RE.sub("", code.strip().lower())
    return ISO_639_2_TO_1.get(base, base)


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, language FROM books WHERE language IS NOT NULL"))
    for book_id, code in rows.all():
        normalized = _normalize_language(code)
        if normalized != code:
            bind.execute(
                sa.text("UPDATE books SET language = :language WHERE id = :id"),
                {"language": normalized, "id": book_id},
            )


def downgrade() -> None:
    # The original spellings are not kept
    pass

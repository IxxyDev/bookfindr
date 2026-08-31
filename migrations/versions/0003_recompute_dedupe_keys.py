"""books.dedupe_key: normalized title + publisher + first author's surname.

The old key hashed the raw lowercased title and every author's full name, so
"Nathan B. Crocker" and "Nathan Crocker" produced two books. Recompute stored keys
with a frozen copy of build_dedupe_key (migrations must not follow later code changes).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23 12:10:00
"""

import hashlib
import json
import re
from collections.abc import Callable

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_PUNCTUATION = re.compile(r"[^\w\s]")


def _normalize_words(text: str) -> str:
    return " ".join(_PUNCTUATION.sub(" ", text.lower()).split())


def _new_key(title: str, publisher_id: str, authors: list[str]) -> str:
    first_author = (authors or [""])[0]
    surname = (_normalize_words(first_author).split() or [""])[-1]
    key_base = f"{_normalize_words(title)}|{publisher_id}|{surname}"
    return hashlib.sha1(key_base.encode("utf-8")).hexdigest()


def _old_key(title: str, publisher_id: str, authors: list[str]) -> str:
    author_part = "|".join(a.lower() for a in authors or [])
    key_base = f"{title.strip().lower()}|{publisher_id}|{author_part}"
    return hashlib.sha1(key_base.encode("utf-8")).hexdigest()


def _rewrite_keys(build_key: Callable[[str, str, list[str]], str]) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, title, publisher_id, authors FROM books")).all()
    for book_id, title, publisher_id, authors in rows:
        key = build_key(title, publisher_id, json.loads(authors) if authors else [])
        bind.execute(
            sa.text("UPDATE books SET dedupe_key = :key WHERE id = :id"),
            {"key": key, "id": book_id},
        )


def upgrade() -> None:
    _rewrite_keys(_new_key)


def downgrade() -> None:
    _rewrite_keys(_old_key)

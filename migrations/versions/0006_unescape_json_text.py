"""JSON columns: store non-ASCII as text, not \\u escapes.

Escaped Cyrillic authors/subjects/topics were invisible to FTS, the LIKE fallback and
the subject filter. Re-serialize the stored values with ensure_ascii=False; the books
update triggers refresh the FTS rows, and startup rebuilds the index anyway.
book_sources.raw is only read back as JSON and stays as it is.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-24 10:00:00
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

COLUMNS = {
    "books": ("authors", "subjects", "topics"),
    "publishers": ("aliases", "languages"),
}


def _reserialize(ensure_ascii: bool) -> None:
    bind = op.get_bind()
    for table, columns in COLUMNS.items():
        rows = bind.execute(sa.text(f"SELECT id, {', '.join(columns)} FROM {table}")).all()
        for row_id, *values in rows:
            updates = {}
            for column, stored in zip(columns, values, strict=True):
                if stored is None:
                    continue
                rewritten = json.dumps(json.loads(stored), ensure_ascii=ensure_ascii)
                if rewritten != stored:
                    updates[column] = rewritten
            if updates:
                assignments = ", ".join(f"{column} = :{column}" for column in updates)
                bind.execute(
                    sa.text(f"UPDATE {table} SET {assignments} WHERE id = :id"),
                    {**updates, "id": row_id},
                )


def upgrade() -> None:
    _reserialize(ensure_ascii=False)


def downgrade() -> None:
    _reserialize(ensure_ascii=True)

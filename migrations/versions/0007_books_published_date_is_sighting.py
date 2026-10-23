"""books.published_date_is_sighting: remember "first seen" dates.

Without the flag a first-seen date could never be replaced by a real publication
date from a lower-priority source. Existing rows are marked as real dates.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-24 10:20:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


COLUMN = "published_date_is_sighting"


def upgrade() -> None:
    # Plain ADD COLUMN, not batch mode: recreating books would drop the FTS triggers and
    # renumber the rowids book_fts points at. Skipped when the column exists (a database
    # stamped at the baseline after create_all() from current models).
    if COLUMN in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("books")}:
        return
    op.add_column(
        "books",
        sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("books", COLUMN)

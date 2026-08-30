"""book_sources: one row per (book, source, source_key).

Every sync used to insert another book_sources row for the same item. Keep the most
recently fetched row of each group and add a unique index so upserts refresh it instead.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23 12:00:00
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

INDEX_NAME = "ux_book_sources_book_source_key"


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM book_sources WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY book_id, source, source_key
                    ORDER BY fetched_at DESC, created_at DESC, id DESC
                ) AS position
                FROM book_sources
            )
            WHERE position > 1
        )
        """
    )
    op.create_index(
        INDEX_NAME,
        "book_sources",
        ["book_id", "source", "source_key"],
        unique=True,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="book_sources")

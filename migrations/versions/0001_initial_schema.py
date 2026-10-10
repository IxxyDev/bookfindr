"""Initial schema: tables, indexes and the FTS5 search index with its sync triggers.

Revision ID: 0001
Revises:
Create Date: 2026-09-19 22:04:37.354185
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Frozen copy: a migration must not change when app code does
FTS_CREATE_SQL = (
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS book_fts
    USING fts5(title, description, authors, content='books', content_rowid='rowid')
    """,
    """
    CREATE TRIGGER IF NOT EXISTS books_ai AFTER INSERT ON books BEGIN
        INSERT INTO book_fts(rowid, title, description, authors)
        VALUES (
            new.rowid,
            coalesce(new.title,''),
            coalesce(new.description,''),
            coalesce(new.authors,'')
        );
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS books_au AFTER UPDATE ON books BEGIN
        INSERT INTO book_fts(book_fts, rowid, title, description, authors)
        VALUES('delete', old.rowid, old.title, old.description, old.authors);
        INSERT INTO book_fts(rowid, title, description, authors)
        VALUES (
            new.rowid,
            coalesce(new.title,''),
            coalesce(new.description,''),
            coalesce(new.authors,'')
        );
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS books_ad AFTER DELETE ON books BEGIN
        INSERT INTO book_fts(book_fts, rowid, title, description, authors)
        VALUES('delete', old.rowid, old.title, old.description, old.authors);
    END
    """,
)
FTS_DROP_SQL = (
    "DROP TRIGGER IF EXISTS books_ai",
    "DROP TRIGGER IF EXISTS books_au",
    "DROP TRIGGER IF EXISTS books_ad",
    "DROP TABLE IF EXISTS book_fts",
)


def upgrade() -> None:
    op.create_table(
        "publishers",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("languages", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "books",
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("subtitle", sa.String(length=500), nullable=True),
        sa.Column("authors", sa.JSON(), nullable=True),
        sa.Column("publisher_id", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("subjects", sa.JSON(), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("isbn_10", sa.String(length=20), nullable=True),
        sa.Column("isbn_13", sa.String(length=32), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("print_type", sa.String(length=50), nullable=True),
        sa.Column("published_date", sa.Date(), nullable=True),
        sa.Column("cover_url", sa.String(length=500), nullable=True),
        sa.Column("info_url", sa.String(length=500), nullable=True),
        sa.Column("source_primary", sa.String(length=50), nullable=True),
        sa.Column("source_keys", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["publisher_id"],
            ["publishers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isbn_10"),
        sa.UniqueConstraint("isbn_13"),
    )
    with op.batch_alter_table("books", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_books_dedupe_key"), ["dedupe_key"], unique=False)
        batch_op.create_index(batch_op.f("ix_books_language"), ["language"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_books_published_date"), ["published_date"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_books_publisher_id"), ["publisher_id"], unique=False)

    op.create_table(
        "fetch_runs",
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("publisher_id", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("new_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["publisher_id"],
            ["publishers.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "book_sources",
        sa.Column("book_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_key", sa.String(length=255), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["book_id"],
            ["books.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("book_sources", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_book_sources_book_id"), ["book_id"], unique=False)

    bind = op.get_bind()
    for statement in FTS_CREATE_SQL:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    for statement in FTS_DROP_SQL:
        bind.exec_driver_sql(statement)
    with op.batch_alter_table("book_sources", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_book_sources_book_id"))

    op.drop_table("book_sources")
    op.drop_table("fetch_runs")
    with op.batch_alter_table("books", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_books_publisher_id"))
        batch_op.drop_index(batch_op.f("ix_books_published_date"))
        batch_op.drop_index(batch_op.f("ix_books_language"))
        batch_op.drop_index(batch_op.f("ix_books_dedupe_key"))

    op.drop_table("books")
    op.drop_table("publishers")

"""fetch_runs.error: drop URL query strings (an API key leaked into a stored error).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-23 12:20:00
"""

import re

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# Frozen copy of app.services.sync._URL_QUERY
_URL_QUERY = re.compile(r"(https?://[^\s?#'\"<>]+)\?[^\s#'\"<>]*")


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, error FROM fetch_runs WHERE error LIKE '%?%'")).all()
    for run_id, error in rows:
        redacted = _URL_QUERY.sub(r"\1?<redacted>", error)
        if redacted != error:
            bind.execute(
                sa.text("UPDATE fetch_runs SET error = :error WHERE id = :id"),
                {"error": redacted, "id": run_id},
            )


def downgrade() -> None:
    # Redacted values cannot be restored
    pass

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.book import Book


async def test_foreign_keys_are_enforced(db_session):
    db_session.add(Book(id=str(uuid4()), title="Orphan", publisher_id="no-such-publisher"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()

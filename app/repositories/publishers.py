from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.publisher import Publisher


class PublisherRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_all(self) -> Sequence[Publisher]:
        return (await self._session.scalars(select(Publisher))).all()

    async def map_by_id(self) -> dict[str, Publisher]:
        return {row.id: row for row in await self.list_all()}

    async def save(self, publisher: Publisher) -> None:
        self._session.add(publisher)

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import PublishersFile
from app.models.publisher import Publisher
from app.repositories import PublisherRepository

logger = logging.getLogger(__name__)


async def sync_publishers(session: AsyncSession, config: PublishersFile) -> dict[str, Publisher]:
    repo = PublisherRepository(session)
    existing = await repo.map_by_id()
    saved: dict[str, Publisher] = {}
    for pub_cfg in config.publishers:
        publisher = existing.get(pub_cfg.id)
        if not publisher:
            publisher = Publisher(
                id=pub_cfg.id,
                name=pub_cfg.name,
                aliases=pub_cfg.aliases,
                languages=pub_cfg.languages,
            )
            await repo.save(publisher)
            logger.info("Added publisher %s", pub_cfg.id)
        else:
            publisher.name = pub_cfg.name
            publisher.aliases = pub_cfg.aliases
            publisher.languages = pub_cfg.languages
        saved[publisher.id] = publisher
    await session.commit()
    return saved

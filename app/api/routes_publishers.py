from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import PublishersFile, get_publishers_config
from app.core.db import get_session
from app.models.publisher import Publisher
from app.repositories import PublisherRepository
from app.schemas.publisher import PublisherSchema

router = APIRouter(prefix="/publishers", tags=["publishers"])


@router.get("", response_model=list[PublisherSchema])
async def list_publishers(
    session: AsyncSession = Depends(get_session),
    config: PublishersFile = Depends(get_publishers_config),
) -> list[Publisher]:
    """Publishers from the config, in config order; rows removed from it stay hidden."""
    stored = await PublisherRepository(session).map_by_id()
    return [stored[pub.id] for pub in config.publishers if pub.id in stored]

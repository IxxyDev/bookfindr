from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.models.publisher import Publisher
from app.repositories import PublisherRepository
from app.schemas.publisher import PublisherSchema

router = APIRouter(prefix="/publishers", tags=["publishers"])


@router.get("", response_model=List[PublisherSchema])
async def list_publishers(session: AsyncSession = Depends(get_session)) -> List[Publisher]:
    repo = PublisherRepository(session)
    return await repo.list_all()

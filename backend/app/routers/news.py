import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.integrations.news_client import news_client
from app.models.user import User
from app.repositories.farm_repository import FarmRepository
from app.schemas.news import FarmNewsResponse
from app.services.farm_service import FarmNotFoundError, FarmService
from app.services.news_service import NewsService, NewsServiceError

router = APIRouter(prefix="/farms", tags=["news"])


def get_farm_service(session: AsyncSession = Depends(get_db)) -> FarmService:
    return FarmService(FarmRepository(session))


def get_news_service() -> NewsService:
    return NewsService(news_client)


@router.get("/{farm_id}/news", response_model=FarmNewsResponse)
async def get_farm_news(
    farm_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    farm_service: FarmService = Depends(get_farm_service),
    news_service: NewsService = Depends(get_news_service),
) -> FarmNewsResponse:
    """Recent farming/agriculture news for this farm's district/state, via
    NewsAPI.org. Returns an empty, is_configured=false feed (not a 503) when
    NEWS_API_KEY isn't set."""
    try:
        farm = await farm_service.get_farm(current_user, farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found.") from exc

    try:
        return await news_service.get_farm_news(farm)
    except NewsServiceError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

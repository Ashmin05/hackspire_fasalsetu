import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.integrations.open_meteo_client import open_meteo_client
from app.models.user import User
from app.repositories.farm_repository import FarmRepository
from app.repositories.weather_cache_repository import WeatherCacheRepository
from app.schemas.weather import FarmWeatherResponse
from app.services.farm_service import FarmNotFoundError, FarmService
from app.services.weather_service import WeatherService, WeatherServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/farms", tags=["weather"])


def get_farm_service(session: AsyncSession = Depends(get_db)) -> FarmService:
    return FarmService(FarmRepository(session))


def get_weather_service(session: AsyncSession = Depends(get_db)) -> WeatherService:
    return WeatherService(WeatherCacheRepository(session), open_meteo_client)


@router.get("/{farm_id}/weather", response_model=FarmWeatherResponse)
async def get_farm_weather(
    farm_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    farm_service: FarmService = Depends(get_farm_service),
    weather_service: WeatherService = Depends(get_weather_service),
) -> FarmWeatherResponse:
    """10-day Open-Meteo forecast for this farm's centroid (temperature,
    precipitation, wind, humidity, UV, ET0), with heavy-rain/heat-stress/
    good-spray-window flags per day. Cached for WEATHER_CACHE_HOURS and
    refetched live after that -- unlike /satellite/latest this never 404s:
    Open-Meteo needs no prior refresh step, so the first call for a farm
    fetches live."""
    try:
        farm = await farm_service.get_farm(current_user, farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found.") from exc

    try:
        return await weather_service.get_weather(farm)
    except WeatherServiceError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

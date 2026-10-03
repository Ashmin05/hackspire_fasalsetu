import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.integrations.earth_engine_client import earth_engine_client
from app.integrations.open_meteo_client import open_meteo_client
from app.models.user import User
from app.repositories.environment_snapshot_repository import EnvironmentSnapshotRepository
from app.repositories.farm_alert_repository import FarmAlertRepository
from app.repositories.farm_repository import FarmRepository
from app.repositories.irrigation_log_repository import IrrigationLogRepository
from app.repositories.irrigation_plan_repository import IrrigationPlanRepository
from app.repositories.satellite_repository import SatelliteRepository
from app.repositories.weather_cache_repository import WeatherCacheRepository
from app.schemas.advisor import AdvisorAskRequest, AdvisorAskResponse
from app.services.advisor_service import AdvisorRateLimitError, AdvisorService, AdvisorServiceError
from app.services.farm_service import FarmNotFoundError, FarmService
from app.services.irrigation_service import IrrigationService
from app.services.market_prices.price_service import PriceService
from app.services.satellite_service import SatelliteService
from app.services.weather_service import WeatherService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/farms", tags=["assistant"])


def get_farm_service(session: AsyncSession = Depends(get_db)) -> FarmService:
    return FarmService(FarmRepository(session))


def get_advisor_service(session: AsyncSession = Depends(get_db)) -> AdvisorService:
    weather_service = WeatherService(WeatherCacheRepository(session), open_meteo_client)
    return AdvisorService(
        satellite_service=SatelliteService(
            SatelliteRepository(session),
            earth_engine_client,
            farm_alert_repository=FarmAlertRepository(session),
            environment_snapshot_repository=EnvironmentSnapshotRepository(session),
        ),
        weather_service=weather_service,
        irrigation_service=IrrigationService(
            IrrigationPlanRepository(session),
            IrrigationLogRepository(session),
            EnvironmentSnapshotRepository(session),
            SatelliteRepository(session),
            earth_engine_client,
            open_meteo_client,
            weather_service,
        ),
        price_service=PriceService(session),
    )


@router.post("/{farm_id}/ask", response_model=AdvisorAskResponse)
async def ask_advisor(
    farm_id: uuid.UUID,
    payload: AdvisorAskRequest,
    current_user: User = Depends(get_current_user),
    farm_service: FarmService = Depends(get_farm_service),
    advisor_service: AdvisorService = Depends(get_advisor_service),
) -> AdvisorAskResponse:
    """Answers a farmer's free-text question about ONE farm using only that
    farm's already-stored data (satellite, alerts, season, environment,
    weather, irrigation, mandi price) -- never general knowledge, never
    another farm's data. Uses Gemini when GEMINI_API_KEYS is configured,
    rotating through keys on a quota/auth/other error, and falls back to a
    scripted, non-LLM summary of the same context when no key is configured
    at all. If Gemini IS configured but every key fails, that's a genuine
    503. Rate-limited per user (ADVISOR_RATE_LIMIT_PER_HOUR)."""
    try:
        farm = await farm_service.get_farm(current_user, farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found.") from exc

    try:
        return await advisor_service.ask(
            farm, current_user, question=payload.question, language=payload.language
        )
    except AdvisorRateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except AdvisorServiceError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

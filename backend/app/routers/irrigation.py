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
from app.repositories.farm_repository import FarmRepository
from app.repositories.irrigation_log_repository import IrrigationLogRepository
from app.repositories.irrigation_plan_repository import IrrigationPlanRepository
from app.repositories.satellite_repository import SatelliteRepository
from app.repositories.weather_cache_repository import WeatherCacheRepository
from app.schemas.irrigation import IrrigationLogRequest, IrrigationPlanResponse
from app.services.farm_service import FarmNotFoundError, FarmService
from app.services.irrigation_service import IrrigationService, IrrigationServiceError
from app.services.weather_service import WeatherService, WeatherServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/farms", tags=["irrigation"])


def get_farm_service(session: AsyncSession = Depends(get_db)) -> FarmService:
    return FarmService(FarmRepository(session))


def get_irrigation_service(session: AsyncSession = Depends(get_db)) -> IrrigationService:
    return IrrigationService(
        IrrigationPlanRepository(session),
        IrrigationLogRepository(session),
        EnvironmentSnapshotRepository(session),
        SatelliteRepository(session),
        earth_engine_client,
        open_meteo_client,
        WeatherService(WeatherCacheRepository(session), open_meteo_client),
    )


@router.get("/{farm_id}/irrigation", response_model=IrrigationPlanResponse)
async def get_irrigation_plan(
    farm_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    farm_service: FarmService = Depends(get_farm_service),
    irrigation_service: IrrigationService = Depends(get_irrigation_service),
) -> IrrigationPlanResponse:
    """FAO-56 root-zone water balance for this farm -- current depletion
    vs. readily available water, and the next modelled irrigation date +
    depth (mm). Rolls forward any days not yet folded into the stored
    balance using CHIRPS/Open-Meteo history, then projects over the
    Open-Meteo forecast; never 404s the way /satellite/latest does -- the
    first call for a farm computes a plan from scratch."""
    try:
        farm = await farm_service.get_farm(current_user, farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found.") from exc

    try:
        return await irrigation_service.get_plan(farm)
    except (IrrigationServiceError, WeatherServiceError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/{farm_id}/irrigation/log", response_model=IrrigationPlanResponse, status_code=status.HTTP_201_CREATED)
async def log_irrigation(
    farm_id: uuid.UUID,
    payload: IrrigationLogRequest,
    current_user: User = Depends(get_current_user),
    farm_service: FarmService = Depends(get_farm_service),
    irrigation_service: IrrigationService = Depends(get_irrigation_service),
) -> IrrigationPlanResponse:
    """Records a farmer-reported irrigation event and returns the
    recomputed plan. A logged date already folded into the stored balance
    is applied immediately; a pending date is picked up the normal way the
    next time the balance rolls forward over it."""
    try:
        farm = await farm_service.get_farm(current_user, farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found.") from exc

    try:
        await irrigation_service.log_irrigation(
            farm, log_date=payload.log_date, depth_mm=payload.depth_mm, note=payload.note
        )
        return await irrigation_service.get_plan(farm)
    except IrrigationServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WeatherServiceError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

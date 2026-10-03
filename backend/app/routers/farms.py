import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.repositories.farm_repository import FarmRepository
from app.routers.satellite import run_background_refresh
from app.schemas.farm import FarmCreateRequest, FarmResponse, FarmUpdateRequest
from app.services.farm_service import FarmError, FarmNotFoundError, FarmService

router = APIRouter(prefix="/farms", tags=["farms"])


def get_farm_service(session: AsyncSession = Depends(get_db)) -> FarmService:
    return FarmService(FarmRepository(session))


@router.get("", response_model=list[FarmResponse])
async def list_farms(
    current_user: User = Depends(get_current_user),
    farm_service: FarmService = Depends(get_farm_service),
) -> list[FarmResponse]:
    farms = await farm_service.list_farms(current_user)
    return [FarmResponse.from_farm(farm) for farm in farms]


@router.post("", response_model=FarmResponse, status_code=status.HTTP_201_CREATED)
async def create_farm(
    payload: FarmCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    farm_service: FarmService = Depends(get_farm_service),
) -> FarmResponse:
    try:
        farm = await farm_service.create_farm(
            current_user,
            name=payload.name,
            crop=payload.crop,
            variety=payload.variety,
            sowing_date=payload.sowing_date,
            irrigation_method=payload.irrigation_method,
            polygon_geojson=payload.polygon_geojson,
            state=payload.state,
            district=payload.district,
            address=payload.address,
            soil_report=payload.soil_report,
        )
    except FarmError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Best-effort: pre-warms /satellite/latest so it's not empty the first
    # time the farmer opens the Satellite page. Never blocks the response,
    # and a failure here (e.g. Earth Engine not configured) is silent --
    # see run_background_refresh.
    background_tasks.add_task(run_background_refresh, farm.id)
    return FarmResponse.from_farm(farm)


@router.get("/{farm_id}", response_model=FarmResponse)
async def get_farm(
    farm_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    farm_service: FarmService = Depends(get_farm_service),
) -> FarmResponse:
    try:
        farm = await farm_service.get_farm(current_user, farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found.") from exc
    return FarmResponse.from_farm(farm)


@router.patch("/{farm_id}", response_model=FarmResponse)
async def update_farm(
    farm_id: uuid.UUID,
    payload: FarmUpdateRequest,
    current_user: User = Depends(get_current_user),
    farm_service: FarmService = Depends(get_farm_service),
) -> FarmResponse:
    try:
        farm = await farm_service.update_farm(
            current_user,
            farm_id,
            name=payload.name,
            crop=payload.crop,
            variety=payload.variety,
            sowing_date=payload.sowing_date,
            irrigation_method=payload.irrigation_method,
            polygon_geojson=payload.polygon_geojson,
            state=payload.state,
            district=payload.district,
            address=payload.address,
            soil_report=payload.soil_report,
        )
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found.") from exc
    except FarmError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return FarmResponse.from_farm(farm)


@router.delete("/{farm_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_farm(
    farm_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    farm_service: FarmService = Depends(get_farm_service),
) -> None:
    try:
        await farm_service.delete_farm(current_user, farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found.") from exc

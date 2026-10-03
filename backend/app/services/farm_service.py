import uuid
from datetime import datetime, timezone

from app.core.geometry import InvalidPolygonError, compute_polygon_metrics
from app.models.farm import Farm
from app.models.user import User
from app.repositories.farm_repository import FarmRepository
from app.schemas.farm import SoilReportIn


class FarmError(Exception):
    """Raised for a bad request (validation, incomplete profile). Safe to
    return to the client as a 400."""


class FarmNotFoundError(Exception):
    """Raised when a farm doesn't exist *or* belongs to someone else.

    Deliberately a single outcome for both cases (never a 403) so a farm id
    can't be enumerated by noticing a different status code for "not yours"
    versus "doesn't exist" — same anti-enumeration principle used for login.
    """


def _soil_report_fields(soil_report: SoilReportIn | None) -> dict:
    """Farm-row columns for a submitted soil report, or {} when none was
    given -- callers merge this into farm_repository.create/update kwargs.
    A given report always wins: it's the authoritative reading, not a hint
    to blend with the OpenLandMap estimate."""
    if soil_report is None:
        return {}
    return {
        "has_soil_report": True,
        "soil_report_ph": soil_report.ph,
        "soil_report_nitrogen": soil_report.nitrogen,
        "soil_report_phosphorus": soil_report.phosphorus,
        "soil_report_potassium": soil_report.potassium,
        "soil_report_organic_matter_pct": soil_report.organic_matter_pct,
        "soil_report_recorded_at": datetime.now(timezone.utc),
    }


class FarmService:
    def __init__(self, farm_repository: FarmRepository) -> None:
        self.farm_repository = farm_repository

    async def list_farms(self, user: User) -> list[Farm]:
        return await self.farm_repository.list_by_user(user.id)

    async def get_farm(self, user: User, farm_id: uuid.UUID) -> Farm:
        farm = await self.farm_repository.get_by_id(farm_id)
        if farm is None or farm.user_id != user.id:
            raise FarmNotFoundError()
        return farm

    async def create_farm(
        self,
        user: User,
        *,
        name: str,
        crop: str,
        variety: str | None,
        sowing_date,
        irrigation_method: str | None,
        polygon_geojson: dict,
        state: str | None,
        district: str | None,
        address: str | None,
        soil_report: SoilReportIn | None = None,
    ) -> Farm:
        if not (user.phone and user.state):
            raise FarmError(
                "Complete your profile (phone and state) before registering a farm."
            )

        try:
            metrics = compute_polygon_metrics(polygon_geojson)
        except InvalidPolygonError as exc:
            raise FarmError(str(exc)) from exc

        return await self.farm_repository.create(
            user_id=user.id,
            name=name,
            crop=crop,
            variety=variety,
            sowing_date=sowing_date,
            irrigation_method=irrigation_method,
            polygon_geojson=polygon_geojson,
            area_ha=metrics.area_ha,
            centroid_lat=metrics.centroid_lat,
            centroid_lng=metrics.centroid_lng,
            state=state,
            district=district,
            address=address,
            **_soil_report_fields(soil_report),
        )

    async def update_farm(
        self,
        user: User,
        farm_id: uuid.UUID,
        *,
        name: str | None = None,
        crop: str | None = None,
        variety: str | None = None,
        sowing_date=None,
        irrigation_method: str | None = None,
        polygon_geojson: dict | None = None,
        state: str | None = None,
        district: str | None = None,
        address: str | None = None,
        soil_report: SoilReportIn | None = None,
    ) -> Farm:
        farm = await self.get_farm(user, farm_id)

        area_ha = centroid_lat = centroid_lng = None
        if polygon_geojson is not None:
            try:
                metrics = compute_polygon_metrics(polygon_geojson)
            except InvalidPolygonError as exc:
                raise FarmError(str(exc)) from exc
            area_ha, centroid_lat, centroid_lng = (
                metrics.area_ha,
                metrics.centroid_lat,
                metrics.centroid_lng,
            )

        return await self.farm_repository.update(
            farm,
            name=name,
            crop=crop,
            variety=variety,
            sowing_date=sowing_date,
            irrigation_method=irrigation_method,
            polygon_geojson=polygon_geojson,
            area_ha=area_ha,
            centroid_lat=centroid_lat,
            centroid_lng=centroid_lng,
            state=state,
            district=district,
            address=address,
            **_soil_report_fields(soil_report),
        )

    async def delete_farm(self, user: User, farm_id: uuid.UUID) -> None:
        farm = await self.get_farm(user, farm_id)
        await self.farm_repository.delete(farm)

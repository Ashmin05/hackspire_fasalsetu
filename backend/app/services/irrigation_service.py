"""FAO-56 single crop coefficient irrigation model.

Keeps a daily root-zone depletion balance per farm:

    depletion += ETc - effective_rain - logged_irrigation
    ETc = ET0 x Kc

rolled forward day by day from the last day already folded in
(`IrrigationPlan.computed_through`) through yesterday, using CHIRPS
(historical rain, falling back to Open-Meteo's reanalysis archive if Earth
Engine isn't configured/reachable) and Open-Meteo's archive (historical
ET0). It's then projected forward over the Open-Meteo forecast (via
WeatherService, so it shares that cache) to find the next day depletion is
expected to cross RAW = p x TAW -- the "Modelled" next irrigation date and
depth this module outputs.

Kc and root depth come from app/ml/irrigation_kc.py's FAO-56 stage tables,
optionally replaced by an NDVI-derived Kc when a recent satellite
observation exists. TAW comes from app/ml/soil_water.py's texture lookup,
using the farm's EnvironmentSnapshot.soil_texture_class (OpenLandMap) when
available.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.integrations.earth_engine_client import (
    EarthEngineClient,
    EarthEngineNotConfiguredError,
    EarthEngineRequestError,
    EarthEngineTimeoutError,
)
from app.integrations.open_meteo_client import OpenMeteoClient
from app.ml.irrigation_kc import depletion_fraction, resolve_kc, root_depth_m
from app.ml.soil_water import DEFAULT_SOIL_TEXTURE, total_available_water_mm
from app.models.farm import Farm
from app.models.irrigation_plan import IrrigationPlan
from app.repositories.environment_snapshot_repository import EnvironmentSnapshotRepository
from app.repositories.irrigation_log_repository import IrrigationLogRepository
from app.repositories.irrigation_plan_repository import IrrigationPlanRepository
from app.repositories.satellite_repository import SatelliteRepository
from app.schemas.irrigation import IrrigationPlanResponse
from app.services.weather_service import WeatherService, WeatherServiceError

# Rule-of-thumb effective rainfall: a day's rain only counts once it clears
# a threshold (smaller amounts are assumed lost to interception/evaporation
# before reaching the root zone), and only 80% of what's above that counts
# as reaching the crop.
EFFECTIVE_RAIN_THRESHOLD_MM = 5.0
EFFECTIVE_RAIN_FRACTION = 0.80

# Bounds how far back a farm's *first-ever* plan computation reaches (a
# farm sown a year ago shouldn't trigger a year of daily Earth Engine /
# Open-Meteo history calls) -- depletion is assumed 0 (field capacity) at
# this cutoff, same simplifying assumption made at sowing_date itself.
MAX_BACKFILL_DAYS = 180

# A satellite observation older than this is treated as too stale to
# describe "today"'s canopy for the NDVI-adjusted Kc -- falls back to the
# crop-stage curve instead (see app/ml/irrigation_kc.py.resolve_kc).
NDVI_MAX_AGE_DAYS = 20

IST = ZoneInfo("Asia/Kolkata")


class IrrigationServiceError(Exception):
    """Raised for a bad request (log_irrigation) or an unrecoverable
    upstream failure while building a plan. Safe to return as a 400/503 --
    see app/routers/irrigation.py."""


def _local_today() -> date:
    # Matches OpenMeteoClient's TIMEZONE -- a farm's irrigation "today" is
    # its own local day, not UTC.
    return datetime.now(IST).date()


def _effective_rainfall_mm(rain_mm: float | None) -> float:
    if rain_mm is None or rain_mm <= EFFECTIVE_RAIN_THRESHOLD_MM:
        return 0.0
    return EFFECTIVE_RAIN_FRACTION * rain_mm


class IrrigationService:
    def __init__(
        self,
        plan_repository: IrrigationPlanRepository,
        log_repository: IrrigationLogRepository,
        environment_snapshot_repository: EnvironmentSnapshotRepository,
        satellite_repository: SatelliteRepository,
        earth_engine_client: EarthEngineClient,
        open_meteo_client: OpenMeteoClient,
        weather_service: WeatherService,
    ) -> None:
        self.plan_repository = plan_repository
        self.log_repository = log_repository
        self.environment_snapshot_repository = environment_snapshot_repository
        self.satellite_repository = satellite_repository
        self.earth_engine_client = earth_engine_client
        self.open_meteo_client = open_meteo_client
        self.weather_service = weather_service

    async def get_plan(self, farm: Farm) -> IrrigationPlanResponse:
        today = _local_today()
        yesterday = today - timedelta(days=1)

        existing = await self.plan_repository.get_by_farm(farm.id)
        depletion_mm = existing.depletion_mm if existing is not None else 0.0
        computed_through = existing.computed_through if existing is not None else farm.sowing_date - timedelta(days=1)
        computed_through = max(computed_through, farm.sowing_date - timedelta(days=1))
        computed_through = max(computed_through, today - timedelta(days=MAX_BACKFILL_DAYS))

        das_today = (today - farm.sowing_date).days
        kc, kc_basis = await self._resolve_kc(farm, das_today, today)
        depth_m = root_depth_m(farm.crop, das_today)

        snapshot = await self.environment_snapshot_repository.get_by_farm(farm.id)
        texture_class = snapshot.soil_texture_class if snapshot is not None else None
        texture_is_default = texture_class is None
        taw = total_available_water_mm(texture_class, depth_m)
        p = depletion_fraction(farm.crop)
        raw = p * taw

        if computed_through < yesterday:
            depletion_mm, computed_through = await self._roll_forward(
                farm, kc, taw, start=computed_through + timedelta(days=1), end=yesterday, depletion_mm=depletion_mm
            )

        next_date, next_depth = await self._project_next_irrigation(
            farm, kc, taw, raw, today=today, depletion_mm=depletion_mm
        )

        plan = await self.plan_repository.upsert(
            farm_id=farm.id,
            crop=farm.crop,
            days_since_sowing=das_today,
            kc=kc,
            kc_basis=kc_basis,
            root_depth_m=round(depth_m, 2),
            soil_texture_class=texture_class or DEFAULT_SOIL_TEXTURE,
            soil_texture_is_default=texture_is_default,
            taw_mm=round(taw, 1),
            raw_mm=round(raw, 1),
            depletion_fraction=p,
            depletion_mm=round(depletion_mm, 1),
            is_deficit=depletion_mm > raw,
            computed_through=computed_through,
            next_irrigation_date=next_date,
            next_irrigation_depth_mm=round(next_depth, 1) if next_depth is not None else None,
            generated_at=datetime.now(timezone.utc),
        )
        return _plan_to_response(plan)

    async def log_irrigation(self, farm: Farm, *, log_date: date, depth_mm: float, note: str | None) -> None:
        if depth_mm <= 0:
            raise IrrigationServiceError("Irrigation depth must be greater than zero.")
        if log_date > _local_today():
            raise IrrigationServiceError("Cannot log irrigation for a future date.")

        await self.log_repository.create(farm_id=farm.id, log_date=log_date, depth_mm=depth_mm, note=note)

        # A day already folded into the stored balance (computed_through)
        # won't be revisited by a future roll-forward, so a backdated log
        # for it has to be applied immediately. A log for today/a future
        # pending day needs no action here -- the next get_plan's
        # roll-forward will pick it up naturally when it processes that day.
        existing = await self.plan_repository.get_by_farm(farm.id)
        if existing is not None and log_date <= existing.computed_through:
            await self.plan_repository.set_depletion(existing, max(0.0, existing.depletion_mm - depth_mm))

    async def _resolve_kc(self, farm: Farm, das_today: int, today: date) -> tuple[float, str]:
        observation = await self.satellite_repository.get_latest_by_farm(farm.id)
        ndvi = None
        if observation is not None and (today - observation.created_at.date()).days <= NDVI_MAX_AGE_DAYS:
            ndvi = observation.ndvi_mean
        return resolve_kc(farm.crop, das_today, ndvi)

    async def _roll_forward(
        self, farm: Farm, kc: float, taw: float, *, start: date, end: date, depletion_mm: float
    ) -> tuple[float, date]:
        historical = await self._historical_days(farm, start, end)
        logged = await self._logged_depth_by_date(farm.id, start, end)

        computed_through = start - timedelta(days=1)
        day = start
        while day <= end:
            day_data = historical.get(day)
            if day_data is None:
                break  # data lag (CHIRPS/archive not backfilled yet) -- stop rather than guess
            et0, rain = day_data
            etc = kc * et0
            depletion_mm = depletion_mm + etc - _effective_rainfall_mm(rain) - logged.get(day, 0.0)
            depletion_mm = max(0.0, min(depletion_mm, taw))
            computed_through = day
            day += timedelta(days=1)

        return depletion_mm, computed_through

    async def _historical_days(self, farm: Farm, start: date, end: date) -> dict[date, tuple[float, float]]:
        if start > end:
            return {}

        archive = await self.open_meteo_client.get_historical(
            latitude=farm.centroid_lat, longitude=farm.centroid_lng, start_date=start, end_date=end
        )
        et0_by_date = {d.day: d.et0_mm for d in archive if d.et0_mm is not None}
        rain_by_date = {d.day: d.precipitation_mm for d in archive if d.precipitation_mm is not None}

        try:
            chirps = await self.earth_engine_client.get_rainfall_daily_series(farm.polygon_geojson, start, end)
            for day, mm in chirps:
                rain_by_date[day] = mm  # CHIRPS preferred over the reanalysis archive when available
        except (EarthEngineNotConfiguredError, EarthEngineTimeoutError, EarthEngineRequestError):
            pass  # fall back to the archive's own precipitation, already in rain_by_date

        return {day: (et0, rain_by_date[day]) for day, et0 in et0_by_date.items() if day in rain_by_date}

    async def _logged_depth_by_date(self, farm_id: uuid.UUID, start: date, end: date) -> dict[date, float]:
        logs = await self.log_repository.list_between(farm_id, start, end)
        totals: dict[date, float] = {}
        for log in logs:
            totals[log.log_date] = totals.get(log.log_date, 0.0) + log.depth_mm
        return totals

    async def _project_next_irrigation(
        self, farm: Farm, kc: float, taw: float, raw: float, *, today: date, depletion_mm: float
    ) -> tuple[date | None, float | None]:
        if depletion_mm > raw:
            # Already past the readily-available-water threshold as of
            # yesterday -- irrigation is due now, not on some future date.
            return today, min(depletion_mm, taw)

        # Left uncaught -- WeatherServiceError propagates to the router as
        # a 503 (Open-Meteo unreachable), same as GET /farms/{id}/weather.
        weather = await self.weather_service.get_weather(farm)

        projected = depletion_mm
        for day in weather.daily:
            if day.date <= today - timedelta(days=1) or day.et0_fao_evapotranspiration_mm is None:
                continue
            etc = kc * day.et0_fao_evapotranspiration_mm
            projected = max(0.0, projected + etc - _effective_rainfall_mm(day.precipitation_sum_mm))
            if projected > raw:
                return day.date, min(projected, taw)

        return None, None


def _plan_to_response(plan: IrrigationPlan) -> IrrigationPlanResponse:
    generated_at = plan.generated_at
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    return IrrigationPlanResponse(
        farm_id=plan.farm_id,
        crop=plan.crop,
        days_since_sowing=plan.days_since_sowing,
        kc=plan.kc,
        kc_basis=plan.kc_basis,
        root_depth_m=plan.root_depth_m,
        soil_texture_class=plan.soil_texture_class,
        soil_texture_is_default=plan.soil_texture_is_default,
        taw_mm=plan.taw_mm,
        raw_mm=plan.raw_mm,
        depletion_fraction=plan.depletion_fraction,
        depletion_mm=plan.depletion_mm,
        is_deficit=plan.is_deficit,
        computed_through=plan.computed_through,
        next_irrigation_date=plan.next_irrigation_date,
        next_irrigation_depth_mm=plan.next_irrigation_depth_mm,
        generated_at=generated_at,
    )

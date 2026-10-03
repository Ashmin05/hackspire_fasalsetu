import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from app.core.satellite_health import compute_health_score, crop_stage_benchmark_ndvi, days_since
from app.integrations.earth_engine_client import (
    MAP_LAYERS_CACHE_HOURS,
    EarthEngineClient,
    EarthEngineNotConfiguredError,
    EarthEngineRequestError,
    EarthEngineTimeoutError,
    NoSentinelImageryAvailableError,
)
from app.ml.crop_benchmarks import benchmark_ndvi_for_crop
from app.models.environment_snapshot import EnvironmentSnapshot
from app.models.farm import Farm
from app.models.farm_alert import FarmAlert
from app.models.index_timeseries import IndexTimeseriesPoint
from app.models.satellite_layer_set import SatelliteLayerSet
from app.models.satellite_observation import SatelliteObservation
from app.models.stress_zone import StressZone
from app.repositories.environment_snapshot_repository import EnvironmentSnapshotRepository
from app.repositories.farm_alert_repository import FarmAlertRepository
from app.repositories.index_timeseries_repository import IndexTimeseriesRepository
from app.repositories.satellite_layer_repository import SatelliteLayerRepository
from app.repositories.satellite_repository import SatelliteRepository
from app.repositories.stress_zone_repository import StressZoneRepository

# One asyncio.Lock per farm id -- see refresh_analysis.
_refresh_locks: dict[uuid.UUID, asyncio.Lock] = {}


def _as_utc(value: datetime) -> datetime:
    # SQLite (the test suite) drops tzinfo on read; the stored value is UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# Timeseries points with field cloud cover at/above this are dropped before
# being stored -- too cloudy to trust for a trend line or alert.
TIMESERIES_CLOUD_THRESHOLD = 30.0

# How far back build_timeseries looks, capped regardless of how old the
# farm's sowing_date is -- keeps the Earth Engine query bounded for an
# old/perennial field (see build_timeseries).
TIMESERIES_LOOKBACK_DAYS = 120

# Alert thresholds -- see _generate_alerts for what each one means.
NDVI_DROP_RELATIVE_THRESHOLD = 0.15
BELOW_BENCHMARK_ABSOLUTE_THRESHOLD = 0.1
# Rough day-after-sowing window treated as "vegetative stage" for the water-
# stress rule -- deliberately generic (not per-crop) since it only gates
# *when* NDWI-below-0 is worth flagging, not what NDVI is expected.
VEGETATIVE_STAGE_DAYS = (20, 90)


class SatelliteAnalysisError(Exception):
    """Raised when a satellite refresh can't complete: Earth Engine isn't
    configured, timed out, or no Sentinel-2 imagery was available in the
    analysis window. Safe to return to the client as a 503 (see router)."""


class SatelliteService:
    def __init__(
        self,
        satellite_repository: SatelliteRepository,
        earth_engine_client: EarthEngineClient,
        index_timeseries_repository: IndexTimeseriesRepository | None = None,
        farm_alert_repository: FarmAlertRepository | None = None,
        satellite_layer_repository: SatelliteLayerRepository | None = None,
        stress_zone_repository: StressZoneRepository | None = None,
        environment_snapshot_repository: EnvironmentSnapshotRepository | None = None,
    ) -> None:
        self.satellite_repository = satellite_repository
        self.earth_engine_client = earth_engine_client
        # Optional: only refresh_analysis()/get_latest() are usable without
        # these (existing callers, e.g. the on-farm-create background
        # refresh, don't need the timeseries/alerts/map-layers machinery).
        self.index_timeseries_repository = index_timeseries_repository
        self.farm_alert_repository = farm_alert_repository
        self.satellite_layer_repository = satellite_layer_repository
        self.stress_zone_repository = stress_zone_repository
        self.environment_snapshot_repository = environment_snapshot_repository

    async def get_latest(self, farm: Farm) -> SatelliteObservation | None:
        """Cache-only read -- never touches Earth Engine."""
        return await self.satellite_repository.get_latest_by_farm(farm.id)

    async def refresh_analysis(self, farm: Farm) -> SatelliteObservation:
        """Runs a live Sentinel-2 analysis for `farm`'s polygon and stores
        the result as a new cached observation.

        At most one analysis per farm runs at a time: creating a farm starts
        a background refresh, and the UI starts its own first analysis
        moments later. A caller that arrives while one is running waits for
        it and returns that result instead of paying for a duplicate ~30 s
        Earth Engine run. (Per process -- enough for the single-worker
        deployment this runs as today.)"""
        requested_at = datetime.now(timezone.utc)
        lock = _refresh_locks.setdefault(farm.id, asyncio.Lock())
        async with lock:
            latest = await self.get_latest(farm)
            if latest is not None and _as_utc(latest.created_at) >= requested_at:
                return latest  # finished by the caller we just waited for
            return await self._run_analysis(farm)

    async def _run_analysis(self, farm: Farm) -> SatelliteObservation:
        try:
            result = await self.earth_engine_client.analyze_field(farm.polygon_geojson)
        except (
            EarthEngineNotConfiguredError,
            EarthEngineTimeoutError,
            EarthEngineRequestError,
            NoSentinelImageryAvailableError,
        ) as exc:
            raise SatelliteAnalysisError(str(exc)) from exc

        benchmark_ndvi = crop_stage_benchmark_ndvi(days_since(farm.sowing_date, result.image_date))
        health_score = compute_health_score(
            mean_ndvi=result.ndvi.mean,
            benchmark_ndvi=benchmark_ndvi,
            stressed_pct=result.stressed_pct,
        )

        return await self.satellite_repository.create(
            farm_id=farm.id,
            image_date=result.image_date,
            satellite=result.satellite,
            cloud_pct=result.cloud_pct,
            is_fallback=result.is_fallback,
            ndvi_mean=result.ndvi.mean,
            ndvi_min=result.ndvi.min,
            ndvi_max=result.ndvi.max,
            ndwi_mean=result.ndwi.mean,
            ndwi_min=result.ndwi.min,
            ndwi_max=result.ndwi.max,
            evi_mean=result.evi.mean,
            evi_min=result.evi.min,
            evi_max=result.evi.max,
            ndmi_mean=result.ndmi.mean,
            ndmi_min=result.ndmi.min,
            ndmi_max=result.ndmi.max,
            healthy_pct=result.healthy_pct,
            moderate_pct=result.moderate_pct,
            stressed_pct=result.stressed_pct,
            health_score=health_score,
        )

    async def get_timeseries(self, farm: Farm) -> list[IndexTimeseriesPoint]:
        """Cache-only read of the accumulated NDVI/NDWI/EVI history -- never
        touches Earth Engine. Populated by build_timeseries, normally via
        the nightly scheduler job (app/jobs/scheduler.py)."""
        assert self.index_timeseries_repository is not None, "index_timeseries_repository required"
        return await self.index_timeseries_repository.list_by_farm(farm.id)

    async def get_alerts(self, farm: Farm) -> list[FarmAlert]:
        assert self.farm_alert_repository is not None, "farm_alert_repository required"
        return await self.farm_alert_repository.list_by_farm(farm.id)

    async def build_timeseries(self, farm: Farm) -> list[IndexTimeseriesPoint]:
        """Rebuilds `farm`'s NDVI/NDWI/EVI timeseries from Sentinel-2 (from
        its sowing date, or TIMESERIES_LOOKBACK_DAYS back, whichever is more
        recent, through today), storing every clear (< 30% field cloud)
        pass, then runs the alert rules over the updated series. Called by
        the nightly scheduler job for every farm -- this is the "check every
        farm for a new clear pass" step.
        """
        assert self.index_timeseries_repository is not None, "index_timeseries_repository required"
        assert self.farm_alert_repository is not None, "farm_alert_repository required"

        today = datetime.now(timezone.utc).date()
        lookback_start = today - timedelta(days=TIMESERIES_LOOKBACK_DAYS)
        start = max(farm.sowing_date, lookback_start)

        try:
            raw_points = await self.earth_engine_client.build_field_timeseries(
                farm.polygon_geojson, start=start, end=today
            )
        except (EarthEngineNotConfiguredError, EarthEngineTimeoutError, EarthEngineRequestError) as exc:
            raise SatelliteAnalysisError(str(exc)) from exc

        clear_points = [p for p in raw_points if p.cloud_pct < TIMESERIES_CLOUD_THRESHOLD]

        for point in clear_points:
            days = days_since(farm.sowing_date, point.image_date)
            benchmark = benchmark_ndvi_for_crop(farm.crop, days)
            await self.index_timeseries_repository.upsert(
                farm_id=farm.id,
                image_date=point.image_date,
                satellite=point.satellite,
                cloud_pct=point.cloud_pct,
                ndvi_mean=point.ndvi_mean,
                ndwi_mean=point.ndwi_mean,
                evi_mean=point.evi_mean,
                benchmark_ndvi=benchmark,
            )

        series = await self.index_timeseries_repository.list_by_farm(farm.id)
        await self._generate_alerts(farm, series)
        return series

    async def _generate_alerts(self, farm: Farm, series: list[IndexTimeseriesPoint]) -> None:
        """Three rules, each checked at every point with a preceding point:
        (a) NDVI dropped more than NDVI_DROP_RELATIVE_THRESHOLD (relative)
            between two consecutive clear passes.
        (b) NDVI has been more than BELOW_BENCHMARK_ABSOLUTE_THRESHOLD below
            the crop-stage benchmark for two consecutive passes.
        (c) NDWI fell below 0 during the vegetative stage (possible water
            stress) -- doesn't need a preceding point.
        Alerts are de-duplicated per (farm, type, detected_at) so re-running
        this over the same historical points (the nightly job re-scans a
        rolling window) doesn't create duplicates.
        """
        assert self.farm_alert_repository is not None, "farm_alert_repository required"

        for i, point in enumerate(series):
            days = days_since(farm.sowing_date, point.image_date)

            if i > 0:
                prev = series[i - 1]
                if prev.ndvi_mean > 0:
                    relative_drop = (prev.ndvi_mean - point.ndvi_mean) / prev.ndvi_mean
                    if relative_drop > NDVI_DROP_RELATIVE_THRESHOLD:
                        await self._create_alert_if_new(
                            farm.id,
                            "ndvi_drop",
                            "warning",
                            point.image_date,
                            f"NDVI dropped {relative_drop * 100:.0f}% between {prev.image_date} and "
                            f"{point.image_date} ({prev.ndvi_mean:.2f} -> {point.ndvi_mean:.2f}).",
                        )

                prev_below = prev.benchmark_ndvi - prev.ndvi_mean > BELOW_BENCHMARK_ABSOLUTE_THRESHOLD
                curr_below = point.benchmark_ndvi - point.ndvi_mean > BELOW_BENCHMARK_ABSOLUTE_THRESHOLD
                if prev_below and curr_below:
                    await self._create_alert_if_new(
                        farm.id,
                        "below_benchmark",
                        "warning",
                        point.image_date,
                        f"NDVI has been more than {BELOW_BENCHMARK_ABSOLUTE_THRESHOLD:.1f} below the "
                        f"{farm.crop} benchmark for two consecutive passes (latest: "
                        f"{point.ndvi_mean:.2f} vs. benchmark {point.benchmark_ndvi:.2f}).",
                    )

            if (
                days is not None
                and VEGETATIVE_STAGE_DAYS[0] <= days <= VEGETATIVE_STAGE_DAYS[1]
                and point.ndwi_mean < 0
            ):
                await self._create_alert_if_new(
                    farm.id,
                    "water_stress",
                    "critical",
                    point.image_date,
                    f"NDWI ({point.ndwi_mean:.2f}) fell below 0 during the vegetative stage "
                    f"(day {days} after sowing) -- possible water stress.",
                )

    async def _create_alert_if_new(self, farm_id, alert_type: str, severity: str, detected_at, message: str) -> None:
        assert self.farm_alert_repository is not None, "farm_alert_repository required"
        if await self.farm_alert_repository.exists(farm_id, alert_type, detected_at):
            return
        await self.farm_alert_repository.create(
            farm_id=farm_id,
            alert_type=alert_type,
            severity=severity,
            detected_at=detected_at,
            message=message,
        )

    async def get_or_build_layers(
        self, farm: Farm, image_date: date | None
    ) -> tuple[SatelliteLayerSet, list[StressZone]]:
        """Returns cached tile URLs + stress zones for `farm` on
        `image_date` (defaulting to the farm's latest known analysis date
        when omitted), regenerating from Earth Engine only when nothing is
        cached yet or the cached set is older than MAP_LAYERS_CACHE_HOURS.
        """
        assert self.satellite_layer_repository is not None, "satellite_layer_repository required"
        assert self.stress_zone_repository is not None, "stress_zone_repository required"

        target_date = image_date
        if target_date is None:
            latest = await self.get_latest(farm)
            if latest is None:
                raise SatelliteAnalysisError(
                    "No satellite analysis yet for this farm. POST .../satellite/refresh to run one first."
                )
            target_date = latest.image_date

        now = datetime.now(timezone.utc)
        existing = await self.satellite_layer_repository.get_by_farm_and_date(farm.id, target_date)
        # SQLite (used by the test suite) drops tzinfo on read even for a
        # DateTime(timezone=True) column -- the stored value is still UTC,
        # so treat a naive expires_at as UTC rather than erroring on the
        # naive/aware comparison below.
        expires_at = existing.expires_at if existing is not None else None
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if existing is not None and expires_at > now:
            zones = await self.stress_zone_repository.list_by_farm_and_date(farm.id, target_date)
            return existing, zones

        try:
            result = await self.earth_engine_client.get_field_map_layers(farm.polygon_geojson, target_date)
        except (
            EarthEngineNotConfiguredError,
            EarthEngineTimeoutError,
            EarthEngineRequestError,
            NoSentinelImageryAvailableError,
        ) as exc:
            raise SatelliteAnalysisError(str(exc)) from exc

        layer_set = await self.satellite_layer_repository.upsert(
            farm_id=farm.id,
            image_date=target_date,
            true_color_tile_url=result.true_color_tile_url,
            ndvi_tile_url=result.ndvi_tile_url,
            ndwi_tile_url=result.ndwi_tile_url,
            evi_tile_url=result.evi_tile_url,
            stress_tile_url=result.stress_tile_url,
            generated_at=now,
            expires_at=now + timedelta(hours=MAP_LAYERS_CACHE_HOURS),
        )
        zones = await self.stress_zone_repository.replace_for_date(farm.id, target_date, result.stress_zones)
        return layer_set, zones

    async def get_environment(self, farm: Farm) -> EnvironmentSnapshot | None:
        """Cache-only read of the farm's environment snapshot -- never
        touches Earth Engine. Populated by refresh_environment, normally via
        the nightly scheduler job (app/jobs/scheduler.py)."""
        assert self.environment_snapshot_repository is not None, "environment_snapshot_repository required"
        return await self.environment_snapshot_repository.get_by_farm(farm.id)

    async def refresh_environment(self, farm: Farm) -> EnvironmentSnapshot:
        """Rainfall/temperature/soil-moisture/soil report for `farm`.
        Rainfall, temperature, and soil moisture are refreshed from Earth
        Engine on every call (they change day to day); soil pH/organic
        carbon/texture class are fetched only the first time this is ever
        called for a farm and reused after that, since soil doesn't change.
        Called by the nightly scheduler job for every farm -- GET
        /farms/{id}/environment itself only reads the cached result (see
        get_environment), the same split as build_timeseries/get_timeseries.
        """
        assert self.environment_snapshot_repository is not None, "environment_snapshot_repository required"

        try:
            dynamics = await self.earth_engine_client.get_environment_dynamics(
                farm.polygon_geojson, farm.sowing_date
            )
        except (EarthEngineNotConfiguredError, EarthEngineTimeoutError, EarthEngineRequestError) as exc:
            raise SatelliteAnalysisError(str(exc)) from exc

        existing = await self.environment_snapshot_repository.get_by_farm(farm.id)
        soil = None
        # A farmer-submitted Soil Health Card / lab report is authoritative
        # (see Farm.has_soil_report) -- never spend an OpenLandMap call
        # fetching an estimate that would just be overridden anyway (see
        # _environment_snapshot_to_response, which prefers the lab report).
        if not farm.has_soil_report and (existing is None or existing.soil_fetched_at is None):
            try:
                soil = await self.earth_engine_client.get_soil_properties(farm.polygon_geojson)
            except (EarthEngineNotConfiguredError, EarthEngineTimeoutError, EarthEngineRequestError) as exc:
                raise SatelliteAnalysisError(str(exc)) from exc

        now = datetime.now(timezone.utc)
        return await self.environment_snapshot_repository.upsert(
            farm_id=farm.id,
            rainfall_7d_mm=dynamics.rainfall.mm_7d,
            rainfall_30d_mm=dynamics.rainfall.mm_30d,
            rainfall_90d_mm=dynamics.rainfall.mm_90d,
            rainfall_since_sowing_mm=dynamics.rainfall.mm_since_sowing,
            rainfall_as_of=dynamics.rainfall.as_of,
            mean_lst_c=dynamics.temperature.mean_lst_c,
            hot_periods_60d=dynamics.temperature.hot_periods_60d,
            temperature_as_of=dynamics.temperature.as_of,
            soil_moisture=dynamics.soil_moisture.surface_moisture,
            soil_moisture_as_of=dynamics.soil_moisture.as_of,
            generated_at=now,
            soil_ph=soil.ph if soil is not None else None,
            soil_organic_carbon_g_per_kg=soil.organic_carbon_g_per_kg if soil is not None else None,
            soil_texture_class=soil.texture_class if soil is not None else None,
            soil_fetched_at=now if soil is not None else None,
        )

"""Tests for IrrigationService's FAO-56 water balance against mocked
OpenMeteoClient/EarthEngineClient and a real in-memory SQLite DB, same
pattern as test_weather_service.py."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.earth_engine_client import EarthEngineNotConfiguredError
from app.integrations.open_meteo_client import DailyForecast, HistoricalDay, OpenMeteoForecast
from app.ml.irrigation_kc import crop_stage_kc
from app.repositories.environment_snapshot_repository import EnvironmentSnapshotRepository
from app.repositories.farm_repository import FarmRepository
from app.repositories.satellite_repository import SatelliteRepository
from app.repositories.user_repository import UserRepository
from app.services.farm_service import FarmService
from app.services.irrigation_service import IrrigationService, IrrigationServiceError
from app.services.weather_service import WeatherService

VALID_POLYGON = {
    "type": "Polygon",
    "coordinates": [[
        [73.789522, 19.989548],
        [73.790478, 19.989548],
        [73.790478, 19.990452],
        [73.789522, 19.990452],
        [73.789522, 19.989548],
    ]],
}

TODAY = date(2026, 9, 28)


def _no_op_forecast(as_of: date = TODAY) -> OpenMeteoForecast:
    """A forecast with negligible ET0 and heavy rain every day -- never
    triggers a projected irrigation, so tests that don't care about the
    forward-projection leg get a deterministic `next_irrigation_date=None`."""
    return OpenMeteoForecast(
        latitude=19.99,
        longitude=73.79,
        timezone="Asia/Kolkata",
        daily=[
            DailyForecast(
                forecast_date=as_of + timedelta(days=i),
                temp_max_c=28.0,
                temp_min_c=20.0,
                precipitation_sum_mm=20.0,
                precipitation_probability_max_pct=80.0,
                wind_speed_max_kmh=5.0,
                relative_humidity_mean_pct=70.0,
                uv_index_max=4.0,
                et0_fao_evapotranspiration_mm=0.1,
            )
            for i in range(10)
        ],
    )


async def _user_with_profile(user_repository: UserRepository):
    user = await user_repository.create(email="farmer@example.com", hashed_password="x")
    return await user_repository.update_profile(user, phone="9876543210", state="Maharashtra")


async def _create_farm(farm_service: FarmService, user, *, sowing_date: date, crop: str = "Wheat"):
    return await farm_service.create_farm(
        user,
        name="Test Field",
        crop=crop,
        variety=None,
        sowing_date=sowing_date,
        irrigation_method="Drip",
        polygon_geojson=VALID_POLYGON,
        state="Maharashtra",
        district="Nashik",
        address="Village road",
    )


def _service(
    irrigation_plan_repository,
    irrigation_log_repository,
    environment_snapshot_repository,
    satellite_repository,
    weather_cache_repository,
    fake_earth_engine,
    fake_open_meteo,
) -> IrrigationService:
    weather_service = WeatherService(weather_cache_repository, fake_open_meteo)
    return IrrigationService(
        irrigation_plan_repository,
        irrigation_log_repository,
        environment_snapshot_repository,
        satellite_repository,
        fake_earth_engine,
        fake_open_meteo,
        weather_service,
    )


@pytest.fixture
def user_repository(session):
    return UserRepository(session)


@pytest.fixture
def farm_service(farm_repository: FarmRepository) -> FarmService:
    return FarmService(farm_repository)


@pytest.fixture
def fake_earth_engine():
    client = MagicMock()
    # Default: behave like an unconfigured EE client -- most tests fall
    # back to the Open-Meteo archive's own rain figures.
    client.get_rainfall_daily_series = AsyncMock(side_effect=EarthEngineNotConfiguredError("not configured"))
    return client


@pytest.fixture
def fake_open_meteo():
    client = MagicMock()
    client.get_forecast = AsyncMock(return_value=_no_op_forecast())
    client.get_historical = AsyncMock(return_value=[])
    return client


class TestGetPlanNoBackfillNeeded:
    async def test_sown_today_has_zero_depletion_and_defaults_to_loam(
        self,
        irrigation_plan_repository,
        irrigation_log_repository,
        environment_snapshot_repository,
        satellite_repository,
        weather_cache_repository,
        farm_service,
        user_repository,
        fake_earth_engine,
        fake_open_meteo,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, sowing_date=TODAY)
        service = _service(
            irrigation_plan_repository,
            irrigation_log_repository,
            environment_snapshot_repository,
            satellite_repository,
            weather_cache_repository,
            fake_earth_engine,
            fake_open_meteo,
        )

        import app.services.irrigation_service as irrigation_module

        original_today = irrigation_module._local_today
        irrigation_module._local_today = lambda: TODAY
        try:
            plan = await service.get_plan(farm)
        finally:
            irrigation_module._local_today = original_today

        assert plan.depletion_mm == 0.0
        assert plan.kc_basis == "crop_stage"
        assert plan.soil_texture_class == "Loam"
        assert plan.soil_texture_is_default is True
        assert plan.is_deficit is False
        # No-op forecast (negligible ET0, heavy rain) never crosses RAW.
        assert plan.next_irrigation_date is None
        assert fake_open_meteo.get_historical.await_count == 0  # nothing to backfill


class TestGetPlanRollsForwardHistory:
    async def test_accumulates_depletion_from_historical_et0_and_rain(
        self,
        irrigation_plan_repository,
        irrigation_log_repository,
        environment_snapshot_repository,
        satellite_repository,
        weather_cache_repository,
        farm_service,
        user_repository,
        fake_earth_engine,
        fake_open_meteo,
    ) -> None:
        sowing_date = TODAY - timedelta(days=3)
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, sowing_date=sowing_date, crop="Wheat")

        # 3 historical days (sowing_date .. TODAY-1), no rain, ET0=5mm/day.
        fake_open_meteo.get_historical = AsyncMock(
            return_value=[
                HistoricalDay(day=sowing_date + timedelta(days=i), et0_mm=5.0, precipitation_mm=0.0)
                for i in range(3)
            ]
        )

        service = _service(
            irrigation_plan_repository,
            irrigation_log_repository,
            environment_snapshot_repository,
            satellite_repository,
            weather_cache_repository,
            fake_earth_engine,
            fake_open_meteo,
        )

        import app.services.irrigation_service as irrigation_module

        original_today = irrigation_module._local_today
        irrigation_module._local_today = lambda: TODAY
        try:
            plan = await service.get_plan(farm)
        finally:
            irrigation_module._local_today = original_today

        # Day 3 after sowing is still within wheat's flat Lini stage -> kc = 0.40.
        expected_kc = crop_stage_kc("wheat", 3)
        assert expected_kc == 0.40
        # 3 days x (0.40 x 5.0mm ET0 - 0 effective rain) = 6.0mm.
        assert plan.depletion_mm == pytest.approx(6.0, abs=0.05)
        assert plan.computed_through == TODAY - timedelta(days=1)
        assert plan.kc == pytest.approx(0.40, abs=1e-6)

    async def test_prefers_chirps_rain_over_archive_when_earth_engine_available(
        self,
        irrigation_plan_repository,
        irrigation_log_repository,
        environment_snapshot_repository,
        satellite_repository,
        weather_cache_repository,
        farm_service,
        user_repository,
        fake_earth_engine,
        fake_open_meteo,
    ) -> None:
        sowing_date = TODAY - timedelta(days=2)
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, sowing_date=sowing_date, crop="Wheat")

        # Archive says no rain; CHIRPS (once "configured") says heavy rain
        # every day -- effective rain should come from CHIRPS, not the
        # archive, so depletion stays near zero instead of accumulating.
        fake_open_meteo.get_historical = AsyncMock(
            return_value=[
                HistoricalDay(day=sowing_date + timedelta(days=i), et0_mm=5.0, precipitation_mm=0.0)
                for i in range(2)
            ]
        )
        fake_earth_engine.get_rainfall_daily_series = AsyncMock(
            return_value=[(sowing_date + timedelta(days=i), 30.0) for i in range(2)]
        )

        service = _service(
            irrigation_plan_repository,
            irrigation_log_repository,
            environment_snapshot_repository,
            satellite_repository,
            weather_cache_repository,
            fake_earth_engine,
            fake_open_meteo,
        )

        import app.services.irrigation_service as irrigation_module

        original_today = irrigation_module._local_today
        irrigation_module._local_today = lambda: TODAY
        try:
            plan = await service.get_plan(farm)
        finally:
            irrigation_module._local_today = original_today

        # etc = 0.40 x 5.0 = 2.0mm/day; effective rain = 0.8 x 30.0 = 24.0mm/day
        # (well above the ETc) -- depletion clamps at 0 each day.
        assert plan.depletion_mm == 0.0


class TestLogIrrigation:
    async def test_rejects_non_positive_depth(
        self,
        irrigation_plan_repository,
        irrigation_log_repository,
        environment_snapshot_repository,
        satellite_repository,
        weather_cache_repository,
        farm_service,
        user_repository,
        fake_earth_engine,
        fake_open_meteo,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, sowing_date=TODAY)
        service = _service(
            irrigation_plan_repository,
            irrigation_log_repository,
            environment_snapshot_repository,
            satellite_repository,
            weather_cache_repository,
            fake_earth_engine,
            fake_open_meteo,
        )

        with pytest.raises(IrrigationServiceError):
            await service.log_irrigation(farm, log_date=TODAY, depth_mm=0.0, note=None)

    async def test_rejects_future_date(
        self,
        irrigation_plan_repository,
        irrigation_log_repository,
        environment_snapshot_repository,
        satellite_repository,
        weather_cache_repository,
        farm_service,
        user_repository,
        fake_earth_engine,
        fake_open_meteo,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, sowing_date=TODAY)
        service = _service(
            irrigation_plan_repository,
            irrigation_log_repository,
            environment_snapshot_repository,
            satellite_repository,
            weather_cache_repository,
            fake_earth_engine,
            fake_open_meteo,
        )

        import app.services.irrigation_service as irrigation_module

        original_today = irrigation_module._local_today
        irrigation_module._local_today = lambda: TODAY
        try:
            with pytest.raises(IrrigationServiceError):
                await service.log_irrigation(farm, log_date=TODAY + timedelta(days=1), depth_mm=5.0, note=None)
        finally:
            irrigation_module._local_today = original_today

    async def test_backdated_log_immediately_reduces_stored_depletion(
        self,
        irrigation_plan_repository,
        irrigation_log_repository,
        environment_snapshot_repository,
        satellite_repository,
        weather_cache_repository,
        farm_service,
        user_repository,
        fake_earth_engine,
        fake_open_meteo,
    ) -> None:
        sowing_date = TODAY - timedelta(days=3)
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, sowing_date=sowing_date, crop="Wheat")

        fake_open_meteo.get_historical = AsyncMock(
            return_value=[
                HistoricalDay(day=sowing_date + timedelta(days=i), et0_mm=5.0, precipitation_mm=0.0)
                for i in range(3)
            ]
        )

        service = _service(
            irrigation_plan_repository,
            irrigation_log_repository,
            environment_snapshot_repository,
            satellite_repository,
            weather_cache_repository,
            fake_earth_engine,
            fake_open_meteo,
        )

        import app.services.irrigation_service as irrigation_module

        original_today = irrigation_module._local_today
        irrigation_module._local_today = lambda: TODAY
        try:
            plan = await service.get_plan(farm)
            assert plan.depletion_mm == pytest.approx(6.0, abs=0.05)  # see test above

            # log_date is within the already-rolled-forward window.
            await service.log_irrigation(
                farm, log_date=TODAY - timedelta(days=2), depth_mm=4.0, note="canal release"
            )
        finally:
            irrigation_module._local_today = original_today

        updated = await irrigation_plan_repository.get_by_farm(farm.id)
        assert updated.depletion_mm == pytest.approx(2.0, abs=0.05)


class TestKcFromNdvi:
    async def test_recent_satellite_observation_drives_ndvi_kc(
        self,
        irrigation_plan_repository,
        irrigation_log_repository,
        environment_snapshot_repository,
        satellite_repository: SatelliteRepository,
        weather_cache_repository,
        farm_service,
        user_repository,
        fake_earth_engine,
        fake_open_meteo,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, sowing_date=TODAY, crop="Onion")
        await satellite_repository.create(
            farm_id=farm.id,
            image_date=TODAY,
            created_at=datetime(TODAY.year, TODAY.month, TODAY.day, tzinfo=timezone.utc),
            satellite="S2A",
            cloud_pct=5.0,
            is_fallback=False,
            ndvi_mean=0.6,
            ndvi_min=0.4,
            ndvi_max=0.8,
            ndwi_mean=0.1,
            ndwi_min=0.0,
            ndwi_max=0.2,
            evi_mean=0.5,
            evi_min=0.3,
            evi_max=0.7,
            ndmi_mean=0.3,
            ndmi_min=0.1,
            ndmi_max=0.5,
            healthy_pct=80.0,
            moderate_pct=15.0,
            stressed_pct=5.0,
            health_score=85.0,
        )

        service = _service(
            irrigation_plan_repository,
            irrigation_log_repository,
            environment_snapshot_repository,
            satellite_repository,
            weather_cache_repository,
            fake_earth_engine,
            fake_open_meteo,
        )

        import app.services.irrigation_service as irrigation_module

        original_today = irrigation_module._local_today
        irrigation_module._local_today = lambda: TODAY
        try:
            plan = await service.get_plan(farm)
        finally:
            irrigation_module._local_today = original_today

        assert plan.kc_basis == "ndvi"
        # onion range [0.70, 1.05]; 1.25 x 0.6 + 0.1 = 0.85, inside range.
        assert plan.kc == pytest.approx(0.85, abs=1e-3)

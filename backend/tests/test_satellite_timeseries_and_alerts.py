"""Tests for SatelliteService.build_timeseries and its alert rules, against
a mocked EarthEngineClient and a real in-memory SQLite DB."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.earth_engine_client import (
    EarthEngineNotConfiguredError,
    TimeseriesPoint,
)
from app.ml.crop_benchmarks import benchmark_ndvi_for_crop
from app.repositories.farm_alert_repository import FarmAlertRepository
from app.repositories.farm_repository import FarmRepository
from app.repositories.index_timeseries_repository import IndexTimeseriesRepository
from app.repositories.satellite_repository import SatelliteRepository
from app.repositories.user_repository import UserRepository
from app.services.farm_service import FarmService
from app.services.satellite_service import SatelliteAnalysisError, SatelliteService

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

SOWING_DATE = date(2026, 6, 1)


async def _user_with_profile(user_repository: UserRepository):
    user = await user_repository.create(email="farmer@example.com", hashed_password="x")
    return await user_repository.update_profile(user, phone="9876543210", state="Maharashtra")


async def _create_farm(farm_service: FarmService, user, *, crop: str = "Wheat"):
    return await farm_service.create_farm(
        user,
        name="North Wheat Field",
        crop=crop,
        variety=None,
        sowing_date=SOWING_DATE,
        irrigation_method="Drip",
        polygon_geojson=VALID_POLYGON,
        state="Maharashtra",
        district="Nashik",
        address="Village road",
    )


def _point(days_after_sowing: int, *, ndvi: float, ndwi: float = 0.2, evi: float = 0.4) -> TimeseriesPoint:
    return TimeseriesPoint(
        image_date=SOWING_DATE + timedelta(days=days_after_sowing),
        satellite="S2A",
        cloud_pct=5.0,
        ndvi_mean=ndvi,
        ndwi_mean=ndwi,
        evi_mean=evi,
    )


def _service(
    satellite_repository: SatelliteRepository,
    index_timeseries_repository: IndexTimeseriesRepository,
    farm_alert_repository: FarmAlertRepository,
    fake_ee_client,
) -> SatelliteService:
    return SatelliteService(
        satellite_repository, fake_ee_client, index_timeseries_repository, farm_alert_repository
    )


@pytest.fixture
def user_repository(session):
    return UserRepository(session)


@pytest.fixture
def farm_service(farm_repository: FarmRepository) -> FarmService:
    return FarmService(farm_repository)


class TestBuildTimeseries:
    async def test_stores_only_clear_points_under_cloud_threshold(
        self,
        satellite_repository,
        index_timeseries_repository,
        farm_alert_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.build_field_timeseries = AsyncMock(
            return_value=[
                _point(10, ndvi=0.3),  # clear (default cloud_pct=5.0)
                TimeseriesPoint(
                    image_date=SOWING_DATE + timedelta(days=15),
                    satellite="S2B",
                    cloud_pct=45.0,  # too cloudy -- must be dropped
                    ndvi_mean=0.35,
                    ndwi_mean=0.1,
                    evi_mean=0.3,
                ),
            ]
        )
        service = _service(satellite_repository, index_timeseries_repository, farm_alert_repository, fake_ee_client)

        series = await service.build_timeseries(farm)

        assert len(series) == 1
        assert series[0].image_date == SOWING_DATE + timedelta(days=10)
        assert series[0].cloud_pct == 5.0

    async def test_stores_benchmark_ndvi_from_the_farms_crop(
        self,
        satellite_repository,
        index_timeseries_repository,
        farm_alert_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, crop="Wheat")
        fake_ee_client = MagicMock()
        fake_ee_client.build_field_timeseries = AsyncMock(return_value=[_point(50, ndvi=0.4)])
        service = _service(satellite_repository, index_timeseries_repository, farm_alert_repository, fake_ee_client)

        series = await service.build_timeseries(farm)

        assert series[0].benchmark_ndvi == benchmark_ndvi_for_crop("Wheat", 50)

    async def test_upsert_updates_existing_point_for_the_same_date_instead_of_duplicating(
        self,
        satellite_repository,
        index_timeseries_repository,
        farm_alert_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.build_field_timeseries = AsyncMock(
            side_effect=[[_point(10, ndvi=0.3)], [_point(10, ndvi=0.55)]]
        )
        service = _service(satellite_repository, index_timeseries_repository, farm_alert_repository, fake_ee_client)

        await service.build_timeseries(farm)
        series = await service.build_timeseries(farm)

        assert len(series) == 1
        assert series[0].ndvi_mean == 0.55

    async def test_wraps_not_configured_error(
        self,
        satellite_repository,
        index_timeseries_repository,
        farm_alert_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.build_field_timeseries = AsyncMock(
            side_effect=EarthEngineNotConfiguredError("GEE_PROJECT_ID is not set.")
        )
        service = _service(satellite_repository, index_timeseries_repository, farm_alert_repository, fake_ee_client)

        with pytest.raises(SatelliteAnalysisError):
            await service.build_timeseries(farm)


class TestAlertRules:
    async def test_no_alerts_for_a_healthy_stable_series(
        self,
        satellite_repository,
        index_timeseries_repository,
        farm_alert_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, crop="Wheat")
        # Both points close to their benchmark, no big drop, NDWI positive.
        fake_ee_client = MagicMock()
        fake_ee_client.build_field_timeseries = AsyncMock(
            return_value=[_point(55, ndvi=0.63, ndwi=0.3), _point(60, ndvi=0.62, ndwi=0.3)]
        )
        service = _service(satellite_repository, index_timeseries_repository, farm_alert_repository, fake_ee_client)

        await service.build_timeseries(farm)
        alerts = await service.get_alerts(farm)

        assert alerts == []

    async def test_ndvi_drop_alert_fires_on_a_sharp_relative_decline(
        self,
        satellite_repository,
        index_timeseries_repository,
        farm_alert_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, crop="Wheat")
        # 0.60 -> 0.45 is a 25% relative drop, over NDVI_DROP_RELATIVE_THRESHOLD (0.15).
        fake_ee_client = MagicMock()
        fake_ee_client.build_field_timeseries = AsyncMock(
            return_value=[_point(55, ndvi=0.60, ndwi=0.3), _point(60, ndvi=0.45, ndwi=0.3)]
        )
        service = _service(satellite_repository, index_timeseries_repository, farm_alert_repository, fake_ee_client)

        await service.build_timeseries(farm)
        alerts = await service.get_alerts(farm)

        ndvi_drop_alerts = [a for a in alerts if a.alert_type == "ndvi_drop"]
        assert len(ndvi_drop_alerts) == 1
        assert ndvi_drop_alerts[0].detected_at == SOWING_DATE + timedelta(days=60)
        assert ndvi_drop_alerts[0].severity == "warning"

    async def test_no_ndvi_drop_alert_for_a_small_decline(
        self,
        satellite_repository,
        index_timeseries_repository,
        farm_alert_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, crop="Wheat")
        # 0.60 -> 0.55 is under a 10% relative drop -- must not fire.
        fake_ee_client = MagicMock()
        fake_ee_client.build_field_timeseries = AsyncMock(
            return_value=[_point(55, ndvi=0.60, ndwi=0.3), _point(60, ndvi=0.55, ndwi=0.3)]
        )
        service = _service(satellite_repository, index_timeseries_repository, farm_alert_repository, fake_ee_client)

        await service.build_timeseries(farm)
        alerts = await service.get_alerts(farm)

        assert [a for a in alerts if a.alert_type == "ndvi_drop"] == []

    async def test_below_benchmark_alert_fires_after_two_consecutive_low_passes(
        self,
        satellite_repository,
        index_timeseries_repository,
        farm_alert_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, crop="Wheat")
        # Wheat benchmark at day 50 ~0.60, day 55 = 0.65 -- 0.30 is >0.1 below both.
        fake_ee_client = MagicMock()
        fake_ee_client.build_field_timeseries = AsyncMock(
            return_value=[_point(50, ndvi=0.30, ndwi=0.3), _point(55, ndvi=0.30, ndwi=0.3)]
        )
        service = _service(satellite_repository, index_timeseries_repository, farm_alert_repository, fake_ee_client)

        await service.build_timeseries(farm)
        alerts = await service.get_alerts(farm)

        below_benchmark_alerts = [a for a in alerts if a.alert_type == "below_benchmark"]
        assert len(below_benchmark_alerts) == 1
        assert below_benchmark_alerts[0].severity == "warning"

    async def test_no_below_benchmark_alert_from_a_single_low_pass(
        self,
        satellite_repository,
        index_timeseries_repository,
        farm_alert_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, crop="Wheat")
        # Only the second pass is far below benchmark -- needs TWO consecutive.
        fake_ee_client = MagicMock()
        fake_ee_client.build_field_timeseries = AsyncMock(
            return_value=[_point(50, ndvi=0.60, ndwi=0.3), _point(55, ndvi=0.30, ndwi=0.3)]
        )
        service = _service(satellite_repository, index_timeseries_repository, farm_alert_repository, fake_ee_client)

        await service.build_timeseries(farm)
        alerts = await service.get_alerts(farm)

        assert [a for a in alerts if a.alert_type == "below_benchmark"] == []

    async def test_water_stress_alert_fires_for_negative_ndwi_in_vegetative_stage(
        self,
        satellite_repository,
        index_timeseries_repository,
        farm_alert_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, crop="Wheat")
        # Day 45 is within VEGETATIVE_STAGE_DAYS (20-90); NDWI < 0.
        fake_ee_client = MagicMock()
        fake_ee_client.build_field_timeseries = AsyncMock(return_value=[_point(45, ndvi=0.5, ndwi=-0.05)])
        service = _service(satellite_repository, index_timeseries_repository, farm_alert_repository, fake_ee_client)

        await service.build_timeseries(farm)
        alerts = await service.get_alerts(farm)

        water_stress_alerts = [a for a in alerts if a.alert_type == "water_stress"]
        assert len(water_stress_alerts) == 1
        assert water_stress_alerts[0].severity == "critical"

    async def test_no_water_stress_alert_outside_vegetative_stage(
        self,
        satellite_repository,
        index_timeseries_repository,
        farm_alert_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, crop="Wheat")
        # Day 10 is before VEGETATIVE_STAGE_DAYS starts (20) -- must not fire
        # even though NDWI is negative.
        fake_ee_client = MagicMock()
        fake_ee_client.build_field_timeseries = AsyncMock(return_value=[_point(10, ndvi=0.2, ndwi=-0.05)])
        service = _service(satellite_repository, index_timeseries_repository, farm_alert_repository, fake_ee_client)

        await service.build_timeseries(farm)
        alerts = await service.get_alerts(farm)

        assert [a for a in alerts if a.alert_type == "water_stress"] == []

    async def test_rerunning_build_timeseries_does_not_duplicate_alerts(
        self,
        satellite_repository,
        index_timeseries_repository,
        farm_alert_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, crop="Wheat")
        fake_ee_client = MagicMock()
        fake_ee_client.build_field_timeseries = AsyncMock(
            return_value=[_point(55, ndvi=0.60, ndwi=0.3), _point(60, ndvi=0.45, ndwi=0.3)]
        )
        service = _service(satellite_repository, index_timeseries_repository, farm_alert_repository, fake_ee_client)

        await service.build_timeseries(farm)
        await service.build_timeseries(farm)  # nightly job re-scanning the same window
        alerts = await service.get_alerts(farm)

        assert len([a for a in alerts if a.alert_type == "ndvi_drop"]) == 1


class TestMarkAlertRead:
    async def test_mark_read_flips_the_flag(
        self,
        satellite_repository,
        index_timeseries_repository,
        farm_alert_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, crop="Wheat")
        fake_ee_client = MagicMock()
        fake_ee_client.build_field_timeseries = AsyncMock(
            return_value=[_point(55, ndvi=0.60, ndwi=0.3), _point(60, ndvi=0.45, ndwi=0.3)]
        )
        service = _service(satellite_repository, index_timeseries_repository, farm_alert_repository, fake_ee_client)
        await service.build_timeseries(farm)
        alerts = await service.get_alerts(farm)
        assert alerts[0].is_read is False

        updated = await farm_alert_repository.mark_read(alerts[0])

        assert updated.is_read is True

"""Tests for SatelliteService against a mocked EarthEngineClient -- a real
in-memory SQLite DB (via the `satellite_repository` fixture) but no real
Earth Engine calls."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.earth_engine_client import (
    EarthEngineNotConfiguredError,
    EarthEngineRequestError,
    FieldAnalysisResult,
    IndexStats,
    NoSentinelImageryAvailableError,
)
from app.repositories.farm_repository import FarmRepository
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


def _sample_result(**overrides) -> FieldAnalysisResult:
    defaults = dict(
        image_date=date(2026, 9, 20),
        satellite="S2A",
        cloud_pct=8.3,
        is_fallback=False,
        ndvi=IndexStats(mean=0.65, min=0.10, max=0.90),
        ndwi=IndexStats(mean=-0.20, min=-0.50, max=0.10),
        evi=IndexStats(mean=0.55, min=0.05, max=0.80),
        ndmi=IndexStats(mean=0.30, min=-0.10, max=0.60),
        healthy_pct=72.0,
        moderate_pct=20.0,
        stressed_pct=8.0,
    )
    defaults.update(overrides)
    return FieldAnalysisResult(**defaults)


async def _user_with_profile(user_repository: UserRepository):
    user = await user_repository.create(email="farmer@example.com", hashed_password="x")
    return await user_repository.update_profile(user, phone="9876543210", state="Maharashtra")


async def _create_farm(farm_service: FarmService, user, *, sowing_date=date(2026, 6, 10)):
    return await farm_service.create_farm(
        user,
        name="North Onion Field",
        crop="Onion",
        variety="Bhima Super",
        sowing_date=sowing_date,
        irrigation_method="Drip",
        polygon_geojson=VALID_POLYGON,
        state="Maharashtra",
        district="Nashik",
        address="Village road",
    )


@pytest.fixture
def user_repository(session):
    return UserRepository(session)


@pytest.fixture
def farm_service(farm_repository: FarmRepository) -> FarmService:
    return FarmService(farm_repository)


class TestGetLatest:
    async def test_returns_none_when_nothing_cached_yet(
        self, satellite_repository: SatelliteRepository, farm_service: FarmService, user_repository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        service = SatelliteService(satellite_repository, fake_ee_client)

        observation = await service.get_latest(farm)

        assert observation is None
        fake_ee_client.analyze_field.assert_not_called()

    async def test_does_not_touch_earth_engine(
        self, satellite_repository: SatelliteRepository, farm_service: FarmService, user_repository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.analyze_field = AsyncMock(side_effect=AssertionError("must not be called"))
        service = SatelliteService(satellite_repository, fake_ee_client)

        await service.get_latest(farm)  # must not raise


class TestRefreshAnalysis:
    async def test_stores_observation_from_earth_engine_result(
        self, satellite_repository: SatelliteRepository, farm_service: FarmService, user_repository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, sowing_date=date(2026, 9, 1))  # 19 days before image_date
        fake_ee_client = MagicMock()
        fake_ee_client.analyze_field = AsyncMock(return_value=_sample_result())
        service = SatelliteService(satellite_repository, fake_ee_client)

        observation = await service.refresh_analysis(farm)

        fake_ee_client.analyze_field.assert_awaited_once_with(farm.polygon_geojson)
        assert observation.farm_id == farm.id
        assert observation.image_date == date(2026, 9, 20)
        assert observation.satellite == "S2A"
        assert observation.cloud_pct == 8.3
        assert observation.is_fallback is False
        assert observation.ndvi_mean == 0.65
        assert observation.ndvi_min == 0.10
        assert observation.ndvi_max == 0.90
        assert observation.stressed_pct == 8.0
        assert observation.source == "Sentinel-2 via Earth Engine"
        # health_score is derived, not passed through verbatim -- just sanity-check
        # the range here; app/core/satellite_health.py's own tests cover the maths.
        assert 0.0 <= observation.health_score <= 100.0

    async def test_get_latest_returns_the_most_recently_refreshed_observation(
        self, satellite_repository: SatelliteRepository, farm_service: FarmService, user_repository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.analyze_field = AsyncMock(
            side_effect=[
                _sample_result(image_date=date(2026, 9, 1), ndvi=IndexStats(mean=0.3, min=0.0, max=0.5)),
                _sample_result(image_date=date(2026, 9, 20), ndvi=IndexStats(mean=0.7, min=0.2, max=0.9)),
            ]
        )
        service = SatelliteService(satellite_repository, fake_ee_client)

        await service.refresh_analysis(farm)
        await service.refresh_analysis(farm)
        latest = await service.get_latest(farm)

        assert latest is not None
        assert latest.image_date == date(2026, 9, 20)
        assert latest.ndvi_mean == 0.7

    async def test_wraps_not_configured_error_as_satellite_analysis_error(
        self, satellite_repository: SatelliteRepository, farm_service: FarmService, user_repository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.analyze_field = AsyncMock(
            side_effect=EarthEngineNotConfiguredError("GEE_PROJECT_ID is not set.")
        )
        service = SatelliteService(satellite_repository, fake_ee_client)

        with pytest.raises(SatelliteAnalysisError):
            await service.refresh_analysis(farm)

    async def test_concurrent_refreshes_for_one_farm_share_a_single_earth_engine_run(
        self, satellite_repository: SatelliteRepository, farm_service: FarmService, user_repository
    ) -> None:
        # e.g. the post-create background refresh + the UI's first analysis
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)

        async def slow_analysis(_polygon):
            await asyncio.sleep(0.05)  # long enough for the second caller to arrive mid-run
            return _sample_result()

        fake_ee_client = MagicMock()
        fake_ee_client.analyze_field = AsyncMock(side_effect=slow_analysis)
        service = SatelliteService(satellite_repository, fake_ee_client)

        first, second = await asyncio.gather(service.refresh_analysis(farm), service.refresh_analysis(farm))

        assert fake_ee_client.analyze_field.await_count == 1
        assert first.id == second.id

    async def test_sequential_refreshes_each_run_a_new_analysis(
        self, satellite_repository: SatelliteRepository, farm_service: FarmService, user_repository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.analyze_field = AsyncMock(return_value=_sample_result())
        service = SatelliteService(satellite_repository, fake_ee_client)

        first = await service.refresh_analysis(farm)
        second = await service.refresh_analysis(farm)

        assert fake_ee_client.analyze_field.await_count == 2
        assert first.id != second.id

    async def test_wraps_earth_engine_request_error_as_satellite_analysis_error(
        self, satellite_repository: SatelliteRepository, farm_service: FarmService, user_repository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.analyze_field = AsyncMock(
            side_effect=EarthEngineRequestError("Earth Engine request failed: quota exceeded")
        )
        service = SatelliteService(satellite_repository, fake_ee_client)

        with pytest.raises(SatelliteAnalysisError, match="quota exceeded"):
            await service.refresh_analysis(farm)

    async def test_wraps_no_imagery_error_as_satellite_analysis_error(
        self, satellite_repository: SatelliteRepository, farm_service: FarmService, user_repository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.analyze_field = AsyncMock(
            side_effect=NoSentinelImageryAvailableError("No Sentinel-2 imagery found.")
        )
        service = SatelliteService(satellite_repository, fake_ee_client)

        with pytest.raises(SatelliteAnalysisError):
            await service.refresh_analysis(farm)

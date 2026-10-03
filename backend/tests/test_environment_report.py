"""Tests for SatelliteService.refresh_environment and get_environment against a mocked
EarthEngineClient and a real in-memory SQLite DB."""

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.earth_engine_client import (
    EarthEngineNotConfiguredError,
    EnvironmentDynamics,
    RainfallSummary,
    SoilMoistureSummary,
    SoilProperties,
    TemperatureSummary,
)
from app.models.environment_snapshot import EnvironmentSnapshot
from app.repositories.environment_snapshot_repository import EnvironmentSnapshotRepository
from app.repositories.farm_repository import FarmRepository
from app.repositories.satellite_repository import SatelliteRepository
from app.repositories.user_repository import UserRepository
from app.routers.satellite import _soil_response
from app.schemas.farm import SoilReportIn
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


def _dynamics(**overrides) -> EnvironmentDynamics:
    defaults = dict(
        rainfall=RainfallSummary(mm_7d=10.0, mm_30d=40.0, mm_90d=120.0, mm_since_sowing=200.0, as_of=date(2026, 9, 15)),
        temperature=TemperatureSummary(mean_lst_c=32.0, hot_periods_60d=1, as_of=date(2026, 9, 14)),
        soil_moisture=SoilMoistureSummary(surface_moisture=0.22, as_of=date(2026, 8, 1)),
    )
    defaults.update(overrides)
    return EnvironmentDynamics(**defaults)


def _soil(**overrides) -> SoilProperties:
    defaults = dict(ph=7.4, organic_carbon_g_per_kg=10.0, texture_class="Sandy Loam")
    defaults.update(overrides)
    return SoilProperties(**defaults)


async def _user_with_profile(user_repository: UserRepository):
    user = await user_repository.create(email="farmer@example.com", hashed_password="x")
    return await user_repository.update_profile(user, phone="9876543210", state="Maharashtra")


async def _create_farm(farm_service: FarmService, user, *, sowing_date=date(2026, 6, 10), soil_report=None):
    return await farm_service.create_farm(
        user,
        name="North Onion Field",
        crop="Onion",
        variety=None,
        sowing_date=sowing_date,
        irrigation_method="Drip",
        polygon_geojson=VALID_POLYGON,
        state="Maharashtra",
        district="Nashik",
        address="Village road",
        soil_report=soil_report,
    )


def _service(satellite_repository, environment_snapshot_repository, fake_ee_client) -> SatelliteService:
    return SatelliteService(
        satellite_repository, fake_ee_client, environment_snapshot_repository=environment_snapshot_repository
    )


@pytest.fixture
def user_repository(session):
    return UserRepository(session)


@pytest.fixture
def farm_service(farm_repository: FarmRepository) -> FarmService:
    return FarmService(farm_repository)


class TestEnvironmentReport:
    async def test_first_call_fetches_and_stores_dynamics_and_soil(
        self,
        satellite_repository: SatelliteRepository,
        environment_snapshot_repository: EnvironmentSnapshotRepository,
        farm_service: FarmService,
        user_repository: UserRepository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.get_environment_dynamics = AsyncMock(return_value=_dynamics())
        fake_ee_client.get_soil_properties = AsyncMock(return_value=_soil())
        service = _service(satellite_repository, environment_snapshot_repository, fake_ee_client)

        snapshot = await service.refresh_environment(farm)

        assert snapshot.rainfall_7d_mm == 10.0
        assert snapshot.rainfall_since_sowing_mm == 200.0
        assert snapshot.mean_lst_c == 32.0
        assert snapshot.hot_periods_60d == 1
        assert snapshot.soil_moisture == 0.22
        assert snapshot.soil_ph == 7.4
        assert snapshot.soil_organic_carbon_g_per_kg == 10.0
        assert snapshot.soil_texture_class == "Sandy Loam"
        assert snapshot.soil_fetched_at is not None
        fake_ee_client.get_soil_properties.assert_awaited_once()

    async def test_second_call_reuses_soil_but_refreshes_dynamics(
        self,
        satellite_repository: SatelliteRepository,
        environment_snapshot_repository: EnvironmentSnapshotRepository,
        farm_service: FarmService,
        user_repository: UserRepository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.get_environment_dynamics = AsyncMock(return_value=_dynamics())
        fake_ee_client.get_soil_properties = AsyncMock(return_value=_soil())
        service = _service(satellite_repository, environment_snapshot_repository, fake_ee_client)

        await service.refresh_environment(farm)

        # Rainfall changed since the first call -- simulates a real day-to-day refresh.
        fake_ee_client.get_environment_dynamics = AsyncMock(
            return_value=_dynamics(
                rainfall=RainfallSummary(
                    mm_7d=25.0, mm_30d=60.0, mm_90d=150.0, mm_since_sowing=220.0, as_of=date(2026, 9, 16)
                )
            )
        )
        snapshot = await service.refresh_environment(farm)

        assert snapshot.rainfall_7d_mm == 25.0
        assert snapshot.rainfall_as_of == date(2026, 9, 16)
        # Soil values are untouched from the first call -- reused, not overwritten.
        assert snapshot.soil_ph == 7.4
        assert snapshot.soil_texture_class == "Sandy Loam"
        fake_ee_client.get_soil_properties.assert_awaited_once()  # never called a 2nd time

    async def test_wraps_not_configured_error_from_dynamics(
        self,
        satellite_repository: SatelliteRepository,
        environment_snapshot_repository: EnvironmentSnapshotRepository,
        farm_service: FarmService,
        user_repository: UserRepository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.get_environment_dynamics = AsyncMock(
            side_effect=EarthEngineNotConfiguredError("not configured")
        )
        service = _service(satellite_repository, environment_snapshot_repository, fake_ee_client)

        with pytest.raises(SatelliteAnalysisError):
            await service.refresh_environment(farm)

    async def test_skips_openlandmap_fetch_when_farm_has_a_soil_report(
        self,
        satellite_repository: SatelliteRepository,
        environment_snapshot_repository: EnvironmentSnapshotRepository,
        farm_service: FarmService,
        user_repository: UserRepository,
    ) -> None:
        """The farmer's lab report is authoritative -- an OpenLandMap
        estimate would just be overridden in the response anyway (see
        _soil_response), so it's never worth spending the Earth Engine call."""
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user, soil_report=SoilReportIn(ph=6.5, nitrogen="High"))
        fake_ee_client = MagicMock()
        fake_ee_client.get_environment_dynamics = AsyncMock(return_value=_dynamics())
        fake_ee_client.get_soil_properties = AsyncMock(return_value=_soil())
        service = _service(satellite_repository, environment_snapshot_repository, fake_ee_client)

        snapshot = await service.refresh_environment(farm)

        fake_ee_client.get_soil_properties.assert_not_called()
        assert snapshot.soil_fetched_at is None
        assert snapshot.soil_ph is None

    async def test_wraps_not_configured_error_from_soil(
        self,
        satellite_repository: SatelliteRepository,
        environment_snapshot_repository: EnvironmentSnapshotRepository,
        farm_service: FarmService,
        user_repository: UserRepository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.get_environment_dynamics = AsyncMock(return_value=_dynamics())
        fake_ee_client.get_soil_properties = AsyncMock(
            side_effect=EarthEngineNotConfiguredError("not configured")
        )
        service = _service(satellite_repository, environment_snapshot_repository, fake_ee_client)

        with pytest.raises(SatelliteAnalysisError):
            await service.refresh_environment(farm)


class TestGetEnvironment:
    """get_environment is the cache-only read GET /farms/{id}/environment
    actually uses -- it never touches Earth Engine. refresh_environment is
    what the nightly scheduler job calls to populate it."""

    async def test_returns_none_when_never_refreshed(
        self,
        satellite_repository: SatelliteRepository,
        environment_snapshot_repository: EnvironmentSnapshotRepository,
        farm_service: FarmService,
        user_repository: UserRepository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        service = _service(satellite_repository, environment_snapshot_repository, fake_ee_client)

        result = await service.get_environment(farm)

        assert result is None
        fake_ee_client.get_environment_dynamics.assert_not_called()
        fake_ee_client.get_soil_properties.assert_not_called()

    async def test_returns_cached_snapshot_without_touching_earth_engine(
        self,
        satellite_repository: SatelliteRepository,
        environment_snapshot_repository: EnvironmentSnapshotRepository,
        farm_service: FarmService,
        user_repository: UserRepository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.get_environment_dynamics = AsyncMock(return_value=_dynamics())
        fake_ee_client.get_soil_properties = AsyncMock(return_value=_soil())
        service = _service(satellite_repository, environment_snapshot_repository, fake_ee_client)
        await service.refresh_environment(farm)

        # A fresh EE mock with no methods configured -- get_environment must
        # never call it, or this test would error on the first call.
        service_read_only = _service(satellite_repository, environment_snapshot_repository, MagicMock())
        result = await service_read_only.get_environment(farm)

        assert result is not None
        assert result.rainfall_7d_mm == 10.0
        assert result.soil_ph == 7.4


def _snapshot(**overrides) -> EnvironmentSnapshot:
    defaults = dict(
        soil_ph=6.9,
        soil_organic_carbon_g_per_kg=12.0,
        soil_texture_class="Clay Loam",
        soil_fetched_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return EnvironmentSnapshot(**defaults)


class TestSoilResponseMerge:
    """_soil_response (app/routers/satellite.py) is what GET /farms/{id}/environment
    uses to decide, per farm, whether the soil section shows the farmer's own
    Soil Health Card / lab report or the OpenLandMap estimate."""

    async def test_uses_openlandmap_when_no_soil_report(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        snapshot = _snapshot()

        soil = _soil_response(farm, snapshot)

        assert soil.is_lab_report is False
        assert soil.ph == 6.9
        assert soil.nitrogen is None
        assert soil.provenance.source == "OpenLandMap soil layers"

    async def test_lab_report_overrides_openlandmap_ph_and_adds_npk(
        self, farm_service: FarmService, user_repository: UserRepository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(
            farm_service,
            user,
            soil_report=SoilReportIn(ph=6.5, nitrogen="High", phosphorus="Low", potassium="Medium", organic_matter_pct=2.4),
        )
        # Even if an OpenLandMap estimate happens to exist on the snapshot
        # (e.g. from before the report was added), the lab report wins.
        snapshot = _snapshot(soil_ph=7.8)

        soil = _soil_response(farm, snapshot)

        assert soil.is_lab_report is True
        assert soil.ph == 6.5  # the farmer's value, not the snapshot's 7.8
        assert soil.nitrogen == "High"
        assert soil.phosphorus == "Low"
        assert soil.potassium == "Medium"
        assert soil.organic_matter_pct == 2.4
        assert soil.provenance.source == "Farmer-submitted Soil Health Card / Lab Test Report"

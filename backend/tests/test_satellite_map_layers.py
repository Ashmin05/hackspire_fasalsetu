"""Tests for SatelliteService.get_or_build_layers against a mocked
EarthEngineClient and a real in-memory SQLite DB."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.earth_engine_client import (
    EarthEngineNotConfiguredError,
    FieldAnalysisResult,
    FieldMapLayers,
    IndexStats,
    StressZoneResult,
)
from app.repositories.farm_repository import FarmRepository
from app.repositories.satellite_layer_repository import SatelliteLayerRepository
from app.repositories.satellite_repository import SatelliteRepository
from app.repositories.stress_zone_repository import StressZoneRepository
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


def _sample_layers(**overrides) -> FieldMapLayers:
    defaults = dict(
        image_date=date(2026, 9, 15),
        true_color_tile_url="https://tile/true_color/{z}/{x}/{y}",
        ndvi_tile_url="https://tile/ndvi/{z}/{x}/{y}",
        ndwi_tile_url="https://tile/ndwi/{z}/{x}/{y}",
        evi_tile_url="https://tile/evi/{z}/{x}/{y}",
        stress_tile_url="https://tile/stress/{z}/{x}/{y}",
        stress_zones=[
            StressZoneResult(
                zone_type="water_stress",
                area_ha=0.05,
                geometry_geojson={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
                suggested_action="Increase irrigation frequency in this zone.",
            )
        ],
    )
    defaults.update(overrides)
    return FieldMapLayers(**defaults)


def _sample_observation(**overrides) -> FieldAnalysisResult:
    defaults = dict(
        image_date=date(2026, 9, 15),
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
        variety=None,
        sowing_date=sowing_date,
        irrigation_method="Drip",
        polygon_geojson=VALID_POLYGON,
        state="Maharashtra",
        district="Nashik",
        address="Village road",
    )


def _service(
    satellite_repository: SatelliteRepository,
    satellite_layer_repository: SatelliteLayerRepository,
    stress_zone_repository: StressZoneRepository,
    fake_ee_client,
) -> SatelliteService:
    return SatelliteService(
        satellite_repository,
        fake_ee_client,
        satellite_layer_repository=satellite_layer_repository,
        stress_zone_repository=stress_zone_repository,
    )


@pytest.fixture
def user_repository(session):
    return UserRepository(session)


@pytest.fixture
def farm_service(farm_repository: FarmRepository) -> FarmService:
    return FarmService(farm_repository)


class TestGetOrBuildLayers:
    async def test_builds_and_stores_layers_and_zones(
        self,
        satellite_repository,
        satellite_layer_repository,
        stress_zone_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.get_field_map_layers = AsyncMock(return_value=_sample_layers())
        service = _service(satellite_repository, satellite_layer_repository, stress_zone_repository, fake_ee_client)

        layer_set, zones = await service.get_or_build_layers(farm, date(2026, 9, 15))

        fake_ee_client.get_field_map_layers.assert_awaited_once_with(farm.polygon_geojson, date(2026, 9, 15))
        assert layer_set.farm_id == farm.id
        assert layer_set.image_date == date(2026, 9, 15)
        assert layer_set.ndvi_tile_url == "https://tile/ndvi/{z}/{x}/{y}"
        assert len(zones) == 1
        assert zones[0].zone_type == "water_stress"
        assert zones[0].area_ha == 0.05

    async def test_second_call_uses_cache_and_does_not_touch_earth_engine(
        self,
        satellite_repository,
        satellite_layer_repository,
        stress_zone_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.get_field_map_layers = AsyncMock(return_value=_sample_layers())
        service = _service(satellite_repository, satellite_layer_repository, stress_zone_repository, fake_ee_client)

        await service.get_or_build_layers(farm, date(2026, 9, 15))
        await service.get_or_build_layers(farm, date(2026, 9, 15))

        fake_ee_client.get_field_map_layers.assert_awaited_once()

    async def test_expired_cache_triggers_regeneration(
        self,
        satellite_repository,
        satellite_layer_repository,
        stress_zone_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.get_field_map_layers = AsyncMock(return_value=_sample_layers())
        service = _service(satellite_repository, satellite_layer_repository, stress_zone_repository, fake_ee_client)

        await service.get_or_build_layers(farm, date(2026, 9, 15))

        # Simulate the cached row having gone stale by writing an
        # already-past expires_at directly through the repository.
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        await satellite_layer_repository.upsert(
            farm_id=farm.id,
            image_date=date(2026, 9, 15),
            true_color_tile_url="https://tile/true_color/{z}/{x}/{y}",
            ndvi_tile_url="https://tile/ndvi/{z}/{x}/{y}",
            ndwi_tile_url="https://tile/ndwi/{z}/{x}/{y}",
            evi_tile_url="https://tile/evi/{z}/{x}/{y}",
            stress_tile_url="https://tile/stress/{z}/{x}/{y}",
            generated_at=past,
            expires_at=past,
        )

        await service.get_or_build_layers(farm, date(2026, 9, 15))

        assert fake_ee_client.get_field_map_layers.await_count == 2

    async def test_regeneration_replaces_rather_than_accumulates_zones(
        self,
        satellite_repository,
        satellite_layer_repository,
        stress_zone_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.get_field_map_layers = AsyncMock(
            side_effect=[
                _sample_layers(
                    stress_zones=[
                        StressZoneResult(
                            zone_type="water_stress", area_ha=0.05,
                            geometry_geojson={"type": "Polygon", "coordinates": []},
                            suggested_action="a",
                        )
                    ]
                ),
                _sample_layers(
                    stress_zones=[
                        StressZoneResult(
                            zone_type="nutrient_pest_suspected", area_ha=0.08,
                            geometry_geojson={"type": "Polygon", "coordinates": []},
                            suggested_action="b",
                        )
                    ]
                ),
            ]
        )
        service = _service(satellite_repository, satellite_layer_repository, stress_zone_repository, fake_ee_client)

        await service.get_or_build_layers(farm, date(2026, 9, 15))
        # Force a regeneration on the second call by expiring the cache directly.
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        existing = await satellite_layer_repository.get_by_farm_and_date(farm.id, date(2026, 9, 15))
        existing.expires_at = past
        await satellite_layer_repository.session.commit()

        _, zones = await service.get_or_build_layers(farm, date(2026, 9, 15))

        assert len(zones) == 1
        assert zones[0].zone_type == "nutrient_pest_suspected"

    async def test_defaults_to_latest_satellite_observation_date(
        self,
        satellite_repository,
        satellite_layer_repository,
        stress_zone_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        await satellite_repository.create(
            farm_id=farm.id,
            image_date=date(2026, 9, 20),
            satellite="S2A", cloud_pct=5.0, is_fallback=False,
            ndvi_mean=0.6, ndvi_min=0.2, ndvi_max=0.8,
            ndwi_mean=0.1, ndwi_min=-0.1, ndwi_max=0.3,
            evi_mean=0.5, evi_min=0.1, evi_max=0.7,
            ndmi_mean=0.2, ndmi_min=-0.1, ndmi_max=0.4,
            healthy_pct=70.0, moderate_pct=20.0, stressed_pct=10.0,
            health_score=75.0,
        )
        fake_ee_client = MagicMock()
        fake_ee_client.get_field_map_layers = AsyncMock(return_value=_sample_layers(image_date=date(2026, 9, 20)))
        service = _service(satellite_repository, satellite_layer_repository, stress_zone_repository, fake_ee_client)

        layer_set, _ = await service.get_or_build_layers(farm, None)

        fake_ee_client.get_field_map_layers.assert_awaited_once_with(farm.polygon_geojson, date(2026, 9, 20))
        assert layer_set.image_date == date(2026, 9, 20)

    async def test_raises_when_no_date_given_and_no_prior_analysis(
        self,
        satellite_repository,
        satellite_layer_repository,
        stress_zone_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        service = _service(satellite_repository, satellite_layer_repository, stress_zone_repository, fake_ee_client)

        with pytest.raises(SatelliteAnalysisError):
            await service.get_or_build_layers(farm, None)

        fake_ee_client.get_field_map_layers.assert_not_called()

    async def test_wraps_not_configured_error(
        self,
        satellite_repository,
        satellite_layer_repository,
        stress_zone_repository,
        farm_service,
        user_repository,
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_ee_client = MagicMock()
        fake_ee_client.get_field_map_layers = AsyncMock(
            side_effect=EarthEngineNotConfiguredError("GEE_PROJECT_ID is not set.")
        )
        service = _service(satellite_repository, satellite_layer_repository, stress_zone_repository, fake_ee_client)

        with pytest.raises(SatelliteAnalysisError):
            await service.get_or_build_layers(farm, date(2026, 9, 15))

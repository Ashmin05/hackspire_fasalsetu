"""Tests for WeatherService.get_weather against a mocked OpenMeteoClient and
a real in-memory SQLite DB."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.open_meteo_client import DailyForecast, OpenMeteoForecast, OpenMeteoRequestError
from app.repositories.farm_repository import FarmRepository
from app.repositories.user_repository import UserRepository
from app.repositories.weather_cache_repository import WeatherCacheRepository
from app.services.farm_service import FarmService
from app.services.weather_service import WeatherService, WeatherServiceError

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


def _sample_forecast(**overrides) -> OpenMeteoForecast:
    defaults = dict(
        latitude=19.99,
        longitude=73.79,
        timezone="Asia/Kolkata",
        daily=[
            DailyForecast(
                forecast_date=date(2026, 9, 28),
                temp_max_c=34.0,
                temp_min_c=24.0,
                precipitation_sum_mm=2.0,
                precipitation_probability_max_pct=10.0,
                wind_speed_max_kmh=8.0,
                relative_humidity_mean_pct=60.0,
                uv_index_max=7.0,
                et0_fao_evapotranspiration_mm=4.5,
            ),
            DailyForecast(
                forecast_date=date(2026, 9, 29),
                temp_max_c=39.0,
                temp_min_c=27.0,
                precipitation_sum_mm=30.0,
                precipitation_probability_max_pct=80.0,
                wind_speed_max_kmh=20.0,
                relative_humidity_mean_pct=85.0,
                uv_index_max=8.0,
                et0_fao_evapotranspiration_mm=5.0,
            ),
        ],
    )
    defaults.update(overrides)
    return OpenMeteoForecast(**defaults)


async def _user_with_profile(user_repository: UserRepository):
    user = await user_repository.create(email="farmer@example.com", hashed_password="x")
    return await user_repository.update_profile(user, phone="9876543210", state="Maharashtra")


async def _create_farm(farm_service: FarmService, user):
    return await farm_service.create_farm(
        user,
        name="North Onion Field",
        crop="Onion",
        variety=None,
        sowing_date=date(2026, 6, 10),
        irrigation_method="Drip",
        polygon_geojson=VALID_POLYGON,
        state="Maharashtra",
        district="Nashik",
        address="Village road",
    )


def _service(weather_cache_repository: WeatherCacheRepository, fake_client) -> WeatherService:
    return WeatherService(weather_cache_repository, fake_client)


@pytest.fixture
def user_repository(session):
    return UserRepository(session)


@pytest.fixture
def farm_service(farm_repository: FarmRepository) -> FarmService:
    return FarmService(farm_repository)


class TestGetWeather:
    async def test_fetches_and_caches_forecast(
        self, weather_cache_repository, farm_service, user_repository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_client = MagicMock()
        fake_client.get_forecast = AsyncMock(return_value=_sample_forecast())
        service = _service(weather_cache_repository, fake_client)

        response = await service.get_weather(farm)

        fake_client.get_forecast.assert_awaited_once_with(latitude=farm.centroid_lat, longitude=farm.centroid_lng)
        assert response.farm_id == farm.id
        assert len(response.daily) == 2
        assert response.provenance.source == "Open-Meteo"
        assert response.provenance.is_live is True

    async def test_second_call_uses_cache_and_does_not_touch_open_meteo(
        self, weather_cache_repository, farm_service, user_repository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_client = MagicMock()
        fake_client.get_forecast = AsyncMock(return_value=_sample_forecast())
        service = _service(weather_cache_repository, fake_client)

        await service.get_weather(farm)
        await service.get_weather(farm)

        fake_client.get_forecast.assert_awaited_once()

    async def test_expired_cache_triggers_refetch(
        self, weather_cache_repository, farm_service, user_repository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_client = MagicMock()
        fake_client.get_forecast = AsyncMock(return_value=_sample_forecast())
        service = _service(weather_cache_repository, fake_client)

        await service.get_weather(farm)

        # Simulate the cached row having gone stale, the same way
        # test_satellite_map_layers does for SatelliteLayerSet.
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        existing = await weather_cache_repository.get_by_farm(farm.id)
        existing.expires_at = past
        await weather_cache_repository.session.commit()

        await service.get_weather(farm)

        assert fake_client.get_forecast.await_count == 2

    async def test_wraps_open_meteo_errors(
        self, weather_cache_repository, farm_service, user_repository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_client = MagicMock()
        fake_client.get_forecast = AsyncMock(side_effect=OpenMeteoRequestError("boom"))
        service = _service(weather_cache_repository, fake_client)

        with pytest.raises(WeatherServiceError):
            await service.get_weather(farm)

    async def test_derives_flags_per_day(
        self, weather_cache_repository, farm_service, user_repository
    ) -> None:
        user = await _user_with_profile(user_repository)
        farm = await _create_farm(farm_service, user)
        fake_client = MagicMock()
        fake_client.get_forecast = AsyncMock(return_value=_sample_forecast())
        service = _service(weather_cache_repository, fake_client)

        response = await service.get_weather(farm)

        calm_day, extreme_day = response.daily
        # Day 1: 2mm rain, 34C, 10% rain chance / 8 km/h wind -- nothing flagged, good spray window.
        assert calm_day.flags.heavy_rain is False
        assert calm_day.flags.heat_stress is False
        assert calm_day.flags.good_spray_window is True

        # Day 2: 30mm rain, 39C, 80% rain chance / 20 km/h wind -- everything flagged, no spray window.
        assert extreme_day.flags.heavy_rain is True
        assert extreme_day.flags.heat_stress is True
        assert extreme_day.flags.good_spray_window is False

import uuid
from datetime import datetime, timedelta, timezone

from app.integrations.open_meteo_client import (
    WEATHER_CACHE_HOURS,
    DailyForecast,
    OpenMeteoClient,
    OpenMeteoError,
)
from app.models.farm import Farm
from app.models.weather_cache import WeatherCache
from app.repositories.weather_cache_repository import WeatherCacheRepository
from app.schemas.weather import DailyWeatherResponse, FarmWeatherResponse, WeatherFlags, WeatherProvenance

# Flag thresholds (see WeatherFlags) -- rough farming-decision heuristics,
# not measured for any specific crop.
HEAVY_RAIN_THRESHOLD_MM = 25.0
HEAT_STRESS_THRESHOLD_C = 38.0
GOOD_SPRAY_MAX_RAIN_PROBABILITY_PCT = 20.0
GOOD_SPRAY_MAX_WIND_KMH = 15.0


class WeatherServiceError(Exception):
    """Raised when the Open-Meteo forecast can't be fetched. Safe to return
    to the client as a 503 (see router)."""


class WeatherService:
    def __init__(self, weather_cache_repository: WeatherCacheRepository, open_meteo_client: OpenMeteoClient) -> None:
        self.weather_cache_repository = weather_cache_repository
        self.open_meteo_client = open_meteo_client

    async def get_weather(self, farm: Farm) -> FarmWeatherResponse:
        """Returns `farm`'s daily forecast, reusing the cached Open-Meteo
        call when it's under WEATHER_CACHE_HOURS old and fetching live
        otherwise. Unlike satellite analysis this never needs a separate
        refresh step -- Open-Meteo is free and fast, so a single GET can
        always serve fresh-enough data."""
        now = datetime.now(timezone.utc)
        existing = await self.weather_cache_repository.get_by_farm(farm.id)
        # SQLite (the test suite) drops tzinfo on read -- the stored value
        # is still UTC (same gotcha as SatelliteService.get_or_build_layers).
        expires_at = existing.expires_at if existing is not None else None
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if existing is not None and expires_at > now:
            cache = existing
        else:
            try:
                forecast = await self.open_meteo_client.get_forecast(
                    latitude=farm.centroid_lat, longitude=farm.centroid_lng
                )
            except OpenMeteoError as exc:
                raise WeatherServiceError(str(exc)) from exc

            cache = await self.weather_cache_repository.upsert(
                farm_id=farm.id,
                daily=[_day_to_dict(day) for day in forecast.daily],
                generated_at=now,
                expires_at=now + timedelta(hours=WEATHER_CACHE_HOURS),
            )

        return _cache_to_response(farm.id, cache)


def _day_to_dict(day: DailyForecast) -> dict:
    return {
        "date": day.forecast_date.isoformat(),
        "temp_max_c": day.temp_max_c,
        "temp_min_c": day.temp_min_c,
        "precipitation_sum_mm": day.precipitation_sum_mm,
        "precipitation_probability_max_pct": day.precipitation_probability_max_pct,
        "wind_speed_max_kmh": day.wind_speed_max_kmh,
        "relative_humidity_mean_pct": day.relative_humidity_mean_pct,
        "uv_index_max": day.uv_index_max,
        "et0_fao_evapotranspiration_mm": day.et0_fao_evapotranspiration_mm,
    }


def _day_response(day: dict) -> DailyWeatherResponse:
    temp_max = day["temp_max_c"]
    precip_sum = day["precipitation_sum_mm"]
    precip_prob = day.get("precipitation_probability_max_pct")
    wind_max = day["wind_speed_max_kmh"]

    return DailyWeatherResponse(
        date=day["date"],
        temp_max_c=temp_max,
        temp_min_c=day["temp_min_c"],
        precipitation_sum_mm=precip_sum,
        precipitation_probability_pct=precip_prob,
        wind_speed_max_kmh=wind_max,
        relative_humidity_pct=day.get("relative_humidity_mean_pct"),
        uv_index_max=day.get("uv_index_max"),
        et0_fao_evapotranspiration_mm=day.get("et0_fao_evapotranspiration_mm"),
        flags=WeatherFlags(
            heavy_rain=precip_sum > HEAVY_RAIN_THRESHOLD_MM,
            heat_stress=temp_max > HEAT_STRESS_THRESHOLD_C,
            good_spray_window=(
                precip_prob is not None
                and precip_prob < GOOD_SPRAY_MAX_RAIN_PROBABILITY_PCT
                and wind_max < GOOD_SPRAY_MAX_WIND_KMH
            ),
        ),
    )


def _cache_to_response(farm_id: uuid.UUID, cache: WeatherCache) -> FarmWeatherResponse:
    generated_at = cache.generated_at
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    return FarmWeatherResponse(
        farm_id=farm_id,
        daily=[_day_response(day) for day in cache.daily],
        provenance=WeatherProvenance(source="Open-Meteo", is_live=True, fetched_at=generated_at),
    )

"""Open-Meteo forecast client -- free, key-free weather API.

api.open-meteo.com/v1/forecast, no auth required. Provides the daily
forecast fields WeatherService needs to build a farm's weather report:
temperature max/min, precipitation sum/probability, wind speed, relative
humidity, UV index and reference evapotranspiration (ET0), anchored to
Asia/Kolkata local days (see TIMEZONE).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
from tenacity import AsyncRetrying, RetryError, retry_if_exception, stop_after_attempt, wait_exponential
from tenacity.wait import wait_base

logger = logging.getLogger(__name__)

# Open-Meteo doesn't reject generic user agents the way Agmarknet does, but
# identify ourselves honestly anyway.
USER_AGENT = "FasalSetu/0.1 (agricultural decision-support app)"
BASE_URL = "https://api.open-meteo.com/v1/forecast"
# Open-Meteo's reanalysis archive (ERA5-Land-derived) -- separate endpoint,
# same no-key philosophy. Used by IrrigationService (app/services/
# irrigation_service.py) for historical ET0 to roll its water balance
# forward day by day; get_forecast only ever looks ahead.
HISTORICAL_BASE_URL = "https://archive-api.open-meteo.com/v1/archive"
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_WAIT = wait_exponential(multiplier=2, min=2, max=30)

# Matches FarmDetailedWeather.forecast10Days on the frontend.
FORECAST_DAYS = 10
# Cached farm weather is treated as stale after this long (see WeatherService).
WEATHER_CACHE_HOURS = 3
# Farm weather is always reported in the farm's own local day, not UTC.
TIMEZONE = "Asia/Kolkata"

DAILY_PARAMS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_speed_10m_max",
    "relative_humidity_2m_mean",
    "uv_index_max",
    "et0_fao_evapotranspiration",
]

# The archive endpoint has no probability/humidity/UV reanalysis fields --
# only what IrrigationService actually needs (ET0 to drive the water
# balance, precipitation as a fallback rain source when CHIRPS isn't
# configured/reachable -- see IrrigationService._historical_days).
HISTORICAL_DAILY_PARAMS = ["precipitation_sum", "et0_fao_evapotranspiration"]
# The archive's near-real-time data lags a few days behind "today" -- a
# request for very recent days can come back with nulls for them.
# IrrigationService treats the first missing day as where history ends
# rather than guessing, so this cap just bounds the request itself.
HISTORICAL_MAX_RANGE_DAYS = 200


class OpenMeteoError(Exception):
    """Base class for Open-Meteo client errors."""


class OpenMeteoRequestError(OpenMeteoError):
    """Raised when the request fails after retries, Open-Meteo rejects it
    (bad params), or the response isn't the JSON forecast body expected.
    Callers turn this into a clean 503 instead of an unhandled 500."""


@dataclass
class DailyForecast:
    """One local day's forecast for a farm's centroid."""

    forecast_date: date
    temp_max_c: float
    temp_min_c: float
    precipitation_sum_mm: float
    precipitation_probability_max_pct: float | None
    wind_speed_max_kmh: float
    relative_humidity_mean_pct: float | None
    uv_index_max: float | None
    et0_fao_evapotranspiration_mm: float | None


@dataclass
class OpenMeteoForecast:
    """Result of OpenMeteoClient.get_forecast -- WeatherService maps this
    into the response shape the frontend expects (see app/schemas/weather.py)."""

    latitude: float
    longitude: float
    timezone: str
    daily: list[DailyForecast]


@dataclass
class HistoricalDay:
    """One past local day's reanalysis ET0/precipitation, from
    OpenMeteoClient.get_historical -- either value can be None if the
    archive hasn't backfilled that day yet (see HISTORICAL_MAX_RANGE_DAYS)."""

    day: date
    et0_mm: float | None
    precipitation_mm: float | None


def _is_retryable(exc: BaseException) -> bool:
    """Network errors, timeouts, 429 and 5xx are worth retrying; any other
    4xx (bad lat/lon) will fail the same way every time."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


class OpenMeteoClient:
    """Async client for Open-Meteo's forecast endpoint. Needs no API key --
    unlike EarthEngineClient or the market-price providers, there's no
    `configured` gate; the client is always usable."""

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        wait: wait_base = DEFAULT_WAIT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.max_attempts = max_attempts
        self.wait = wait
        self._client = client or httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_forecast(
        self, *, latitude: float, longitude: float, forecast_days: int = FORECAST_DAYS
    ) -> OpenMeteoForecast:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": ",".join(DAILY_PARAMS),
            "timezone": TIMEZONE,
            "forecast_days": forecast_days,
        }
        body = await self._fetch(self.base_url, params)
        return _parse_forecast(body)

    async def get_historical(
        self, *, latitude: float, longitude: float, start_date: date, end_date: date
    ) -> list[HistoricalDay]:
        """Past local days' ET0/precipitation from Open-Meteo's reanalysis
        archive, `start_date`..`end_date` inclusive -- see IrrigationService's
        catch-up roll-forward. Returns [] for an empty/inverted range rather
        than making a pointless request."""
        if start_date > end_date:
            return []
        end_date = min(end_date, start_date + timedelta(days=HISTORICAL_MAX_RANGE_DAYS))

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": ",".join(HISTORICAL_DAILY_PARAMS),
            "timezone": TIMEZONE,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        body = await self._fetch(HISTORICAL_BASE_URL, params)
        return _parse_historical(body)

    async def _fetch(self, url: str, params: dict) -> dict:
        async def attempt() -> httpx.Response:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response

        try:
            response = None
            async for try_ in AsyncRetrying(
                retry=retry_if_exception(_is_retryable),
                stop=stop_after_attempt(self.max_attempts),
                wait=self.wait,
                reraise=False,
            ):
                with try_:
                    response = await attempt()
        except RetryError as exc:
            last = exc.last_attempt.exception()
            raise OpenMeteoRequestError(
                f"Open-Meteo request failed after {self.max_attempts} attempts: {last}"
            ) from last
        except httpx.HTTPStatusError as exc:
            raise OpenMeteoRequestError(
                f"Open-Meteo rejected the request (HTTP {exc.response.status_code})"
            ) from exc

        assert response is not None
        try:
            return response.json()
        except ValueError as exc:
            raise OpenMeteoRequestError(
                f"Open-Meteo returned a non-JSON response (HTTP {response.status_code})"
            ) from exc


def _parse_forecast(body: dict) -> OpenMeteoForecast:
    daily = body.get("daily")
    if not isinstance(daily, dict):
        raise OpenMeteoRequestError("Open-Meteo response is missing the 'daily' block")

    try:
        dates = daily["time"]
        temp_max = daily["temperature_2m_max"]
        temp_min = daily["temperature_2m_min"]
        precip_sum = daily["precipitation_sum"]
        wind_max = daily["wind_speed_10m_max"]
    except KeyError as exc:
        raise OpenMeteoRequestError(f"Open-Meteo response is missing expected field {exc}") from exc

    # Fields that don't fail the whole request when Open-Meteo omits them.
    precip_prob = daily.get("precipitation_probability_max") or [None] * len(dates)
    humidity = daily.get("relative_humidity_2m_mean") or [None] * len(dates)
    uv_index = daily.get("uv_index_max") or [None] * len(dates)
    et0 = daily.get("et0_fao_evapotranspiration") or [None] * len(dates)

    days = [
        DailyForecast(
            forecast_date=date.fromisoformat(dates[i]),
            temp_max_c=temp_max[i],
            temp_min_c=temp_min[i],
            precipitation_sum_mm=precip_sum[i] or 0.0,
            precipitation_probability_max_pct=precip_prob[i],
            wind_speed_max_kmh=wind_max[i],
            relative_humidity_mean_pct=humidity[i],
            uv_index_max=uv_index[i],
            et0_fao_evapotranspiration_mm=et0[i],
        )
        for i in range(len(dates))
    ]

    return OpenMeteoForecast(
        latitude=body.get("latitude", 0.0),
        longitude=body.get("longitude", 0.0),
        timezone=body.get("timezone", TIMEZONE),
        daily=days,
    )


def _parse_historical(body: dict) -> list[HistoricalDay]:
    daily = body.get("daily")
    if not isinstance(daily, dict):
        raise OpenMeteoRequestError("Open-Meteo archive response is missing the 'daily' block")

    dates = daily.get("time")
    if not dates:
        return []

    precip = daily.get("precipitation_sum") or [None] * len(dates)
    et0 = daily.get("et0_fao_evapotranspiration") or [None] * len(dates)

    return [
        HistoricalDay(
            day=date.fromisoformat(dates[i]),
            et0_mm=et0[i],
            precipitation_mm=precip[i],
        )
        for i in range(len(dates))
    ]


# Module-level singleton, same pattern as earth_engine_client -- Open-Meteo
# needs no config/credentials, so there's no lazy _build_client() step.
open_meteo_client = OpenMeteoClient()

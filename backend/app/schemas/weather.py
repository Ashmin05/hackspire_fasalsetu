import uuid
from datetime import date, datetime

from pydantic import BaseModel


class WeatherFlags(BaseModel):
    """Farming-relevant thresholds derived from one day's forecast -- see
    app/services/weather_service.py for the threshold constants."""

    heavy_rain: bool
    heat_stress: bool
    good_spray_window: bool


class DailyWeatherResponse(BaseModel):
    date: date
    temp_max_c: float
    temp_min_c: float
    precipitation_sum_mm: float
    precipitation_probability_pct: float | None
    wind_speed_max_kmh: float
    relative_humidity_pct: float | None
    uv_index_max: float | None
    et0_fao_evapotranspiration_mm: float | None
    flags: WeatherFlags


class WeatherProvenance(BaseModel):
    source: str
    is_live: bool
    fetched_at: datetime


class FarmWeatherResponse(BaseModel):
    farm_id: uuid.UUID
    daily: list[DailyWeatherResponse]
    provenance: WeatherProvenance

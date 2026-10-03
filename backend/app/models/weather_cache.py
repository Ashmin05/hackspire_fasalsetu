import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# JSONB on Postgres (indexable, efficient); falls back to plain JSON on any
# other dialect -- same as Farm.polygon_geojson, needed for the SQLite test
# suite (see app/models/farm.py).
JsonVariant = JSON().with_variant(JSONB(), "postgresql")


class WeatherCache(Base):
    """Cached Open-Meteo daily forecast for one farm's centroid. Built by
    WeatherService.get_weather (backend/app/services/weather_service.py),
    one row per farm -- like EnvironmentSnapshot, not a timeseries. Treated
    as stale after `expires_at` and refetched.

    `daily` holds the raw per-day fields as JSON (one dict per day, see
    weather_service._day_to_dict) rather than one column per field, so a new
    Open-Meteo daily variable never needs a migration to surface.
    """

    __tablename__ = "weather_cache"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    daily: Mapped[list] = mapped_column(JsonVariant, nullable=False)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

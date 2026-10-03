import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# JSONB on Postgres, plain JSON elsewhere (in-memory SQLite tests) -- same
# pattern as Farm.polygon_geojson (see app/models/farm.py).
JsonVariant = JSON().with_variant(JSONB(), "postgresql")


class StressZone(Base):
    """One detected stress zone within a farm, vectorized from pixels
    significantly below the field's own mean NDVI for a given scene. Built
    by SatelliteService.get_or_build_layers, replaced (not accumulated)
    each time a farm's layers are regenerated for a given date.
    """

    __tablename__ = "stress_zones"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_date: Mapped[date] = mapped_column(Date, nullable=False)

    # "water_stress" | "nutrient_pest_suspected"
    zone_type: Mapped[str] = mapped_column(String(30), nullable=False)
    area_ha: Mapped[float] = mapped_column(Float, nullable=False)
    geometry_geojson: Mapped[dict] = mapped_column(JsonVariant, nullable=False)
    suggested_action: Mapped[str] = mapped_column(String(500), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

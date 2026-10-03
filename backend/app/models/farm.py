import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# JSONB on Postgres (indexable, efficient); falls back to plain JSON on any
# other dialect — needed so the test suite's in-memory SQLite DB can create
# this table too (SQLite has no JSONB type).
JsonVariant = JSON().with_variant(JSONB(), "postgresql")

from app.models.base import Base


class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    crop: Mapped[str] = mapped_column(String(100), nullable=False)
    variety: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sowing_date: Mapped[date] = mapped_column(Date, nullable=False)
    irrigation_method: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # GeoJSON Polygon (EPSG:4326 — lng/lat) exactly as drawn on the map.
    polygon_geojson: Mapped[dict] = mapped_column(JsonVariant, nullable=False)

    # Always server-computed from polygon_geojson (see FarmService) — never
    # trust an area/centroid value sent by the client.
    area_ha: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_lat: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_lng: Mapped[float] = mapped_column(Float, nullable=False)

    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Farmer-submitted Soil Health Card / lab test report, entered at
    # registration. When present this is the authoritative soil reading for
    # the farm -- it takes priority over the OpenLandMap satellite estimate
    # (see SatelliteService.refresh_environment) rather than being replaced
    # by it. When has_soil_report is False, no lab values were given and the
    # OpenLandMap estimate is used instead.
    has_soil_report: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    soil_report_ph: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_report_nitrogen: Mapped[str | None] = mapped_column(String(10), nullable=True)
    soil_report_phosphorus: Mapped[str | None] = mapped_column(String(10), nullable=True)
    soil_report_potassium: Mapped[str | None] = mapped_column(String(10), nullable=True)
    soil_report_organic_matter_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_report_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

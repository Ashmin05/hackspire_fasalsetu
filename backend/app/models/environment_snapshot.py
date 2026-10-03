import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EnvironmentSnapshot(Base):
    """One farm's environment report -- rainfall/temperature/soil-moisture
    (refreshed from Earth Engine on every SatelliteService.environment_report
    call) plus static soil properties (pH/organic carbon/texture class,
    fetched from Earth Engine only once and reused after that, since soil
    doesn't change). One row per farm, not a timeseries.
    """

    __tablename__ = "environment_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    # Rainfall (CHIRPS) -- see EarthEngineClient._get_rainfall_summary
    rainfall_7d_mm: Mapped[float] = mapped_column(Float, nullable=False)
    rainfall_30d_mm: Mapped[float] = mapped_column(Float, nullable=False)
    rainfall_90d_mm: Mapped[float] = mapped_column(Float, nullable=False)
    rainfall_since_sowing_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    rainfall_as_of: Mapped[date] = mapped_column(Date, nullable=False)

    # Land-surface temperature (MODIS) -- see _get_temperature_summary
    mean_lst_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    hot_periods_60d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    temperature_as_of: Mapped[date] = mapped_column(Date, nullable=False)

    # Soil moisture (SMAP L4, regional ~9-11km) -- see _get_soil_moisture_summary
    soil_moisture: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_moisture_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Static soil properties (OpenLandMap) -- soil_fetched_at is set once,
    # the first time these are populated, and is what SatelliteService
    # checks to decide whether to reuse instead of re-fetching.
    soil_ph: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_organic_carbon_g_per_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_texture_class: Mapped[str | None] = mapped_column(String(30), nullable=True)
    soil_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

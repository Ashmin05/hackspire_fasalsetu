import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IndexTimeseriesPoint(Base):
    """One clear (< 30% field cloud) Sentinel-2 pass for a farm, part of its
    ongoing NDVI/NDWI/EVI history. Built by SatelliteService.build_timeseries
    (backend/app/services/satellite_service.py), one row per (farm, date).
    """

    __tablename__ = "index_timeseries"
    __table_args__ = (
        UniqueConstraint("farm_id", "image_date", name="uq_index_timeseries_farm_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, index=True
    )

    image_date: Mapped[date] = mapped_column(Date, nullable=False)
    satellite: Mapped[str] = mapped_column(String(10), nullable=False)  # "S2A" / "S2B"
    cloud_pct: Mapped[float] = mapped_column(Float, nullable=False)

    ndvi_mean: Mapped[float] = mapped_column(Float, nullable=False)
    ndwi_mean: Mapped[float] = mapped_column(Float, nullable=False)
    evi_mean: Mapped[float] = mapped_column(Float, nullable=False)

    # The crop-stage benchmark NDVI (app/ml/crop_benchmarks.py) *as of this
    # point's date* -- stored rather than recomputed later, since the alert
    # logic compares against it and the crop-stage curve is date-dependent.
    benchmark_ndvi: Mapped[float] = mapped_column(Float, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

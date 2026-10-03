import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SatelliteObservation(Base):
    """One Sentinel-2 analysis result for a farm, cached so /satellite/latest
    doesn't need to hit Earth Engine on every request. A farm can have many
    observations over time; the most recent one (by created_at) is "latest".
    """

    __tablename__ = "satellite_observations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, index=True
    )

    image_date: Mapped[date] = mapped_column(Date, nullable=False)
    satellite: Mapped[str] = mapped_column(String(10), nullable=False)  # "S2A" / "S2B"
    cloud_pct: Mapped[float] = mapped_column(Float, nullable=False)
    is_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    ndvi_mean: Mapped[float] = mapped_column(Float, nullable=False)
    ndvi_min: Mapped[float] = mapped_column(Float, nullable=False)
    ndvi_max: Mapped[float] = mapped_column(Float, nullable=False)
    ndwi_mean: Mapped[float] = mapped_column(Float, nullable=False)
    ndwi_min: Mapped[float] = mapped_column(Float, nullable=False)
    ndwi_max: Mapped[float] = mapped_column(Float, nullable=False)
    evi_mean: Mapped[float] = mapped_column(Float, nullable=False)
    evi_min: Mapped[float] = mapped_column(Float, nullable=False)
    evi_max: Mapped[float] = mapped_column(Float, nullable=False)
    ndmi_mean: Mapped[float] = mapped_column(Float, nullable=False)
    ndmi_min: Mapped[float] = mapped_column(Float, nullable=False)
    ndmi_max: Mapped[float] = mapped_column(Float, nullable=False)

    healthy_pct: Mapped[float] = mapped_column(Float, nullable=False)
    moderate_pct: Mapped[float] = mapped_column(Float, nullable=False)
    stressed_pct: Mapped[float] = mapped_column(Float, nullable=False)
    health_score: Mapped[float] = mapped_column(Float, nullable=False)

    source: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Sentinel-2 via Earth Engine"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

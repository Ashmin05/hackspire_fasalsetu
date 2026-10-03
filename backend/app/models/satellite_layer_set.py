import uuid
from datetime import date, datetime, timezone

from sqlalchemy import DateTime, Date, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SatelliteLayerSet(Base):
    """Cached, farm-polygon-clipped Earth Engine tile URLs for one farm's
    scene on one date. Built by SatelliteService.get_or_build_layers
    (backend/app/services/satellite_service.py), one row per (farm, date).
    Tile URLs are treated as stale after `expires_at` and regenerated.
    """

    __tablename__ = "satellite_layer_sets"
    __table_args__ = (
        UniqueConstraint("farm_id", "image_date", name="uq_satellite_layer_sets_farm_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_date: Mapped[date] = mapped_column(Date, nullable=False)

    true_color_tile_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    ndvi_tile_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    ndwi_tile_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    evi_tile_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    stress_tile_url: Mapped[str] = mapped_column(String(1000), nullable=False)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

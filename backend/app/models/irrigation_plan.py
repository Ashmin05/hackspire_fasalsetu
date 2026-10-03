import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IrrigationPlan(Base):
    """One farm's current FAO-56 root-zone water balance and irrigation
    recommendation -- built by IrrigationService.get_plan (see
    app/services/irrigation_service.py), one row per farm, like WeatherCache
    and EnvironmentSnapshot rather than a timeseries. `depletion_mm` is a
    running balance rolled forward day by day (ETc - effective rain -
    logged irrigation) each time the plan is recomputed, not recomputed
    from scratch -- `computed_through` is the last calendar day already
    folded into it.
    """

    __tablename__ = "irrigation_plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    crop: Mapped[str] = mapped_column(String(100), nullable=False)
    days_since_sowing: Mapped[int] = mapped_column(Integer, nullable=False)

    # "ndvi" (Kc ~ 1.25 x NDVI + 0.1, clamped) or "crop_stage" (FAO-56
    # days-after-sowing curve) -- see app/ml/irrigation_kc.py.
    kc: Mapped[float] = mapped_column(Float, nullable=False)
    kc_basis: Mapped[str] = mapped_column(String(20), nullable=False)
    root_depth_m: Mapped[float] = mapped_column(Float, nullable=False)

    # The USDA texture class actually used for TAW (app/ml/soil_water.py) --
    # either EnvironmentSnapshot.soil_texture_class, or the DEFAULT_SOIL_TEXTURE
    # fallback when none is available yet (soil_texture_is_default is then True).
    soil_texture_class: Mapped[str] = mapped_column(String(30), nullable=False)
    soil_texture_is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    taw_mm: Mapped[float] = mapped_column(Float, nullable=False)  # total available water = AWC x root depth
    raw_mm: Mapped[float] = mapped_column(Float, nullable=False)  # readily available water = p x TAW
    depletion_fraction: Mapped[float] = mapped_column(Float, nullable=False)  # p

    depletion_mm: Mapped[float] = mapped_column(Float, nullable=False)  # current root-zone depletion, clamped [0, TAW]
    is_deficit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # depletion_mm > raw_mm

    computed_through: Mapped[date] = mapped_column(Date, nullable=False)

    next_irrigation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_irrigation_depth_mm: Mapped[float | None] = mapped_column(Float, nullable=True)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IrrigationLog(Base):
    """One farmer-reported irrigation event -- POST /farms/{id}/irrigation/log
    (see app/routers/irrigation.py). A farm accumulates many of these; each
    is subtracted from that day's root-zone depletion the next time
    IrrigationService.get_plan rolls the balance forward over that date
    (see app/services/irrigation_service.py).
    """

    __tablename__ = "irrigation_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    farm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, index=True
    )

    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    depth_mm: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

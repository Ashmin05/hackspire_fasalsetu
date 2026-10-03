import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.farm_alert import FarmAlert


class FarmAlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_farm(self, farm_id: uuid.UUID) -> list[FarmAlert]:
        result = await self.session.execute(
            select(FarmAlert)
            .where(FarmAlert.farm_id == farm_id)
            .order_by(FarmAlert.detected_at.desc(), FarmAlert.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, alert_id: uuid.UUID) -> FarmAlert | None:
        return await self.session.get(FarmAlert, alert_id)

    async def exists(self, farm_id: uuid.UUID, alert_type: str, detected_at: date) -> bool:
        """Used to de-duplicate: the nightly job re-scans a rolling window of
        passes each run and must not create the same alert twice for the
        same farm/type/pass."""
        result = await self.session.execute(
            select(FarmAlert.id).where(
                FarmAlert.farm_id == farm_id,
                FarmAlert.alert_type == alert_type,
                FarmAlert.detected_at == detected_at,
            )
        )
        return result.scalars().first() is not None

    async def create(
        self,
        *,
        farm_id: uuid.UUID,
        alert_type: str,
        severity: str,
        message: str,
        detected_at: date,
    ) -> FarmAlert:
        alert = FarmAlert(
            farm_id=farm_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
            detected_at=detected_at,
        )
        self.session.add(alert)
        await self.session.commit()
        await self.session.refresh(alert)
        return alert

    async def mark_read(self, alert: FarmAlert) -> FarmAlert:
        alert.is_read = True
        await self.session.commit()
        await self.session.refresh(alert)
        return alert

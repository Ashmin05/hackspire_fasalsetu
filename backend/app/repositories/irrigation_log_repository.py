import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.irrigation_log import IrrigationLog


class IrrigationLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, *, farm_id: uuid.UUID, log_date: date, depth_mm: float, note: str | None
    ) -> IrrigationLog:
        log = IrrigationLog(farm_id=farm_id, log_date=log_date, depth_mm=depth_mm, note=note)
        self.session.add(log)
        await self.session.commit()
        await self.session.refresh(log)
        return log

    async def list_between(self, farm_id: uuid.UUID, start_date: date, end_date: date) -> list[IrrigationLog]:
        result = await self.session.execute(
            select(IrrigationLog).where(
                IrrigationLog.farm_id == farm_id,
                IrrigationLog.log_date >= start_date,
                IrrigationLog.log_date <= end_date,
            )
        )
        return list(result.scalars().all())

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.satellite_observation import SatelliteObservation


class SatelliteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_latest_by_farm(self, farm_id: uuid.UUID) -> SatelliteObservation | None:
        result = await self.session.execute(
            select(SatelliteObservation)
            .where(SatelliteObservation.farm_id == farm_id)
            .order_by(SatelliteObservation.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def create(self, *, farm_id: uuid.UUID, **fields) -> SatelliteObservation:
        observation = SatelliteObservation(farm_id=farm_id, **fields)
        self.session.add(observation)
        await self.session.commit()
        await self.session.refresh(observation)
        return observation

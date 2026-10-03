import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.weather_cache import WeatherCache


class WeatherCacheRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_farm(self, farm_id: uuid.UUID) -> WeatherCache | None:
        result = await self.session.execute(select(WeatherCache).where(WeatherCache.farm_id == farm_id))
        return result.scalars().first()

    async def upsert(
        self,
        *,
        farm_id: uuid.UUID,
        daily: list[dict],
        generated_at: datetime,
        expires_at: datetime,
    ) -> WeatherCache:
        existing = await self.get_by_farm(farm_id)
        if existing is not None:
            existing.daily = daily
            existing.generated_at = generated_at
            existing.expires_at = expires_at
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        cache = WeatherCache(farm_id=farm_id, daily=daily, generated_at=generated_at, expires_at=expires_at)
        self.session.add(cache)
        await self.session.commit()
        await self.session.refresh(cache)
        return cache

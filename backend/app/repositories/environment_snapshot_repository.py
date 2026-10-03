import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.environment_snapshot import EnvironmentSnapshot


class EnvironmentSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_farm(self, farm_id: uuid.UUID) -> EnvironmentSnapshot | None:
        result = await self.session.execute(
            select(EnvironmentSnapshot).where(EnvironmentSnapshot.farm_id == farm_id)
        )
        return result.scalars().first()

    async def upsert(
        self,
        *,
        farm_id: uuid.UUID,
        rainfall_7d_mm: float,
        rainfall_30d_mm: float,
        rainfall_90d_mm: float,
        rainfall_since_sowing_mm: float | None,
        rainfall_as_of: date,
        mean_lst_c: float | None,
        hot_periods_60d: int,
        temperature_as_of: date,
        soil_moisture: float | None,
        soil_moisture_as_of: date | None,
        generated_at: datetime,
        soil_ph: float | None = None,
        soil_organic_carbon_g_per_kg: float | None = None,
        soil_texture_class: str | None = None,
        soil_fetched_at: datetime | None = None,
    ) -> EnvironmentSnapshot:
        """Updates the dynamic fields (rainfall/temperature/soil moisture)
        unconditionally. The soil_* fields are only written when
        `soil_fetched_at` is given (i.e. the caller actually just fetched
        them this call) -- otherwise any existing static soil values are
        left untouched, which is what makes "fetch once per farm, reuse"
        work.
        """
        existing = await self.get_by_farm(farm_id)
        if existing is not None:
            existing.rainfall_7d_mm = rainfall_7d_mm
            existing.rainfall_30d_mm = rainfall_30d_mm
            existing.rainfall_90d_mm = rainfall_90d_mm
            existing.rainfall_since_sowing_mm = rainfall_since_sowing_mm
            existing.rainfall_as_of = rainfall_as_of
            existing.mean_lst_c = mean_lst_c
            existing.hot_periods_60d = hot_periods_60d
            existing.temperature_as_of = temperature_as_of
            existing.soil_moisture = soil_moisture
            existing.soil_moisture_as_of = soil_moisture_as_of
            existing.generated_at = generated_at
            if soil_fetched_at is not None:
                existing.soil_ph = soil_ph
                existing.soil_organic_carbon_g_per_kg = soil_organic_carbon_g_per_kg
                existing.soil_texture_class = soil_texture_class
                existing.soil_fetched_at = soil_fetched_at
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        snapshot = EnvironmentSnapshot(
            farm_id=farm_id,
            rainfall_7d_mm=rainfall_7d_mm,
            rainfall_30d_mm=rainfall_30d_mm,
            rainfall_90d_mm=rainfall_90d_mm,
            rainfall_since_sowing_mm=rainfall_since_sowing_mm,
            rainfall_as_of=rainfall_as_of,
            mean_lst_c=mean_lst_c,
            hot_periods_60d=hot_periods_60d,
            temperature_as_of=temperature_as_of,
            soil_moisture=soil_moisture,
            soil_moisture_as_of=soil_moisture_as_of,
            generated_at=generated_at,
            soil_ph=soil_ph,
            soil_organic_carbon_g_per_kg=soil_organic_carbon_g_per_kg,
            soil_texture_class=soil_texture_class,
            soil_fetched_at=soil_fetched_at,
        )
        self.session.add(snapshot)
        await self.session.commit()
        await self.session.refresh(snapshot)
        return snapshot

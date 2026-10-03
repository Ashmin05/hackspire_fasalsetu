import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.index_timeseries import IndexTimeseriesPoint


class IndexTimeseriesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_farm(self, farm_id: uuid.UUID) -> list[IndexTimeseriesPoint]:
        result = await self.session.execute(
            select(IndexTimeseriesPoint)
            .where(IndexTimeseriesPoint.farm_id == farm_id)
            .order_by(IndexTimeseriesPoint.image_date.asc())
        )
        return list(result.scalars().all())

    async def get_by_farm_and_date(
        self, farm_id: uuid.UUID, image_date: date
    ) -> IndexTimeseriesPoint | None:
        result = await self.session.execute(
            select(IndexTimeseriesPoint).where(
                IndexTimeseriesPoint.farm_id == farm_id,
                IndexTimeseriesPoint.image_date == image_date,
            )
        )
        return result.scalars().first()

    async def upsert(
        self,
        *,
        farm_id: uuid.UUID,
        image_date: date,
        satellite: str,
        cloud_pct: float,
        ndvi_mean: float,
        ndwi_mean: float,
        evi_mean: float,
        benchmark_ndvi: float,
    ) -> IndexTimeseriesPoint:
        """Updates the point for (farm_id, image_date) if one already exists
        (the nightly job re-scans a rolling window and will re-see the same
        clear passes), otherwise inserts a new one."""
        existing = await self.get_by_farm_and_date(farm_id, image_date)
        if existing is not None:
            existing.satellite = satellite
            existing.cloud_pct = cloud_pct
            existing.ndvi_mean = ndvi_mean
            existing.ndwi_mean = ndwi_mean
            existing.evi_mean = evi_mean
            existing.benchmark_ndvi = benchmark_ndvi
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        point = IndexTimeseriesPoint(
            farm_id=farm_id,
            image_date=image_date,
            satellite=satellite,
            cloud_pct=cloud_pct,
            ndvi_mean=ndvi_mean,
            ndwi_mean=ndwi_mean,
            evi_mean=evi_mean,
            benchmark_ndvi=benchmark_ndvi,
        )
        self.session.add(point)
        await self.session.commit()
        await self.session.refresh(point)
        return point

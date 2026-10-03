import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.satellite_layer_set import SatelliteLayerSet


class SatelliteLayerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_farm_and_date(
        self, farm_id: uuid.UUID, image_date: date
    ) -> SatelliteLayerSet | None:
        result = await self.session.execute(
            select(SatelliteLayerSet).where(
                SatelliteLayerSet.farm_id == farm_id,
                SatelliteLayerSet.image_date == image_date,
            )
        )
        return result.scalars().first()

    async def upsert(
        self,
        *,
        farm_id: uuid.UUID,
        image_date: date,
        true_color_tile_url: str,
        ndvi_tile_url: str,
        ndwi_tile_url: str,
        evi_tile_url: str,
        stress_tile_url: str,
        generated_at,
        expires_at,
    ) -> SatelliteLayerSet:
        existing = await self.get_by_farm_and_date(farm_id, image_date)
        if existing is not None:
            existing.true_color_tile_url = true_color_tile_url
            existing.ndvi_tile_url = ndvi_tile_url
            existing.ndwi_tile_url = ndwi_tile_url
            existing.evi_tile_url = evi_tile_url
            existing.stress_tile_url = stress_tile_url
            existing.generated_at = generated_at
            existing.expires_at = expires_at
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        layer_set = SatelliteLayerSet(
            farm_id=farm_id,
            image_date=image_date,
            true_color_tile_url=true_color_tile_url,
            ndvi_tile_url=ndvi_tile_url,
            ndwi_tile_url=ndwi_tile_url,
            evi_tile_url=evi_tile_url,
            stress_tile_url=stress_tile_url,
            generated_at=generated_at,
            expires_at=expires_at,
        )
        self.session.add(layer_set)
        await self.session.commit()
        await self.session.refresh(layer_set)
        return layer_set

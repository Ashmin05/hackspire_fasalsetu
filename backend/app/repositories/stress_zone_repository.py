import uuid
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.earth_engine_client import StressZoneResult
from app.models.stress_zone import StressZone


class StressZoneRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_farm_and_date(self, farm_id: uuid.UUID, image_date: date) -> list[StressZone]:
        result = await self.session.execute(
            select(StressZone).where(
                StressZone.farm_id == farm_id,
                StressZone.image_date == image_date,
            )
        )
        return list(result.scalars().all())

    async def replace_for_date(
        self, farm_id: uuid.UUID, image_date: date, zones: list[StressZoneResult]
    ) -> list[StressZone]:
        """Deletes any zones already stored for this (farm, date) and
        inserts the freshly computed set -- zones aren't accumulated across
        re-generations of the same date the way timeseries points are,
        since a re-run supersedes rather than adds to the previous result.
        """
        await self.session.execute(
            delete(StressZone).where(
                StressZone.farm_id == farm_id,
                StressZone.image_date == image_date,
            )
        )
        rows = [
            StressZone(
                farm_id=farm_id,
                image_date=image_date,
                zone_type=zone.zone_type,
                area_ha=zone.area_ha,
                geometry_geojson=zone.geometry_geojson,
                suggested_action=zone.suggested_action,
            )
            for zone in zones
        ]
        self.session.add_all(rows)
        await self.session.commit()
        for row in rows:
            await self.session.refresh(row)
        return rows

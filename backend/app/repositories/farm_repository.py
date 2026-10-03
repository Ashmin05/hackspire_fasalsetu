import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.farm import Farm


class FarmRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, farm_id: uuid.UUID) -> Farm | None:
        return await self.session.get(Farm, farm_id)

    async def list_by_user(self, user_id: uuid.UUID) -> list[Farm]:
        result = await self.session.execute(
            select(Farm).where(Farm.user_id == user_id).order_by(Farm.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[Farm]:
        """Every farm across every user -- used by the nightly satellite
        timeseries job (app/jobs/scheduler.py), which has no single owner
        to scope to."""
        result = await self.session.execute(select(Farm))
        return list(result.scalars().all())

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        crop: str,
        variety: str | None,
        sowing_date,
        irrigation_method: str | None,
        polygon_geojson: dict,
        area_ha: float,
        centroid_lat: float,
        centroid_lng: float,
        state: str | None,
        district: str | None,
        address: str | None,
        has_soil_report: bool = False,
        soil_report_ph: float | None = None,
        soil_report_nitrogen: str | None = None,
        soil_report_phosphorus: str | None = None,
        soil_report_potassium: str | None = None,
        soil_report_organic_matter_pct: float | None = None,
        soil_report_recorded_at=None,
    ) -> Farm:
        farm = Farm(
            user_id=user_id,
            name=name,
            crop=crop,
            variety=variety,
            sowing_date=sowing_date,
            irrigation_method=irrigation_method,
            polygon_geojson=polygon_geojson,
            area_ha=area_ha,
            centroid_lat=centroid_lat,
            centroid_lng=centroid_lng,
            state=state,
            district=district,
            address=address,
            has_soil_report=has_soil_report,
            soil_report_ph=soil_report_ph,
            soil_report_nitrogen=soil_report_nitrogen,
            soil_report_phosphorus=soil_report_phosphorus,
            soil_report_potassium=soil_report_potassium,
            soil_report_organic_matter_pct=soil_report_organic_matter_pct,
            soil_report_recorded_at=soil_report_recorded_at,
        )
        self.session.add(farm)
        await self.session.commit()
        await self.session.refresh(farm)
        return farm

    async def update(self, farm: Farm, **fields) -> Farm:
        for key, value in fields.items():
            if value is not None:
                setattr(farm, key, value)
        await self.session.commit()
        await self.session.refresh(farm)
        return farm

    async def delete(self, farm: Farm) -> None:
        await self.session.delete(farm)
        await self.session.commit()

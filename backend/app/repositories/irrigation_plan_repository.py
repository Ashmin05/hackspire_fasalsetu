import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.irrigation_plan import IrrigationPlan


class IrrigationPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_farm(self, farm_id: uuid.UUID) -> IrrigationPlan | None:
        result = await self.session.execute(select(IrrigationPlan).where(IrrigationPlan.farm_id == farm_id))
        return result.scalars().first()

    async def upsert(
        self,
        *,
        farm_id: uuid.UUID,
        crop: str,
        days_since_sowing: int,
        kc: float,
        kc_basis: str,
        root_depth_m: float,
        soil_texture_class: str,
        soil_texture_is_default: bool,
        taw_mm: float,
        raw_mm: float,
        depletion_fraction: float,
        depletion_mm: float,
        is_deficit: bool,
        computed_through: date,
        next_irrigation_date: date | None,
        next_irrigation_depth_mm: float | None,
        generated_at: datetime,
    ) -> IrrigationPlan:
        existing = await self.get_by_farm(farm_id)
        fields = dict(
            crop=crop,
            days_since_sowing=days_since_sowing,
            kc=kc,
            kc_basis=kc_basis,
            root_depth_m=root_depth_m,
            soil_texture_class=soil_texture_class,
            soil_texture_is_default=soil_texture_is_default,
            taw_mm=taw_mm,
            raw_mm=raw_mm,
            depletion_fraction=depletion_fraction,
            depletion_mm=depletion_mm,
            is_deficit=is_deficit,
            computed_through=computed_through,
            next_irrigation_date=next_irrigation_date,
            next_irrigation_depth_mm=next_irrigation_depth_mm,
            generated_at=generated_at,
        )
        if existing is not None:
            for key, value in fields.items():
                setattr(existing, key, value)
            await self.session.commit()
            await self.session.refresh(existing)
            return existing

        plan = IrrigationPlan(farm_id=farm_id, **fields)
        self.session.add(plan)
        await self.session.commit()
        await self.session.refresh(plan)
        return plan

    async def set_depletion(self, plan: IrrigationPlan, depletion_mm: float) -> IrrigationPlan:
        """Applies a backdated irrigation log directly to the stored
        balance (see IrrigationService.log_irrigation) -- used only when
        the logged date falls on or before `plan.computed_through`, i.e.
        a day whose contribution to depletion_mm is already baked in and
        won't be revisited by a future roll-forward."""
        plan.depletion_mm = depletion_mm
        plan.is_deficit = depletion_mm > plan.raw_mm
        await self.session.commit()
        await self.session.refresh(plan)
        return plan

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class IrrigationLogRequest(BaseModel):
    log_date: date
    depth_mm: float = Field(gt=0, le=500)
    note: str | None = Field(default=None, max_length=255)


class IrrigationPlanResponse(BaseModel):
    farm_id: uuid.UUID
    crop: str
    days_since_sowing: int

    kc: float
    kc_basis: Literal["ndvi", "crop_stage"]
    root_depth_m: float

    soil_texture_class: str
    soil_texture_is_default: bool

    taw_mm: float
    raw_mm: float
    depletion_fraction: float
    depletion_mm: float
    is_deficit: bool

    computed_through: date
    next_irrigation_date: date | None
    next_irrigation_depth_mm: float | None

    basis: Literal["Modelled"] = "Modelled"
    generated_at: datetime

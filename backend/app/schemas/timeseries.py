import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class TimeseriesPointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    farm_id: uuid.UUID
    image_date: date
    satellite: str
    cloud_pct: float
    ndvi_mean: float
    ndwi_mean: float
    evi_mean: float
    benchmark_ndvi: float
    created_at: datetime


class FarmAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    farm_id: uuid.UUID
    alert_type: str
    severity: str
    message: str
    detected_at: date
    is_read: bool
    created_at: datetime

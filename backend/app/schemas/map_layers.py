import uuid
from datetime import date, datetime

from pydantic import BaseModel


class TileLayerUrls(BaseModel):
    true_color: str
    ndvi: str
    ndwi: str
    evi: str
    stress: str


class StressZoneResponse(BaseModel):
    id: uuid.UUID
    zone_type: str
    area_ha: float
    geometry_geojson: dict
    suggested_action: str


class SatelliteLayersResponse(BaseModel):
    farm_id: uuid.UUID
    image_date: date
    layers: TileLayerUrls
    generated_at: datetime
    expires_at: datetime
    stress_zones: list[StressZoneResponse]

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SoilLevel = Literal["Low", "Medium", "High"]


class SoilReportIn(BaseModel):
    """A farmer-submitted Soil Health Card / lab test report. Presence of
    this object on a create/update request is what sets has_soil_report."""

    ph: float | None = Field(default=None, ge=0, le=14)
    nitrogen: SoilLevel | None = None
    phosphorus: SoilLevel | None = None
    potassium: SoilLevel | None = None
    organic_matter_pct: float | None = Field(default=None, ge=0, le=100)


class SoilReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ph: float | None
    nitrogen: SoilLevel | None
    phosphorus: SoilLevel | None
    potassium: SoilLevel | None
    organic_matter_pct: float | None
    recorded_at: datetime | None


class FarmCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    crop: str = Field(min_length=1, max_length=100)
    variety: str | None = Field(default=None, max_length=100)
    sowing_date: date
    irrigation_method: str | None = Field(default=None, max_length=100)
    # GeoJSON Polygon geometry, e.g. {"type": "Polygon", "coordinates": [[[lng, lat], ...]]}
    polygon_geojson: dict
    state: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=255)
    # Set when the farmer ticked "I have a Soil Health Card / Lab Test
    # Report" and entered values -- omit/null when they didn't.
    soil_report: SoilReportIn | None = None


class FarmUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    crop: str | None = Field(default=None, min_length=1, max_length=100)
    variety: str | None = Field(default=None, max_length=100)
    sowing_date: date | None = None
    irrigation_method: str | None = Field(default=None, max_length=100)
    polygon_geojson: dict | None = None
    state: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=255)
    soil_report: SoilReportIn | None = None


class FarmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    crop: str
    variety: str | None
    sowing_date: date
    irrigation_method: str | None
    polygon_geojson: dict
    area_ha: float
    centroid_lat: float
    centroid_lng: float
    state: str | None
    district: str | None
    address: str | None
    has_soil_report: bool
    soil_report: SoilReportOut | None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def from_farm(farm) -> "FarmResponse":  # type: ignore[no-untyped-def]
        soil_report = (
            SoilReportOut(
                ph=farm.soil_report_ph,
                nitrogen=farm.soil_report_nitrogen,
                phosphorus=farm.soil_report_phosphorus,
                potassium=farm.soil_report_potassium,
                organic_matter_pct=farm.soil_report_organic_matter_pct,
                recorded_at=farm.soil_report_recorded_at,
            )
            if farm.has_soil_report
            else None
        )
        return FarmResponse(
            id=farm.id,
            name=farm.name,
            crop=farm.crop,
            variety=farm.variety,
            sowing_date=farm.sowing_date,
            irrigation_method=farm.irrigation_method,
            polygon_geojson=farm.polygon_geojson,
            area_ha=farm.area_ha,
            centroid_lat=farm.centroid_lat,
            centroid_lng=farm.centroid_lng,
            state=farm.state,
            district=farm.district,
            address=farm.address,
            has_soil_report=farm.has_soil_report,
            soil_report=soil_report,
            created_at=farm.created_at,
            updated_at=farm.updated_at,
        )

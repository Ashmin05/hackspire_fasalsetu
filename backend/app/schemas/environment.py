import uuid
from datetime import date, datetime

from pydantic import BaseModel


class Provenance(BaseModel):
    """Source + native resolution for one section of the environment
    report, so the UI can show e.g. '10 m field' vs '~10 km regional'
    instead of presenting every number as equally precise."""

    source: str
    resolution: str
    as_of: date | None


class RainfallResponse(BaseModel):
    mm_7d: float
    mm_30d: float
    mm_90d: float
    mm_since_sowing: float | None
    provenance: Provenance


class TemperatureResponse(BaseModel):
    mean_lst_c: float | None
    hot_periods_60d: int
    provenance: Provenance


class SoilMoistureResponse(BaseModel):
    surface_moisture: float | None
    provenance: Provenance


class SoilResponse(BaseModel):
    ph: float | None
    organic_carbon_g_per_kg: float | None
    texture_class: str | None
    # Only ever set when is_lab_report is True -- OpenLandMap has no NPK or
    # organic-matter-% readings, only a lab test does.
    nitrogen: str | None = None
    phosphorus: str | None = None
    potassium: str | None = None
    organic_matter_pct: float | None = None
    is_lab_report: bool = False
    provenance: Provenance


class EnvironmentReportResponse(BaseModel):
    farm_id: uuid.UUID
    rainfall: RainfallResponse
    temperature: TemperatureResponse
    soil_moisture: SoilMoistureResponse
    soil: SoilResponse
    generated_at: datetime

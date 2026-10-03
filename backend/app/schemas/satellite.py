import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.satellite_observation import SatelliteObservation


class IndexStatsResponse(BaseModel):
    mean: float
    min: float
    max: float


class ProvenanceResponse(BaseModel):
    """Carried on every satellite response so the frontend can show (or a
    reviewer can verify) that a number is real, live Sentinel-2 data and not
    a fallback/synthetic value."""

    source: str
    is_live: bool
    as_of: date
    cloud_pct: float


class SatelliteObservationResponse(BaseModel):
    id: uuid.UUID
    farm_id: uuid.UUID
    image_date: date
    satellite: str
    cloud_pct: float
    is_fallback: bool
    ndvi: IndexStatsResponse
    ndwi: IndexStatsResponse
    evi: IndexStatsResponse
    ndmi: IndexStatsResponse
    healthy_pct: float
    moderate_pct: float
    stressed_pct: float
    health_score: float
    provenance: ProvenanceResponse
    created_at: datetime


def observation_to_response(observation: SatelliteObservation) -> SatelliteObservationResponse:
    """Builds the nested API response from the flat-columns ORM row. Not a
    plain `from_attributes` mapping since the response nests mean/min/max
    per index while the table stores them as flat `<index>_mean` etc.
    columns (simpler to query/index)."""
    return SatelliteObservationResponse(
        id=observation.id,
        farm_id=observation.farm_id,
        image_date=observation.image_date,
        satellite=observation.satellite,
        cloud_pct=observation.cloud_pct,
        is_fallback=observation.is_fallback,
        ndvi=IndexStatsResponse(
            mean=observation.ndvi_mean, min=observation.ndvi_min, max=observation.ndvi_max
        ),
        ndwi=IndexStatsResponse(
            mean=observation.ndwi_mean, min=observation.ndwi_min, max=observation.ndwi_max
        ),
        evi=IndexStatsResponse(
            mean=observation.evi_mean, min=observation.evi_min, max=observation.evi_max
        ),
        ndmi=IndexStatsResponse(
            mean=observation.ndmi_mean, min=observation.ndmi_min, max=observation.ndmi_max
        ),
        healthy_pct=observation.healthy_pct,
        moderate_pct=observation.moderate_pct,
        stressed_pct=observation.stressed_pct,
        health_score=observation.health_score,
        provenance=ProvenanceResponse(
            source=observation.source,
            is_live=True,
            as_of=observation.image_date,
            cloud_pct=observation.cloud_pct,
        ),
        created_at=observation.created_at,
    )

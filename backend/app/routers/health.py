import time

from fastapi import APIRouter
from pydantic import BaseModel

from app.integrations.earth_engine_client import (
    EarthEngineNotConfiguredError,
    earth_engine_client,
)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


class EarthEngineHealthResponse(BaseModel):
    configured: bool
    ok: bool
    auth_mode: str | None = None  # "service_account" | "application_default" | None
    image_count: int | None = None
    latency_ms: float
    detail: str | None = None


@router.get("/health/earth-engine", response_model=EarthEngineHealthResponse)
async def earth_engine_health() -> EarthEngineHealthResponse:
    """Proves the Earth Engine connection actually works end-to-end by
    counting recent Sentinel-2 scenes over a fixed point — not just that a
    key file was found, but that EE accepted it and answered a real query."""
    started = time.perf_counter()
    try:
        image_count = await earth_engine_client.count_recent_sentinel2_images()
        return EarthEngineHealthResponse(
            configured=True,
            ok=True,
            auth_mode=earth_engine_client.auth_mode,
            image_count=image_count,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )
    except EarthEngineNotConfiguredError as exc:
        return EarthEngineHealthResponse(
            configured=False,
            ok=False,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            detail=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 — covers EarthEngineTimeoutError and any EE failure; health check must never 500
        return EarthEngineHealthResponse(
            configured=earth_engine_client.configured,
            ok=False,
            auth_mode=earth_engine_client.auth_mode,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            detail=str(exc),
        )

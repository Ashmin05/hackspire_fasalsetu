"""Static, per-crop NDVI-by-growth-stage reference curves.

**These are reference curves, not a trained model or a scientifically
calibrated agronomic dataset.** Each curve is a small set of (days-after-
sowing, expected NDVI) points assembled from generally known crop growth
patterns -- typical emergence/vegetative/peak/senescence NDVI ranges for
that crop -- not from real field trial data for any specific region, soil,
or season. They exist to give `SatelliteService`'s alerting logic (see
`app/services/satellite_service.py`) a rough sense of "is this NDVI on
track for this crop and age", not to make an authoritative agronomic claim.
A crop with no entry here falls back to the generic curve in
`app/core/satellite_health.py`.
"""

from app.core.satellite_health import (
    GENERIC_STAGE_BENCHMARKS,
    BenchmarkCurve,
    interpolate_benchmark_curve,
)

# Day-after-sowing -> expected mean NDVI. Points are approximate midpoints
# of each growth stage (emergence -> vegetative -> peak -> senescence ->
# harvest-ready); values interpolate linearly between them.
CROP_BENCHMARKS: dict[str, BenchmarkCurve] = {
    "rice": [(0, 0.15), (20, 0.32), (45, 0.62), (70, 0.80), (100, 0.75), (120, 0.55), (140, 0.35)],
    "wheat": [(0, 0.15), (25, 0.35), (55, 0.65), (80, 0.75), (100, 0.65), (120, 0.45), (135, 0.30)],
    "onion": [(0, 0.15), (20, 0.30), (45, 0.55), (70, 0.70), (90, 0.65), (110, 0.45), (130, 0.30)],
    "tomato": [(0, 0.15), (20, 0.35), (45, 0.65), (65, 0.80), (90, 0.75), (110, 0.55), (130, 0.35)],
    "sugarcane": [(0, 0.15), (40, 0.35), (90, 0.60), (150, 0.80), (240, 0.82), (300, 0.60), (360, 0.35)],
    "cotton": [(0, 0.15), (30, 0.30), (60, 0.55), (90, 0.75), (120, 0.70), (150, 0.50), (180, 0.30)],
    "maize": [(0, 0.15), (20, 0.35), (45, 0.65), (65, 0.82), (90, 0.72), (110, 0.50), (125, 0.30)],
    "soybean": [(0, 0.15), (20, 0.30), (45, 0.60), (65, 0.75), (90, 0.68), (110, 0.45), (120, 0.30)],
}


def benchmark_ndvi_for_crop(crop: str | None, days_since_sowing: int | None) -> float:
    """Expected NDVI for `crop` this many days after sowing. Matching is
    case-insensitive on the crop name; an unrecognised crop (or no crop
    given) falls back to the generic curve, and an unknown sowing date
    falls back to that curve's own peak value."""
    curve = CROP_BENCHMARKS.get((crop or "").strip().lower(), GENERIC_STAGE_BENCHMARKS)
    default = max(ndvi for _, ndvi in curve)
    return interpolate_benchmark_curve(curve, days_since_sowing, default=default)

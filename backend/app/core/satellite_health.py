"""Pure, Earth-Engine-free math for turning raw Sentinel-2 index stats into a
0-100 field health score. Kept separate from earth_engine_client.py so it can
be unit-tested with plain numbers -- no EE mocking required.
"""

from datetime import date

BenchmarkCurve = list[tuple[int, float]]

# A rough, non-scientific NDVI-by-growth-stage curve used only to judge
# whether today's NDVI is "on track" for however long it's been since
# sowing. This is the *generic* curve -- used as a fallback for a crop with
# no entry in app/ml/crop_benchmarks.py's per-crop curves.
GENERIC_STAGE_BENCHMARKS: BenchmarkCurve = [
    (0, 0.20),  # emergence
    (20, 0.35),
    (40, 0.65),
    (60, 0.78),  # peak vegetative / reproductive
    (90, 0.70),
    (120, 0.45),  # senescence
    (150, 0.30),  # harvest-ready
]


def interpolate_benchmark_curve(
    curve: BenchmarkCurve, days_since_sowing: int | None, *, default: float
) -> float:
    """Expected NDVI this many days after sowing, read off a simple
    piecewise-linear `curve` of (day, NDVI) points sorted by day. Falls back
    to `default` when the sowing date is unknown, and clamps to the curve's
    first/last point outside its range (rather than extrapolating)."""
    if days_since_sowing is None:
        return default
    if days_since_sowing <= curve[0][0]:
        return curve[0][1]
    if days_since_sowing >= curve[-1][0]:
        return curve[-1][1]
    for (day_a, ndvi_a), (day_b, ndvi_b) in zip(curve, curve[1:]):
        if day_a <= days_since_sowing <= day_b:
            fraction = (days_since_sowing - day_a) / (day_b - day_a)
            return ndvi_a + fraction * (ndvi_b - ndvi_a)
    return curve[-1][1]  # unreachable; keeps type checkers happy


def crop_stage_benchmark_ndvi(days_since_sowing: int | None) -> float:
    """Expected NDVI for a generic (crop-unaware) curve -- see
    app.ml.crop_benchmarks.benchmark_ndvi_for_crop for the per-crop version
    used by the satellite timeseries/alerts feature."""
    return interpolate_benchmark_curve(GENERIC_STAGE_BENCHMARKS, days_since_sowing, default=0.78)


def days_since(sowing_date: date | None, as_of: date) -> int | None:
    """Days between `sowing_date` and `as_of`, or None if there's no sowing
    date to measure from."""
    if sowing_date is None:
        return None
    return (as_of - sowing_date).days


def compute_health_score(*, mean_ndvi: float, benchmark_ndvi: float, stressed_pct: float) -> float:
    """0-100 field health score: 70% how the field's mean NDVI compares to
    the crop-stage benchmark (capped at 100% credit, so wildly exceeding the
    benchmark can't overflow the score), 30% how little of the field falls
    in the stressed NDVI band (<0.3)."""
    ndvi_component = 0.0 if benchmark_ndvi <= 0 else min(mean_ndvi / benchmark_ndvi, 1.0) * 100
    ndvi_component = max(ndvi_component, 0.0)
    stress_component = max(0.0, 100.0 - stressed_pct)
    score = 0.7 * ndvi_component + 0.3 * stress_component
    return round(max(0.0, min(100.0, score)), 1)

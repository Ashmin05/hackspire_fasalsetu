"""FAO-56 single crop coefficient (Kc) and root-depth-by-growth-stage
tables, used by IrrigationService (app/services/irrigation_service.py) to
build each farm's daily root-zone depletion balance.

**These are typical published FAO-56 values (Table 12 / Table 22 /
Table 22 depletion fractions), not a trained model or a site-calibrated
agronomic dataset** -- same caveat as app/ml/crop_benchmarks.py's NDVI
curves. Stage lengths and root depths are generic mid-range figures, not
tuned to any specific region, season, or variety.

Covers the app's five currently farm-registerable crops (rice, wheat,
onion, sugarcane, potato -- see EXPLAIN.md's crop-list restriction) plus
the other crops app/ml/crop_benchmarks.py already has NDVI curves for
(tomato, cotton, maize, soybean), so an older farm registered before the
crop-list restriction still gets a real profile instead of the generic
fallback.
"""

from dataclasses import dataclass, field

from app.core.satellite_health import BenchmarkCurve, interpolate_benchmark_curve

# "Total available water" (TAW) response cares about root depth in metres,
# growing from Zr_min (sowing) to Zr_max (reached once the crop is fully
# developed, held constant after) -- FAO-56 Table 22.
RootDepthCurve = list[tuple[int, float]]


@dataclass
class CropWaterProfile:
    """One crop's FAO-56 stage lengths (days after sowing) -> Kc and root
    depth curves, plus its readily-available-water depletion fraction p
    (FAO-56 Table 22 -- the fraction of TAW that can be depleted before the
    crop is water-stressed)."""

    # (day-after-sowing, Kc) control points: flat at kc_ini through the
    # initial stage, ramping linearly to kc_mid through development, flat
    # through mid-season, ramping down to kc_end through late season.
    kc_curve: BenchmarkCurve
    # (day-after-sowing, root depth metres) control points: ramping from
    # Zr_min to Zr_max over initial+development, flat after.
    root_depth_curve: RootDepthCurve
    p: float
    kc_min: float = field(init=False)
    kc_max: float = field(init=False)

    def __post_init__(self) -> None:
        values = [kc for _, kc in self.kc_curve]
        self.kc_min = min(values)
        self.kc_max = max(values)


def _profile(
    *,
    l_ini: int,
    l_dev: int,
    l_mid: int,
    l_late: int,
    kc_ini: float,
    kc_mid: float,
    kc_end: float,
    zr_min_m: float,
    zr_max_m: float,
    p: float,
) -> CropWaterProfile:
    dev_end = l_ini + l_dev
    mid_end = dev_end + l_mid
    total = mid_end + l_late
    return CropWaterProfile(
        kc_curve=[(0, kc_ini), (l_ini, kc_ini), (dev_end, kc_mid), (mid_end, kc_mid), (total, kc_end)],
        root_depth_curve=[(0, zr_min_m), (dev_end, zr_max_m), (total, zr_max_m)],
        p=p,
    )


# Stage lengths / Kc / root depth / depletion fraction -- FAO-56 Table 12
# (Kc), Table 22 (root depth, depletion fraction p). Crop keys match
# app/ml/crop_benchmarks.py's lowercase naming.
CROP_WATER_PROFILES: dict[str, CropWaterProfile] = {
    "rice": _profile(
        l_ini=20, l_dev=25, l_mid=60, l_late=35,
        kc_ini=1.05, kc_mid=1.20, kc_end=0.90,
        zr_min_m=0.10, zr_max_m=0.50, p=0.20,
    ),
    "wheat": _profile(
        l_ini=20, l_dev=25, l_mid=60, l_late=30,
        kc_ini=0.40, kc_mid=1.15, kc_end=0.40,
        zr_min_m=0.30, zr_max_m=1.20, p=0.55,
    ),
    "onion": _profile(
        l_ini=15, l_dev=25, l_mid=70, l_late=20,
        kc_ini=0.70, kc_mid=1.05, kc_end=0.80,
        zr_min_m=0.15, zr_max_m=0.30, p=0.30,
    ),
    "sugarcane": _profile(
        l_ini=35, l_dev=60, l_mid=190, l_late=75,
        kc_ini=0.40, kc_mid=1.25, kc_end=0.75,
        zr_min_m=0.30, zr_max_m=1.50, p=0.50,
    ),
    "potato": _profile(
        l_ini=25, l_dev=30, l_mid=45, l_late=30,
        kc_ini=0.50, kc_mid=1.15, kc_end=0.75,
        zr_min_m=0.20, zr_max_m=0.50, p=0.35,
    ),
    "tomato": _profile(
        l_ini=25, l_dev=30, l_mid=45, l_late=30,
        kc_ini=0.60, kc_mid=1.15, kc_end=0.80,
        zr_min_m=0.20, zr_max_m=0.90, p=0.40,
    ),
    "cotton": _profile(
        l_ini=30, l_dev=50, l_mid=60, l_late=40,
        kc_ini=0.35, kc_mid=1.18, kc_end=0.60,
        zr_min_m=0.30, zr_max_m=1.30, p=0.65,
    ),
    "maize": _profile(
        l_ini=20, l_dev=35, l_mid=40, l_late=30,
        kc_ini=0.30, kc_mid=1.20, kc_end=0.60,
        zr_min_m=0.30, zr_max_m=1.20, p=0.55,
    ),
    "soybean": _profile(
        l_ini=20, l_dev=30, l_mid=40, l_late=30,
        kc_ini=0.40, kc_mid=1.15, kc_end=0.50,
        zr_min_m=0.30, zr_max_m=0.90, p=0.50,
    ),
}

# An unrecognised crop (or none registered) falls back to this generic,
# mid-range profile rather than failing the irrigation plan outright --
# same fallback principle as GENERIC_STAGE_BENCHMARKS in satellite_health.py.
GENERIC_WATER_PROFILE = _profile(
    l_ini=20, l_dev=30, l_mid=50, l_late=30,
    kc_ini=0.50, kc_mid=1.10, kc_end=0.70,
    zr_min_m=0.25, zr_max_m=0.80, p=0.50,
)


def _profile_for(crop: str | None) -> CropWaterProfile:
    return CROP_WATER_PROFILES.get((crop or "").strip().lower(), GENERIC_WATER_PROFILE)


def crop_stage_kc(crop: str | None, days_since_sowing: int | None) -> float:
    """Kc read off the crop's FAO-56 stage curve for this many days after
    sowing -- clamps to kc_ini/kc_end outside the curve's range rather than
    extrapolating (same behaviour as interpolate_benchmark_curve)."""
    profile = _profile_for(crop)
    default = profile.kc_curve[-1][1]
    return interpolate_benchmark_curve(profile.kc_curve, days_since_sowing, default=default)


def root_depth_m(crop: str | None, days_since_sowing: int | None) -> float:
    """Root depth (metres) for this many days after sowing, per the crop's
    FAO-56 Table 22 root-growth curve."""
    profile = _profile_for(crop)
    default = profile.root_depth_curve[-1][1]
    return interpolate_benchmark_curve(profile.root_depth_curve, days_since_sowing, default=default)


def depletion_fraction(crop: str | None) -> float:
    """p -- the fraction of TAW a crop can deplete before being water-
    stressed (FAO-56 Table 22). Readily available water (RAW) = p x TAW."""
    return _profile_for(crop).p


def ndvi_adjusted_kc(crop: str | None, ndvi: float) -> float:
    """Kc estimated from the farm's latest measured NDVI instead of days-
    since-sowing: Kc ~ 1.25 x NDVI + 0.1 (a common empirical NDVI-Kc
    relationship), clamped to this crop's own [kc_min, kc_max] stage-curve
    range so a noisy NDVI reading can't push Kc outside physically
    plausible bounds for the crop."""
    profile = _profile_for(crop)
    raw = 1.25 * ndvi + 0.1
    return max(profile.kc_min, min(profile.kc_max, raw))


def resolve_kc(crop: str | None, days_since_sowing: int | None, ndvi: float | None) -> tuple[float, str]:
    """The Kc to use for today's irrigation computation, and how it was
    derived: NDVI-adjusted when a recent satellite reading is available
    (see IrrigationService), otherwise the crop-stage curve."""
    if ndvi is not None:
        return round(ndvi_adjusted_kc(crop, ndvi), 3), "ndvi"
    return round(crop_stage_kc(crop, days_since_sowing), 3), "crop_stage"

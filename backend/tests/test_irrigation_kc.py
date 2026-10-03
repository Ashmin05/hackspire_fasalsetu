"""Tests for the pure FAO-56 Kc/root-depth/TAW math in app/ml/irrigation_kc.py
and app/ml/soil_water.py -- no DB, no external clients."""

from app.ml.irrigation_kc import (
    crop_stage_kc,
    depletion_fraction,
    ndvi_adjusted_kc,
    resolve_kc,
    root_depth_m,
)
from app.ml.soil_water import (
    DEFAULT_SOIL_TEXTURE,
    available_water_capacity_mm_per_m,
    total_available_water_mm,
)


class TestCropStageKc:
    def test_initial_stage_is_flat_at_kc_ini(self) -> None:
        # Wheat: Lini=20 days at kc_ini=0.40.
        assert crop_stage_kc("wheat", 0) == 0.40
        assert crop_stage_kc("wheat", 10) == 0.40
        assert crop_stage_kc("wheat", 20) == 0.40

    def test_mid_season_is_flat_at_kc_mid(self) -> None:
        # Wheat mid-season spans day 45-105 (dev_end=45, mid_end=105) at kc_mid=1.15.
        assert crop_stage_kc("wheat", 60) == 1.15
        assert crop_stage_kc("wheat", 105) == 1.15

    def test_ramps_between_stages(self) -> None:
        # Day 32 is 12/25 of the way through wheat's development stage
        # (day 20-45): Kc = 0.40 + (12/25) * (1.15 - 0.40) = 0.76.
        assert abs(crop_stage_kc("wheat", 32) - 0.76) < 0.01

    def test_unknown_crop_falls_back_to_generic_profile(self) -> None:
        assert crop_stage_kc("durian", 0) == crop_stage_kc(None, 0) == 0.50

    def test_case_insensitive_and_clamps_past_harvest(self) -> None:
        assert crop_stage_kc("WHEAT", 0) == crop_stage_kc("wheat", 0)
        assert crop_stage_kc("wheat", 10_000) == 0.40  # kc_end


class TestRootDepthM:
    def test_grows_from_min_to_max_then_flat(self) -> None:
        assert root_depth_m("onion", 0) == 0.15
        assert root_depth_m("onion", 40) == 0.30  # dev_end for onion = 15+25
        assert root_depth_m("onion", 130) == 0.30

    def test_unknown_crop_uses_generic_curve(self) -> None:
        assert root_depth_m("durian", 0) == 0.25


class TestDepletionFraction:
    def test_rice_is_low_wheat_is_higher(self) -> None:
        assert depletion_fraction("rice") == 0.20
        assert depletion_fraction("wheat") == 0.55

    def test_unknown_crop_uses_generic_p(self) -> None:
        assert depletion_fraction("durian") == 0.50


class TestNdviAdjustedKc:
    def test_matches_formula_within_range(self) -> None:
        # onion kc range is [0.70, 1.05]; ndvi=0.6 -> 1.25*0.6+0.1 = 0.85, inside range.
        assert abs(ndvi_adjusted_kc("onion", 0.6) - 0.85) < 1e-9

    def test_clamps_to_crop_range(self) -> None:
        assert ndvi_adjusted_kc("onion", 0.05) == 0.70  # formula gives 0.1625, clamped up
        assert ndvi_adjusted_kc("onion", 0.99) == 1.05  # formula gives 1.3375, clamped down


class TestResolveKc:
    def test_prefers_ndvi_when_given(self) -> None:
        kc, basis = resolve_kc("onion", 40, 0.6)
        assert basis == "ndvi"
        assert abs(kc - 0.85) < 1e-9

    def test_falls_back_to_crop_stage_without_ndvi(self) -> None:
        kc, basis = resolve_kc("wheat", 0, None)
        assert basis == "crop_stage"
        assert kc == 0.40


class TestSoilWater:
    def test_known_texture_lookup(self) -> None:
        assert available_water_capacity_mm_per_m("Loam") == 175.0
        assert available_water_capacity_mm_per_m("Sand") == 90.0

    def test_unknown_or_missing_texture_falls_back_to_default(self) -> None:
        assert available_water_capacity_mm_per_m(None) == available_water_capacity_mm_per_m(DEFAULT_SOIL_TEXTURE)
        assert available_water_capacity_mm_per_m("Loess") == available_water_capacity_mm_per_m(DEFAULT_SOIL_TEXTURE)

    def test_taw_is_awc_times_root_depth(self) -> None:
        assert total_available_water_mm("Loam", 0.5) == 87.5

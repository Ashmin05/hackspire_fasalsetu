"""Unit tests for app/ml/crop_benchmarks.py -- pure math, known inputs,
no Earth Engine or database involved."""

from app.core.satellite_health import GENERIC_STAGE_BENCHMARKS, interpolate_benchmark_curve
from app.ml.crop_benchmarks import CROP_BENCHMARKS, benchmark_ndvi_for_crop


class TestBenchmarkNdviForCrop:
    def test_known_crop_matches_its_own_curve(self) -> None:
        for crop, curve in CROP_BENCHMARKS.items():
            for day, expected_ndvi in curve:
                assert benchmark_ndvi_for_crop(crop, day) == expected_ndvi

    def test_matching_is_case_insensitive(self) -> None:
        assert benchmark_ndvi_for_crop("Wheat", 55) == benchmark_ndvi_for_crop("wheat", 55)
        assert benchmark_ndvi_for_crop("RICE", 0) == CROP_BENCHMARKS["rice"][0][1]

    def test_matching_ignores_surrounding_whitespace(self) -> None:
        assert benchmark_ndvi_for_crop("  onion  ", 45) == CROP_BENCHMARKS["onion"][2][1]

    def test_unknown_crop_falls_back_to_generic_curve(self) -> None:
        assert benchmark_ndvi_for_crop("dragonfruit", 60) == interpolate_benchmark_curve(
            GENERIC_STAGE_BENCHMARKS, 60, default=0.78
        )

    def test_none_crop_falls_back_to_generic_curve(self) -> None:
        assert benchmark_ndvi_for_crop(None, 40) == interpolate_benchmark_curve(
            GENERIC_STAGE_BENCHMARKS, 40, default=0.78
        )

    def test_unknown_sowing_date_falls_back_to_that_crops_own_peak(self) -> None:
        for crop, curve in CROP_BENCHMARKS.items():
            expected_peak = max(ndvi for _, ndvi in curve)
            assert benchmark_ndvi_for_crop(crop, None) == expected_peak

    def test_interpolates_between_a_crops_own_points(self) -> None:
        # Wheat: (25, 0.35) -> (55, 0.65); halfway (day 40) -> 0.50
        assert benchmark_ndvi_for_crop("wheat", 40) == 0.5

    def test_clamps_before_first_point(self) -> None:
        assert benchmark_ndvi_for_crop("maize", -10) == CROP_BENCHMARKS["maize"][0][1]

    def test_clamps_after_last_point(self) -> None:
        assert benchmark_ndvi_for_crop("cotton", 999) == CROP_BENCHMARKS["cotton"][-1][1]

    def test_all_expected_crops_are_present(self) -> None:
        expected = {"rice", "wheat", "onion", "tomato", "sugarcane", "cotton", "maize", "soybean"}
        assert expected.issubset(CROP_BENCHMARKS.keys())

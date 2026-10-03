"""Unit tests for app/core/satellite_health.py -- pure math, known inputs,
no Earth Engine involved at all."""

from datetime import date

import pytest

from app.core.satellite_health import compute_health_score, crop_stage_benchmark_ndvi, days_since


class TestCropStageBenchmarkNdvi:
    def test_unknown_stage_returns_peak_benchmark(self) -> None:
        assert crop_stage_benchmark_ndvi(None) == 0.78

    def test_at_emergence_returns_first_point(self) -> None:
        assert crop_stage_benchmark_ndvi(0) == 0.20

    def test_before_first_point_clamps_to_first_point(self) -> None:
        assert crop_stage_benchmark_ndvi(-5) == 0.20

    def test_at_peak_returns_peak_point(self) -> None:
        assert crop_stage_benchmark_ndvi(60) == 0.78

    def test_past_last_point_clamps_to_last_point(self) -> None:
        assert crop_stage_benchmark_ndvi(500) == 0.30

    def test_interpolates_linearly_between_points(self) -> None:
        # Halfway between (40, 0.65) and (60, 0.78) -> 0.715
        assert crop_stage_benchmark_ndvi(50) == pytest.approx(0.715)

    def test_exact_breakpoint_matches_table_value(self) -> None:
        assert crop_stage_benchmark_ndvi(90) == 0.70


class TestDaysSince:
    def test_none_sowing_date_returns_none(self) -> None:
        assert days_since(None, date(2026, 6, 1)) is None

    def test_computes_day_difference(self) -> None:
        assert days_since(date(2026, 6, 1), date(2026, 7, 1)) == 30

    def test_same_day_is_zero(self) -> None:
        assert days_since(date(2026, 6, 1), date(2026, 6, 1)) == 0


class TestComputeHealthScore:
    def test_ndvi_exactly_at_benchmark_with_no_stress_is_100(self) -> None:
        # ndvi_component = 100 (mean == benchmark), stress_component = 100 (0% stressed)
        # -> 0.7*100 + 0.3*100 = 100
        score = compute_health_score(mean_ndvi=0.6, benchmark_ndvi=0.6, stressed_pct=0.0)
        assert score == 100.0

    def test_ndvi_at_half_benchmark_with_no_stress(self) -> None:
        # ndvi_component = 50, stress_component = 100 -> 0.7*50 + 0.3*100 = 65
        score = compute_health_score(mean_ndvi=0.3, benchmark_ndvi=0.6, stressed_pct=0.0)
        assert score == 65.0

    def test_ndvi_exceeding_benchmark_is_capped_at_full_credit(self) -> None:
        # mean_ndvi double the benchmark still only gives 100% credit, not 200%.
        score_double = compute_health_score(mean_ndvi=1.2, benchmark_ndvi=0.6, stressed_pct=0.0)
        score_exact = compute_health_score(mean_ndvi=0.6, benchmark_ndvi=0.6, stressed_pct=0.0)
        assert score_double == score_exact == 100.0

    def test_full_stress_drags_score_down(self) -> None:
        # ndvi_component = 100, stress_component = 0 -> 0.7*100 + 0.3*0 = 70
        score = compute_health_score(mean_ndvi=0.6, benchmark_ndvi=0.6, stressed_pct=100.0)
        assert score == 70.0

    def test_zero_ndvi_and_full_stress_is_zero(self) -> None:
        score = compute_health_score(mean_ndvi=0.0, benchmark_ndvi=0.6, stressed_pct=100.0)
        assert score == 0.0

    def test_score_never_goes_negative_or_above_100(self) -> None:
        low = compute_health_score(mean_ndvi=-0.5, benchmark_ndvi=0.6, stressed_pct=150.0)
        high = compute_health_score(mean_ndvi=10.0, benchmark_ndvi=0.01, stressed_pct=-50.0)
        assert 0.0 <= low <= 100.0
        assert 0.0 <= high <= 100.0

    def test_zero_or_negative_benchmark_gives_zero_ndvi_credit(self) -> None:
        score = compute_health_score(mean_ndvi=0.5, benchmark_ndvi=0.0, stressed_pct=0.0)
        # ndvi_component = 0 (guarded), stress_component = 100 -> 0.7*0 + 0.3*100 = 30
        assert score == 30.0

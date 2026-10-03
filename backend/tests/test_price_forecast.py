"""Forecasting: leakage safety, chronological validation, selection,
storage and estimate generation.

The series here are synthetic *test inputs* built in this file (so the
expected behaviour is known exactly) -- never presented as market data."""

import json
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import insert, select

from app.ml.price_forecast import evaluate as ev
from app.ml.price_forecast.dataset import HORIZONS, build_dataset, season_of
from app.ml.price_forecast.models import Forecaster, NaiveModel
from app.ml.price_forecast.service import generate_forecasts, train_models
from app.models.market_price import (
    Commodity,
    Market,
    MarketDistrict,
    MarketPriceDaily,
    MarketState,
    PriceForecast,
    PriceForecastModel,
)

START = date(2025, 1, 1)


def synthetic_daily(n_days=500, markets=(1, 2, 3), gaps_every=6, seed=0) -> pd.DataFrame:
    """Trending, seasonal, noisy prices; one day a week without trading."""
    rng = np.random.default_rng(seed)
    rows = []
    for m in markets:
        level = 1000 + 150 * m
        for d in range(n_days):
            if gaps_every and d % gaps_every == 5:
                continue
            day = START + timedelta(days=d)
            price = level * (1 + 0.0004 * d) * (1 + 0.08 * np.sin(2 * np.pi * d / 365)) * (1 + rng.normal(0, 0.01))
            rows.append(
                {"market_id": m, "district_id": 10 + m, "state_id": 1, "commodity_id": 7, "date": day,
                 "modal_price": round(price, 2), "min_price": round(price * 0.95, 2), "max_price": round(price * 1.05, 2),
                 "arrival_quantity": float(50 + rng.integers(0, 20))}
            )
    return pd.DataFrame(rows)


class TestDataset:
    def test_features_never_see_the_future(self) -> None:
        daily = synthetic_daily(n_days=200, markets=(1,))
        base = build_dataset(daily)
        cutoff = pd.Timestamp(START + timedelta(days=120))
        tampered = daily.copy()
        future = pd.to_datetime(tampered["date"]) > cutoff
        tampered.loc[future, ["modal_price", "min_price", "max_price", "arrival_quantity"]] *= 3.0
        changed = build_dataset(tampered)

        feature_cols = [c for c in base.columns if not c.startswith("target")]
        past_a = base[base["date"] <= cutoff][feature_cols].reset_index(drop=True)
        past_b = changed[changed["date"] <= cutoff][feature_cols].reset_index(drop=True)
        pd.testing.assert_frame_equal(past_a, past_b)
        # ...while targets of those same rows do look ahead (that's the point).
        assert not np.allclose(
            base[base["date"] == cutoff - pd.Timedelta(days=5)]["target_7"],
            changed[changed["date"] == cutoff - pd.Timedelta(days=5)]["target_7"],
        )

    def test_targets_use_the_latest_report_within_tolerance(self) -> None:
        daily = synthetic_daily(n_days=40, markets=(1,), gaps_every=0)
        daily = daily[~pd.to_datetime(daily["date"]).isin([pd.Timestamp(START + timedelta(days=17))])]
        ds = build_dataset(daily).set_index("date")
        t = pd.Timestamp(START + timedelta(days=10))
        # t+7 = day 17 has no report -> day 16's price is the target.
        expected = daily.set_index(pd.to_datetime(daily["date"]))["modal_price"][pd.Timestamp(START + timedelta(days=16))]
        assert ds.loc[t, "target_price_7"] == expected
        assert ds.loc[t, "target_date_7"] == t + pd.Timedelta(days=7)

    def test_rows_only_for_traded_days_and_seasons(self) -> None:
        ds = build_dataset(synthetic_daily(n_days=30, markets=(1,), gaps_every=6))
        assert len(ds) == 25  # days 5, 11, 17, 23, 29 had no trading
        assert (season_of(7), season_of(12), season_of(4)) == (0, 1, 2)

    def test_seasonal_feature_needs_a_year_of_history(self) -> None:
        ds = build_dataset(synthetic_daily(n_days=400, markets=(1,), gaps_every=0))
        assert ds[ds["date"] < pd.Timestamp(START + timedelta(days=365))]["seasonal_ratio_7"].isna().all()
        assert ds[ds["date"] >= pd.Timestamp(START + timedelta(days=380))]["seasonal_ratio_7"].notna().all()


class TestValidation:
    def test_folds_are_chronological_and_purged(self) -> None:
        ds = build_dataset(synthetic_daily(n_days=300))
        for h in HORIZONS:
            split = list(ev.folds(ds, h))
            assert len(split) == ev.N_FOLDS
            previous_test_start = None
            for _, train_idx, test_idx in split:
                test_start = ds.loc[test_idx, "date"].min()
                assert ds.loc[train_idx, f"target_date_{h}"].max() < test_start  # no target reaches the test period
                assert set(train_idx).isdisjoint(test_idx)
                assert previous_test_start is None or test_start > previous_test_start
                previous_test_start = test_start

    def test_metrics(self) -> None:
        m = ev.metrics(np.array([100.0, 200.0]), np.array([110.0, 180.0]))
        assert (m["mae"], m["rmse"], m["mape"]) == (15.0, round(float(np.sqrt(250)), 2), 10.0)

    def test_non_finite_values_never_reach_metrics_or_storage(self) -> None:
        # Regression: an extrapolating model once produced exp(huge) = inf,
        # which Postgres JSONB rejected as "Infinity".
        from app.ml.price_forecast.models import MAX_ABS_LOG_CHANGE, bounded
        from app.ml.price_forecast.service import json_safe

        capped = bounded([np.inf, -np.inf, np.nan, 40.0, 0.1])
        assert list(capped) == [MAX_ABS_LOG_CHANGE, -MAX_ABS_LOG_CHANGE, 0.0, MAX_ABS_LOG_CHANGE, 0.1]
        assert ev.metrics(np.array([100.0]), np.array([np.inf]))["mae"] is None
        assert json_safe({"a": np.float64("inf"), "b": [np.nan, np.int64(3)], "c": np.float32(1.5)}) == {"a": None, "b": [None, 3], "c": 1.5}

    def test_wild_extrapolation_is_capped_during_validation(self) -> None:
        class Wild(Forecaster):
            name, kind = "wild", "learned"

            def predict(self, X):
                return np.full(len(X), 50.0)  # exp(50) x today's price

        ds = build_dataset(synthetic_daily(n_days=300))
        result = ev.evaluate(ds, 7, model_classes=(NaiveModel, Wild))
        assert np.isfinite(result.results["wild"].pooled["mae"]) and result.selected == "naive"

    def test_a_learned_model_must_beat_the_best_baseline(self) -> None:
        class Worse(Forecaster):
            name, kind = "worse", "learned"

            def predict(self, X):
                return np.full(len(X), 0.2)

        ds = build_dataset(synthetic_daily(n_days=300))
        result = ev.evaluate(ds, 7, model_classes=(NaiveModel, Worse))
        assert result.selected == "naive"
        assert "no learned model beat" in result.selection_note
        summary = result.summary()
        assert set(summary["models"]) == {"naive", "worse"} and summary["models"]["worse"]["mae"] > summary["models"]["naive"]["mae"]

    def test_interval_coverage_is_measured_out_of_sample(self) -> None:
        ds = build_dataset(synthetic_daily(n_days=300))
        result = ev.evaluate(ds, 7, model_classes=(NaiveModel,))
        low, high = result.interval_log_quantiles
        assert low < 0 < high
        assert 0.0 <= result.holdout_coverage <= 1.0


async def seed(session, daily: pd.DataFrame) -> tuple[int, int]:
    state = MarketState(external_id="1", name="Test State", name_key="test state")
    commodity = Commodity(external_id="7", name="Test Crop", name_key="test crop")
    session.add_all([state, commodity])
    await session.flush()
    ids = {}
    for m in sorted(daily["market_id"].unique()):
        district = MarketDistrict(state_id=state.id, name=f"D{m}", name_key=f"d{m}")
        session.add(district)
        await session.flush()
        market = Market(state_id=state.id, district_id=district.id, name=f"Market {m}", name_key=f"market {m}")
        session.add(market)
        await session.flush()
        ids[m] = market.id
    rows = [
        {"market_id": ids[r.market_id], "commodity_id": commodity.id, "date": r.date, "state_id": state.id,
         "modal_price": Decimal(str(r.modal_price)), "min_price": Decimal(str(r.min_price)),
         "max_price": Decimal(str(r.max_price)), "arrival_quantity": Decimal(str(r.arrival_quantity)),
         "report_count": 1, "weighted": True, "source": "agmarknet"}
        for r in daily.itertuples()
    ]
    await session.execute(insert(MarketPriceDaily), rows)
    await session.commit()
    return commodity.id, state.id


class TestTrainAndForecast:
    async def test_trains_stores_and_forecasts(self, session, tmp_path, monkeypatch) -> None:
        import app.ml.price_forecast.models as models

        monkeypatch.setattr(models.RandomForestModel, "fit", _small_forest_fit)
        daily = synthetic_daily(n_days=420, markets=(1, 2, 3))
        # Market 3 stopped reporting a month ago -> no forecast for it.
        daily = daily[~((daily["market_id"] == 3) & (pd.to_datetime(daily["date"]) > pd.Timestamp(START + timedelta(days=390))))]
        commodity_id, state_id = await seed(session, daily)

        registered = await train_models(session, commodity_id, state_id, model_dir=tmp_path)

        assert sorted(m.horizon_days for m in registered) == list(HORIZONS)
        for m in registered:
            folder = tmp_path / "test-crop" / "test-state" / f"{m.horizon_days}d" / m.model_version
            meta = json.loads((folder / "metadata.json").read_text())
            metrics = json.loads((folder / "metrics.json").read_text())
            assert (folder / "model.pkl").exists()
            assert meta["model_name"] == m.model_name and meta["training_data"]["markets"] == 3
            assert {"naive", "moving_average", "seasonal_naive", "ridge", "random_forest", "lightgbm", "lightgbm_huber"} <= set(metrics["models"])
            assert m.mae is not None and m.interval_low_log < m.interval_high_log

        written = await generate_forecasts(session, commodity_id, state_id)
        forecasts = (await session.scalars(select(PriceForecast))).all()
        assert written == len(forecasts) == 2 * len(HORIZONS)  # markets 1 and 2 only
        for f in forecasts:
            assert f.lower_bound <= f.predicted_price <= f.upper_bound
            assert f.forecast_date == f.base_date + timedelta(days=f.horizon_days)

        # Re-running replaces rather than duplicates; retraining deactivates old models.
        await generate_forecasts(session, commodity_id, state_id)
        assert len((await session.scalars(select(PriceForecast))).all()) == len(forecasts)
        await train_models(session, commodity_id, state_id, model_dir=tmp_path)
        active = (await session.scalars(select(PriceForecastModel).where(PriceForecastModel.is_active.is_(True)))).all()
        assert len(active) == len(HORIZONS)

    async def test_too_little_history_trains_nothing(self, session, tmp_path) -> None:
        commodity_id, state_id = await seed(session, synthetic_daily(n_days=100, markets=(1,)))
        assert await train_models(session, commodity_id, state_id, model_dir=tmp_path) == []
        assert await generate_forecasts(session, commodity_id, state_id) == 0


def _small_forest_fit(self, X, y):
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import make_pipeline

    self.model = make_pipeline(SimpleImputer(strategy="median"), RandomForestRegressor(n_estimators=10, max_depth=6, random_state=0))
    self.model.fit(X[self.features], y)
    return self


@pytest.fixture(autouse=True)
def _quiet_lightgbm(monkeypatch):
    import warnings

    warnings.filterwarnings("ignore", category=UserWarning)

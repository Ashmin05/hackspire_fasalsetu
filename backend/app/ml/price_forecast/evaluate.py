"""Chronological validation and model selection.

Rolling-origin (expanding window) evaluation, never a random split:

    fold k:  train = samples whose TARGET date < cutoff_k   (purged)
             test  = samples whose ORIGIN date in [cutoff_k, cutoff_k + FOLD_DAYS)

Purging on the target date matters: a sample from just before the cutoff
has a target inside the test period, and training on it would leak the
answer. The last fold is the most recent month -- the closest analogue to
forecasting tomorrow.

Metrics are in price space (Rs/quintal): MAE, RMSE and MAPE. Mandi modal
prices are strictly positive (zero-price reports are rejected at
ingestion), so MAPE is well-defined; any actual below MIN_PRICE_FOR_MAPE is
excluded from MAPE and counted.

Selection: lowest pooled MAE across folds. A learned model is chosen only
if it beats the best baseline; otherwise the baseline is used and the
metrics say so.

Prediction intervals: empirical quantiles of the chosen model's validation
errors (in log space) -- 10th/90th percentile = an 80% interval. Coverage
is checked honestly: quantiles from the earlier folds, coverage measured on
the last fold.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.ml.price_forecast.models import ALL_MODELS, Forecaster, bounded

N_FOLDS = 4
FOLD_DAYS = 30
MIN_PRICE_FOR_MAPE = 1.0
INTERVAL = (0.10, 0.90)


def _finite(value: float, digits: int = 2) -> float | None:
    return round(float(value), digits) if np.isfinite(value) else None


def metrics(actual: np.ndarray, predicted: np.ndarray) -> dict:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    errors = predicted - actual
    mape_mask = actual >= MIN_PRICE_FOR_MAPE
    return {
        "n": int(len(actual)),
        "mae": _finite(np.mean(np.abs(errors))) if len(actual) else None,
        "rmse": _finite(np.sqrt(np.mean(errors**2))) if len(actual) else None,
        "mape": _finite(np.mean(np.abs(errors[mape_mask] / actual[mape_mask])) * 100) if mape_mask.any() else None,
        "mape_excluded": int((~mape_mask).sum()),
    }


def folds(ds: pd.DataFrame, horizon: int, *, n_folds: int = N_FOLDS, fold_days: int = FOLD_DAYS):
    """Yield (fold_no, train_index, test_index). Only samples with a known
    target take part."""
    target = f"target_{horizon}"
    usable = ds[ds[target].notna()]
    if usable.empty:
        return
    last_origin = usable["date"].max()
    for k in range(n_folds):
        cutoff = last_origin - pd.Timedelta(days=fold_days * (n_folds - k) - 1)
        test = usable[(usable["date"] >= cutoff) & (usable["date"] < cutoff + pd.Timedelta(days=fold_days))]
        train = usable[usable[f"target_date_{horizon}"] < cutoff]
        if len(test) and len(train):
            yield k, train.index, test.index


@dataclass
class ModelResult:
    name: str
    kind: str
    pooled: dict
    by_fold: list[dict] = field(default_factory=list)
    by_market: dict[int, dict] = field(default_factory=dict)
    log_errors: np.ndarray = field(default_factory=lambda: np.array([]))
    fold_of_error: np.ndarray = field(default_factory=lambda: np.array([]))


@dataclass
class Evaluation:
    horizon: int
    results: dict[str, ModelResult]
    selected: str
    selection_note: str
    interval_log_quantiles: tuple[float, float] | None
    holdout_coverage: float | None
    n_train_last_fold: int
    n_test_total: int

    def summary(self) -> dict:
        return {
            "horizon_days": self.horizon,
            "selected_model": self.selected,
            "selection_note": self.selection_note,
            "interval": {"quantiles": INTERVAL, "log_error_quantiles": self.interval_log_quantiles,
                         "holdout_coverage": self.holdout_coverage},
            "validation": {"scheme": f"rolling origin, {N_FOLDS} folds x {FOLD_DAYS} days, purged on target date",
                           "test_samples": self.n_test_total, "train_samples_last_fold": self.n_train_last_fold},
            "models": {
                name: {"kind": r.kind, **r.pooled, "by_fold": r.by_fold}
                for name, r in self.results.items()
            },
            "by_market_mae": {str(m): v for m, v in self.results[self.selected].by_market.items()},
        }


def evaluate(ds: pd.DataFrame, horizon: int, model_classes=ALL_MODELS) -> Evaluation | None:
    target = f"target_{horizon}"
    target_price = f"target_price_{horizon}"
    split = list(folds(ds, horizon))
    if not split:
        return None

    results: dict[str, ModelResult] = {}
    for cls in model_classes:
        model: Forecaster = cls(horizon)
        actual_all, pred_all, err_all, fold_all, market_all = [], [], [], [], []
        by_fold = []
        for k, train_idx, test_idx in split:
            train, test = ds.loc[train_idx], ds.loc[test_idx]
            model.fit(train, train[target])
            pred_log = bounded(model.predict(test))
            predicted = test["current_modal_price"].to_numpy() * np.exp(pred_log)
            actual = test[target_price].to_numpy()
            by_fold.append({"fold": k, "from": str(test["date"].min().date()), "to": str(test["date"].max().date()),
                            **metrics(actual, predicted)})
            actual_all.append(actual)
            pred_all.append(predicted)
            err_all.append(test[target].to_numpy() - pred_log)
            fold_all.append(np.full(len(test), k))
            market_all.append(test["market_id"].to_numpy())
        actual, predicted = np.concatenate(actual_all), np.concatenate(pred_all)
        markets = np.concatenate(market_all)
        by_market = {int(m): metrics(actual[markets == m], predicted[markets == m])["mae"] for m in np.unique(markets)}
        results[cls.name] = ModelResult(
            name=cls.name, kind=cls.kind, pooled=metrics(actual, predicted), by_fold=by_fold,
            by_market=by_market, log_errors=np.concatenate(err_all), fold_of_error=np.concatenate(fold_all),
        )

    baselines = {n: r for n, r in results.items() if r.kind == "baseline"}
    learned = {n: r for n, r in results.items() if r.kind == "learned"}
    def mae(r: ModelResult) -> float:
        return r.pooled["mae"] if r.pooled["mae"] is not None else float("inf")

    best_baseline = min(baselines.values(), key=mae)
    best_learned = min(learned.values(), key=mae) if learned else None
    if best_learned and mae(best_learned) < mae(best_baseline):
        selected = best_learned
        gain = (1 - best_learned.pooled["mae"] / best_baseline.pooled["mae"]) * 100
        note = f"{selected.name} beat the best baseline ({best_baseline.name}) by {gain:.1f}% MAE"
    else:
        selected = best_baseline
        note = (
            f"no learned model beat the best baseline ({best_baseline.name})"
            if best_learned else f"baseline {best_baseline.name} (no learned models evaluated)"
        )

    errors, fold_ids = selected.log_errors, selected.fold_of_error
    quantiles = tuple(float(q) for q in np.quantile(errors, INTERVAL)) if len(errors) >= 20 else None
    coverage = None
    last = fold_ids.max()
    earlier, holdout = errors[fold_ids < last], errors[fold_ids == last]
    if len(earlier) >= 20 and len(holdout):
        lo, hi = np.quantile(earlier, INTERVAL)
        coverage = round(float(np.mean((holdout >= lo) & (holdout <= hi))), 3)

    return Evaluation(
        horizon=horizon,
        results=results,
        selected=selected.name,
        selection_note=note,
        interval_log_quantiles=quantiles,
        holdout_coverage=coverage,
        n_train_last_fold=len(split[-1][1]),
        n_test_total=int(sum(len(t) for _, _, t in split)),
    )

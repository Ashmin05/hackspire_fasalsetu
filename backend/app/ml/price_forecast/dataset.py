"""Time-series dataset for mandi price forecasting.

One sample = one market on one day it traded (the "origin" t). Features use
only information available at t; the target is the modal price h days later.

Leakage rules:
* every feature is computed from the market's series up to and including t
  (lags/rolling windows look backwards only; the seasonal feature looks at
  last year's values, which are all before t);
* targets are what the market actually reported around t+h (the latest
  report in [t+h-3, t+h] -- mandis don't trade every day);
* validation splits by time and purges training samples whose *target*
  date reaches into the test period (see evaluate.py).

Prices vary a lot between markets, so models learn *relative* moves:
target = log(price_{t+h} / price_t) and most features are ratios to price_t.
The forecast is price_t * exp(prediction).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (7, 14, 30)
# A target is the latest report within this many days before t+h.
TARGET_TOLERANCE_DAYS = 3
# Carry a price forward at most this long for lag/change features.
FFILL_LIMIT_DAYS = 14

# Indian cropping seasons by calendar month.
KHARIF, RABI, ZAID = 0, 1, 2


def season_of(month: int) -> int:
    if 6 <= month <= 10:
        return KHARIF
    if month >= 11 or month <= 3:
        return RABI
    return ZAID


LAGS = (1, 3, 7, 14, 30)
WINDOWS = (7, 14, 30)

# Model inputs. ID columns are only used by the tree models.
RELATIVE_FEATURES = [
    *(f"lag_{k}_ratio" for k in LAGS),
    *(f"rolling_mean_{w}_ratio" for w in WINDOWS),
    *(f"rolling_std_{w}_rel" for w in WINDOWS),
    "price_range_rel",
    "change_7d",
    "change_30d",
    "log_arrival_quantity",
    "arrival_lag_7_log",
    "arrival_rolling_mean_7_log",
    "arrival_rolling_mean_30_log",
    "arrival_vs_30d",
    "trading_days_30",
]
CALENDAR_FEATURES = ["day", "month", "week", "day_of_week", "day_of_year", "season", "doy_sin", "doy_cos"]
ID_FEATURES = ["market_code", "district_code"]


def seasonal_feature(h: int) -> str:
    return f"seasonal_ratio_{h}"


def model_features(h: int, *, with_ids: bool) -> list[str]:
    return [*RELATIVE_FEATURES, *CALENDAR_FEATURES, seasonal_feature(h), *(ID_FEATURES if with_ids else [])]


def _market_frame(g: pd.DataFrame) -> pd.DataFrame:
    """One market's daily rows -> calendar-day frame with every feature."""
    g = g.sort_values("date").set_index("date")
    full = g.reindex(pd.date_range(g.index.min(), g.index.max(), freq="D"))
    modal = full["modal_price"]
    observed = modal.notna()
    carried = modal.ffill(limit=FFILL_LIMIT_DAYS)
    arrivals = full["arrival_quantity"]

    f = pd.DataFrame(index=full.index)
    f["observed"] = observed
    f["current_modal_price"] = modal
    f["min_price"] = full["min_price"]
    f["max_price"] = full["max_price"]
    f["arrival_quantity"] = arrivals

    for k in LAGS:
        f[f"lag_{k}"] = carried.shift(k)
        f[f"lag_{k}_ratio"] = np.log(f[f"lag_{k}"] / modal)
    for w in WINDOWS:
        mean = modal.rolling(w, min_periods=max(2, w // 4)).mean()
        std = modal.rolling(w, min_periods=max(3, w // 4)).std()
        f[f"rolling_mean_{w}"] = mean
        f[f"rolling_std_{w}"] = std
        f[f"rolling_mean_{w}_ratio"] = np.log(mean / modal)
        f[f"rolling_std_{w}_rel"] = std / mean
    f["price_range"] = full["max_price"] - full["min_price"]
    f["price_range_rel"] = f["price_range"] / modal
    f["change_7d"] = modal / carried.shift(7) - 1
    f["change_30d"] = modal / carried.shift(30) - 1

    f["log_arrival_quantity"] = np.log1p(arrivals)
    f["arrival_lag_7"] = arrivals.shift(7)
    f["arrival_lag_7_log"] = np.log1p(f["arrival_lag_7"])
    f["arrival_rolling_mean_7"] = arrivals.rolling(7, min_periods=1).mean()
    f["arrival_rolling_mean_30"] = arrivals.rolling(30, min_periods=3).mean()
    f["arrival_rolling_mean_7_log"] = np.log1p(f["arrival_rolling_mean_7"])
    f["arrival_rolling_mean_30_log"] = np.log1p(f["arrival_rolling_mean_30"])
    f["arrival_vs_30d"] = np.log1p(arrivals) - np.log1p(f["arrival_rolling_mean_30"])
    f["trading_days_30"] = observed.astype(float).rolling(30, min_periods=1).sum()

    idx = f.index
    f["day"] = idx.day
    f["month"] = idx.month
    f["week"] = idx.isocalendar().week.astype(int).to_numpy()
    f["day_of_week"] = idx.dayofweek
    f["day_of_year"] = idx.dayofyear
    f["season"] = [season_of(m) for m in idx.month]
    f["doy_sin"] = np.sin(2 * np.pi * idx.dayofyear / 365.25)
    f["doy_cos"] = np.cos(2 * np.pi * idx.dayofyear / 365.25)

    for h in HORIZONS:
        # Last year's move over the same stretch: price(t-365+h)/price(t-365).
        # Both points are before t, so this is known at t.
        f[seasonal_feature(h)] = np.log(carried.shift(365 - h) / carried.shift(365))
        # Target: latest report within [t+h-TOL, t+h], closest to t+h first.
        target = pd.Series(np.nan, index=idx)
        for back in range(TARGET_TOLERANCE_DAYS + 1):
            target = target.fillna(modal.shift(-(h - back)))
        f[f"target_price_{h}"] = target
        f[f"target_{h}"] = np.log(target / modal)

    f = f[observed]
    f.index.name = "date"
    return f.reset_index()


def build_dataset(daily: pd.DataFrame) -> pd.DataFrame:
    """`daily`: columns market_id, district_id, state_id, commodity_id, date,
    modal_price, min_price, max_price, arrival_quantity (one row per market
    and day, as in market_price_daily). Returns one row per market x traded
    day with features, targets (NaN where the future isn't known yet) and
    target dates."""
    if daily.empty:
        return pd.DataFrame()
    daily = daily.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    for column in ("modal_price", "min_price", "max_price", "arrival_quantity"):
        daily[column] = pd.to_numeric(daily[column], errors="coerce").astype(float)
    frames = []
    for (market_id, district_id, state_id, commodity_id), g in daily.groupby(
        ["market_id", "district_id", "state_id", "commodity_id"], dropna=False
    ):
        frame = _market_frame(g[["date", "modal_price", "min_price", "max_price", "arrival_quantity"]])
        frame["market_id"] = market_id
        frame["district_id"] = district_id
        frame["state_id"] = state_id
        frame["commodity_id"] = commodity_id
        frames.append(frame)
    ds = pd.concat(frames, ignore_index=True)
    ds["market_code"] = ds["market_id"].astype(int)
    ds["district_code"] = ds["district_id"].fillna(-1).astype(int)
    for h in HORIZONS:
        ds[f"target_date_{h}"] = ds["date"] + pd.Timedelta(days=h)
    return ds.replace([np.inf, -np.inf], np.nan).sort_values(["date", "market_id"]).reset_index(drop=True)

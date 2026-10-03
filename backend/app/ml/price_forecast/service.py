"""Train, store and apply price forecasters.

train_models(): for one commodity in one state, build the dataset from
market_price_daily, evaluate every candidate per horizon (evaluate.py),
refit the selected one on all labelled data, write the artifact
(PRICE_MODEL_DIR/<commodity>/<state>/<horizon>d/<version>/) and register it
as the active model for that slot.

generate_forecasts(): apply the active models to each market's latest data
and store 7/14/30-day estimates with their expected range. Markets whose
data is stale or too thin get no forecast (the API then says why) rather
than a made-up one. Both are scheduled work -- never run per request.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ml.price_forecast.dataset import HORIZONS, build_dataset
from app.ml.price_forecast.evaluate import INTERVAL, evaluate
from app.ml.price_forecast.models import ALL_MODELS, bounded
from app.models.market_price import (
    Commodity,
    Market,
    MarketPriceDaily,
    MarketState,
    PriceForecast,
    PriceForecastModel,
)

logger = logging.getLogger(__name__)

# Minimums before a model is trained / a market gets a forecast.
MIN_TRAIN_SAMPLES = 500
MIN_HISTORY_DAYS = 180
FORECAST_MAX_STALENESS_DAYS = 10  # vs the commodity's newest report in the state
FORECAST_MIN_TRADING_DAYS_60 = 15
# Enough history for the 365-day seasonal feature plus a margin.
FORECAST_LOOKBACK_DAYS = 400


def json_safe(value):
    """Plain JSON: NaN/inf -> None (Postgres JSONB rejects them), numpy -> Python."""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


async def load_daily_frame(
    session: AsyncSession, commodity_id: int, state_id: int, *, since: date | None = None
) -> pd.DataFrame:
    query = (
        select(
            MarketPriceDaily.market_id,
            Market.district_id,
            MarketPriceDaily.state_id,
            MarketPriceDaily.commodity_id,
            MarketPriceDaily.date,
            MarketPriceDaily.modal_price,
            MarketPriceDaily.min_price,
            MarketPriceDaily.max_price,
            MarketPriceDaily.arrival_quantity,
        )
        .join(Market, Market.id == MarketPriceDaily.market_id)
        .where(MarketPriceDaily.commodity_id == commodity_id, MarketPriceDaily.state_id == state_id)
    )
    if since is not None:
        query = query.where(MarketPriceDaily.date >= since)
    rows = (await session.execute(query)).all()
    columns = ["market_id", "district_id", "state_id", "commodity_id", "date", "modal_price", "min_price", "max_price", "arrival_quantity"]
    return pd.DataFrame(rows, columns=columns)


@dataclass
class TrainedSlot:
    horizon: int
    model: object
    evaluation: dict
    interval: tuple[float, float] | None
    selected: str
    pooled: dict
    n_samples: int


def _train_sync(ds: pd.DataFrame) -> list[TrainedSlot]:
    """CPU-bound part (run in a worker thread)."""
    slots = []
    for h in HORIZONS:
        labelled = ds[ds[f"target_{h}"].notna()]
        if len(labelled) < MIN_TRAIN_SAMPLES:
            logger.info("Horizon %sd: only %d labelled samples -- not training", h, len(labelled))
            continue
        result = evaluate(ds, h)
        if result is None:
            continue
        cls = next(c for c in ALL_MODELS if c.name == result.selected)
        model = cls(h).fit(labelled, labelled[f"target_{h}"])
        slots.append(
            TrainedSlot(
                horizon=h,
                model=model,
                evaluation=result.summary(),
                interval=result.interval_log_quantiles,
                selected=result.selected,
                pooled=result.results[result.selected].pooled,
                n_samples=len(labelled),
            )
        )
    return slots


async def train_models(session: AsyncSession, commodity_id: int, state_id: int, *, model_dir: Path | None = None) -> list[PriceForecastModel]:
    commodity = await session.get(Commodity, commodity_id)
    state = await session.get(MarketState, state_id)
    daily = await load_daily_frame(session, commodity_id, state_id)
    if daily.empty:
        logger.info("No price history for %s in %s -- nothing to train", commodity.name, state.name)
        return []
    start, end = min(daily["date"]), max(daily["date"])
    if (end - start).days < MIN_HISTORY_DAYS:
        logger.info("%s in %s: only %d days of history -- not training", commodity.name, state.name, (end - start).days)
        return []

    ds = build_dataset(daily)
    slots = await asyncio.to_thread(_train_sync, ds)

    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_dir = (model_dir or settings.price_model_dir) / slug(commodity.name) / slug(state.name)
    registered = []
    for slot in slots:
        folder = base_dir / f"{slot.horizon}d" / version
        folder.mkdir(parents=True, exist_ok=True)
        joblib.dump(slot.model, folder / "model.pkl")
        metadata = {
            "commodity": commodity.name,
            "commodity_id": commodity_id,
            "state": state.name,
            "state_id": state_id,
            "horizon_days": slot.horizon,
            "model_name": slot.selected,
            "model_version": version,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "training_data": {"from": str(start), "to": str(end), "samples": slot.n_samples,
                              "markets": int(daily["market_id"].nunique())},
            "features": slot.model.features,
            "target": f"log(modal_price[t+{slot.horizon}] / modal_price[t])",
            "interval": {"quantiles": INTERVAL, "log_error_quantiles": slot.interval},
        }
        (folder / "metadata.json").write_text(json.dumps(json_safe(metadata), indent=2), encoding="utf-8")
        (folder / "metrics.json").write_text(json.dumps(json_safe(slot.evaluation), indent=2), encoding="utf-8")

        await session.execute(
            update(PriceForecastModel)
            .where(
                PriceForecastModel.commodity_id == commodity_id,
                PriceForecastModel.state_id == state_id,
                PriceForecastModel.horizon_days == slot.horizon,
            )
            .values(is_active=False)
        )
        row = PriceForecastModel(
            commodity_id=commodity_id,
            state_id=state_id,
            horizon_days=slot.horizon,
            model_name=slot.selected,
            model_version=version,
            train_start=start,
            train_end=end,
            n_samples=slot.n_samples,
            n_markets=int(daily["market_id"].nunique()),
            features=slot.model.features,
            mae=slot.pooled["mae"],
            rmse=slot.pooled["rmse"],
            mape=slot.pooled["mape"],
            evaluation=json_safe(slot.evaluation),
            interval_low_log=slot.interval[0] if slot.interval else None,
            interval_high_log=slot.interval[1] if slot.interval else None,
            artifact_path=str(folder),
            is_active=True,
        )
        session.add(row)
        registered.append(row)
        logger.info(
            "Trained %s %s %sd: %s (MAE %.1f, MAPE %s%%) -- %s",
            commodity.name, state.name, slot.horizon, slot.selected, slot.pooled["mae"], slot.pooled["mape"],
            slot.evaluation["selection_note"],
        )
    await session.commit()
    return registered


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def generate_forecasts(session: AsyncSession, commodity_id: int, state_id: int) -> int:
    """Forecast every eligible market of one commodity in one state with the
    active models. Returns forecasts written."""
    models = (
        await session.scalars(
            select(PriceForecastModel).where(
                PriceForecastModel.commodity_id == commodity_id,
                PriceForecastModel.state_id == state_id,
                PriceForecastModel.is_active.is_(True),
            )
        )
    ).all()
    if not models:
        return 0
    loaded = {}
    for m in models:
        path = Path(m.artifact_path) / "model.pkl"
        if not path.exists():
            logger.warning("Model artifact missing: %s", path)
            continue
        loaded[m.horizon_days] = (m, joblib.load(path))
    if not loaded:
        return 0

    newest = await session.scalar(
        select(MarketPriceDaily.date)
        .where(MarketPriceDaily.commodity_id == commodity_id, MarketPriceDaily.state_id == state_id)
        .order_by(MarketPriceDaily.date.desc())
        .limit(1)
    )
    if newest is None:
        return 0
    daily = await load_daily_frame(session, commodity_id, state_id, since=newest - timedelta(days=FORECAST_LOOKBACK_DAYS))
    ds = build_dataset(daily)
    if ds.empty:
        return 0
    latest = ds.sort_values("date").groupby("market_id").tail(1)
    newest_ts = pd.Timestamp(newest)
    recent = daily[pd.to_datetime(daily["date"]) > newest_ts - pd.Timedelta(days=60)].groupby("market_id").size()
    eligible = latest[
        (latest["date"] >= newest_ts - pd.Timedelta(days=FORECAST_MAX_STALENESS_DAYS))
        & (latest["market_id"].map(recent).fillna(0) >= FORECAST_MIN_TRADING_DAYS_60)
    ]

    now = datetime.now(timezone.utc)
    rows = []
    for h, (meta, model) in loaded.items():
        if eligible.empty:
            break
        pred_log = bounded(model.predict(eligible))
        for (_, sample), log_ratio in zip(eligible.iterrows(), pred_log):
            base = float(sample["current_modal_price"])
            predicted = base * float(np.exp(log_ratio))
            lower = base * float(np.exp(log_ratio + meta.interval_low_log)) if meta.interval_low_log is not None else None
            upper = base * float(np.exp(log_ratio + meta.interval_high_log)) if meta.interval_high_log is not None else None
            base_date = sample["date"].date()
            rows.append(
                PriceForecast(
                    market_id=int(sample["market_id"]),
                    commodity_id=commodity_id,
                    model_id=meta.id,
                    base_date=base_date,
                    base_price=_money(base),
                    forecast_date=base_date + timedelta(days=h),
                    horizon_days=h,
                    predicted_price=_money(predicted),
                    lower_bound=_money(lower) if lower is not None else None,
                    upper_bound=_money(upper) if upper is not None else None,
                    model_name=meta.model_name,
                    model_version=meta.model_version,
                    generated_at=now,
                )
            )
    market_ids = [int(m) for m in eligible["market_id"]]
    # Replace today's run for these markets (re-running is idempotent).
    if market_ids:
        await session.execute(
            delete(PriceForecast).where(
                PriceForecast.commodity_id == commodity_id,
                PriceForecast.market_id.in_(market_ids),
                PriceForecast.model_id.in_([m.id for m, _ in loaded.values()]),
                PriceForecast.base_date.in_({r.base_date for r in rows}),
            )
        )
    session.add_all(rows)
    await session.commit()
    logger.info("Generated %d forecast(s) for commodity %s in state %s (%d markets)", len(rows), commodity_id, state_id, len(market_ids))
    return len(rows)

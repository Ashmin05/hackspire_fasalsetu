"""Price analytics, precomputed after ingestion.

1. rebuild_daily(): market_prices -> market_price_daily (one price per
   market x commodity x day; see MarketPriceDaily for how several reports
   in a day are combined).
2. refresh_stats(): market_price_daily -> market_price_stats, per market x
   commodity, as of that market's latest report.

Definitions (modal price is the primary metric throughout):
* N-day average / min / max: over trading days in the N calendar days
  ending at the as-of date (inclusive).
* N-day change: (current - reference) / reference x 100, where reference is
  the latest price on or before (as_of - N days), found within a grace
  window (N=7: up to 7 more days back; N=30: up to 15). No reference, or a
  zero reference -> None, never a division by zero.
* Volatility: standard deviation of day-to-day % changes over the last 30
  days (needs >= 5 changes).
* Trend: mean of the last 7 days vs mean of the 7 days before them;
  >= +TREND_THRESHOLD_PCT increasing, <= -TREND_THRESHOLD_PCT decreasing,
  otherwise stable; fewer than 3 trading days in either window ->
  insufficient_data.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_price import MarketPrice, MarketPriceDaily, MarketPriceStats

# Earlier in the list wins when two sources report the same market/day.
SOURCE_PRIORITY = ("agmarknet", "data_gov_in", "ceda")
TREND_THRESHOLD_PCT = 2.5
MIN_TREND_DAYS = 3
TWO = Decimal("0.01")
THREE = Decimal("0.001")


def _money(value: float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(TWO, rounding=ROUND_HALF_UP)


def _rank(source: str) -> int:
    return SOURCE_PRIORITY.index(source) if source in SOURCE_PRIORITY else len(SOURCE_PRIORITY)


# ---------------------------------------------------------------------------
# Daily series
# ---------------------------------------------------------------------------


async def rebuild_daily(session: AsyncSession, commodity_id: int, *, since: date | None = None) -> int:
    """Recompute market_price_daily for one commodity from `since` (all
    history when None). Returns rows written."""
    grouped = (
        select(
            MarketPrice.market_id,
            MarketPrice.state_id,
            MarketPrice.arrival_date,
            MarketPrice.source,
            func.count().label("n"),
            func.count(MarketPrice.arrival_quantity).label("n_arrivals"),
            func.sum(MarketPrice.arrival_quantity).label("arrivals"),
            func.sum(MarketPrice.modal_price * MarketPrice.arrival_quantity).label("weighted_sum"),
            func.avg(MarketPrice.modal_price).label("mean_modal"),
            func.min(func.coalesce(MarketPrice.min_price, MarketPrice.modal_price)).label("low"),
            func.max(func.coalesce(MarketPrice.max_price, MarketPrice.modal_price)).label("high"),
        )
        .where(MarketPrice.commodity_id == commodity_id)
        .group_by(MarketPrice.market_id, MarketPrice.state_id, MarketPrice.arrival_date, MarketPrice.source)
    )
    if since is not None:
        grouped = grouped.where(MarketPrice.arrival_date >= since)

    best: dict[tuple[int, date], dict] = {}
    for row in (await session.execute(grouped)).mappings():
        key = (row["market_id"], row["arrival_date"])
        if key in best and _rank(best[key]["source"]) <= _rank(row["source"]):
            continue
        best[key] = dict(row)

    rows = []
    for (market_id, day), r in best.items():
        arrivals = Decimal(str(r["arrivals"])) if r["arrivals"] is not None else None
        weighted = r["n_arrivals"] == r["n"] and arrivals is not None and arrivals > 0
        modal = Decimal(str(r["weighted_sum"])) / arrivals if weighted else Decimal(str(r["mean_modal"]))
        rows.append(
            {
                "market_id": market_id,
                "commodity_id": commodity_id,
                "date": day,
                "state_id": r["state_id"],
                "modal_price": _money(modal),
                "min_price": _money(r["low"]),
                "max_price": _money(r["high"]),
                "arrival_quantity": arrivals.quantize(THREE) if arrivals is not None else None,
                "report_count": r["n"],
                "weighted": weighted,
                "source": r["source"],
            }
        )

    stmt = delete(MarketPriceDaily).where(MarketPriceDaily.commodity_id == commodity_id)
    if since is not None:
        stmt = stmt.where(MarketPriceDaily.date >= since)
    await session.execute(stmt)
    for i in range(0, len(rows), 1000):
        await session.execute(insert(MarketPriceDaily), rows[i : i + 1000])
    return len(rows)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@dataclass
class DayPrice:
    date: date
    modal: float
    low: float | None = None
    high: float | None = None
    arrivals: float | None = None


def _window(series: list[DayPrice], as_of: date, days: int) -> list[DayPrice]:
    start = as_of - timedelta(days=days - 1)
    return [p for p in series if start <= p.date <= as_of]


def _reference(series: list[DayPrice], target: date, grace_days: int) -> DayPrice | None:
    earliest = target - timedelta(days=grace_days)
    candidates = [p for p in series if earliest <= p.date <= target]
    return candidates[-1] if candidates else None


def pct_change(current: float, reference: float | None) -> float | None:
    if reference is None or reference == 0:
        return None
    return round((current - reference) / reference * 100, 2)


def trend_of(series: list[DayPrice], as_of: date) -> tuple[str, float | None]:
    recent = _window(series, as_of, 7)
    before = _window(series, as_of - timedelta(days=7), 7)
    if len(recent) < MIN_TREND_DAYS or len(before) < MIN_TREND_DAYS:
        return "insufficient_data", None
    change = pct_change(statistics.fmean(p.modal for p in recent), statistics.fmean(p.modal for p in before))
    if change is None:
        return "insufficient_data", None
    if change >= TREND_THRESHOLD_PCT:
        return "increasing", change
    if change <= -TREND_THRESHOLD_PCT:
        return "decreasing", change
    return "stable", change


def compute_stats(series: list[DayPrice]) -> dict | None:
    """Stats for one market x commodity; `series` sorted by date."""
    if not series:
        return None
    current = series[-1]
    as_of = current.date
    w7, w14, w30 = (_window(series, as_of, n) for n in (7, 14, 30))
    ref7 = _reference(series, as_of - timedelta(days=7), grace_days=7)
    ref30 = _reference(series, as_of - timedelta(days=30), grace_days=15)
    returns = [
        (b.modal - a.modal) / a.modal * 100 for a, b in zip(w30, w30[1:]) if a.modal
    ]
    volatility = round(statistics.stdev(returns), 2) if len(returns) >= 5 else None
    trend, trend_change = trend_of(series, as_of)

    def avg(window):
        return _money(statistics.fmean(p.modal for p in window)) if window else None

    return {
        "as_of_date": as_of,
        "current_modal_price": _money(current.modal),
        "current_min_price": _money(current.low),
        "current_max_price": _money(current.high),
        "current_arrival_quantity": Decimal(str(current.arrivals)).quantize(THREE) if current.arrivals is not None else None,
        "avg_7d": avg(w7),
        "avg_14d": avg(w14),
        "avg_30d": avg(w30),
        "change_7d_pct": pct_change(current.modal, ref7.modal if ref7 else None),
        "change_30d_pct": pct_change(current.modal, ref30.modal if ref30 else None),
        "min_7d": _money(min(p.modal for p in w7)),
        "max_7d": _money(max(p.modal for p in w7)),
        "min_30d": _money(min(p.modal for p in w30)),
        "max_30d": _money(max(p.modal for p in w30)),
        "volatility_30d_pct": volatility if volatility is None or math.isfinite(volatility) else None,
        "trading_days_30d": len(w30),
        "trend": trend,
        "trend_change_pct": trend_change,
    }


async def load_series(
    session: AsyncSession, commodity_id: int, *, market_ids: list[int] | None = None, since: date | None = None
) -> dict[int, list[DayPrice]]:
    query = select(
        MarketPriceDaily.market_id,
        MarketPriceDaily.date,
        MarketPriceDaily.modal_price,
        MarketPriceDaily.min_price,
        MarketPriceDaily.max_price,
        MarketPriceDaily.arrival_quantity,
    ).where(MarketPriceDaily.commodity_id == commodity_id)
    if market_ids is not None:
        query = query.where(MarketPriceDaily.market_id.in_(market_ids))
    if since is not None:
        query = query.where(MarketPriceDaily.date >= since)
    series: dict[int, list[DayPrice]] = defaultdict(list)
    for market_id, day, modal, low, high, arrivals in await session.execute(query.order_by(MarketPriceDaily.date)):
        series[market_id].append(
            DayPrice(
                day,
                float(modal),
                float(low) if low is not None else None,
                float(high) if high is not None else None,
                float(arrivals) if arrivals is not None else None,
            )
        )
    return series


async def refresh_stats(session: AsyncSession, commodity_id: int) -> int:
    """Recompute market_price_stats for every market of one commodity."""
    latest = await session.execute(
        select(MarketPriceDaily.market_id, MarketPriceDaily.state_id, func.max(MarketPriceDaily.date))
        .where(MarketPriceDaily.commodity_id == commodity_id)
        .group_by(MarketPriceDaily.market_id, MarketPriceDaily.state_id)
    )
    latest_by_market = {m: (s, d) for m, s, d in latest}
    await session.execute(delete(MarketPriceStats).where(MarketPriceStats.commodity_id == commodity_id))
    if not latest_by_market:
        return 0
    # 60 days before the oldest as-of date covers every window + grace.
    since = min(d for _, d in latest_by_market.values()) - timedelta(days=60)
    series = await load_series(session, commodity_id, since=since)
    now = datetime.now(timezone.utc)
    rows = []
    for market_id, (state_id, as_of) in latest_by_market.items():
        points = [p for p in series.get(market_id, []) if p.date >= as_of - timedelta(days=60)]
        stats = compute_stats(points)
        if stats:
            rows.append({"market_id": market_id, "commodity_id": commodity_id, "state_id": state_id, "computed_at": now, **stats})
    for i in range(0, len(rows), 1000):
        await session.execute(insert(MarketPriceStats), rows[i : i + 1000])
    return len(rows)


async def refresh_analytics(session: AsyncSession, touched: dict[int, date | None]) -> dict[int, dict]:
    """Rebuild the daily series from each commodity's earliest touched date
    (None = full rebuild) and recompute its stats. Commits."""
    summary = {}
    for commodity_id, since in touched.items():
        daily = await rebuild_daily(session, commodity_id, since=since)
        stats = await refresh_stats(session, commodity_id)
        await session.commit()
        summary[commodity_id] = {"daily_rows": daily, "markets": stats}
    return summary

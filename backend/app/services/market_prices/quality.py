"""Data-quality report over stored prices and the ingestion logs."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_price import (
    Commodity,
    Market,
    MarketPrice,
    MarketPriceDaily,
    PriceIngestionRun,
    PriceQualityIssue,
)

# A day-over-day modal move beyond this is reported as abnormal.
ABNORMAL_CHANGE_PCT = 50.0
# A market silent for longer than this (vs the commodity's newest report)
# counts as stale; a gap longer than this inside the window as missing dates.
STALE_AFTER_DAYS = 14
GAP_DAYS = 7


async def quality_report(session: AsyncSession, *, today: date, window_days: int = 90, examples: int = 5) -> dict:
    since = today - timedelta(days=window_days)

    totals = (
        await session.execute(
            select(func.count(), func.min(MarketPrice.arrival_date), func.max(MarketPrice.arrival_date))
        )
    ).one()

    issues = [
        {"severity": sev, "code": code, "count": n}
        for sev, code, n in await session.execute(
            select(PriceQualityIssue.severity, PriceQualityIssue.code, func.count())
            .group_by(PriceQualityIssue.severity, PriceQualityIssue.code)
            .order_by(func.count().desc())
        )
    ]

    flagged: dict[str, int] = defaultdict(int)
    for (flags,) in await session.execute(
        select(MarketPrice.quality_flags).where(MarketPrice.arrival_date >= since)
    ):
        for flag in flags or []:
            flagged[flag] += 1

    # Cross-source overlap: the same market/commodity/day from >1 source is
    # expected (the daily series prefers the primary), but worth knowing.
    overlap = await session.scalar(
        select(func.count()).select_from(
            select(MarketPrice.market_id, MarketPrice.commodity_id, MarketPrice.arrival_date)
            .where(MarketPrice.arrival_date >= since)
            .group_by(MarketPrice.market_id, MarketPrice.commodity_id, MarketPrice.arrival_date)
            .having(func.count(func.distinct(MarketPrice.source)) > 1)
            .subquery()
        )
    )

    # Series checks on the daily table.
    names = {
        "market": dict((await session.execute(select(Market.id, Market.name))).all()),
        "commodity": dict((await session.execute(select(Commodity.id, Commodity.name))).all()),
    }
    series: dict[tuple[int, int], list[tuple[date, float]]] = defaultdict(list)
    for market_id, commodity_id, day, modal in await session.execute(
        select(MarketPriceDaily.market_id, MarketPriceDaily.commodity_id, MarketPriceDaily.date, MarketPriceDaily.modal_price)
        .where(MarketPriceDaily.date >= since)
        .order_by(MarketPriceDaily.date)
    ):
        series[(market_id, commodity_id)].append((day, float(modal)))

    latest_by_commodity: dict[int, date] = {}
    for (_, commodity_id), points in series.items():
        latest_by_commodity[commodity_id] = max(latest_by_commodity.get(commodity_id, points[-1][0]), points[-1][0])

    abnormal, gaps, stale = [], [], []
    for (market_id, commodity_id), points in series.items():
        label = {"market": names["market"].get(market_id), "commodity": names["commodity"].get(commodity_id)}
        for (d0, p0), (d1, p1) in zip(points, points[1:]):
            if p0 and abs(p1 - p0) / p0 * 100 > ABNORMAL_CHANGE_PCT:
                abnormal.append({**label, "from": d0.isoformat(), "to": d1.isoformat(), "from_price": p0, "to_price": p1,
                                 "change_pct": round((p1 - p0) / p0 * 100, 1)})
            if (d1 - d0).days > GAP_DAYS:
                gaps.append({**label, "from": d0.isoformat(), "to": d1.isoformat(), "days": (d1 - d0).days})
        silent = (latest_by_commodity[commodity_id] - points[-1][0]).days
        if silent > STALE_AFTER_DAYS:
            stale.append({**label, "last_report": points[-1][0].isoformat(), "days_behind": silent})

    runs = [
        {
            "id": r.id, "kind": r.kind, "status": r.status, "provider": r.provider,
            "started_at": r.started_at.isoformat() if r.started_at else None, "duration_ms": r.duration_ms,
            "fetched": r.records_fetched, "inserted": r.records_inserted, "updated": r.records_updated,
            "skipped": r.records_skipped, "rejected": r.records_rejected, "flagged": r.records_flagged,
            "requests": r.requests_made, "error": r.error,
        }
        for r in (
            await session.scalars(select(PriceIngestionRun).order_by(PriceIngestionRun.started_at.desc()).limit(10))
        ).all()
    ]

    abnormal.sort(key=lambda a: -abs(a["change_pct"]))
    gaps.sort(key=lambda g: -g["days"])
    stale.sort(key=lambda s: -s["days_behind"])
    return {
        "generated_for": today.isoformat(),
        "window_days": window_days,
        "stored_records": totals[0],
        "date_range": {"from": totals[1].isoformat() if totals[1] else None, "to": totals[2].isoformat() if totals[2] else None},
        "issues_by_code": issues,
        "flagged_records_in_window": dict(flagged),
        "cross_source_overlaps_in_window": overlap or 0,
        "abnormal_changes": {"threshold_pct": ABNORMAL_CHANGE_PCT, "count": len(abnormal), "examples": abnormal[:examples]},
        "missing_dates": {"gap_days_over": GAP_DAYS, "count": len(gaps), "examples": gaps[:examples]},
        "stale_markets": {"days_over": STALE_AFTER_DAYS, "count": len(stale), "examples": stale[:examples]},
        "recent_runs": runs,
    }

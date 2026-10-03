"""Read side for the market-price API. Everything here reads precomputed
tables (market_price_stats / market_price_daily / price_forecasts) or
indexed ranges of market_prices -- no external calls, no model training."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.market_prices.text import commodity_keys, name_key
from app.models.farm import Farm
from app.models.market_price import (
    Commodity,
    Grade,
    Market,
    MarketDistrict,
    MarketPrice,
    MarketPriceDaily,
    MarketPriceStats,
    MarketState,
    PriceForecast,
    PriceForecastModel,
    PriceIngestionRun,
    Variety,
)
from app.services.market_prices.nearby import OSM_ATTRIBUTION, nearby_markets
from app.services.market_prices.watchlist import commodities_for_crop

SOURCE_LABELS = {
    "agmarknet": "Agmarknet 2.0 (agmarknet.gov.in)",
    "ceda": "CEDA Agri Market API (archive of Agmarknet)",
    "data_gov_in": "data.gov.in (Agmarknet daily prices)",
}
# Prices older than this (vs today) are flagged stale in responses.
STALE_AFTER_DAYS = 7
# Nearby comparison only lists markets that reported within this window.
NEARBY_MAX_AGE_DAYS = 30
OUTLOOK_THRESHOLD_PCT = 2.5
FORECAST_DISCLAIMER = (
    "Forecasts are statistical estimates from historical mandi prices, seasonal patterns, recent trends and "
    "arrival data. They are not guaranteed prices."
)


class NotFoundError(LookupError):
    pass


class AmbiguousError(ValueError):
    pass


# ---------------------------------------------------------------- resolving


async def resolve_commodity(session: AsyncSession, value: str | int) -> Commodity:
    if isinstance(value, int) or str(value).isdigit():
        row = await session.get(Commodity, int(value))
        if row:
            return row
        raise NotFoundError(f"No commodity with id {value}")
    keys = commodity_keys(str(value))
    rows = (await session.scalars(select(Commodity).where(Commodity.name_key.in_(keys)))).all()
    if not rows:
        raise NotFoundError(f"Unknown commodity {value!r}")
    if len(rows) > 1:
        # Prefer the one we actually have prices for.
        with_data = set((await session.scalars(select(MarketPriceStats.commodity_id).where(MarketPriceStats.commodity_id.in_([r.id for r in rows])))).all())
        rows = [r for r in rows if r.id in with_data] or rows
        if len(rows) > 1:
            raise AmbiguousError(f"{value!r} matches several commodities; pass commodity_id")
    return rows[0]


async def resolve_state(session: AsyncSession, value: str | None) -> MarketState | None:
    if not value:
        return None
    row = await session.scalar(select(MarketState).where(MarketState.name_key == name_key(value)))
    if row is None:
        raise NotFoundError(f"Unknown state {value!r}")
    return row


async def resolve_district(session: AsyncSession, state: MarketState | None, value: str | None) -> MarketDistrict | None:
    if not value:
        return None
    query = select(MarketDistrict).where(MarketDistrict.name_key == name_key(value))
    if state is not None:
        query = query.where(MarketDistrict.state_id == state.id)
    rows = (await session.scalars(query)).all()
    if not rows:
        raise NotFoundError(f"Unknown district {value!r}")
    if len(rows) > 1:
        raise AmbiguousError(f"District {value!r} exists in several states; pass state too")
    return rows[0]


async def get_market(session: AsyncSession, market_id: int) -> Market:
    market = await session.get(Market, market_id)
    if market is None:
        raise NotFoundError(f"No market with id {market_id}")
    return market


async def market_out(session: AsyncSession, market: Market) -> dict:
    state_name = await session.scalar(select(MarketState.name).where(MarketState.id == market.state_id))
    district_name = (
        await session.scalar(select(MarketDistrict.name).where(MarketDistrict.id == market.district_id))
        if market.district_id else None
    )
    return {
        "id": market.id, "name": market.name, "district": district_name, "state": state_name,
        "latitude": market.latitude, "longitude": market.longitude,
        "coordinate_source": market.coordinate_source, "coordinate_precision": market.coordinate_precision,
        "latest_date": None,
    }


# --------------------------------------------------------------- provenance


@dataclass
class Provenance:
    sources: list[str]
    as_of: date | None
    is_stale: bool
    last_ingested_at: datetime | None
    last_ingestion_status: str | None


async def provenance(session: AsyncSession, *, as_of: date | None, sources: set[str], today: date) -> Provenance:
    last = await session.scalar(
        select(PriceIngestionRun)
        .where(PriceIngestionRun.kind.in_(("current", "backfill")), PriceIngestionRun.finished_at.is_not(None))
        .order_by(PriceIngestionRun.finished_at.desc())
        .limit(1)
    )
    return Provenance(
        sources=[SOURCE_LABELS.get(s, s) for s in sorted(sources)] or [SOURCE_LABELS["agmarknet"]],
        as_of=as_of,
        is_stale=as_of is None or (today - as_of).days > STALE_AFTER_DAYS,
        last_ingested_at=last.finished_at if last else None,
        last_ingestion_status=last.status if last else None,
    )


# ------------------------------------------------------------------ catalogue


async def commodities_with_data(
    session: AsyncSession, state: MarketState | None, *, always_include: list[str] | None = None
) -> list[dict]:
    """Commodities with stored prices (optionally in one state), plus any
    `always_include` names even when they have none -- e.g. a crop the UI
    always offers but that Agmarknet mandis never actually report (cane is
    procured by mills, not auctioned)."""
    on_clause = [MarketPriceStats.commodity_id == Commodity.id]
    if state is not None:
        on_clause.append(MarketPriceStats.state_id == state.id)
    query = (
        select(
            Commodity.id, Commodity.name, Commodity.commodity_group,
            func.count(MarketPriceStats.market_id), func.max(MarketPriceStats.as_of_date),
        )
        .outerjoin(MarketPriceStats, and_(*on_clause))
        .group_by(Commodity.id, Commodity.name, Commodity.commodity_group)
        .having(or_(func.count(MarketPriceStats.market_id) > 0, Commodity.name.in_(always_include or [])))
        .order_by(Commodity.name)
    )
    return [
        {"id": i, "name": n, "commodity_group": g, "markets": c, "latest_date": d}
        for i, n, g, c, d in await session.execute(query)
    ]


async def locations_with_data(session: AsyncSession, commodity: Commodity | None) -> list[dict]:
    query = (
        select(MarketState.id, MarketState.name, MarketDistrict.id, MarketDistrict.name, func.count(Market.id))
        .join(Market, Market.state_id == MarketState.id)
        .join(MarketPriceStats, MarketPriceStats.market_id == Market.id)
        .outerjoin(MarketDistrict, MarketDistrict.id == Market.district_id)
        .group_by(MarketState.id, MarketState.name, MarketDistrict.id, MarketDistrict.name)
    )
    if commodity is not None:
        query = query.where(MarketPriceStats.commodity_id == commodity.id)
    states: dict[int, dict] = {}
    for state_id, state_name, district_id, district_name, count in await session.execute(query):
        entry = states.setdefault(state_id, {"id": state_id, "name": state_name, "districts": []})
        if district_id is not None:
            entry["districts"].append({"id": district_id, "name": district_name, "markets": count})
    for entry in states.values():
        entry["districts"].sort(key=lambda d: d["name"])
    return sorted(states.values(), key=lambda s: s["name"])


async def list_markets(
    session: AsyncSession, *, state: MarketState | None, district: MarketDistrict | None, commodity: Commodity | None
) -> list[dict]:
    query = (
        select(Market, MarketDistrict.name, MarketState.name)
        .join(MarketState, MarketState.id == Market.state_id)
        .outerjoin(MarketDistrict, MarketDistrict.id == Market.district_id)
        .order_by(Market.name)
    )
    if commodity is not None:
        query = query.join(
            MarketPriceStats, (MarketPriceStats.market_id == Market.id) & (MarketPriceStats.commodity_id == commodity.id)
        ).add_columns(MarketPriceStats.as_of_date)
    if state is not None:
        query = query.where(Market.state_id == state.id)
    if district is not None:
        query = query.where(Market.district_id == district.id)
    out = []
    for row in await session.execute(query):
        market, district_name, state_name = row[0], row[1], row[2]
        out.append(
            {
                "id": market.id, "name": market.name, "district": district_name, "state": state_name,
                "latitude": market.latitude, "longitude": market.longitude,
                "coordinate_source": market.coordinate_source, "coordinate_precision": market.coordinate_precision,
                "latest_date": row[3] if commodity is not None else None,
            }
        )
    return out


# --------------------------------------------------------------------- prices


def stats_dict(stats: MarketPriceStats, market: Market, district_name: str | None, state_name: str | None) -> dict:
    return {
        "market_id": market.id,
        "market": market.name,
        "district": district_name,
        "state": state_name,
        "as_of": stats.as_of_date,
        "modal_price": stats.current_modal_price,
        "min_price": stats.current_min_price,
        "max_price": stats.current_max_price,
        "arrival_quantity": stats.current_arrival_quantity,
        "avg_7d": stats.avg_7d,
        "avg_14d": stats.avg_14d,
        "avg_30d": stats.avg_30d,
        "change_7d_pct": stats.change_7d_pct,
        "change_30d_pct": stats.change_30d_pct,
        "min_7d": stats.min_7d,
        "max_7d": stats.max_7d,
        "min_30d": stats.min_30d,
        "max_30d": stats.max_30d,
        "volatility_30d_pct": stats.volatility_30d_pct,
        "trading_days_30d": stats.trading_days_30d,
        "trend": stats.trend,
        "trend_change_pct": stats.trend_change_pct,
    }


async def latest_prices(
    session: AsyncSession, commodity: Commodity, *, state: MarketState | None, district: MarketDistrict | None
) -> list[dict]:
    query = (
        select(MarketPriceStats, Market, MarketDistrict.name, MarketState.name)
        .join(Market, Market.id == MarketPriceStats.market_id)
        .join(MarketState, MarketState.id == Market.state_id)
        .outerjoin(MarketDistrict, MarketDistrict.id == Market.district_id)
        .where(MarketPriceStats.commodity_id == commodity.id)
        .order_by(MarketPriceStats.as_of_date.desc(), Market.name)
    )
    if state is not None:
        query = query.where(MarketPriceStats.state_id == state.id)
    if district is not None:
        query = query.where(Market.district_id == district.id)
    return [stats_dict(s, m, d, st) for s, m, d, st in await session.execute(query)]


async def raw_prices(
    session: AsyncSession,
    commodity: Commodity,
    *,
    state: MarketState | None,
    district: MarketDistrict | None,
    market_id: int | None,
    from_date: date,
    to_date: date,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    base = (
        select(MarketPrice, Market.name, MarketDistrict.name, Variety.name, Grade.name)
        .join(Market, Market.id == MarketPrice.market_id)
        .outerjoin(MarketDistrict, MarketDistrict.id == Market.district_id)
        .outerjoin(Variety, Variety.id == MarketPrice.variety_id)
        .outerjoin(Grade, Grade.id == MarketPrice.grade_id)
        .where(
            MarketPrice.commodity_id == commodity.id,
            MarketPrice.arrival_date >= from_date,
            MarketPrice.arrival_date <= to_date,
        )
    )
    if state is not None:
        base = base.where(MarketPrice.state_id == state.id)
    if district is not None:
        base = base.where(Market.district_id == district.id)
    if market_id is not None:
        base = base.where(MarketPrice.market_id == market_id)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.execute(
        base.order_by(MarketPrice.arrival_date.desc(), Market.name, MarketPrice.id).offset((page - 1) * page_size).limit(page_size)
    )
    return (
        [
            {
                "market_id": p.market_id, "market": m, "district": d, "variety": v, "grade": g,
                "arrival_date": p.arrival_date, "min_price": p.min_price, "max_price": p.max_price,
                "modal_price": p.modal_price, "arrival_quantity": p.arrival_quantity, "unit": p.unit,
                "arrival_unit": p.arrival_unit, "source": p.source, "quality_flags": p.quality_flags or [],
            }
            for p, m, d, v, g in rows
        ],
        total or 0,
    )


async def history(session: AsyncSession, market: Market, commodity: Commodity, *, from_date: date, to_date: date) -> list[dict]:
    rows = await session.scalars(
        select(MarketPriceDaily)
        .where(
            MarketPriceDaily.market_id == market.id,
            MarketPriceDaily.commodity_id == commodity.id,
            MarketPriceDaily.date >= from_date,
            MarketPriceDaily.date <= to_date,
        )
        .order_by(MarketPriceDaily.date)
    )
    return [
        {"date": r.date, "modal_price": r.modal_price, "min_price": r.min_price, "max_price": r.max_price,
         "arrival_quantity": r.arrival_quantity, "report_count": r.report_count, "source": r.source}
        for r in rows
    ]


async def market_stats(session: AsyncSession, market: Market, commodity: Commodity) -> dict | None:
    row = (
        await session.execute(
            select(MarketPriceStats, MarketDistrict.name, MarketState.name)
            .join(MarketState, MarketState.id == MarketPriceStats.state_id)
            .outerjoin(MarketDistrict, MarketDistrict.id == market.district_id)
            .where(MarketPriceStats.market_id == market.id, MarketPriceStats.commodity_id == commodity.id)
        )
    ).first()
    if row is None:
        return None
    stats, district_name, state_name = row
    return stats_dict(stats, market, district_name, state_name)


async def trends(session: AsyncSession, commodity: Commodity, *, state: MarketState | None, today: date) -> dict:
    prices = await latest_prices(session, commodity, state=state, district=None)
    fresh = [p for p in prices if (today - p["as_of"]).days <= STALE_AFTER_DAYS]
    counts = {k: sum(1 for p in fresh if p["trend"] == k) for k in ("increasing", "stable", "decreasing", "insufficient_data")}
    movers = sorted((p for p in fresh if p["change_7d_pct"] is not None), key=lambda p: p["change_7d_pct"])
    modal = [float(p["modal_price"]) for p in fresh]
    return {
        "markets_reporting": len(fresh),
        "markets_stale": len(prices) - len(fresh),
        "trend_counts": counts,
        "average_modal_price": round(sum(modal) / len(modal), 2) if modal else None,
        "median_change_7d_pct": _median([p["change_7d_pct"] for p in fresh if p["change_7d_pct"] is not None]),
        "median_change_30d_pct": _median([p["change_30d_pct"] for p in fresh if p["change_30d_pct"] is not None]),
        "top_gainers": list(reversed(movers[-5:])),
        "top_decliners": movers[:5],
        "as_of": max((p["as_of"] for p in prices), default=None),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    mid = len(values) // 2
    return round(values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2, 2)


# ------------------------------------------------------------------- nearby


async def nearby(
    session: AsyncSession,
    commodity: Commodity,
    *,
    lat: float | None,
    lon: float | None,
    radius_km: float,
    state: MarketState | None,
    district: MarketDistrict | None,
    limit: int,
) -> list[dict]:
    found = await nearby_markets(
        session, commodity_id=commodity.id, lat=lat, lon=lon, radius_km=radius_km,
        state_id=state.id if state else None, district_id=district.id if district else None, limit=limit,
        reported_since=today_utc() - timedelta(days=NEARBY_MAX_AGE_DAYS),
    )
    state_names = dict((await session.execute(select(MarketState.id, MarketState.name))).all())
    return [
        {
            **stats_dict(n.stats, n.market, n.district_name, state_names.get(n.market.state_id)),
            "distance_km": n.distance_km,
            "scope": n.scope,
            "coordinate_precision": n.market.coordinate_precision,
        }
        for n in found
    ]


def distance_attribution(rows: list[dict]) -> str | None:
    return f"Market locations approximate, {OSM_ATTRIBUTION}" if any(r["distance_km"] is not None for r in rows) else None


# ------------------------------------------------------------------ forecast


async def forecast(session: AsyncSession, market: Market, commodity: Commodity, *, horizons: list[int]) -> dict:
    """Latest stored estimates for this market, or the reason there are none."""
    latest_generated = await session.scalar(
        select(func.max(PriceForecast.generated_at)).where(
            PriceForecast.market_id == market.id, PriceForecast.commodity_id == commodity.id
        )
    )
    active_models = (
        await session.scalars(
            select(PriceForecastModel).where(
                PriceForecastModel.commodity_id == commodity.id,
                PriceForecastModel.state_id == market.state_id,
                PriceForecastModel.is_active.is_(True),
            )
        )
    ).all()
    if latest_generated is None:
        if not active_models:
            reason = "Forecast unavailable: no model has been trained for this commodity in this state yet (insufficient historical data)."
        else:
            reason = "Forecast unavailable: this market has too little recent price history for a reliable estimate."
        return {"available": False, "reason": reason, "forecasts": [], "models": [], "disclaimer": FORECAST_DISCLAIMER}

    rows = (
        await session.execute(
            select(PriceForecast, PriceForecastModel)
            .join(PriceForecastModel, PriceForecastModel.id == PriceForecast.model_id)
            .where(
                PriceForecast.market_id == market.id,
                PriceForecast.commodity_id == commodity.id,
                PriceForecast.generated_at == latest_generated,
                PriceForecast.horizon_days.in_(horizons),
            )
            .order_by(PriceForecast.horizon_days)
        )
    ).all()
    forecasts, models = [], {}
    for f, m in rows:
        forecasts.append(
            {
                "horizon_days": f.horizon_days, "base_date": f.base_date, "base_price": f.base_price,
                "forecast_date": f.forecast_date, "predicted_price": f.predicted_price,
                "lower_bound": f.lower_bound, "upper_bound": f.upper_bound,
                "change_pct": round((float(f.predicted_price) / float(f.base_price) - 1) * 100, 2) if f.base_price else None,
                "model_name": f.model_name, "model_version": f.model_version,
            }
        )
        baseline = m.evaluation.get("models", {}).get("naive", {})
        models[m.id] = {
            "horizon_days": m.horizon_days, "model_name": m.model_name, "model_version": m.model_version,
            "trained_at": m.trained_at, "training_period": {"from": m.train_start, "to": m.train_end},
            "training_samples": m.n_samples, "markets": m.n_markets,
            "validation": {"mae": m.mae, "rmse": m.rmse, "mape": m.mape,
                           "naive_mae": baseline.get("mae"), "scheme": m.evaluation.get("validation", {}).get("scheme")},
            "selection_note": m.evaluation.get("selection_note"),
            "interval": {"level": 0.8, "holdout_coverage": m.evaluation.get("interval", {}).get("holdout_coverage")},
        }
    return {
        "available": bool(forecasts),
        "reason": None if forecasts else "Forecast unavailable for the requested horizon.",
        "generated_at": latest_generated,
        "forecasts": forecasts,
        "models": list(models.values()),
        "disclaimer": FORECAST_DISCLAIMER,
    }


# ------------------------------------------------------------------- outlook


def outlook(commodity: Commodity, stats: dict | None, forecast_data: dict | None, nearby_rows: list[dict] | None) -> dict:
    """Deterministic summary from the numbers above -- no LLM, nothing
    hard-coded. Every sentence states its basis."""
    if stats is None:
        return {"label": "unavailable", "statements": ["No recent mandi price is available for this commodity at this market."]}
    statements = []
    market = stats["market"]
    change_30 = stats["change_30d_pct"]
    if change_30 is not None:
        direction = "increased" if change_30 > 0 else "decreased" if change_30 < 0 else "not changed"
        statements.append(
            f"{commodity.name} prices at {market} have {direction}"
            + (f" {abs(change_30):.1f}%" if change_30 else "")
            + " over the last 30 days."
        )
    f7 = next((f for f in (forecast_data or {}).get("forecasts", []) if f["horizon_days"] == 7), None)
    if f7 and f7["change_pct"] is not None:
        c = f7["change_pct"]
        if c >= OUTLOOK_THRESHOLD_PCT:
            statements.append(f"The 7-day forecast estimates a rise of about {c:.1f}% (estimate, not guaranteed).")
        elif c <= -OUTLOOK_THRESHOLD_PCT:
            statements.append(f"The 7-day forecast estimates a fall of about {abs(c):.1f}% (estimate, not guaranteed).")
        else:
            statements.append("The 7-day forecast estimates prices to remain relatively stable (estimate, not guaranteed).")
    # Compare only with markets that reported within a week of this one.
    comparable = [r for r in (nearby_rows or []) if abs((r["as_of"] - stats["as_of"]).days) <= STALE_AFTER_DAYS]
    if len(comparable) > 1:
        top = max(comparable, key=lambda r: r["modal_price"])
        where = f" ({top['distance_km']:.0f} km away)" if top.get("distance_km") is not None else ""
        statements.append(
            f"Among nearby markets, {top['market']}{where} currently has the highest modal price "
            f"(₹{float(top['modal_price']):,.0f}/quintal on {top['as_of'].strftime('%d %b %Y')})."
        )

    signals = []
    if stats["trend"] in ("increasing", "decreasing"):
        signals.append(1 if stats["trend"] == "increasing" else -1)
    if f7 and f7["change_pct"] is not None and abs(f7["change_pct"]) >= OUTLOOK_THRESHOLD_PCT:
        signals.append(1 if f7["change_pct"] > 0 else -1)
    score = sum(signals)
    label = "positive" if score > 0 else "negative" if score < 0 else ("stable" if stats["trend"] != "insufficient_data" or f7 else "unclear")
    return {
        "label": label,
        "statements": statements,
        "basis": {"trend": stats["trend"], "change_30d_pct": change_30, "forecast_7d_change_pct": f7["change_pct"] if f7 else None},
    }


# ---------------------------------------------------------------------- farm


async def farm_context(session: AsyncSession, farm: Farm) -> dict:
    """Map a farm's crop and location onto the catalogue."""
    names = commodities_for_crop(farm.crop)
    commodities = []
    for n in names:
        try:
            commodities.append(await resolve_commodity(session, n))
        except (NotFoundError, AmbiguousError):
            continue
    state = district = None
    try:
        state = await resolve_state(session, farm.state)
    except NotFoundError:
        pass
    if state and farm.district:
        try:
            district = await resolve_district(session, state, farm.district)
        except (NotFoundError, AmbiguousError):
            district = None
    return {"commodities": commodities, "state": state, "district": district}


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def default_range(from_date: date | None, to_date: date | None, *, days: int, today: date) -> tuple[date, date]:
    to_date = to_date or today
    return from_date or to_date - timedelta(days=days), to_date

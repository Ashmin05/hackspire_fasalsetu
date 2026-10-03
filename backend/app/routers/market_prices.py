"""Mandi price API. Read-only and cache-only: every endpoint reads what the
scheduled ingestion/analytics/forecast jobs stored -- nothing here calls
Agmarknet or trains a model. Public (prices are public data), except the
farm endpoint, which needs the farm's owner."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.repositories.farm_repository import FarmRepository
from app.schemas.market_prices import (
    AnalyticsOut,
    CommodityOut,
    FarmForecastOut,
    FarmMarketOut,
    ForecastOut,
    HistoryOut,
    LatestPricesOut,
    MarketOut,
    NearbyOut,
    RawPricesOut,
    StateOut,
    TrendsOut,
)
from app.services.farm_service import FarmNotFoundError, FarmService
from app.services.market_prices import queries as q
from app.services.market_prices.price_service import PriceService

router = APIRouter(prefix="/market-prices", tags=["market-prices"])
farm_router = APIRouter(tags=["market-prices"])

HORIZONS = (7, 14, 30)
MAX_HISTORY_DAYS = 3 * 366


def _raise(exc: Exception):
    if isinstance(exc, q.NotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, q.AmbiguousError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    raise exc


async def _commodity(session, commodity: str | None, commodity_id: int | None):
    if commodity_id is None and not commodity:
        raise HTTPException(status_code=422, detail="Pass commodity (name) or commodity_id.")
    try:
        return await q.resolve_commodity(session, commodity_id if commodity_id is not None else commodity)
    except (q.NotFoundError, q.AmbiguousError) as exc:
        _raise(exc)


async def _location(session, state: str | None, district: str | None):
    try:
        state_row = await q.resolve_state(session, state)
        district_row = await q.resolve_district(session, state_row, district)
    except (q.NotFoundError, q.AmbiguousError) as exc:
        _raise(exc)
    return state_row, district_row


async def _market(session, market_id: int):
    try:
        market = await q.get_market(session, market_id)
    except q.NotFoundError as exc:
        _raise(exc)
    return market, await q.market_out(session, market)


def _ref(commodity) -> dict:
    return {"id": commodity.id, "name": commodity.name}


async def _provenance(session, rows: list[dict], *, as_of_key: str = "as_of", sources: set[str] | None = None):
    as_of = max((r[as_of_key] for r in rows if r.get(as_of_key)), default=None)
    return (await q.provenance(session, as_of=as_of, sources=sources or {"agmarknet"}, today=q.today_utc())).__dict__


@router.get("/commodities", response_model=list[CommodityOut])
async def list_commodities(state: str | None = None, include: str | None = None, session: AsyncSession = Depends(get_db)):
    """Commodities with stored prices (optionally in one state), plus any
    comma-separated `include` names even without data."""
    state_row, _ = await _location(session, state, None)
    always_include = [n.strip() for n in include.split(",") if n.strip()] if include else None
    return await q.commodities_with_data(session, state_row, always_include=always_include)


@router.get("/locations", response_model=list[StateOut])
async def list_locations(
    commodity: str | None = None, commodity_id: int | None = None, session: AsyncSession = Depends(get_db)
):
    """States and districts that have market prices (for a commodity)."""
    commodity_row = await _commodity(session, commodity, commodity_id) if (commodity or commodity_id) else None
    return await q.locations_with_data(session, commodity_row)


@router.get("/markets", response_model=list[MarketOut])
async def list_markets(
    state: str | None = None,
    district: str | None = None,
    commodity: str | None = None,
    commodity_id: int | None = None,
    session: AsyncSession = Depends(get_db),
):
    """Markets (optionally only those reporting a commodity)."""
    if not (state or district or commodity or commodity_id):
        raise HTTPException(status_code=422, detail="Filter by state, district or commodity.")
    state_row, district_row = await _location(session, state, district)
    commodity_row = await _commodity(session, commodity, commodity_id) if (commodity or commodity_id) else None
    return await q.list_markets(session, state=state_row, district=district_row, commodity=commodity_row)


@router.get("/latest", response_model=LatestPricesOut)
async def latest(
    commodity: str | None = None,
    commodity_id: int | None = None,
    state: str | None = None,
    district: str | None = None,
    session: AsyncSession = Depends(get_db),
):
    """Each market's most recent price for a commodity, with its analytics."""
    commodity_row = await _commodity(session, commodity, commodity_id)
    state_row, district_row = await _location(session, state, district)
    prices = await q.latest_prices(session, commodity_row, state=state_row, district=district_row)
    return {
        "commodity": _ref(commodity_row),
        "state": state_row.name if state_row else None,
        "district": district_row.name if district_row else None,
        "prices": prices,
        "provenance": await _provenance(session, prices),
    }


@router.get("", response_model=RawPricesOut)
async def raw_prices(
    commodity: str | None = None,
    commodity_id: int | None = None,
    state: str | None = None,
    district: str | None = None,
    market_id: int | None = None,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
):
    """Individual reports as stored (variety/grade level), paginated."""
    commodity_row = await _commodity(session, commodity, commodity_id)
    state_row, district_row = await _location(session, state, district)
    start, end = q.default_range(from_date, to_date, days=30, today=q.today_utc())
    if start > end:
        raise HTTPException(status_code=422, detail="'from' is after 'to'.")
    records, total = await q.raw_prices(
        session, commodity_row, state=state_row, district=district_row, market_id=market_id,
        from_date=start, to_date=end, page=page, page_size=page_size,
    )
    return {"commodity": _ref(commodity_row), "from_date": start, "to_date": end, "page": page,
            "page_size": page_size, "total": total, "records": records}


@router.get("/history", response_model=HistoryOut)
async def price_history(
    market_id: int,
    commodity: str | None = None,
    commodity_id: int | None = None,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    session: AsyncSession = Depends(get_db),
):
    """Daily modal/min/max series for one market (default: last 180 days)."""
    commodity_row = await _commodity(session, commodity, commodity_id)
    market, market_out = await _market(session, market_id)
    start, end = q.default_range(from_date, to_date, days=180, today=q.today_utc())
    if start > end:
        raise HTTPException(status_code=422, detail="'from' is after 'to'.")
    if (end - start).days > MAX_HISTORY_DAYS:
        raise HTTPException(status_code=422, detail="History is limited to 3 years per request.")
    series = await q.history(session, market, commodity_row, from_date=start, to_date=end)
    return {
        "market": market_out, "commodity": _ref(commodity_row), "from_date": start, "to_date": end, "series": series,
        "provenance": await _provenance(session, series, as_of_key="date", sources={p["source"] for p in series}),
    }


@router.get("/nearby", response_model=NearbyOut)
async def nearby(
    commodity: str | None = None,
    commodity_id: int | None = None,
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    radius_km: float = Query(100, gt=0, le=500),
    state: str | None = None,
    district: str | None = None,
    limit: int = Query(25, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
):
    """Markets near a point (by distance where market coordinates are
    known) and/or in a district/state. A comparison, not a recommendation."""
    if (lat is None) != (lon is None):
        raise HTTPException(status_code=422, detail="Pass both lat and lon.")
    if lat is None and not state:
        raise HTTPException(status_code=422, detail="Pass lat/lon and/or state.")
    commodity_row = await _commodity(session, commodity, commodity_id)
    state_row, district_row = await _location(session, state, district)
    rows = await q.nearby(session, commodity_row, lat=lat, lon=lon, radius_km=radius_km,
                          state=state_row, district=district_row, limit=limit)
    return {
        "commodity": _ref(commodity_row),
        "origin": {"lat": lat, "lon": lon, "state": state_row.name if state_row else None,
                   "district": district_row.name if district_row else None},
        "radius_km": radius_km,
        "markets": rows,
        "note": "Ranked by distance where market locations are known, then same district, then same state. "
                "The highest price is not necessarily the best market once transport and time are considered.",
        "attribution": q.distance_attribution(rows),
        "provenance": await _provenance(session, rows),
    }


@router.get("/trends", response_model=TrendsOut)
async def trends(
    commodity: str | None = None, commodity_id: int | None = None, state: str | None = None,
    session: AsyncSession = Depends(get_db),
):
    """How a commodity is moving across markets (fresh markets only)."""
    commodity_row = await _commodity(session, commodity, commodity_id)
    state_row, _ = await _location(session, state, None)
    return {"commodity": _ref(commodity_row), "state": state_row.name if state_row else None,
            **await q.trends(session, commodity_row, state=state_row, today=q.today_utc())}


@router.get("/analytics", response_model=AnalyticsOut)
async def analytics(
    market_id: int,
    commodity: str | None = None,
    commodity_id: int | None = None,
    radius_km: float = Query(100, gt=0, le=500),
    session: AsyncSession = Depends(get_db),
):
    """Full analytics for one market + a deterministic outlook."""
    commodity_row = await _commodity(session, commodity, commodity_id)
    market, market_out = await _market(session, market_id)
    stats = await q.market_stats(session, market, commodity_row)
    forecast = await q.forecast(session, market, commodity_row, horizons=[7])
    state_row = await q.resolve_state(session, market_out["state"]) if market_out["state"] else None
    near = await q.nearby(
        session, commodity_row, lat=market.latitude, lon=market.longitude, radius_km=radius_km,
        state=state_row, district=None, limit=25,
    ) if stats else []
    near = [r for r in near if r["distance_km"] is not None or r["scope"] == "district"] or near
    return {
        "market": market_out, "commodity": _ref(commodity_row), "stats": stats,
        "outlook": q.outlook(commodity_row, stats, forecast, near),
        "provenance": await _provenance(session, [stats] if stats else []),
    }


@router.get("/forecast", response_model=ForecastOut)
async def forecast(
    market_id: int,
    commodity: str | None = None,
    commodity_id: int | None = None,
    horizon: int | None = Query(None, description="7, 14 or 30; all three when omitted"),
    session: AsyncSession = Depends(get_db),
):
    """Stored 7/14/30-day estimates with expected range and the model's
    validation metrics. Estimates, never guaranteed prices."""
    if horizon is not None and horizon not in HORIZONS:
        raise HTTPException(status_code=422, detail="horizon must be 7, 14 or 30.")
    commodity_row = await _commodity(session, commodity, commodity_id)
    market, market_out = await _market(session, market_id)
    result = await q.forecast(session, market, commodity_row, horizons=[horizon] if horizon else list(HORIZONS))
    return {"market": market_out, "commodity": _ref(commodity_row), **result}


@router.get("/quality")
async def quality(days: int = Query(90, ge=7, le=730), session: AsyncSession = Depends(get_db)):
    """Data-quality report over stored prices and ingestion runs."""
    from app.services.market_prices.quality import quality_report

    return await quality_report(session, today=q.today_utc(), window_days=days)


async def _own_farm(session: AsyncSession, user: User, farm_id: uuid.UUID):
    try:
        return await FarmService(FarmRepository(session)).get_farm(user, farm_id)
    except FarmNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Farm not found.") from exc


@farm_router.get("/farms/{farm_id}/market/forecast", response_model=FarmForecastOut)
async def farm_market_forecast(
    farm_id: uuid.UUID,
    commodity_id: int | None = None,
    market_id: int | None = None,
    radius_km: float = Query(100, gt=0, le=500),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """The farm's crop at the nearest mandi with a forecast (or the given
    commodity/mandi): live price, 90 days of history, 7/14/30-day estimates,
    nearby mandis, and a sell-now / hold-N-days suggestion that only says
    hold when the estimated rise beats the model's error plus an assumed
    holding cost. Estimates, never guaranteed prices."""
    farm = await _own_farm(session, current_user, farm_id)
    try:
        return await PriceService(session).farm_forecast(
            farm, commodity_id=commodity_id, market_id=market_id, radius_km=radius_km
        )
    except (q.NotFoundError, q.AmbiguousError) as exc:
        _raise(exc)


@farm_router.get("/farms/{farm_id}/market-prices", response_model=FarmMarketOut)
async def farm_market_prices(
    farm_id: uuid.UUID,
    commodity_id: int | None = None,
    radius_km: float = Query(100, gt=0, le=500),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """The farm's crop mapped to mandi commodities, and nearby markets for
    it from the farm's centre point / district / state."""
    farm = await _own_farm(session, current_user, farm_id)
    ctx = await q.farm_context(session, farm)
    commodities = ctx["commodities"]
    selected = next((c for c in commodities if c.id == commodity_id), None) if commodity_id else None
    rows: list[dict] = []
    if selected is None:
        # Default to the first of the crop's commodities that has nearby data.
        for c in commodities:
            rows = await q.nearby(session, c, lat=farm.centroid_lat, lon=farm.centroid_lng, radius_km=radius_km,
                                  state=ctx["state"], district=ctx["district"], limit=25)
            if rows:
                selected = c
                break
        selected = selected or (commodities[0] if commodities else None)
    else:
        rows = await q.nearby(session, selected, lat=farm.centroid_lat, lon=farm.centroid_lng, radius_km=radius_km,
                              state=ctx["state"], district=ctx["district"], limit=25)
    message = None
    if not commodities:
        message = f"No mandi commodity is mapped for the crop {farm.crop!r}."
    elif not rows:
        message = "No recent mandi price is available near this farm for its crop."
    return {
        "farm_id": str(farm.id), "crop": farm.crop,
        "commodities": [_ref(c) for c in commodities],
        "state": ctx["state"].name if ctx["state"] else farm.state,
        "district": ctx["district"].name if ctx["district"] else farm.district,
        "selected_commodity": _ref(selected) if selected else None,
        "nearby": rows,
        "attribution": q.distance_attribution(rows),
        "message": message,
    }

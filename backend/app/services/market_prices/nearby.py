"""Nearby-mandi comparison and (opt-in) market geocoding.

Agmarknet publishes no market coordinates. geocode_markets() can fill them
from OpenStreetMap's Nominatim -- every point records its source and
precision ("place" = the market's town/locality was found, "district" =
only the district centroid). Nothing is ever guessed: a market Nominatim
can't place keeps NULL coordinates. Nominatim policy: at most 1 request per
second, an identifying User-Agent, and "(c) OpenStreetMap contributors"
attribution wherever the distances are shown.

nearby_markets() ranks what's stored, transparently:
  * with coordinates: by great-circle distance from the farm/point,
    within the radius;
  * without: markets in the same district, then the rest of the state
    (distance None).
Markets that haven't reported since `reported_since` are left out. The
result is a comparison, not a recommendation of where to sell.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.market_prices.http import USER_AGENT
from app.models.market_price import Market, MarketDistrict, MarketPriceStats, MarketState

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_SOURCE = "OpenStreetMap Nominatim"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass
class NearbyMarket:
    stats: MarketPriceStats
    market: Market
    district_name: str | None
    distance_km: float | None
    scope: str  # "radius" | "district" | "state"


async def nearby_markets(
    session: AsyncSession,
    *,
    commodity_id: int,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float = 100.0,
    state_id: int | None = None,
    district_id: int | None = None,
    limit: int = 25,
    reported_since: date | None = None,
) -> list[NearbyMarket]:
    query = (
        select(MarketPriceStats, Market, MarketDistrict.name)
        .join(Market, Market.id == MarketPriceStats.market_id)
        .outerjoin(MarketDistrict, MarketDistrict.id == Market.district_id)
        .where(MarketPriceStats.commodity_id == commodity_id)
    )
    if reported_since is not None:
        # A market that stopped reporting long ago isn't a useful comparison.
        query = query.where(MarketPriceStats.as_of_date >= reported_since)
    rows = (await session.execute(query)).all()

    found: dict[int, NearbyMarket] = {}
    if lat is not None and lon is not None:
        for stats, market, district_name in rows:
            if market.latitude is None or market.longitude is None:
                continue
            distance = haversine_km(lat, lon, market.latitude, market.longitude)
            if distance <= radius_km:
                found[market.id] = NearbyMarket(stats, market, district_name, round(distance, 1), "radius")
    if state_id is not None:
        for stats, market, district_name in rows:
            if market.id in found or market.state_id != state_id:
                continue
            if market.latitude is not None and lat is not None:
                continue  # has coordinates but is outside the radius
            scope = "district" if district_id is not None and market.district_id == district_id else "state"
            found[market.id] = NearbyMarket(stats, market, district_name, None, scope)

    order = {"radius": 0, "district": 1, "state": 2}
    ranked = sorted(
        found.values(),
        key=lambda n: (order[n.scope], n.distance_km if n.distance_km is not None else 0, n.market.name),
    )
    return ranked[:limit]


# ---------------------------------------------------------------------------
# Geocoding (opt-in; scripts/geocode_markets.py)
# ---------------------------------------------------------------------------

_SUFFIX = re.compile(r"\b(apmc|mandi|market yard|regulated market|market|vfpck)\b", re.IGNORECASE)
_PARENS = re.compile(r"\(.*?\)")


def place_name(market_name: str) -> str:
    """'Bishnupur(Bankura) APMC' -> 'Bishnupur'."""
    name = _PARENS.sub(" ", market_name)
    name = _SUFFIX.sub(" ", name)
    return " ".join(name.replace("/", " ").split()).strip(" ,.-")


async def _search(client: httpx.AsyncClient, params: dict) -> dict | None:
    response = await client.get(NOMINATIM_URL, params={**params, "format": "jsonv2", "limit": 1, "countrycodes": "in"})
    response.raise_for_status()
    results = response.json()
    return results[0] if results else None


async def geocode_markets(
    session: AsyncSession,
    *,
    state_names: list[str],
    overwrite: bool = False,
    client: httpx.AsyncClient | None = None,
    delay_seconds: float = 1.1,
) -> dict:
    """Fill markets.latitude/longitude for the given states. Returns counts."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT})
    counts = {"place": 0, "district": 0, "not_found": 0, "skipped": 0}
    try:
        rows = (
            await session.execute(
                select(Market, MarketDistrict.name, MarketState.name)
                .join(MarketState, MarketState.id == Market.state_id)
                .outerjoin(MarketDistrict, MarketDistrict.id == Market.district_id)
                .where(MarketState.name.in_(state_names))
                .order_by(Market.name)
            )
        ).all()
        district_cache: dict[tuple[str, str], dict | None] = {}
        for market, district, state in rows:
            if market.latitude is not None and not overwrite:
                counts["skipped"] += 1
                continue
            place = place_name(market.name)
            hit = None
            if place:
                hit = await _search(client, {"q": ", ".join(p for p in (place, district, state, "India") if p)})
                await asyncio.sleep(delay_seconds)
            precision = "place"
            if hit is None and district:
                key = (district, state)
                if key not in district_cache:
                    district_cache[key] = await _search(client, {"q": f"{district} district, {state}, India"})
                    await asyncio.sleep(delay_seconds)
                hit, precision = district_cache[key], "district"
            if hit is None:
                counts["not_found"] += 1
                logger.info("No coordinates found for %s (%s, %s)", market.name, district, state)
                continue
            market.latitude, market.longitude = float(hit["lat"]), float(hit["lon"])
            market.coordinate_source = NOMINATIM_SOURCE
            market.coordinate_precision = precision
            counts[precision] += 1
            await session.commit()
    finally:
        if own:
            await client.aclose()
    return counts


def is_fresh(as_of: date, *, today: date, max_age_days: int = 7) -> bool:
    return (today - as_of).days <= max_age_days

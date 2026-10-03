"""Which (state, commodity) pairs the current-price job keeps fresh: the
configured ones plus, for every farm, its state and its crop's commodities."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.market_prices.base import PriceQuery
from app.integrations.market_prices.text import name_key
from app.models.farm import Farm

# FasalSetu crop names (frontend FarmsPage CROPS) -> Agmarknet 2.0 commodity
# names, most relevant first. Farmers growing rice mostly sell paddy.
CROP_TO_COMMODITIES: dict[str, list[str]] = {
    "rice": ["Paddy(Common)", "Rice"],
    "wheat": ["Wheat"],
    "onion": ["Onion"],
    "tomato": ["Tomato"],
    "sugarcane": ["Sugarcane"],
    "cotton": ["Cotton"],
    "maize": ["Maize"],
    "soybean": ["Soyabean"],
    "potato": ["Potato"],
    "chilli": ["Green Chilli", "Dry Chillies"],
}


def commodities_for_crop(crop: str | None) -> list[str]:
    if not crop:
        return []
    key = crop.strip().lower()
    if key == "other":
        return []
    return CROP_TO_COMMODITIES.get(key, [crop.strip()])


def configured_pairs() -> list[tuple[str, str]]:
    return [(s, c) for s in settings.market_price_states for c in settings.market_price_commodities]


async def farm_pairs(session: AsyncSession) -> list[tuple[str, str]]:
    rows = await session.execute(select(Farm.state, Farm.crop).where(Farm.state.is_not(None)).distinct())
    return [(state, commodity) for state, crop in rows if state for commodity in commodities_for_crop(crop)]


async def watchlist(session: AsyncSession, *, include_farms: bool = True) -> list[tuple[str, str]]:
    pairs = configured_pairs() + (await farm_pairs(session) if include_farms else [])
    seen: set[tuple[str, str]] = set()
    unique = []
    for state, commodity in pairs:
        key = (name_key(state), name_key(commodity))
        if key not in seen:
            seen.add(key)
            unique.append((state, commodity))
    return unique


def current_queries(pairs: list[tuple[str, str]], *, today: date, days_back: int) -> list[PriceQuery]:
    """Re-fetch the last `days_back` days: mandis report late and revise,
    and the upsert makes the overlap free."""
    start = today - timedelta(days=days_back)
    return [PriceQuery(state=s, commodity=c, from_date=start, to_date=today) for s, c in pairs]

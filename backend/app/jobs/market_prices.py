"""Scheduled mandi price work (registered in app/jobs/scheduler.py; each also
runnable by hand from backend/scripts/)."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.integrations.market_prices.agmarknet import AgmarknetProvider
from app.integrations.market_prices.registry import configured_providers
from app.integrations.market_prices.text import commodity_keys, name_key
from app.ml.price_forecast.service import generate_forecasts, train_models
from app.models.market_price import Commodity, MarketPriceDaily, MarketState, PriceIngestionRun
from app.services.market_prices.analytics import refresh_analytics
from app.services.market_prices.ingestion import MarketPriceIngestionService
from app.services.market_prices.watchlist import current_queries, watchlist

logger = logging.getLogger(__name__)


async def _close(providers) -> None:
    for provider in providers:
        await provider.aclose()


async def refresh_after_ingestion(session, touched) -> None:
    """Rebuild the daily series + stats for whatever the ingestion changed.
    Logged, not raised: stale analytics beat a failed job."""
    if not touched:
        return
    try:
        summary = await refresh_analytics(session, touched)
        logger.info("Market price analytics refreshed: %s", summary)
    except Exception:  # noqa: BLE001
        await session.rollback()
        logger.exception("Market price analytics refresh failed")


async def run_market_catalog_sync(session_factory=None) -> PriceIngestionRun:
    """Weekly: refresh states/districts/markets/commodities/varieties/grades
    from Agmarknet 2.0's catalogue."""
    provider = AgmarknetProvider()
    try:
        async with (session_factory or AsyncSessionLocal)() as session:
            run = await MarketPriceIngestionService(session, [provider]).sync_catalog(provider)
    finally:
        await provider.aclose()
    if run.status != "succeeded":
        logger.warning("Market catalogue sync failed: %s", run.error)
    return run


async def run_current_price_ingestion(
    session_factory=None,
    *,
    providers=None,
    today: date | None = None,
) -> PriceIngestionRun:
    """Nightly: re-fetch the last MARKET_PRICE_CURRENT_DAYS days for every
    watched (state, commodity). Failures are recorded on the run, never
    raised -- the API keeps serving what's stored, marked stale."""
    today = today or date.today()
    owned = providers is None
    providers = providers if providers is not None else configured_providers()
    try:
        async with (session_factory or AsyncSessionLocal)() as session:
            pairs = await watchlist(session, include_farms=settings.MARKET_PRICE_INCLUDE_FARM_CROPS)
            queries = current_queries(pairs, today=today, days_back=settings.MARKET_PRICE_CURRENT_DAYS)
            service = MarketPriceIngestionService(session, providers, today=today)
            run = await service.ingest(
                queries, kind="current", params={"pairs": [list(p) for p in pairs], "days_back": settings.MARKET_PRICE_CURRENT_DAYS}
            )
            await refresh_after_ingestion(session, service.touched)
    finally:
        if owned:
            await _close(providers)
    if run.status != "succeeded":
        logger.warning("Market price ingestion %s: %s", run.status, run.error)
    return run


async def watched_slots(session) -> list[tuple[int, int]]:
    """(commodity_id, state_id) for every watched pair that has daily data."""
    pairs = await watchlist(session, include_farms=settings.MARKET_PRICE_INCLUDE_FARM_CROPS)
    have = set((await session.execute(select(MarketPriceDaily.commodity_id, MarketPriceDaily.state_id).distinct())).all())
    states = {s.name_key: s.id for s in (await session.scalars(select(MarketState))).all()}
    commodities: dict[str, list[int]] = {}
    for c in (await session.scalars(select(Commodity))).all():
        commodities.setdefault(c.name_key, []).append(c.id)
    slots: list[tuple[int, int]] = []
    for state, commodity in pairs:
        state_id = states.get(name_key(state))
        for key in commodity_keys(commodity):
            for commodity_id in commodities.get(key, []):
                slot = (commodity_id, state_id)
                if state_id and slot in have and slot not in slots:
                    slots.append(slot)
    return slots


async def run_price_model_training(session_factory=None) -> int:
    """Weekly: retrain forecasters for every watched commodity x state."""
    trained = 0
    async with (session_factory or AsyncSessionLocal)() as session:
        for commodity_id, state_id in await watched_slots(session):
            try:
                trained += len(await train_models(session, commodity_id, state_id))
            except Exception:  # noqa: BLE001 -- one bad slot must not stop the rest
                await session.rollback()
                logger.exception("Training failed for commodity %s state %s", commodity_id, state_id)
    logger.info("Price model training finished: %d model(s) registered", trained)
    return trained


async def run_price_forecasts(session_factory=None) -> int:
    """Nightly, after ingestion: refresh 7/14/30-day estimates."""
    written = 0
    async with (session_factory or AsyncSessionLocal)() as session:
        for commodity_id, state_id in await watched_slots(session):
            try:
                written += await generate_forecasts(session, commodity_id, state_id)
            except Exception:  # noqa: BLE001
                await session.rollback()
                logger.exception("Forecasting failed for commodity %s state %s", commodity_id, state_id)
    logger.info("Price forecasts refreshed: %d estimate(s)", written)
    return written

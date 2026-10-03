"""Fetch mandi prices now, the same way the nightly job does.

    cd backend
    python scripts/ingest_market_prices.py                  # the nightly watchlist, last N days
    python scripts/ingest_market_prices.py --state "West Bengal" --commodity Potato --days 30
    python scripts/ingest_market_prices.py --state "West Bengal" --commodity Potato \\
        --from 2026-08-01 --to 2026-09-27 --provider agmarknet

For long date ranges use scripts/backfill_market_prices.py (resumable).
Exit code 1 if the run didn't fully succeed.
"""

import argparse
import asyncio
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.integrations.market_prices.base import PriceQuery  # noqa: E402
from app.integrations.market_prices.registry import build_provider, configured_providers  # noqa: E402
from app.jobs.market_prices import refresh_after_ingestion, run_current_price_ingestion  # noqa: E402
from app.services.market_prices.ingestion import MarketPriceIngestionService  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", action="append", help="Agmarknet state name (repeatable)")
    parser.add_argument("--commodity", action="append", help="Agmarknet commodity name (repeatable)")
    parser.add_argument("--days", type=int, help=f"days back from today (default {settings.MARKET_PRICE_CURRENT_DAYS})")
    parser.add_argument("--from", dest="from_date", type=date.fromisoformat)
    parser.add_argument("--to", dest="to_date", type=date.fromisoformat)
    parser.add_argument("--provider", action="append", help="agmarknet / ceda / data_gov_in (repeatable, in order)")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    providers = [build_provider(p) for p in args.provider] if args.provider else configured_providers()
    try:
        if not (args.state or args.commodity or args.from_date):
            run = await run_current_price_ingestion(providers=providers)
        else:
            today = date.today()
            to_date = args.to_date or today
            from_date = args.from_date or to_date - timedelta(days=args.days or settings.MARKET_PRICE_CURRENT_DAYS)
            states = args.state or settings.market_price_states
            commodities = args.commodity or settings.market_price_commodities
            queries = [PriceQuery(s, c, from_date, to_date) for s in states for c in commodities]
            async with AsyncSessionLocal() as session:
                service = MarketPriceIngestionService(session, providers, today=today)
                run = await service.ingest(
                    queries, kind="current", params={"manual": True, "from": str(from_date), "to": str(to_date)}
                )
                await refresh_after_ingestion(session, service.touched)
    finally:
        for provider in providers:
            await provider.aclose()

    print(
        f"Run {run.id} {run.status} in {run.duration_ms} ms via {run.provider}: "
        f"{run.records_fetched} fetched, {run.records_inserted} inserted, {run.records_updated} updated, "
        f"{run.records_skipped} skipped, {run.records_rejected} rejected, {run.records_flagged} flagged, "
        f"{run.requests_made} request(s)"
    )
    for note in run.notes:
        print("  ", note)
    if run.error:
        print("Errors:", run.error)
    return 0 if run.status == "succeeded" else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from app.core.database import engine

    engine.echo = False  # development mode echoes every SQL statement
    sys.exit(asyncio.run(main()))

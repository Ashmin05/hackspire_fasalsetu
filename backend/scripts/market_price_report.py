"""Rebuild market price analytics and/or print the data-quality report.

    cd backend
    python scripts/market_price_report.py --rebuild            # daily series + stats for every commodity
    python scripts/market_price_report.py --quality [--days 90]
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.market_price import MarketPrice  # noqa: E402
from app.services.market_prices.analytics import refresh_analytics  # noqa: E402
from app.services.market_prices.quality import quality_report  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--quality", action="store_true")
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    if not (args.rebuild or args.quality):
        parser.error("choose --rebuild and/or --quality")
    async with AsyncSessionLocal() as session:
        if args.rebuild:
            commodity_ids = (await session.scalars(select(MarketPrice.commodity_id).distinct())).all()
            summary = await refresh_analytics(session, {cid: None for cid in commodity_ids})
            print("Rebuilt:", summary)
        if args.quality:
            print(json.dumps(await quality_report(session, today=date.today(), window_days=args.days), indent=2, default=str))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from app.core.database import engine

    engine.echo = False  # development mode echoes every SQL statement
    sys.exit(asyncio.run(main()))

"""Opt-in: fill market coordinates from OpenStreetMap Nominatim so nearby-
mandi comparison can show distances. Markets it can't place stay without
coordinates (never guessed). ~1 request/second per Nominatim's policy.

    cd backend
    python scripts/geocode_markets.py --state "West Bengal" [--overwrite]

Data (c) OpenStreetMap contributors, ODbL.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.market_prices.nearby import geocode_markets  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", action="append", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    async with AsyncSessionLocal() as session:
        counts = await geocode_markets(session, state_names=args.state, overwrite=args.overwrite)
    print(f"Geocoded: {counts}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from app.core.database import engine

    engine.echo = False  # development mode echoes every SQL statement
    sys.exit(asyncio.run(main()))

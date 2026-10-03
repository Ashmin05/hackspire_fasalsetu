"""Refresh the mandi catalogue (states, districts, markets, commodities,
varieties, grades) from Agmarknet 2.0.

    cd backend && python scripts/sync_market_catalog.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.jobs.market_prices import run_market_catalog_sync  # noqa: E402


async def main() -> int:
    run = await run_market_catalog_sync()
    print(f"Catalogue sync {run.status} in {run.duration_ms} ms: {run.notes[0] if run.notes else run.error}")
    return 0 if run.status == "succeeded" else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from app.core.database import engine

    engine.echo = False  # development mode echoes every SQL statement
    sys.exit(asyncio.run(main()))

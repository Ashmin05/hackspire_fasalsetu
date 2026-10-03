"""Train (evaluate + select + store) price forecasters, and optionally
generate forecasts with them.

    cd backend
    python scripts/train_price_models.py                       # every watched commodity x state
    python scripts/train_price_models.py --state "West Bengal" --commodity Potato --forecast
    python scripts/train_price_models.py --forecast-only       # just refresh the estimates
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.integrations.market_prices.text import commodity_keys, name_key  # noqa: E402
from app.jobs.market_prices import watched_slots  # noqa: E402
from app.ml.price_forecast.service import generate_forecasts, train_models  # noqa: E402
from app.models.market_price import Commodity, MarketState  # noqa: E402


async def resolve(session, states: list[str], commodities: list[str]) -> list[tuple[int, int]]:
    all_states = (await session.scalars(select(MarketState))).all()
    all_commodities = (await session.scalars(select(Commodity))).all()
    slots = []
    for s in states:
        state = next((x for x in all_states if x.name_key == name_key(s)), None)
        if state is None:
            raise SystemExit(f"Unknown state {s!r}")
        for c in commodities:
            keys = commodity_keys(c)
            slots += [(x.id, state.id) for x in all_commodities if x.name_key in keys]
    return slots


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", action="append")
    parser.add_argument("--commodity", action="append")
    parser.add_argument("--forecast", action="store_true", help="generate forecasts after training")
    parser.add_argument("--forecast-only", action="store_true")
    args = parser.parse_args()
    async with AsyncSessionLocal() as session:
        if args.state and args.commodity:
            slots = await resolve(session, args.state, args.commodity)
        else:
            slots = await watched_slots(session)
        for commodity_id, state_id in slots:
            if not args.forecast_only:
                for m in await train_models(session, commodity_id, state_id):
                    table = {name: {k: v[k] for k in ("mae", "rmse", "mape")} for name, v in m.evaluation["models"].items()}
                    print(
                        f"commodity={commodity_id} state={state_id} {m.horizon_days}d -> {m.model_name} "
                        f"(MAE {m.mae}, RMSE {m.rmse}, MAPE {m.mape}%) | {m.evaluation['selection_note']}"
                    )
                    print("   ", json.dumps(table))
                    print("    80% interval coverage on the last fold:", m.evaluation["interval"]["holdout_coverage"])
            if args.forecast or args.forecast_only:
                written = await generate_forecasts(session, commodity_id, state_id)
                print(f"commodity={commodity_id} state={state_id}: {written} forecast(s)")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from app.core.database import engine

    engine.echo = False  # development mode echoes every SQL statement
    sys.exit(asyncio.run(main()))

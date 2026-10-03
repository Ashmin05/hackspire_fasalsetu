"""Historical mandi price backfill -- configurable and resumable.

    cd backend
    # create a job (one task per state x commodity x month) and run it
    python scripts/backfill_market_prices.py create --start 2021-01-01 --end 2026-09-27 \\
        --state "West Bengal" --commodity Potato --commodity Tomato --run
    # resume / retry an interrupted or partly failed job
    python scripts/backfill_market_prices.py run --job 1
    # progress
    python scripts/backfill_market_prices.py status --job 1

Optional --district / --market narrow what's stored (the source request
is per state, so they don't reduce requests). A job is capped at 2,000
monthly requests -- split bigger ones. Agmarknet 2.0 has data from Jan 2021;
earlier months fall back to CEDA (needs CEDA_API_KEY; 40 requests/hour).
"""

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.integrations.market_prices.registry import build_provider, configured_providers  # noqa: E402
from app.services.market_prices.backfill import BackfillConfigError, MarketPriceBackfillService  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="create a job")
    create.add_argument("--start", required=True, type=date.fromisoformat)
    create.add_argument("--end", required=True, type=date.fromisoformat)
    create.add_argument("--state", action="append", required=True)
    create.add_argument("--commodity", action="append", required=True)
    create.add_argument("--district")
    create.add_argument("--market")
    create.add_argument("--name")
    create.add_argument("--run", action="store_true", help="run it straight away")
    run = sub.add_parser("run", help="run / resume a job")
    run.add_argument("--job", required=True, type=int)
    run.add_argument("--max-tasks", type=int)
    status = sub.add_parser("status", help="show a job's progress")
    status.add_argument("--job", required=True, type=int)
    for p in (create, run):
        p.add_argument("--provider", action="append", help="agmarknet / ceda / data_gov_in (repeatable, in order)")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    providers = []
    if args.command in ("create", "run"):
        providers = [build_provider(p) for p in args.provider] if args.provider else configured_providers()
    try:
        async with AsyncSessionLocal() as session:
            service = MarketPriceBackfillService(session, providers)
            if args.command == "create":
                job = await service.create_job(
                    start=args.start, end=args.end, states=args.state, commodities=args.commodity,
                    district=args.district, market=args.market, name=args.name,
                )
                progress = await service.progress(job.id)
                print(f"Created backfill job {job.id}: {progress.total} task(s)")
                if not args.run:
                    return 0
                job_id = job.id
                max_tasks = None
            elif args.command == "run":
                job_id, max_tasks = args.job, args.max_tasks
            else:
                print((await service.progress(args.job)).as_dict())
                return 0
            progress = await service.run_job(job_id, max_tasks=max_tasks)
            print(f"Backfill job {job_id}: {progress.as_dict()}")
            return 0 if progress.failed == 0 else 1
    except BackfillConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    finally:
        for provider in providers:
            await provider.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from app.core.database import engine

    engine.echo = False  # development mode echoes every SQL statement
    sys.exit(asyncio.run(main()))

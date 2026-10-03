"""Configurable, resumable historical backfill.

A job is (start, end, states, commodities[, district][, market]). It's
split into one task per state x commodity x calendar month -- exactly one
Agmarknet request each. Running a job processes tasks that aren't done yet,
committing after every task, so an interrupted or partly failed job simply
continues on the next run. Tasks failing MAX_ATTEMPTS times are left
'failed' (with the error) for a human to look at.
"""

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.market_prices.agmarknet import months_between
from app.integrations.market_prices.base import PriceDataProvider, PriceQuery
from app.models.market_price import PriceBackfillJob, PriceBackfillTask
from app.repositories.market_price_repository import MarketPriceRepository
from app.services.market_prices.analytics import refresh_analytics
from app.services.market_prices.ingestion import MarketPriceIngestionService

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
# Guard against "download everything": a job this big must be split up.
MAX_TASKS_PER_JOB = 2000


class BackfillConfigError(ValueError):
    pass


@dataclass
class BackfillProgress:
    job_id: int
    total: int
    done: int
    failed: int
    pending: int
    status: str

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def month_periods(start: date, end: date) -> list[tuple[date, date]]:
    periods = []
    for year, month in months_between(start, end):
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        periods.append((max(first, start), min(last, end)))
    return periods


class MarketPriceBackfillService:
    def __init__(self, session: AsyncSession, providers: list[PriceDataProvider], *, today: date | None = None) -> None:
        self.session = session
        self.providers = providers
        self.today = today or date.today()
        self.repository = MarketPriceRepository(session)

    async def create_job(
        self,
        *,
        start: date,
        end: date,
        states: list[str],
        commodities: list[str],
        district: str | None = None,
        market: str | None = None,
        name: str | None = None,
    ) -> PriceBackfillJob:
        if start > end:
            raise BackfillConfigError("start date is after end date")
        if end > self.today:
            raise BackfillConfigError("end date is in the future")
        if not states or not commodities:
            raise BackfillConfigError("at least one state and one commodity are required")
        periods = month_periods(start, end)
        total = len(periods) * len(states) * len(commodities)
        if total > MAX_TASKS_PER_JOB:
            raise BackfillConfigError(
                f"{total} monthly requests exceeds the {MAX_TASKS_PER_JOB} per-job limit -- narrow the range or split the job"
            )
        job = PriceBackfillJob(
            name=name,
            status="pending",
            params={
                "start": start.isoformat(),
                "end": end.isoformat(),
                "states": states,
                "commodities": commodities,
                "district": district,
                "market": market,
            },
        )
        self.session.add(job)
        await self.session.flush()
        for state in states:
            for commodity in commodities:
                for period_start, period_end in periods:
                    self.session.add(
                        PriceBackfillTask(
                            job_id=job.id, state=state, commodity=commodity,
                            period_start=period_start, period_end=period_end, status="pending",
                        )
                    )
        await self.session.commit()
        logger.info("Backfill job %s created: %d task(s)", job.id, total)
        return job

    async def progress(self, job_id: int) -> BackfillProgress:
        job = await self.session.get(PriceBackfillJob, job_id)
        if job is None:
            raise BackfillConfigError(f"no backfill job {job_id}")
        rows = await self.session.execute(
            select(PriceBackfillTask.status, func.count()).where(PriceBackfillTask.job_id == job_id).group_by(PriceBackfillTask.status)
        )
        counts = dict(rows.all())
        total = sum(counts.values())
        return BackfillProgress(
            job_id=job_id,
            total=total,
            done=counts.get("done", 0),
            failed=counts.get("failed", 0),
            pending=counts.get("pending", 0) + counts.get("running", 0),
            status=job.status,
        )

    async def run_job(self, job_id: int, *, max_tasks: int | None = None) -> BackfillProgress:
        """Process the job's unfinished tasks (oldest month first). Safe to
        call repeatedly; returns progress afterwards."""
        job = await self.session.get(PriceBackfillJob, job_id)
        if job is None:
            raise BackfillConfigError(f"no backfill job {job_id}")
        params = job.params
        job.status = "running"
        await self.session.commit()

        task_ids = (
            await self.session.scalars(
                select(PriceBackfillTask.id)
                .where(
                    PriceBackfillTask.job_id == job_id,
                    # 'running' = left behind by a crashed process; retry it.
                    PriceBackfillTask.status.in_(("pending", "running", "failed")),
                    PriceBackfillTask.attempts < MAX_ATTEMPTS,
                )
                .order_by(PriceBackfillTask.period_start, PriceBackfillTask.state, PriceBackfillTask.commodity)
            )
        ).all()
        if max_tasks is not None:
            task_ids = task_ids[:max_tasks]

        ingestion = MarketPriceIngestionService(self.session, self.providers, today=self.today)
        await ingestion.ensure_catalog()
        run = await self.repository.start_run("backfill", params={"job_id": job_id, "tasks": len(task_ids)})
        run_id = run.id

        for position, task_id in enumerate(task_ids, start=1):
            task = await self.session.get(PriceBackfillTask, task_id)
            task.status = "running"
            task.attempts += 1
            await self.session.commit()
            query = PriceQuery(
                state=task.state,
                commodity=task.commodity,
                from_date=task.period_start,
                to_date=task.period_end,
                district=params.get("district"),
                market=params.get("market"),
            )
            outcome = await ingestion.ingest_query(query, run_id=run_id)

            task = await self.session.get(PriceBackfillTask, task_id)
            task.provider = outcome.provider
            task.records_fetched = outcome.stats.fetched
            task.records_inserted = outcome.stats.inserted
            task.records_updated = outcome.stats.updated
            task.records_rejected = outcome.stats.rejected
            task.run_id = run_id
            task.status = "done" if outcome.ok else "failed"
            task.last_error = outcome.error
            run = await self.repository.get_run(run_id)
            outcome.stats.add_to(run)
            await self.session.commit()
            logger.info(
                "Backfill job %s [%d/%d] %s %s %s..%s: %s (%d fetched, %d inserted)%s",
                job_id, position, len(task_ids), task.state, task.commodity, task.period_start, task.period_end,
                task.status, outcome.stats.fetched, outcome.stats.inserted,
                f" -- {outcome.error}" if outcome.error else "",
            )

        if ingestion.touched:
            await refresh_analytics(self.session, ingestion.touched)

        progress = await self.progress(job_id)
        job = await self.session.get(PriceBackfillJob, job_id)
        job.status = "done" if progress.done == progress.total else "incomplete"
        run = await self.repository.get_run(run_id)
        run.notes = [progress.as_dict()]
        await self.session.commit()
        status = "succeeded" if progress.failed == 0 else ("partial" if progress.done else "failed")
        await self.repository.finish_run(run, status=status)
        progress.status = job.status
        return progress

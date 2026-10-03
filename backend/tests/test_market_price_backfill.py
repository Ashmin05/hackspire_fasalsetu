"""Resumable historical backfill."""

from datetime import date

import httpx
import pytest
import respx
from sqlalchemy import func, select
from tenacity import wait_none

from app.integrations.market_prices.agmarknet import BASE_URL, DATEWISE_PATH, FILTERS_PATH, AgmarknetProvider
from app.integrations.market_prices.base import PriceQuery, ProviderPriceBatch, ProviderUnsupportedError
from app.models.market_price import MarketPrice, PriceBackfillTask
from app.services.market_prices.backfill import (
    MAX_ATTEMPTS,
    BackfillConfigError,
    MarketPriceBackfillService,
    month_periods,
)
from tests.market_prices_fixtures import load
from tests.test_market_price_ingestion import FakeProvider, loaded, record

TODAY = date(2026, 9, 27)


class MonthlyProvider(FakeProvider):
    """Serves one distinct record per requested month; can fail months."""

    def __init__(self, name="agmarknet", fail_months=()):
        super().__init__(name=name)
        self.fail_months = set(fail_months)
        self.queries: list[PriceQuery] = []

    async def fetch_prices(self, query):
        self.queries.append(query)
        month = query.from_date.strftime("%Y-%m")
        if month in self.fail_months:
            from app.integrations.market_prices.base import ProviderError

            raise ProviderError(f"HTTP 502 for {month}")
        return ProviderPriceBatch(
            [record(source=self.name, source_record_id=f"{self.name}:{month}", arrival_date=query.from_date,
                    state_external_id=None if self.name != "agmarknet" else "36")],
            requests_made=1,
        )


def backfill(session, providers) -> MarketPriceBackfillService:
    return MarketPriceBackfillService(session, providers, today=TODAY)


async def job(session, providers, **kw):
    params = dict(start=date(2026, 5, 15), end=date(2026, 8, 10), states=["West Bengal"], commodities=["Potato"])
    params.update(kw)
    return await backfill(session, providers).create_job(**params)


def test_month_periods_clip_to_the_range() -> None:
    assert month_periods(date(2026, 1, 15), date(2026, 3, 2)) == [
        (date(2026, 1, 15), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 3, 1), date(2026, 3, 2)),
    ]


class TestCreate:
    async def test_one_task_per_state_commodity_month(self, session) -> None:
        created = await job(session, [], commodities=["Potato", "Tomato"])
        progress = await backfill(session, []).progress(created.id)
        assert (progress.total, progress.pending, progress.status) == (8, 8, "pending")

    @pytest.mark.parametrize(
        ("kw", "message"),
        [
            ({"start": date(2026, 9, 1), "end": date(2026, 8, 1)}, "after end"),
            ({"end": date(2026, 10, 1)}, "future"),
            ({"states": []}, "at least one"),
            ({"start": date(2021, 1, 1), "end": date(2026, 9, 1), "commodities": [f"C{i}" for i in range(30)]}, "per-job limit"),
        ],
    )
    async def test_rejects_unbounded_or_invalid_jobs(self, session, kw, message) -> None:
        with pytest.raises(BackfillConfigError, match=message):
            await job(session, [], **kw)


class TestRun:
    async def test_runs_every_month_once(self, session) -> None:
        await loaded(session)
        provider = MonthlyProvider()
        created = await job(session, [provider])

        progress = await backfill(session, [provider]).run_job(created.id)

        assert (progress.done, progress.failed, progress.status) == (4, 0, "done")
        assert [(q.from_date, q.to_date) for q in provider.queries] == month_periods(date(2026, 5, 15), date(2026, 8, 10))
        assert await session.scalar(select(func.count()).select_from(MarketPrice)) == 4

    async def test_resumes_after_failures_without_duplicating(self, session) -> None:
        await loaded(session)
        created = await job(session, [])
        flaky = MonthlyProvider(fail_months={"2026-06", "2026-07"})

        first = await backfill(session, [flaky]).run_job(created.id)
        assert (first.done, first.failed, first.status) == (2, 2, "incomplete")
        failed = (await session.scalars(select(PriceBackfillTask).where(PriceBackfillTask.status == "failed"))).all()
        assert {t.last_error for t in failed} == {"agmarknet: HTTP 502 for 2026-06", "agmarknet: HTTP 502 for 2026-07"}

        healthy = MonthlyProvider()
        second = await backfill(session, [healthy]).run_job(created.id)
        assert (second.done, second.failed, second.status) == (4, 0, "done")
        assert len(healthy.queries) == 2  # only the failed months were retried
        assert await session.scalar(select(func.count()).select_from(MarketPrice)) == 4

        third = await backfill(session, [healthy]).run_job(created.id)
        assert third.status == "done" and len(healthy.queries) == 2  # nothing left to do

    async def test_max_tasks_and_attempt_cap(self, session) -> None:
        await loaded(session)
        created = await job(session, [])
        partial = await backfill(session, [MonthlyProvider()]).run_job(created.id, max_tasks=1)
        assert (partial.done, partial.pending) == (1, 3)

        always_down = MonthlyProvider(fail_months={"2026-06", "2026-07", "2026-08"})
        for _ in range(MAX_ATTEMPTS + 1):
            await backfill(session, [always_down]).run_job(created.id)
        # Each failing month was tried MAX_ATTEMPTS times, then left alone.
        assert len(always_down.queries) == 3 * MAX_ATTEMPTS

    async def test_falls_back_to_ceda_for_months_agmarknet_lacks(self, session) -> None:
        await loaded(session)

        class TooOld(MonthlyProvider):
            async def fetch_prices(self, query):
                raise ProviderUnsupportedError("Agmarknet 2.0 has prices only from 2021-01-01")

        ceda = MonthlyProvider(name="ceda")
        created = await job(session, [], start=date(2020, 11, 1), end=date(2020, 12, 31))
        progress = await backfill(session, [TooOld(), ceda]).run_job(created.id)
        assert progress.done == 2 and len(ceda.queries) == 2
        tasks = (await session.scalars(select(PriceBackfillTask))).all()
        assert {t.provider for t in tasks} == {"ceda"}


class TestAgmarknetCoverage:
    @respx.mock
    async def test_declines_ranges_before_its_first_date_and_trims_overlaps(self) -> None:
        respx.get(BASE_URL + FILTERS_PATH).mock(return_value=httpx.Response(200, json=load("agmarknet_filters.json")))
        route = respx.get(BASE_URL + DATEWISE_PATH).mock(return_value=httpx.Response(200, json=load("agmarknet_datewise_empty.json")))
        provider = AgmarknetProvider(wait=wait_none(), min_request_interval=0)

        with pytest.raises(ProviderUnsupportedError):
            await provider.fetch_prices(PriceQuery("West Bengal", "Potato", date(2020, 1, 1), date(2020, 12, 31)))
        batch = await provider.fetch_prices(PriceQuery("West Bengal", "Potato", date(2020, 12, 1), date(2021, 1, 31)))
        assert [c.request.url.params["month"] for c in route.calls] == ["1"]
        assert "earlier days skipped" in batch.notes[0]

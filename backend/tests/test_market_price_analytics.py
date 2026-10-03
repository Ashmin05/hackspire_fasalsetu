"""Daily series, precomputed stats, data-quality report and nearby mandis."""

from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
import respx
from sqlalchemy import select

from app.integrations.market_prices.base import ProviderPriceBatch
from app.jobs.market_prices import run_current_price_ingestion
from app.models.market_price import Commodity, Market, MarketPriceDaily, MarketPriceStats, MarketState
from app.services.market_prices.analytics import (
    DayPrice,
    compute_stats,
    pct_change,
    rebuild_daily,
    refresh_analytics,
    trend_of,
)
from app.services.market_prices.ingestion import MarketPriceIngestionService
from app.services.market_prices.nearby import (
    NOMINATIM_SOURCE,
    NOMINATIM_URL,
    geocode_markets,
    haversine_km,
    nearby_markets,
    place_name,
)
from app.services.market_prices.quality import quality_report
from tests.test_market_price_ingestion import QUERY, TODAY, FakeProvider, loaded, record

AS_OF = date(2026, 9, 25)


def series(prices: dict[int, float]) -> list[DayPrice]:
    """{days_before_AS_OF: modal} -> sorted DayPrice list."""
    return sorted((DayPrice(AS_OF - timedelta(days=d), p) for d, p in prices.items()), key=lambda p: p.date)


class TestStats:
    def test_windows_changes_and_extremes(self) -> None:
        # Daily prices for 35 days: 1000 rising by 10/day up to today.
        points = series({d: 1000 + (35 - d) * 10 for d in range(0, 36)})
        s = compute_stats(points)

        assert s["as_of_date"] == AS_OF and s["current_modal_price"] == Decimal("1350.00")
        assert s["avg_7d"] == Decimal("1320.00")  # mean of 1290..1350
        assert s["avg_30d"] == Decimal("1205.00")  # mean of 1060..1350
        assert (s["min_7d"], s["max_7d"]) == (Decimal("1290.00"), Decimal("1350.00"))
        assert s["change_7d_pct"] == pct_change(1350, 1280)  # 7 days before: 1280
        assert s["change_30d_pct"] == pct_change(1350, 1050)
        assert s["trading_days_30d"] == 30
        assert s["trend"] == "increasing"

    def test_change_uses_the_latest_price_within_the_grace_window(self) -> None:
        # No trade exactly 7 days back; the latest before it (9 days) is used.
        points = series({0: 1100, 9: 1000, 20: 950})
        assert compute_stats(points)["change_7d_pct"] == 10.0
        # Nothing within 7+7 days -> no 7-day change, rather than a stale one.
        assert compute_stats(series({0: 1100, 20: 1000}))["change_7d_pct"] is None

    def test_zero_or_missing_reference_is_safe(self) -> None:
        assert pct_change(100, 0) is None and pct_change(100, None) is None

    def test_volatility_needs_five_changes(self) -> None:
        assert compute_stats(series({0: 100, 1: 110, 2: 100}))["volatility_30d_pct"] is None
        assert compute_stats(series({d: 100 + (d % 2) * 10 for d in range(8)}))["volatility_30d_pct"] > 0

    @pytest.mark.parametrize(
        ("recent", "before", "expected"),
        [(1030, 1000, "increasing"), (1010, 1000, "stable"), (970, 1000, "decreasing")],
    )
    def test_trend_thresholds(self, recent, before, expected) -> None:
        points = series({**{d: before for d in range(7, 14)}, **{d: recent for d in range(0, 7)}})
        assert trend_of(points, AS_OF)[0] == expected

    def test_trend_needs_three_days_in_each_week(self) -> None:
        points = series({0: 1000, 1: 1000, 2: 1000, 8: 900, 9: 900})
        assert trend_of(points, AS_OF) == ("insufficient_data", None)


async def ingest(session, records) -> MarketPriceIngestionService:
    service = MarketPriceIngestionService(session, [FakeProvider(batches=[ProviderPriceBatch(records)])], today=TODAY)
    await service.ingest([QUERY], kind="current")
    return service


class TestDailySeries:
    async def test_combines_reports_and_prefers_the_primary_source(self, session) -> None:
        await loaded(session)
        day = date(2026, 9, 25)
        service = await ingest(
            session,
            [
                # Two lots: 100 t @ 1400 and 300 t @ 1600 -> weighted 1550.
                record(source_record_id="a1", modal_price=Decimal("1400"), min_price=Decimal("1300"), max_price=Decimal("1500"), arrival_quantity=Decimal("100")),
                record(source_record_id="a2", modal_price=Decimal("1600"), min_price=Decimal("1550"), max_price=Decimal("1700"), arrival_quantity=Decimal("300")),
                # CEDA's report for the same market/day is ignored.
                record(source="ceda", source_record_id="c1", modal_price=Decimal("999"), arrival_quantity=None, state_external_id=None, commodity_external_id=None),
                # Next day, one report without arrivals -> plain mean.
                record(source_record_id="b1", arrival_date=day + timedelta(days=1), modal_price=Decimal("1500"), arrival_quantity=None),
                record(source_record_id="b2", arrival_date=day + timedelta(days=1), modal_price=Decimal("1700"), arrival_quantity=Decimal("50")),
            ],
        )
        await refresh_analytics(session, service.touched)

        rows = {r.date: r for r in (await session.execute(select(MarketPriceDaily))).scalars()}
        first, second = rows[day], rows[day + timedelta(days=1)]
        assert (first.modal_price, first.weighted, first.source, first.report_count) == (Decimal("1550.00"), True, "agmarknet", 2)
        assert (first.min_price, first.max_price, first.arrival_quantity) == (Decimal("1300.00"), Decimal("1700.00"), Decimal("400.000"))
        assert (second.modal_price, second.weighted) == (Decimal("1600.00"), False)

        stats = (await session.execute(select(MarketPriceStats))).scalars().one()
        assert stats.as_of_date == day + timedelta(days=1) and stats.current_modal_price == Decimal("1600.00")

    async def test_partial_rebuild_keeps_older_days(self, session) -> None:
        await loaded(session)
        service = await ingest(session, [record(source_record_id=f"d{i}", arrival_date=date(2026, 9, 1) + timedelta(days=i)) for i in range(10)])
        commodity_id = next(iter(service.touched))
        await rebuild_daily(session, commodity_id)
        await rebuild_daily(session, commodity_id, since=date(2026, 9, 8))
        assert len((await session.execute(select(MarketPriceDaily))).scalars().all()) == 10

    async def test_nightly_job_refreshes_analytics(self, session) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        await loaded(session)
        factory = async_sessionmaker(bind=session.bind, expire_on_commit=False)
        provider = FakeProvider(batches=[ProviderPriceBatch([record()])])
        run = await run_current_price_ingestion(factory, providers=[provider], today=TODAY)
        assert run.status == "succeeded"
        assert (await session.execute(select(MarketPriceStats))).scalars().one().trend == "insufficient_data"


class TestQualityReport:
    async def test_reports_abnormal_moves_gaps_stale_markets_and_issues(self, session) -> None:
        await loaded(session)
        records = [
            record(source_record_id="p1", arrival_date=date(2026, 9, 1), modal_price=Decimal("1000")),
            record(source_record_id="p2", arrival_date=date(2026, 9, 2), modal_price=Decimal("1800")),  # +80%
            record(source_record_id="p3", arrival_date=date(2026, 9, 25), modal_price=Decimal("1800")),  # 23-day gap
            record(source_record_id="s1", market="Burdwan APMC", market_external_id=None, district="Purba Bardhaman",
                   arrival_date=date(2026, 9, 3)),  # stale vs 25th
            record(source_record_id="bad", modal_price=None, parse_issues=["modal_price missing"]),
        ]
        service = await ingest(session, records)
        await refresh_analytics(session, service.touched)

        report = await quality_report(session, today=TODAY)

        assert report["stored_records"] == 4
        assert report["abnormal_changes"]["count"] == 1 and report["abnormal_changes"]["examples"][0]["change_pct"] == 80.0
        assert report["missing_dates"]["count"] == 1 and report["missing_dates"]["examples"][0]["days"] == 23
        assert report["stale_markets"]["count"] == 1 and report["stale_markets"]["examples"][0]["market"] == "Burdwan APMC"
        assert {"severity": "rejected", "code": "missing_modal_price", "count": 1} in report["issues_by_code"]
        assert report["recent_runs"][0]["rejected"] == 1


class TestNearby:
    def test_haversine(self) -> None:
        # Kolkata (22.5726, 88.3639) -> Bardhaman (23.2324, 87.8615): ~90 km.
        assert 85 < haversine_km(22.5726, 88.3639, 23.2324, 87.8615) < 95

    def test_place_name(self) -> None:
        assert place_name("Bishnupur(Bankura) APMC") == "Bishnupur"
        assert place_name("Egra/contai APMC") == "Egra contai"

    async def test_ranks_by_distance_then_district_then_state(self, session) -> None:
        await loaded(session)
        service = await ingest(
            session,
            [
                record(source_record_id="k", market="Bara Bazar (Posta Bazar) APMC"),
                record(source_record_id="b", market="Burdwan APMC", district="Purba Bardhaman"),
                record(source_record_id="a", market="Alipurduar APMC", district="Alipurduar"),
                record(source_record_id="s", market="Sheoraphuly APMC", district="Hooghly"),
            ],
        )
        await refresh_analytics(session, service.touched)
        markets = {m.name: m for m in (await session.execute(select(Market).where(Market.state_id.is_not(None)))).scalars()}
        markets["Bara Bazar (Posta Bazar) APMC"].latitude, markets["Bara Bazar (Posta Bazar) APMC"].longitude = 22.5850, 88.3560
        markets["Burdwan APMC"].latitude, markets["Burdwan APMC"].longitude = 23.2324, 87.8615
        await session.commit()
        commodity = (await session.execute(select(Commodity).where(Commodity.name == "Potato"))).scalars().one()
        wb = (await session.execute(select(MarketState).where(MarketState.name == "West Bengal"))).scalars().one()
        hooghly_id = markets["Sheoraphuly APMC"].district_id

        result = await nearby_markets(
            session, commodity_id=commodity.id, lat=22.5726, lon=88.3639, radius_km=50,
            state_id=wb.id, district_id=hooghly_id,
        )

        assert [(n.market.name, n.scope) for n in result] == [
            ("Bara Bazar (Posta Bazar) APMC", "radius"),  # ~1.5 km
            ("Sheoraphuly APMC", "district"),  # no coordinates, same district
            ("Alipurduar APMC", "state"),
        ]  # Burdwan has coordinates but is ~90 km away -> outside the radius
        assert result[0].distance_km < 3 and result[1].distance_km is None

    @respx.mock
    async def test_geocoding_records_source_and_precision_and_never_guesses(self, session) -> None:
        await loaded(session)

        def answer(request):
            q = request.url.params["q"]
            if q.startswith("Alipurduar,"):
                return httpx.Response(200, json=[{"lat": "26.49", "lon": "89.52"}])
            if q == "Purba Bardhaman district, West Bengal, India":
                return httpx.Response(200, json=[{"lat": "23.25", "lon": "87.85"}])
            return httpx.Response(200, json=[])

        respx.get(NOMINATIM_URL).mock(side_effect=answer)
        counts = await geocode_markets(session, state_names=["West Bengal"], delay_seconds=0)

        alipurduar = (await session.execute(select(Market).where(Market.name == "Alipurduar APMC"))).scalars().one()
        burdwan = (await session.execute(select(Market).where(Market.name == "Burdwan APMC"))).scalars().one()
        howrah = (await session.execute(select(Market).where(Market.name.like("Howrah%")))).scalars().first()
        assert (alipurduar.latitude, alipurduar.coordinate_precision, alipurduar.coordinate_source) == (26.49, "place", NOMINATIM_SOURCE)
        assert (burdwan.latitude, burdwan.coordinate_precision) == (23.25, "district")
        assert howrah is None or howrah.latitude is None
        assert counts["place"] >= 1 and counts["not_found"] >= 1

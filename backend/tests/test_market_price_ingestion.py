"""Validation, catalogue resolution and the ingestion pipeline, on an
in-memory SQLite DB, fed by real captured responses (respx) or a fake
provider for edge cases."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tenacity import wait_none

from app.integrations.market_prices.agmarknet import BASE_URL, DATEWISE_PATH, FILTERS_PATH, AgmarknetProvider, parse_catalog
from app.integrations.market_prices.base import (
    NormalizedMarketPrice,
    PriceQuery,
    ProviderCatalog,
    ProviderError,
    ProviderPriceBatch,
)
from app.jobs.market_prices import run_current_price_ingestion
from app.models import Base
from app.models.farm import Farm
from app.models.market_price import Commodity, Market, MarketPrice, PriceIngestionRun, PriceQualityIssue, Variety
from app.services.market_prices.catalog import CatalogResolver, sync_catalog
from app.services.market_prices.ingestion import MarketPriceIngestionService
from app.services.market_prices.validation import validate
from app.services.market_prices.watchlist import commodities_for_crop, current_queries, watchlist
from tests.market_prices_fixtures import datewise_rows, load

TODAY = date(2026, 9, 27)
QUERY = PriceQuery("West Bengal", "Potato", date(2026, 9, 1), date(2026, 9, 30))


def record(**overrides) -> NormalizedMarketPrice:
    base = NormalizedMarketPrice(
        source="agmarknet",
        source_record_id="agmarknet:36:24:3625:jyoti:2026-09-25:1",
        state="West Bengal",
        district="Kolkata",
        market="Bara Bazar (Posta Bazar) APMC",
        commodity="Potato",
        variety="Jyoti",
        grade=None,
        arrival_date=date(2026, 9, 25),
        min_price=Decimal("1400.00"),
        max_price=Decimal("1500.00"),
        modal_price=Decimal("1450.00"),
        arrival_quantity=Decimal("120.000"),
        state_external_id="36",
        commodity_external_id="24",
        raw={"modalPrice": 1450.0},
    )
    return replace(base, **overrides)


class FakeProvider:
    """Stands in for a provider: returns fixed batches or raises."""

    def __init__(self, name="agmarknet", batches=None, error=None, catalog=None, fail_states=()):
        self.name = name
        self.batches = list(batches or [])
        self.error = error
        self.catalog = catalog
        self.fail_states = set(fail_states)
        self.calls = 0

    @property
    def configured(self) -> bool:
        return True

    async def fetch_catalog(self) -> ProviderCatalog:
        return self.catalog or parse_catalog(load("agmarknet_filters.json")["data"])

    async def fetch_prices(self, query):
        self.calls += 1
        if self.error or query.state in self.fail_states:
            raise ProviderError(self.error or f"no data for {query.state}")
        return self.batches.pop(0) if self.batches else ProviderPriceBatch()

    async def aclose(self) -> None:
        pass


async def loaded(session) -> None:
    await sync_catalog(session, parse_catalog(load("agmarknet_filters.json")["data"]))
    await session.commit()


async def count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


class TestValidation:
    def test_clean_record_passes(self) -> None:
        result = validate(record(), today=TODAY)
        assert result.accepted and result.flags == []

    @pytest.mark.parametrize(
        ("overrides", "code"),
        [
            ({"modal_price": None, "parse_issues": ["modal_price not a number: 'NR'"]}, "missing_modal_price"),
            ({"modal_price": Decimal("0.00")}, "zero_modal_price"),
            ({"min_price": Decimal("-5.00")}, "negative_price"),
            ({"arrival_date": None, "parse_issues": ["arrival_date unparseable: '31/02/2026'"]}, "invalid_date"),
            ({"arrival_date": date(2026, 10, 5)}, "future_date"),
            ({"market": None}, "missing_market"),
            ({"commodity": None}, "missing_commodity"),
            ({"price_unit": "Rs./Kg"}, "unexpected_price_unit"),
            ({"arrival_quantity": Decimal("-1")}, "invalid_arrival_quantity"),
            ({"arrival_unit": "Quintal"}, "unexpected_arrival_unit"),
        ],
    )
    def test_rejections(self, overrides, code) -> None:
        result = validate(record(**overrides), today=TODAY)
        assert not result.accepted
        assert code in {f.code for f in result.rejections}

    @pytest.mark.parametrize(
        ("overrides", "code"),
        [
            ({"min_price": Decimal("1600.00")}, "price_order"),  # min > max
            ({"modal_price": Decimal("1550.00")}, "price_order"),  # modal above max
            ({"max_price": None}, "missing_min_max"),
        ],
    )
    def test_flags_keep_the_record_and_its_values(self, overrides, code) -> None:
        r = record(**overrides)
        result = validate(r, today=TODAY)
        assert result.accepted
        assert code in {f.code for f in result.flags}
        assert result.record is r and r.modal_price == overrides.get("modal_price", Decimal("1450.00"))


class TestCatalog:
    async def test_sync_is_idempotent(self, session) -> None:
        catalog = parse_catalog(load("agmarknet_filters.json")["data"])
        first = await sync_catalog(session, catalog)
        second = await sync_catalog(session, catalog)
        assert first.created > 0 and second.created == 0 and second.updated == 0
        assert await count(session, Market) == len(catalog.markets)

    async def test_adopts_a_market_first_learnt_by_name(self, session) -> None:
        await loaded(session)
        resolver = CatalogResolver(session)
        await resolver.load()
        # A CEDA-only market appears before Agmarknet lists it...
        ids, _, flags = await resolver.resolve(record(source="ceda", market="Brand New Mandi", market_external_id=None))
        assert [f.code for f in flags] == ["new_market"]
        catalog = parse_catalog(load("agmarknet_filters.json")["data"])
        from app.integrations.market_prices.base import CatalogMarket

        catalog.markets.append(CatalogMarket("99999", "Brand New Mandi APMC", "36", None))
        await sync_catalog(session, catalog)
        # ...and is adopted (external id set) rather than duplicated.
        market = await session.get(Market, ids.market_id)
        assert market.external_id == "99999"
        assert await session.scalar(select(func.count()).select_from(Market).where(Market.name_key == "brand new")) == 1


class TestResolver:
    async def resolver(self, session) -> CatalogResolver:
        await loaded(session)
        resolver = CatalogResolver(session)
        await resolver.load()
        return resolver

    async def test_ceda_names_match_agmarknet_markets_and_commodity_aliases(self, session) -> None:
        resolver = await self.resolver(session)
        ids, rejections, flags = await resolver.resolve(
            record(source="ceda", market="Bara Bazar (Posta Bazar)", commodity="Paddy(Dhan)(Common)",
                   state_external_id=None, commodity_external_id=None, variety=None)
        )
        assert rejections == [] and flags == []
        market = await session.get(Market, ids.market_id)
        commodity = await session.get(Commodity, ids.commodity_id)
        assert (market.name, market.external_id, commodity.name) == ("Bara Bazar (Posta Bazar) APMC", "2894", "Paddy(Common)")
        assert ids.variety_id is None

    async def test_unknown_state_and_commodity_are_rejected(self, session) -> None:
        resolver = await self.resolver(session)
        _, rejections, _ = await resolver.resolve(record(state="Atlantis", state_external_id=None))
        assert [f.code for f in rejections] == ["unknown_state"]
        _, rejections, _ = await resolver.resolve(record(commodity="Unobtainium", commodity_external_id=None))
        assert [f.code for f in rejections] == ["unknown_commodity"]

    async def test_ambiguous_market_is_rejected_not_guessed(self, session) -> None:
        resolver = await self.resolver(session)
        wb = resolver.state_by_ext["36"]
        for district in (None, None):
            session.add(Market(state_id=wb.id, district_id=district, name="Twin Mandi", name_key="twin"))
        await session.flush()
        await resolver.load()
        ids, rejections, _ = await resolver.resolve(record(source="ceda", market="Twin Mandi", district=None))
        assert ids is None and [f.code for f in rejections] == ["ambiguous_market"]

    async def test_new_variety_is_created_under_its_commodity(self, session) -> None:
        resolver = await self.resolver(session)
        ids, _, _ = await resolver.resolve(record(variety="Kufri Pukhraj Special"))
        variety = await session.get(Variety, ids.variety_id)
        assert variety.name == "Kufri Pukhraj Special" and variety.external_id is None


def service(session, providers) -> MarketPriceIngestionService:
    return MarketPriceIngestionService(session, providers, today=TODAY)


class TestIngestion:
    @respx.mock
    async def test_real_report_end_to_end_and_idempotent(self, session) -> None:
        respx.get(BASE_URL + FILTERS_PATH).mock(return_value=httpx.Response(200, json=load("agmarknet_filters.json")))
        respx.get(BASE_URL + DATEWISE_PATH).mock(
            return_value=httpx.Response(200, json=load("agmarknet_datewise_wb_potato_2026_09.json"))
        )
        provider = AgmarknetProvider(wait=wait_none(), min_request_interval=0)
        rows = len(datewise_rows(load("agmarknet_datewise_wb_potato_2026_09.json")))

        first = await service(session, [provider]).ingest([QUERY], kind="current")
        second = await service(session, [provider]).ingest([QUERY], kind="current")

        assert (first.status, first.records_fetched, first.records_inserted, first.records_rejected) == ("succeeded", rows, rows, 0)
        assert (second.records_inserted, second.records_updated, second.records_skipped) == (0, 0, rows)
        assert await count(session, MarketPrice) == rows
        stored = (await session.execute(select(MarketPrice).limit(1))).scalars().one()
        assert isinstance(stored.modal_price, Decimal) and stored.unit == "Rs/quintal" and stored.arrival_unit == "tonnes"
        # The catalogue was pulled automatically on first use.
        assert await session.scalar(select(func.count()).select_from(PriceIngestionRun).where(PriceIngestionRun.kind == "catalog")) == 1

    async def test_changed_report_updates_in_place(self, session) -> None:
        await loaded(session)
        await service(session, [FakeProvider(batches=[ProviderPriceBatch([record()])])]).ingest([QUERY], kind="current")
        run = await service(session, [FakeProvider(batches=[ProviderPriceBatch([record(modal_price=Decimal("1475.00"))])])]).ingest([QUERY], kind="current")

        assert (run.records_inserted, run.records_updated) == (0, 1)
        row = (await session.execute(select(MarketPrice))).scalars().one()
        await session.refresh(row)
        assert row.modal_price == Decimal("1475.00")

    async def test_separate_lots_of_one_variety_are_both_kept(self, session) -> None:
        await loaded(session)
        lots = [record(), record(source_record_id="agmarknet:36:24:3625:jyoti:2026-09-25:2", modal_price=Decimal("1300.00"), arrival_quantity=Decimal("40"))]
        run = await service(session, [FakeProvider(batches=[ProviderPriceBatch(lots)])]).ingest([QUERY], kind="current")
        assert run.records_inserted == 2

    async def test_rejections_are_logged_with_the_raw_row_once(self, session) -> None:
        await loaded(session)
        bad = record(modal_price=None, parse_issues=["modal_price not a number: 'NR'"], raw={"modalPrice": "NR"})
        for _ in range(2):
            run = await service(session, [FakeProvider(batches=[ProviderPriceBatch([bad, record(source_record_id="ok")])])]).ingest([QUERY], kind="current")
        assert run.records_rejected == 1
        issues = (await session.execute(select(PriceQualityIssue))).scalars().all()
        assert [(i.severity, i.code, i.raw) for i in issues] == [("rejected", "missing_modal_price", {"modalPrice": "NR"})]
        assert await count(session, MarketPrice) == 1

    async def test_flagged_rows_are_stored_as_reported(self, session) -> None:
        await loaded(session)
        odd = record(min_price=Decimal("1600.00"))
        run = await service(session, [FakeProvider(batches=[ProviderPriceBatch([odd])])]).ingest([QUERY], kind="current")
        row = (await session.execute(select(MarketPrice))).scalars().one()
        assert run.records_flagged == 1 and row.quality_flags == ["price_order"]
        assert row.min_price == Decimal("1600.00")  # not "fixed"

    async def test_conflicting_duplicate_keeps_the_first(self, session) -> None:
        await loaded(session)
        batch = ProviderPriceBatch([record(), record(modal_price=Decimal("999.00"))])
        run = await service(session, [FakeProvider(batches=[batch])]).ingest([QUERY], kind="current")
        assert (run.records_inserted, run.records_rejected) == (1, 1)

    async def test_falls_back_to_the_next_provider_on_error(self, session) -> None:
        await loaded(session)
        broken = FakeProvider("agmarknet", error="HTTP 502")
        backup = FakeProvider("ceda", batches=[ProviderPriceBatch([record(source="ceda", source_record_id="ceda:1", state_external_id=None, commodity_external_id=None)])])
        run = await service(session, [broken, backup]).ingest([QUERY], kind="current")
        assert (run.status, run.provider, run.records_inserted) == ("succeeded", "ceda", 1)
        assert "agmarknet: HTTP 502" in run.notes[0]["notes"][0]

    async def test_statuses(self, session) -> None:
        await loaded(session)
        failed = await service(session, [FakeProvider(error="down")]).ingest([QUERY], kind="current")
        assert failed.status == "failed" and "down" in failed.error
        provider = FakeProvider(batches=[ProviderPriceBatch([record()])], fail_states={"Atlantis"})
        partial = await service(session, [provider]).ingest(
            [QUERY, PriceQuery("Atlantis", "Potato", QUERY.from_date, QUERY.to_date)], kind="current"
        )
        assert partial.status == "partial" and partial.records_inserted == 1
        assert "Atlantis/Potato: agmarknet: no data for Atlantis" in partial.error
        assert partial.finished_at is not None and partial.duration_ms is not None


class TestJob:
    @pytest.fixture
    async def session_factory(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(bind=engine, expire_on_commit=False)
        await engine.dispose()

    async def test_watchlist_includes_farm_crops(self, session, monkeypatch) -> None:
        from app.core.config import settings

        monkeypatch.setattr(settings, "MARKET_PRICE_STATES", "West Bengal")
        monkeypatch.setattr(settings, "MARKET_PRICE_COMMODITIES", "Potato")
        session.add(Farm(user_id=__import__("uuid").uuid4(), name="f", crop="Rice", sowing_date=TODAY, polygon_geojson={},
                         area_ha=1, centroid_lat=22.5, centroid_lng=88.3, state="West Bengal"))
        await session.commit()
        pairs = await watchlist(session)
        assert pairs == [("West Bengal", "Potato"), ("West Bengal", "Paddy(Common)"), ("West Bengal", "Rice")]
        assert current_queries(pairs[:1], today=TODAY, days_back=10)[0].from_date == date(2026, 9, 17)

    def test_commodities_for_crop(self) -> None:
        assert commodities_for_crop("Soybean") == ["Soyabean"]
        assert commodities_for_crop("Other") == [] and commodities_for_crop(None) == []
        assert commodities_for_crop("Brinjal") == ["Brinjal"]

    async def test_job_records_failures_without_raising(self, session_factory) -> None:
        async with session_factory() as session:
            await loaded(session)
        run = await run_current_price_ingestion(session_factory, providers=[FakeProvider(error="gateway down")], today=TODAY)
        assert run.status == "failed" and "gateway down" in run.error

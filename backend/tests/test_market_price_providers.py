"""Provider layer against respx-mocked copies of real API responses."""

from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx
from tenacity import wait_none

from app.integrations.market_prices.agmarknet import (
    BASE_URL as AGM_BASE,
    DATEWISE_PATH,
    FILTERS_PATH,
    AgmarknetProvider,
    months_between,
    parse_catalog,
)
from app.integrations.market_prices.base import (
    PRICE_UNIT,
    PriceQuery,
    ProviderError,
    ProviderNotConfiguredError,
)
from app.integrations.market_prices.ceda import BASE_URL as CEDA_BASE
from app.integrations.market_prices.ceda import CedaProvider
from app.integrations.market_prices.data_gov import BASE_URL as DG_BASE
from app.integrations.market_prices.data_gov import RESOURCE_ID, DataGovProvider, parse_row
from app.integrations.market_prices.text import market_key, name_key, parse_date, parse_decimal
from tests.market_prices_fixtures import datewise_rows, load

FILTERS_URL = AGM_BASE + FILTERS_PATH
DATEWISE_URL = AGM_BASE + DATEWISE_PATH
SEPT = PriceQuery(state="West Bengal", commodity="Potato", from_date=date(2026, 9, 1), to_date=date(2026, 9, 30))


def agmarknet(**kw) -> AgmarknetProvider:
    return AgmarknetProvider(wait=wait_none(), min_request_interval=0, **kw)


def mock_agmarknet(datewise=None):
    respx.get(FILTERS_URL).mock(return_value=httpx.Response(200, json=load("agmarknet_filters.json")))
    return respx.get(DATEWISE_URL).mock(
        return_value=httpx.Response(200, json=datewise or load("agmarknet_datewise_wb_potato_2026_09.json"))
    )


class TestTextHelpers:
    def test_name_key_ignores_case_punctuation_and_spacing(self) -> None:
        assert name_key("Black Gram (Urd Beans)(Whole)") == name_key("black gram(urd beans)(whole)")
        assert name_key("  Purba   Bardhaman ") == "purba bardhaman"

    def test_market_key_drops_apmc_style_suffixes(self) -> None:
        assert market_key("Bara Bazar (Posta Bazar) APMC") == market_key("Bara Bazar (Posta Bazar)")

    def test_parse_decimal(self) -> None:
        issues: list[str] = []
        assert parse_decimal("1,950", "p", issues) == Decimal("1950.00")
        assert parse_decimal(620.0, "p", issues) == Decimal("620.00")
        assert parse_decimal(1348.0701754, "p", issues) == Decimal("1348.07")
        assert issues == []
        assert parse_decimal("NR", "p", issues) is None
        assert parse_decimal(None, "p", issues) is None
        assert parse_decimal("NaN", "p", issues) is None
        assert len(issues) == 3

    def test_parse_date_formats(self) -> None:
        issues: list[str] = []
        assert parse_date("25/09/2026", issues) == date(2026, 9, 25)
        assert parse_date("2025-10-20T00:00:00.000Z", issues) == date(2025, 10, 20)
        assert parse_date("2026-09-25", issues) == date(2026, 9, 25)
        assert issues == []
        assert parse_date("31/02/2026", issues) is None
        assert issues == ["arrival_date unparseable: '31/02/2026'"]

    def test_months_between(self) -> None:
        assert months_between(date(2025, 11, 20), date(2026, 2, 1)) == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]


class TestAgmarknetCatalog:
    def test_parses_real_filters_and_drops_all_pseudo_entries(self) -> None:
        catalog = parse_catalog(load("agmarknet_filters.json")["data"])

        assert {s.name for s in catalog.states} == {"West Bengal", "Maharashtra"}
        assert all(int(m.external_id) < 100000 for m in catalog.markets)
        burdwan = next(m for m in catalog.markets if m.name == "Burdwan APMC")
        district = next(d for d in catalog.districts if d.external_id == burdwan.district_external_id)
        assert (burdwan.state_external_id, district.name) == ("36", "Purba Bardhaman")
        potato = next(c for c in catalog.commodities if c.name == "Potato")
        assert (potato.external_id, potato.commodity_group) == ("24", "Vegetables")
        assert any("24" in v.commodity_external_ids for v in catalog.varieties)
        assert catalog.earliest_price_date == date(2021, 1, 1)


class TestAgmarknetPrices:
    @respx.mock
    async def test_normalises_every_row_of_the_real_report(self) -> None:
        route = mock_agmarknet()
        body = load("agmarknet_datewise_wb_potato_2026_09.json")

        batch = await agmarknet().fetch_prices(SEPT)

        assert batch.requests_made == 1
        assert len(batch.records) == len(datewise_rows(body))
        params = route.calls.last.request.url.params
        assert (params["stateId"], params["commodityId"], params["year"], params["month"]) == ("36", "24", "2026", "9")
        assert route.calls.last.request.headers["user-agent"].startswith("FasalSetu/")

        market, day, row = datewise_rows(body)[0]
        first = batch.records[0]
        assert (first.market, first.state, first.commodity, first.variety) == (market, "West Bengal", "Potato", row["variety"])
        assert first.arrival_date.strftime("%d/%m/%Y") == day
        assert first.modal_price == Decimal(str(row["modalPrice"])).quantize(Decimal("0.01"))
        assert first.arrival_quantity == Decimal(str(row["arrivals"])).quantize(Decimal("0.01"))
        assert (first.price_unit, first.arrival_unit) == (PRICE_UNIT, "tonnes")
        assert first.market_external_id == "676" and first.district == "Alipurduar"
        assert first.parse_issues == []
        assert all(r.grade is None for r in batch.records)

    @respx.mock
    async def test_source_record_ids_are_unique_and_stable(self) -> None:
        mock_agmarknet()
        first = await agmarknet().fetch_prices(SEPT)
        second = await agmarknet().fetch_prices(SEPT)

        ids = [r.source_record_id for r in first.records]
        assert len(ids) == len(set(ids))
        assert ids == [r.source_record_id for r in second.records]

    @respx.mock
    async def test_one_request_per_month_and_date_filtering(self) -> None:
        route = mock_agmarknet()
        query = PriceQuery(state="west bengal", commodity="POTATO", from_date=date(2026, 8, 30), to_date=date(2026, 9, 24))

        batch = await agmarknet().fetch_prices(query)

        assert [c.request.url.params["month"] for c in route.calls] == ["8", "9"]
        assert batch.records and all(r.arrival_date <= date(2026, 9, 24) for r in batch.records)

    @respx.mock
    async def test_district_filter(self) -> None:
        mock_agmarknet()
        batch = await agmarknet().fetch_prices(
            PriceQuery(state="West Bengal", commodity="Potato", from_date=SEPT.from_date, to_date=SEPT.to_date, district="Purba Bardhaman")
        )
        assert {r.market for r in batch.records} == {"Burdwan APMC"}

    @respx.mock
    async def test_empty_month_is_noted_not_an_error(self) -> None:
        mock_agmarknet(load("agmarknet_datewise_empty.json"))
        batch = await agmarknet().fetch_prices(SEPT)
        assert batch.records == []
        assert "no market reported Potato in West Bengal" in batch.notes[0]

    @respx.mock
    async def test_unknown_state_or_commodity(self) -> None:
        mock_agmarknet()
        with pytest.raises(ProviderError, match="no state"):
            await agmarknet().fetch_prices(PriceQuery("Atlantis", "Potato", date(2026, 9, 1), date(2026, 9, 2)))
        with pytest.raises(ProviderError, match="no commodity"):
            await agmarknet().fetch_prices(PriceQuery("West Bengal", "Unobtainium", date(2026, 9, 1), date(2026, 9, 2)))

    @respx.mock
    async def test_unreadable_values_are_reported_not_guessed(self) -> None:
        body = load("agmarknet_datewise_wb_potato_2026_09.json")
        row = body["markets"][0]["dates"][0]["data"][0]
        row["modalPrice"], row["maximumPrice"] = "NR", None
        body["markets"][0]["marketName"] = "Nowhere Mandi APMC"
        mock_agmarknet(body)

        record = (await agmarknet().fetch_prices(SEPT)).records[0]

        assert record.modal_price is None and record.max_price is None
        assert record.market_external_id is None
        assert any("not in the Agmarknet catalogue" in i for i in record.parse_issues)
        assert "modal_price not a number: 'NR'" in record.parse_issues
        assert record.raw["modalPrice"] == "NR"

    @respx.mock
    async def test_a_changed_unit_is_carried_through_for_the_validator(self) -> None:
        body = load("agmarknet_datewise_wb_potato_2026_09.json")
        for column in body["columns"]:
            if column["key"] == "modalPrice":
                column["title"] = "Modal Price (Rs./Kg)"
        mock_agmarknet(body)

        record = (await agmarknet().fetch_prices(SEPT)).records[0]
        assert record.price_unit == "Rs./Kg"

    @respx.mock
    async def test_retries_transient_failures(self) -> None:
        respx.get(FILTERS_URL).mock(
            side_effect=[httpx.Response(502), httpx.ConnectTimeout("slow"), httpx.Response(200, json=load("agmarknet_filters.json"))]
        )
        catalog = await agmarknet().fetch_catalog()
        assert catalog.states

    @respx.mock
    async def test_gives_up_after_max_attempts_on_server_errors(self) -> None:
        route = respx.get(FILTERS_URL).mock(return_value=httpx.Response(500, text="<h1>Server Error (500)</h1>"))
        with pytest.raises(ProviderError, match="after 3 attempts"):
            await agmarknet(max_attempts=3).fetch_catalog()
        assert route.call_count == 3

    @respx.mock
    async def test_403_is_not_retried(self) -> None:
        route = respx.get(FILTERS_URL).mock(return_value=httpx.Response(403, text="<h1>403 Forbidden</h1>"))
        with pytest.raises(ProviderError, match="HTTP 403"):
            await agmarknet().fetch_catalog()
        assert route.call_count == 1

    @respx.mock
    async def test_unsuccessful_body(self) -> None:
        mock_agmarknet({"success": False, "message": "No data found."})
        with pytest.raises(ProviderError, match="No data found"):
            await agmarknet().fetch_prices(SEPT)


def ceda(**kw) -> CedaProvider:
    return CedaProvider("test-key", wait=wait_none(), **kw)


def mock_ceda(prices=None, rate_remaining="30"):
    headers = {"ratelimit-remaining": rate_remaining}
    respx.get(f"{CEDA_BASE}/agmarknet/commodities").mock(return_value=httpx.Response(200, json=load("ceda_commodities.json"), headers=headers))
    respx.get(f"{CEDA_BASE}/agmarknet/geographies").mock(return_value=httpx.Response(200, json=load("ceda_geographies.json"), headers=headers))
    respx.post(f"{CEDA_BASE}/agmarknet/markets").mock(return_value=httpx.Response(200, json=load("ceda_markets_kolkata_potato.json"), headers=headers))
    return respx.post(f"{CEDA_BASE}/agmarknet/prices").mock(
        return_value=httpx.Response(200, json=prices or load("ceda_prices_kolkata_potato.json"), headers=headers)
    )


CEDA_QUERY = PriceQuery("West Bengal", "Potato", date(2025, 10, 20), date(2025, 10, 30))


class TestCeda:
    async def test_needs_a_key(self) -> None:
        with pytest.raises(ProviderNotConfiguredError):
            await CedaProvider(None).fetch_catalog()

    @respx.mock
    async def test_market_rows_get_names_from_the_markets_endpoint(self) -> None:
        prices = mock_ceda()

        batch = await ceda().fetch_prices(CEDA_QUERY)

        body = prices.calls.last.request
        assert body.headers["authorization"] == "Bearer test-key"
        sent = __import__("json").loads(body.content)
        assert sent["state_id"] == 19 and sent["commodity_id"] == 24 and len(sent["district_id"]) == 19
        assert batch.records
        assert {r.market for r in batch.records} == {"Bara Bazar (Posta Bazar)"}
        assert {r.district for r in batch.records} == {"Kolkata"}
        assert all(r.variety is None and r.arrival_quantity is None for r in batch.records)
        assert all(r.market_external_id is None for r in batch.records)  # CEDA ids aren't Agmarknet ids

    @respx.mock
    async def test_same_market_same_day_rows_stay_distinct(self) -> None:
        mock_ceda()
        records = (await ceda().fetch_prices(CEDA_QUERY)).records
        ids = [r.source_record_id for r in records]
        assert len(ids) == len(set(ids))

    @respx.mock
    async def test_after_the_archive_end_nothing_is_requested(self) -> None:
        prices = mock_ceda()
        batch = await ceda().fetch_prices(PriceQuery("West Bengal", "Potato", date(2026, 1, 1), date(2026, 9, 1)))
        assert batch.records == [] and prices.call_count == 0
        assert "archive ends" in batch.notes[0]

    @respx.mock
    async def test_429_stops_without_retrying(self) -> None:
        mock_ceda()
        route = respx.post(f"{CEDA_BASE}/agmarknet/prices").mock(return_value=httpx.Response(429, json={"message": "Too many"}))
        provider = ceda()
        with pytest.raises(ProviderError, match="rate limit"):
            await provider.fetch_prices(CEDA_QUERY)
        assert route.call_count == 1
        assert provider.rate_limit_remaining == 0

    @respx.mock
    async def test_tracks_remaining_quota(self) -> None:
        mock_ceda(rate_remaining="7")
        provider = ceda()
        await provider.fetch_catalog()
        assert provider.rate_limit_remaining == 7

    @respx.mock
    async def test_commodity_alias(self) -> None:
        prices = mock_ceda()
        await ceda().fetch_prices(PriceQuery("West Bengal", "Paddy(Common)", date(2025, 10, 1), date(2025, 10, 2)))
        assert __import__("json").loads(prices.calls.last.request.content)["commodity_id"] == 2


class TestDataGov:
    def test_parse_row_keeps_missing_values_missing(self) -> None:
        record = parse_row(
            {"state": "West Bengal", "district": "Kolkata", "market": "Bara Bazar", "commodity": "Potato",
             "variety": "Jyoti", "grade": "FAQ", "arrival_date": "26/09/2026",
             "min_price": "", "max_price": "1,500", "modal_price": "1450"}
        )
        assert record.min_price is None and "min_price missing" in record.parse_issues
        assert record.max_price == Decimal("1500.00") and record.modal_price == Decimal("1450.00")
        assert record.grade == "FAQ" and record.arrival_date == date(2026, 9, 26)

    async def test_needs_a_key(self) -> None:
        with pytest.raises(ProviderNotConfiguredError):
            await DataGovProvider(None).fetch_prices(SEPT)

    @respx.mock
    async def test_pages_and_filters(self) -> None:
        row = {"state": "West Bengal", "district": "Kolkata", "market": "Bara Bazar", "commodity": "Potato",
               "variety": "Jyoti", "grade": "FAQ", "arrival_date": "26/09/2026",
               "min_price": "1400", "max_price": "1500", "modal_price": "1450"}
        route = respx.get(f"{DG_BASE}/{RESOURCE_ID}").mock(
            side_effect=[
                httpx.Response(200, json={"status": "ok", "total": 3, "records": [row, dict(row, market="Sealdah")]}),
                httpx.Response(200, json={"status": "ok", "total": 3, "records": [dict(row, market="Howrah")]}),
            ]
        )
        batch = await DataGovProvider("k", page_size=2, wait=wait_none()).fetch_prices(SEPT)
        assert [r.market for r in batch.records] == ["Bara Bazar", "Sealdah", "Howrah"]
        assert route.calls[0].request.url.params["filters[state.keyword]"] == "West Bengal"

    @respx.mock
    async def test_error_message_never_contains_the_key(self) -> None:
        respx.get(f"{DG_BASE}/{RESOURCE_ID}").mock(return_value=httpx.Response(502))
        with pytest.raises(ProviderError) as info:
            await DataGovProvider("secret-key-123", max_attempts=2, wait=wait_none()).fetch_prices(SEPT)
        assert "secret-key-123" not in str(info.value)

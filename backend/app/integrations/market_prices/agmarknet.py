"""Agmarknet 2.0 (api.agmarknet.gov.in/v1) -- the primary mandi price source.

Verified endpoints (see docs/market-price-api.md for the full write-up):

* GET  daily-price-arrival/filters
      Public. The whole catalogue in one response: states, districts,
      markets (with their state/district ids), commodities, commodity groups,
      varieties and grades, plus the date range prices are available for.
* GET  prices-and-arrivals/date-wise/specific-commodity
          ?year=&month=&stateId=&commodityId=&includeExcel=false
      Public. Every market in a state that reported the commodity during a
      calendar month: per day, per variety, min/max/modal price (Rs/quintal)
      and arrivals (metric tonnes). One request = one state x commodity x
      month, which makes it the unit of both the daily refresh and the
      historical backfill (data from Jan 2021).

Not used, deliberately: daily-price-arrival/report requires a CAPTCHA or a
signed-in token, and location-master/variety/grade require sign-in. We do
not work around either.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date

import httpx
from tenacity.wait import wait_base

from app.integrations.market_prices.base import (
    ARRIVAL_UNIT,
    PRICE_UNIT,
    CatalogCommodity,
    CatalogDistrict,
    CatalogGrade,
    CatalogMarket,
    CatalogState,
    CatalogVariety,
    NormalizedMarketPrice,
    PriceQuery,
    ProviderCatalog,
    ProviderError,
    ProviderPriceBatch,
    ProviderUnsupportedError,
)
from app.integrations.market_prices.http import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_TIMEOUT,
    DEFAULT_WAIT,
    USER_AGENT,
    request_json,
)
from app.integrations.market_prices.text import (
    clean_text,
    market_key,
    name_key,
    parse_date,
    parse_decimal,
)

logger = logging.getLogger(__name__)

SOURCE = "agmarknet"
BASE_URL = "https://api.agmarknet.gov.in/v1/"
FILTERS_PATH = "daily-price-arrival/filters"
DATEWISE_PATH = "prices-and-arrivals/date-wise/specific-commodity"

# The filters endpoint pads each list with "All ..." pseudo-entries whose ids
# start at 100000 -- they aren't real states/markets/commodities.
PSEUDO_ID_FLOOR = 100000

# Column titles the date-wise report uses today. If Agmarknet ever changes a
# unit, the record carries the new unit and the validator rejects it rather
# than us mixing units silently.
EXPECTED_PRICE_UNIT_TITLE = "rs./quintal"
EXPECTED_ARRIVAL_UNIT_TITLE = "metric tonnes"


def months_between(start: date, end: date) -> list[tuple[int, int]]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


class AgmarknetProvider:
    name = SOURCE

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        wait: wait_base = DEFAULT_WAIT,
        min_request_interval: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.max_attempts = max_attempts
        self.wait = wait
        # Politeness: at most ~2 requests/second during a backfill.
        self.min_request_interval = min_request_interval
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._owns_client = client is None
        self._catalog: ProviderCatalog | None = None
        self._last_request_at = 0.0

    @property
    def configured(self) -> bool:
        return True  # public endpoints -- no key needed

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------ http

    async def _get(self, path: str, params: dict | None = None) -> object:
        wait_for = self.min_request_interval - (time.monotonic() - self._last_request_at)
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        try:
            _, body = await request_json(
                self._client,
                "GET",
                path,
                source="Agmarknet",
                max_attempts=self.max_attempts,
                wait=self.wait,
                params=params,
            )
        finally:
            self._last_request_at = time.monotonic()
        return body

    # -------------------------------------------------------------- catalogue

    async def fetch_catalog(self) -> ProviderCatalog:
        body = await self._get(FILTERS_PATH)
        if not isinstance(body, dict) or not body.get("status") or not isinstance(body.get("data"), dict):
            raise ProviderError(f"Agmarknet filters response not understood: {str(body)[:200]}")
        self._catalog = parse_catalog(body["data"])
        return self._catalog

    async def catalog(self) -> ProviderCatalog:
        if self._catalog is None:
            await self.fetch_catalog()
        assert self._catalog is not None
        return self._catalog

    # ----------------------------------------------------------------- prices

    async def fetch_prices(self, query: PriceQuery) -> ProviderPriceBatch:
        catalog = await self.catalog()
        state = resolve_state(catalog, query.state)
        commodity = resolve_commodity(catalog, query.commodity)
        batch = ProviderPriceBatch()

        start = query.from_date
        earliest = catalog.earliest_price_date
        if earliest and query.to_date < earliest:
            # Lets the ingestion fall back to a provider with older data (CEDA).
            raise ProviderUnsupportedError(f"Agmarknet 2.0 has prices only from {earliest.isoformat()}")
        if earliest and start < earliest:
            batch.notes.append(f"Agmarknet 2.0 has prices only from {earliest.isoformat()}; earlier days skipped")
            start = earliest

        for year, month in months_between(start, query.to_date):
            body = await self._get(
                DATEWISE_PATH,
                {
                    "year": year,
                    "month": month,
                    "stateId": state.external_id,
                    "commodityId": commodity.external_id,
                    "includeExcel": "false",
                },
            )
            batch.requests_made += 1
            records = parse_datewise(body, catalog=catalog, state=state, commodity=commodity)
            kept = [r for r in records if _in_query(r, query)]
            if not records:
                batch.notes.append(f"{year}-{month:02d}: no market reported {commodity.name} in {state.name}")
            batch.records.extend(kept)
        return batch


# ---------------------------------------------------------------------------
# Parsing (pure functions -- unit-tested against real captured responses)
# ---------------------------------------------------------------------------


def _real(entry_id) -> bool:
    return isinstance(entry_id, int) and entry_id < PSEUDO_ID_FLOOR


def parse_catalog(data: dict) -> ProviderCatalog:
    groups = {g["id"]: clean_text(g.get("cmdt_grp_name")) for g in data.get("cmdt_group_data", []) if _real(g.get("id"))}
    catalog = ProviderCatalog(source=SOURCE)
    catalog.states = [
        CatalogState(str(s["state_id"]), clean_text(s["state_name"]))
        for s in data.get("state_data", [])
        if _real(s.get("state_id")) and clean_text(s.get("state_name"))
    ]
    catalog.districts = [
        CatalogDistrict(str(d["id"]), str(d["state_id"]), clean_text(d["district_name"]))
        for d in data.get("district_data", [])
        if _real(d.get("id")) and d.get("state_id") is not None and clean_text(d.get("district_name"))
    ]
    catalog.markets = [
        CatalogMarket(
            str(m["id"]),
            clean_text(m["mkt_name"]),
            str(m["state_id"]) if m.get("state_id") is not None else None,
            str(m["district_id"]) if m.get("district_id") is not None else None,
        )
        for m in data.get("market_data", [])
        if _real(m.get("id")) and clean_text(m.get("mkt_name"))
    ]
    catalog.commodities = [
        CatalogCommodity(str(c["cmdt_id"]), clean_text(c["cmdt_name"]), groups.get(c.get("cmdt_group_id")))
        for c in data.get("cmdt_data", [])
        if _real(c.get("cmdt_id")) and clean_text(c.get("cmdt_name"))
    ]
    catalog.varieties = [
        CatalogVariety(
            str(v["id"]),
            clean_text(v["variety_name"]),
            tuple(str(c) for c in (v.get("cmdt_id") or [])),
        )
        for v in data.get("variety_data", [])
        if _real(v.get("id")) and clean_text(v.get("variety_name"))
    ]
    catalog.grades = [
        CatalogGrade(str(g["grade_id"]), clean_text(g["grade_name"]))
        for g in data.get("grade_data", [])
        if _real(g.get("grade_id")) and clean_text(g.get("grade_name"))
    ]
    price_range = next((r.get("price") for r in data.get("range_data", []) if isinstance(r, dict)), None) or {}
    issues: list[str] = []
    catalog.earliest_price_date = parse_date(price_range.get("from_date"), issues) if price_range.get("from_date") else None
    catalog.latest_price_date = parse_date(price_range.get("to_date"), issues) if price_range.get("to_date") else None
    return catalog


def resolve_state(catalog: ProviderCatalog, state: str) -> CatalogState:
    wanted = name_key(state)
    for s in catalog.states:
        if s.external_id == state or name_key(s.name) == wanted:
            return s
    raise ProviderError(f"Agmarknet has no state named {state!r}")


def resolve_commodity(catalog: ProviderCatalog, commodity: str) -> CatalogCommodity:
    wanted = name_key(commodity)
    for c in catalog.commodities:
        if c.external_id == commodity or name_key(c.name) == wanted:
            return c
    raise ProviderError(f"Agmarknet has no commodity named {commodity!r}")


def _unit_from_titles(columns: list, key: str) -> str | None:
    for column in columns or []:
        if isinstance(column, dict) and column.get("key") == key:
            title = str(column.get("title", ""))
            if "(" in title and title.endswith(")"):
                return title[title.rfind("(") + 1 : -1].strip()
    return None


def parse_datewise(
    body: object,
    *,
    catalog: ProviderCatalog,
    state: CatalogState,
    commodity: CatalogCommodity,
) -> list[NormalizedMarketPrice]:
    if not isinstance(body, dict) or body.get("success") is not True:
        message = body.get("message") if isinstance(body, dict) else None
        raise ProviderError(f"Agmarknet date-wise report failed: {message or str(body)[:200]}")

    columns = body.get("columns") or []
    price_title = _unit_from_titles(columns, "modalPrice")
    arrival_title = _unit_from_titles(columns, "arrivals")
    price_unit = PRICE_UNIT if (price_title or "").lower() == EXPECTED_PRICE_UNIT_TITLE else (price_title or "unknown")
    arrival_unit = ARRIVAL_UNIT if (arrival_title or "").lower() == EXPECTED_ARRIVAL_UNIT_TITLE else arrival_title

    markets_by_key: dict[str, list[CatalogMarket]] = {}
    for m in catalog.markets:
        if m.state_external_id == state.external_id:
            markets_by_key.setdefault(market_key(m.name), []).append(m)
    districts = {d.external_id: d for d in catalog.districts}

    records: list[NormalizedMarketPrice] = []
    for market_block in body.get("markets") or []:
        market_name = clean_text(market_block.get("marketName"))
        candidates = markets_by_key.get(market_key(market_name), [])
        # The report names markets without ids; a name shared by several
        # markets in the state can't be attributed, so it stays unresolved.
        market = candidates[0] if len(candidates) == 1 else None
        district = districts.get(market.district_external_id) if market and market.district_external_id else None
        for day in market_block.get("dates") or []:
            # One market/day can list the same variety more than once --
            # separate lots (the rows' arrivals add up to the day's
            # total_arrivals) that the report doesn't label further. Each
            # keeps its own record, numbered in report order.
            lot_numbers: dict[str, int] = {}
            for row in day.get("data") or []:
                issues: list[str] = []
                lot_key = name_key(clean_text(row.get("variety"))) or "-"
                lot_numbers[lot_key] = lot_numbers.get(lot_key, 0) + 1
                if not candidates:
                    issues.append(f"market {market_name!r} not in the Agmarknet catalogue for {state.name}")
                elif market is None:
                    issues.append(
                        f"market {market_name!r} is ambiguous: {len(candidates)} catalogue markets in {state.name} share the name"
                    )
                arrival_date = parse_date(day.get("arrivalDate"), issues)
                variety = clean_text(row.get("variety"))
                arrivals = row.get("arrivals")
                record = NormalizedMarketPrice(
                    source=SOURCE,
                    source_record_id=":".join(
                        [
                            SOURCE,
                            state.external_id,
                            commodity.external_id,
                            market.external_id if market else market_key(market_name),
                            name_key(variety) or "-",
                            arrival_date.isoformat() if arrival_date else str(day.get("arrivalDate")),
                            str(lot_numbers[lot_key]),
                        ]
                    ),
                    state=state.name,
                    district=district.name if district else None,
                    market=market_name,
                    commodity=commodity.name,
                    variety=variety,
                    grade=None,  # this report doesn't break prices down by grade
                    arrival_date=arrival_date,
                    min_price=parse_decimal(row.get("minimumPrice"), "min_price", issues),
                    max_price=parse_decimal(row.get("maximumPrice"), "max_price", issues),
                    modal_price=parse_decimal(row.get("modalPrice"), "modal_price", issues),
                    arrival_quantity=(
                        parse_decimal(arrivals, "arrival_quantity", issues) if arrivals not in (None, "") else None
                    ),
                    price_unit=price_unit,
                    arrival_unit=arrival_unit,
                    state_external_id=state.external_id,
                    district_external_id=district.external_id if district else None,
                    market_external_id=market.external_id if market else None,
                    commodity_external_id=commodity.external_id,
                    parse_issues=issues,
                    raw={"marketName": market_block.get("marketName"), "arrivalDate": day.get("arrivalDate"), **row},
                )
                records.append(record)
    return records


def _in_query(record: NormalizedMarketPrice, query: PriceQuery) -> bool:
    if record.arrival_date is not None and not (query.from_date <= record.arrival_date <= query.to_date):
        return False
    if query.district and name_key(record.district) != name_key(query.district):
        return False
    if query.market and market_key(record.market) != market_key(query.market):
        return False
    return True

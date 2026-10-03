"""CEDA Agri Market API (api.ceda.ashoka.edu.in/v1) -- fallback / archive.

Verified with a real key (see docs/market-price-api.md):

* Bearer-token auth (CEDA_API_KEY); rate limit 40 requests per hour
  (`ratelimit-*` response headers).
* Data is an archive of the *old* Agmarknet portal: it ends 2025-10-30, so it
  can't serve current prices, but it reaches further back than Agmarknet 2.0.
* Ids are CEDA's own (census state/district ids, its own market ids) -- not
  Agmarknet 2.0's. We therefore hand names downstream, never CEDA ids as if
  they were Agmarknet ids.
* POST /agmarknet/prices with every district id of a state returns one row
  per market per day (min/max/modal, no variety, no arrivals). Without
  district ids it returns a state *average*, which we never store as if it
  were a market's price.
* Market names come from POST /agmarknet/markets, one call per district --
  cached per provider instance to spare the rate limit.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta

import httpx
from tenacity.wait import wait_base

from app.integrations.market_prices.base import (
    CatalogCommodity,
    CatalogDistrict,
    CatalogState,
    NormalizedMarketPrice,
    PriceQuery,
    ProviderCatalog,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderPriceBatch,
)
from app.integrations.market_prices.http import (
    DEFAULT_TIMEOUT,
    DEFAULT_WAIT,
    USER_AGENT,
    request_json,
)
from app.integrations.market_prices.text import clean_text, commodity_keys, name_key, parse_date, parse_decimal

logger = logging.getLogger(__name__)

SOURCE = "ceda"
BASE_URL = "https://api.ceda.ashoka.edu.in/v1"
# Last date CEDA's archive holds (verified 2026-09-27).
ARCHIVE_END = date(2025, 10, 30)
# Keep each price request to a year so responses stay a sensible size.
MAX_SPAN = timedelta(days=366)


def _retryable(exc: BaseException) -> bool:
    """Like the shared rule, but a 429 here means "come back within the
    hour" -- retrying after seconds only burns more of the quota."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class CedaProvider:
    name = SOURCE

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = BASE_URL,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        max_attempts: int = 3,
        wait: wait_base = DEFAULT_WAIT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.max_attempts = max_attempts
        self.wait = wait
        self._client = client or httpx.AsyncClient(
            base_url=base_url, timeout=timeout, headers={"User-Agent": USER_AGENT}
        )
        self._owns_client = client is None
        self._catalog: ProviderCatalog | None = None
        self._market_names: dict[tuple[str, str], dict[str, str]] = {}
        self.rate_limit_remaining: int | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _call(self, method: str, path: str, json: dict | None = None) -> dict:
        if not self.configured:
            raise ProviderNotConfiguredError("CEDA_API_KEY is not set")
        if self.rate_limit_remaining == 0:
            raise ProviderError("CEDA hourly rate limit exhausted -- try again later")
        try:
            response, body = await request_json(
                self._client,
                method,
                path,
                source="CEDA",
                max_attempts=self.max_attempts,
                wait=self.wait,
                retryable=_retryable,
                json=json,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except ProviderError as exc:
            if "HTTP 429" in str(exc):
                self.rate_limit_remaining = 0
                raise ProviderError("CEDA hourly rate limit exhausted (HTTP 429) -- try again later") from exc
            raise
        remaining = response.headers.get("ratelimit-remaining")
        if remaining is not None and remaining.isdigit():
            self.rate_limit_remaining = int(remaining)
        output = body.get("output") if isinstance(body, dict) else None
        if not isinstance(output, dict) or output.get("type") != "success":
            raise ProviderError(f"CEDA {path} failed: {str(body)[:200]}")
        data = output.get("data")
        return {"message": output.get("message"), "data": data if isinstance(data, list) else []}

    # -------------------------------------------------------------- catalogue

    async def fetch_catalog(self) -> ProviderCatalog:
        commodities = await self._call("GET", "/agmarknet/commodities")
        geographies = await self._call("GET", "/agmarknet/geographies")
        self._catalog = parse_catalog(commodities["data"], geographies["data"])
        return self._catalog

    async def catalog(self) -> ProviderCatalog:
        if self._catalog is None:
            await self.fetch_catalog()
        assert self._catalog is not None
        return self._catalog

    async def market_names(self, commodity_id: str, state_id: str, district_id: str) -> dict[str, str]:
        key = (commodity_id, district_id)
        if key not in self._market_names:
            result = await self._call(
                "POST",
                "/agmarknet/markets",
                {
                    "commodity_id": int(commodity_id),
                    "state_id": int(state_id),
                    "district_id": int(district_id),
                    "indicator": "price",
                },
            )
            self._market_names[key] = {
                str(m["market_id"]): clean_text(m.get("market_name"))
                for m in result["data"]
                if m.get("market_id") is not None
            }
        return self._market_names[key]

    # ----------------------------------------------------------------- prices

    async def fetch_prices(self, query: PriceQuery) -> ProviderPriceBatch:
        batch = ProviderPriceBatch()
        if query.from_date > ARCHIVE_END:
            batch.notes.append(f"CEDA's archive ends {ARCHIVE_END.isoformat()} -- nothing to fetch")
            return batch

        catalog = await self.catalog()
        state = resolve_state(catalog, query.state)
        commodity = resolve_commodity(catalog, query.commodity)
        districts = [d for d in catalog.districts if d.state_external_id == state.external_id]
        if query.district:
            districts = [d for d in districts if name_key(d.name) == name_key(query.district)]
            if not districts:
                raise ProviderError(f"CEDA has no district {query.district!r} in {state.name}")
        district_names = {d.external_id: d.name for d in districts}

        start, end = query.from_date, min(query.to_date, ARCHIVE_END)
        rows: list[dict] = []
        while start <= end:
            chunk_end = min(end, start + MAX_SPAN - timedelta(days=1))
            result = await self._call(
                "POST",
                "/agmarknet/prices",
                {
                    "commodity_id": int(commodity.external_id),
                    "state_id": int(state.external_id),
                    "district_id": [int(d.external_id) for d in districts],
                    "from_date": start.isoformat(),
                    "to_date": chunk_end.isoformat(),
                },
            )
            batch.requests_made += 1
            rows.extend(result["data"])
            start = chunk_end + timedelta(days=1)

        # Market names, one lookup per district that actually has rows.
        names: dict[str, str] = {}
        for district_id in sorted({str(r.get("census_district_id")) for r in rows if r.get("census_district_id")}):
            before = len(self._market_names)
            names.update(await self.market_names(commodity.external_id, state.external_id, district_id))
            batch.requests_made += len(self._market_names) - before

        batch.records = parse_prices(
            rows, state=state, commodity=commodity, district_names=district_names, market_names=names
        )
        if query.market:
            wanted = name_key(query.market)
            batch.records = [r for r in batch.records if name_key(r.market) == wanted]
        return batch


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_catalog(commodities: list[dict], geographies: list[dict]) -> ProviderCatalog:
    catalog = ProviderCatalog(source=SOURCE, latest_price_date=ARCHIVE_END)
    catalog.commodities = [
        CatalogCommodity(str(c["commodity_id"]), clean_text(c["commodity_name"]))
        for c in commodities
        if c.get("commodity_id") is not None and clean_text(c.get("commodity_name"))
    ]
    states: dict[str, str] = {}
    for g in geographies:
        states[str(g["census_state_id"])] = clean_text(g["census_state_name"])
        if g.get("census_district_id") is not None:
            catalog.districts.append(
                CatalogDistrict(str(g["census_district_id"]), str(g["census_state_id"]), clean_text(g["census_district_name"]))
            )
    catalog.states = [CatalogState(k, v) for k, v in states.items()]
    return catalog


def resolve_state(catalog: ProviderCatalog, state: str) -> CatalogState:
    wanted = name_key(state)
    for s in catalog.states:
        if name_key(s.name) == wanted:
            return s
    raise ProviderError(f"CEDA has no state named {state!r}")


def resolve_commodity(catalog: ProviderCatalog, commodity: str) -> CatalogCommodity:
    wanted = commodity_keys(commodity)
    for c in catalog.commodities:
        if name_key(c.name) in wanted:
            return c
    raise ProviderError(f"CEDA has no commodity named {commodity!r}")


def parse_prices(
    rows: list[dict],
    *,
    state: CatalogState,
    commodity: CatalogCommodity,
    district_names: dict[str, str],
    market_names: dict[str, str],
) -> list[NormalizedMarketPrice]:
    records: list[NormalizedMarketPrice] = []
    # CEDA can return several rows for one market/day (different, unlabelled
    # varieties). They're kept apart by their order within the day.
    ordinal: dict[tuple, int] = defaultdict(int)
    for row in rows:
        issues: list[str] = []
        if row.get("market_id") is None:
            # A district/state aggregate, not a market report.
            continue
        market_id = str(row["market_id"])
        district_id = str(row.get("census_district_id")) if row.get("census_district_id") is not None else None
        arrival_date = parse_date(row.get("date"), issues)
        market_name = market_names.get(market_id)
        if market_name is None:
            issues.append(f"CEDA market id {market_id} has no name")
        key = (market_id, arrival_date)
        ordinal[key] += 1
        records.append(
            NormalizedMarketPrice(
                source=SOURCE,
                source_record_id=f"{SOURCE}:{commodity.external_id}:{market_id}:{arrival_date or row.get('date')}:{ordinal[key]}",
                state=state.name,
                district=district_names.get(district_id) if district_id else None,
                market=market_name,
                commodity=commodity.name,
                variety=None,
                grade=None,
                arrival_date=arrival_date,
                min_price=parse_decimal(row.get("min_price"), "min_price", issues),
                max_price=parse_decimal(row.get("max_price"), "max_price", issues),
                modal_price=parse_decimal(row.get("modal_price"), "modal_price", issues),
                arrival_quantity=None,
                arrival_unit=None,
                parse_issues=issues,
                raw=row,
            )
        )
    return records

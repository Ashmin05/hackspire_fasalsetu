"""data.gov.in's "Current Daily Price of Various Commodities from Various
Markets (Mandi)" resource -- optional provider.

It only ever holds the latest day, and its gateway was returning 502/504
throughout development, so it's never required: the Agmarknet 2.0 provider
covers the same data (and history). Needs DATA_GOV_IN_API_KEY.
"""

from __future__ import annotations

import httpx
from tenacity.wait import wait_base

from app.integrations.market_prices.base import (
    NormalizedMarketPrice,
    PriceQuery,
    ProviderCatalog,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderPriceBatch,
)
from app.integrations.market_prices.http import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_TIMEOUT,
    DEFAULT_WAIT,
    USER_AGENT,
    request_json,
)
from app.integrations.market_prices.text import clean_text, market_key, name_key, parse_date, parse_decimal

SOURCE = "data_gov_in"
BASE_URL = "https://api.data.gov.in/resource"
RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
DEFAULT_PAGE_SIZE = 500
MAX_RECORDS = 50_000


class DataGovProvider:
    name = SOURCE

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = BASE_URL,
        resource_id: str = RESOURCE_ID,
        page_size: int = DEFAULT_PAGE_SIZE,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        wait: wait_base = DEFAULT_WAIT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.url = f"{base_url}/{resource_id}"
        self.page_size = page_size
        self.max_attempts = max_attempts
        self.wait = wait
        self._client = client or httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_catalog(self) -> ProviderCatalog:
        # The resource has no catalogue endpoint; entities are learnt from rows.
        return ProviderCatalog(source=SOURCE)

    async def fetch_prices(self, query: PriceQuery) -> ProviderPriceBatch:
        if not self.configured:
            raise ProviderNotConfiguredError("DATA_GOV_IN_API_KEY is not set")
        batch = ProviderPriceBatch()
        offset = 0
        while offset < MAX_RECORDS:
            params = {
                "api-key": self.api_key,
                "format": "json",
                "offset": offset,
                "limit": self.page_size,
                "filters[state.keyword]": query.state,
                "filters[commodity]": query.commodity,
            }
            _, body = await request_json(
                self._client,
                "GET",
                self.url,
                source="data.gov.in",
                max_attempts=self.max_attempts,
                wait=self.wait,
                params=params,
            )
            batch.requests_made += 1
            if not isinstance(body, dict) or body.get("status") == "error":
                message = body.get("message") if isinstance(body, dict) else str(body)[:200]
                raise ProviderError(f"data.gov.in returned an error: {message}")
            rows = body.get("records") or []
            batch.records.extend(r for r in (parse_row(row) for row in rows) if _in_query(r, query))
            offset += self.page_size
            try:
                total = int(body.get("total", len(rows)))
            except (TypeError, ValueError):
                total = len(rows)
            if not rows or offset >= total:
                break
        return batch


def parse_row(row: dict) -> NormalizedMarketPrice:
    issues: list[str] = []
    arrival_date = parse_date(row.get("arrival_date"), issues)
    market = clean_text(row.get("market"))
    commodity = clean_text(row.get("commodity"))
    variety = clean_text(row.get("variety"))
    grade = clean_text(row.get("grade"))
    return NormalizedMarketPrice(
        source=SOURCE,
        source_record_id=":".join(
            [
                SOURCE,
                name_key(row.get("state")) or "-",
                market_key(market) or "-",
                name_key(commodity) or "-",
                name_key(variety) or "-",
                name_key(grade) or "-",
                arrival_date.isoformat() if arrival_date else str(row.get("arrival_date")),
            ]
        ),
        state=clean_text(row.get("state")),
        district=clean_text(row.get("district")),
        market=market,
        commodity=commodity,
        variety=variety,
        grade=grade,
        arrival_date=arrival_date,
        min_price=parse_decimal(row.get("min_price"), "min_price", issues),
        max_price=parse_decimal(row.get("max_price"), "max_price", issues),
        modal_price=parse_decimal(row.get("modal_price"), "modal_price", issues),
        arrival_quantity=None,
        arrival_unit=None,
        parse_issues=issues,
        raw=row,
    )


def _in_query(record: NormalizedMarketPrice, query: PriceQuery) -> bool:
    if record.arrival_date is not None and not (query.from_date <= record.arrival_date <= query.to_date):
        return False
    if query.district and name_key(record.district) != name_key(query.district):
        return False
    return True

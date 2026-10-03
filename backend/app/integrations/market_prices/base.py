"""Provider-neutral types for mandi price data.

Every provider (Agmarknet 2.0, CEDA, data.gov.in) converts its own response
format into these structures, so nothing downstream -- validation,
ingestion, analytics, the API -- knows which source a row came from beyond
the `source` label it carries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

# Units every provider is converted *to*. A provider whose source reports
# another unit must say so (price_unit/arrival_unit on the record) instead of
# silently rescaling -- the validator then rejects/flags it.
PRICE_UNIT = "Rs/quintal"
ARRIVAL_UNIT = "tonnes"


class ProviderError(Exception):
    """The source failed or rejected a request, after any retries."""


class ProviderNotConfiguredError(ProviderError):
    """A required credential (API key) isn't set."""


class ProviderUnsupportedError(ProviderError):
    """The provider can't answer this kind of query (e.g. a date range from a
    current-day-only feed)."""


# --------------------------------------------------------------------------
# Catalogue (states / districts / markets / commodities / varieties / grades)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogState:
    external_id: str
    name: str


@dataclass(frozen=True)
class CatalogDistrict:
    external_id: str
    state_external_id: str
    name: str


@dataclass(frozen=True)
class CatalogMarket:
    external_id: str
    name: str
    state_external_id: str | None
    district_external_id: str | None


@dataclass(frozen=True)
class CatalogCommodity:
    external_id: str
    name: str
    commodity_group: str | None = None


@dataclass(frozen=True)
class CatalogVariety:
    external_id: str
    name: str
    commodity_external_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CatalogGrade:
    external_id: str
    name: str


@dataclass
class ProviderCatalog:
    source: str
    states: list[CatalogState] = field(default_factory=list)
    districts: list[CatalogDistrict] = field(default_factory=list)
    markets: list[CatalogMarket] = field(default_factory=list)
    commodities: list[CatalogCommodity] = field(default_factory=list)
    varieties: list[CatalogVariety] = field(default_factory=list)
    grades: list[CatalogGrade] = field(default_factory=list)
    # Earliest/latest date the source says it can serve, when it says so.
    earliest_price_date: date | None = None
    latest_price_date: date | None = None


# --------------------------------------------------------------------------
# Prices
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PriceQuery:
    """One fetch: a state + commodity over a date range. `state` and
    `commodity` are names (as the user/config knows them); each provider
    resolves them to its own ids. district/market narrow the result when the
    provider can filter on them."""

    state: str
    commodity: str
    from_date: date
    to_date: date
    district: str | None = None
    market: str | None = None


@dataclass
class NormalizedMarketPrice:
    """One market's report for one commodity/variety/grade on one day.

    Names are whitespace-cleaned but otherwise exactly as the source spelt
    them. Prices are Decimal in PRICE_UNIT, arrivals Decimal in ARRIVAL_UNIT.
    A value the parser couldn't read is None and explained in parse_issues
    -- never guessed. `raw` keeps the source row for the rejection log.
    """

    source: str
    source_record_id: str
    state: str | None
    district: str | None
    market: str | None
    commodity: str | None
    variety: str | None
    grade: str | None
    arrival_date: date | None
    min_price: Decimal | None
    max_price: Decimal | None
    modal_price: Decimal | None
    arrival_quantity: Decimal | None = None
    price_unit: str = PRICE_UNIT
    arrival_unit: str | None = ARRIVAL_UNIT
    # Source-side ids, when the source publishes them (Agmarknet 2.0 does
    # for everything but variety; CEDA uses its own census ids).
    state_external_id: str | None = None
    district_external_id: str | None = None
    market_external_id: str | None = None
    commodity_external_id: str | None = None
    parse_issues: list[str] = field(default_factory=list)
    raw: dict | None = None


@dataclass
class ProviderPriceBatch:
    records: list[NormalizedMarketPrice] = field(default_factory=list)
    requests_made: int = 0
    # Human-readable notes about the fetch (e.g. "Nov 2026: no markets
    # reported"), surfaced in ingestion logs.
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class PriceDataProvider(Protocol):
    name: str

    @property
    def configured(self) -> bool: ...

    async def fetch_catalog(self) -> ProviderCatalog: ...

    async def fetch_prices(self, query: PriceQuery) -> ProviderPriceBatch: ...

    async def aclose(self) -> None: ...

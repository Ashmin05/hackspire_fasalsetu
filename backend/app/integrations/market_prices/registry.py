"""Builds the configured providers, in fallback order."""

from app.core.config import settings
from app.integrations.market_prices.agmarknet import AgmarknetProvider
from app.integrations.market_prices.base import PriceDataProvider
from app.integrations.market_prices.ceda import CedaProvider
from app.integrations.market_prices.data_gov import DataGovProvider

PROVIDER_NAMES = ("agmarknet", "ceda", "data_gov_in")


def build_provider(name: str) -> PriceDataProvider:
    if name == "agmarknet":
        return AgmarknetProvider()
    if name == "ceda":
        return CedaProvider(settings.CEDA_API_KEY)
    if name == "data_gov_in":
        return DataGovProvider(settings.DATA_GOV_IN_API_KEY)
    raise ValueError(f"Unknown market price provider {name!r} (expected one of {', '.join(PROVIDER_NAMES)})")


def configured_providers(names: list[str] | None = None) -> list[PriceDataProvider]:
    """Providers in fallback order, skipping any without credentials."""
    providers = [build_provider(n) for n in (names or settings.market_price_provider_order)]
    return [p for p in providers if p.configured]

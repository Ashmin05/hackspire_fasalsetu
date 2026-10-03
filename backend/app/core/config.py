"""Application settings, loaded from the project's .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repo root (4 levels up)
ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENVIRONMENT: str = "development"
    PORT: int = 8000

    # Async SQLAlchemy connection string, e.g.
    # postgresql+asyncpg://user:password@localhost:5432/fasalsetu
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/fasalsetu"

    # Origin of the Next.js frontend — used for the CORS allow-list.
    FRONTEND_ORIGIN: str = "http://localhost:3000"

    # Secret used to sign JWTs. Override with a random value in every real environment.
    JWT_SECRET_KEY: str = "dev-only-insecure-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # OAuth client ID from Google Cloud Console — used to verify "Sign in with
    # Google" ID tokens. Must match the frontend's NEXT_PUBLIC_GOOGLE_CLIENT_ID.
    GOOGLE_CLIENT_ID: str | None = None

    # External API keys used by app/integrations/
    WEATHER_API_KEY: str | None = None
    SATELLITE_API_KEY: str | None = None
    AI_API_KEY: str | None = None

    # NewsAPI.org key for the farmer news feed (app/integrations/news_client.py).
    # Free tier: https://newsapi.org/register. Blank means "not configured" --
    # NewsService then returns a clean empty feed instead of erroring.
    NEWS_API_KEY: str | None = None
    NEWS_API_BASE_URL: str = "https://newsapi.org/v2"
    # How long a location's fetched articles are reused before refetching
    # (in-memory, per process -- see app/integrations/news_client.py).
    NEWS_CACHE_MINUTES: int = 30

    # Gemini (Google GenAI) API keys for the AI Advisor / KrishiBot
    # (app/integrations/gemini_client.py, app/services/advisor_service.py).
    # Comma-separated so a quota/auth error on one key falls through to the
    # next rather than failing the request. Blank means "no Gemini key
    # configured" -- AdvisorService then answers with its scripted (non-LLM)
    # fallback instead of erroring.
    GEMINI_API_KEYS: str = ""
    GEMINI_MODEL: str = "gemini-3.6-flash"
    # Tried in order (with every key) when GEMINI_MODEL is overloaded,
    # retired, or out of quota on all keys. Free-tier quota is counted per
    # model, so each fallback is fresh quota on the same keys.
    GEMINI_FALLBACK_MODELS: str = "gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    # Per-user cap on POST /farms/{id}/ask. In-memory (see
    # AdvisorService's _RateLimiter) -- single process, resets on restart.
    ADVISOR_RATE_LIMIT_PER_HOUR: int = 20

    # Google Earth Engine (app/integrations/earth_engine_client.py).
    # GEE_PROJECT_ID is always required. GEE_SERVICE_ACCOUNT_EMAIL/
    # GEE_KEY_PATH are optional — set both for production (a service-account
    # key); leave both blank for local dev, where the client instead uses
    # Application Default Credentials from `gcloud auth application-default
    # login` (works even when an org policy blocks service-account key
    # creation). If GEE_PROJECT_ID itself is missing, the client just stays
    # "not configured" and the rest of the API still starts normally.
    GEE_PROJECT_ID: str | None = None
    GEE_SERVICE_ACCOUNT_EMAIL: str | None = None
    GEE_KEY_PATH: str | None = None

    # ---- Mandi prices (app/integrations/market_prices/) ----
    # Agmarknet 2.0 is public and needs no key. The other two are optional:
    # CEDA Agri Market API (https://api.ceda.ashoka.edu.in/documentation/) --
    # archive of the old Agmarknet portal, used as a historical fallback.
    CEDA_API_KEY: str | None = None
    # data.gov.in Open Government Data API key (free: sign up at
    # https://data.gov.in, then "My Account" -> API key). Current day only.
    DATA_GOV_IN_API_KEY: str | None = None
    # Providers to try, in order, comma-separated. A provider without its key
    # is skipped.
    MARKET_PRICE_PROVIDERS: str = "agmarknet,ceda,data_gov_in"
    # What the nightly job keeps fresh (comma-separated Agmarknet names), plus
    # every farm's state x crop when MARKET_PRICE_INCLUDE_FARM_CROPS is true.
    MARKET_PRICE_STATES: str = "West Bengal"
    MARKET_PRICE_COMMODITIES: str = "Potato,Rice,Paddy(Common),Wheat,Tomato,Onion,Sugarcane"
    MARKET_PRICE_INCLUDE_FARM_CROPS: bool = True
    # Days re-fetched each night (late and revised reports get picked up).
    MARKET_PRICE_CURRENT_DAYS: int = 10
    # Where trained price-forecast models are written (gitignored). Relative
    # paths are resolved against backend/.
    PRICE_MODEL_DIR: str = "models_store"
    # Sell-or-hold suggestion (app/services/market_prices/price_service.py).
    # Assumed cost of holding a crop, as % of its value per 30 days: storage
    # charges plus weight/quality loss. Rough planning figures, not measured
    # -- tune them per region. "Commodity:pct" pairs keyed by Agmarknet
    # commodity name; anything unlisted uses the default.
    MARKET_HOLDING_COST_PCT: str = (
        "Wheat:1,Rice:1,Paddy(Common):1,Maize:1.5,Soyabean:1.5,Cotton:1,Dry Chillies:2,"
        "Potato:3,Onion:4,Green Chilli:15,Tomato:20,Sugarcane:10"
    )
    MARKET_HOLDING_COST_DEFAULT_PCT: float = 3.0
    # Crops that spoil within days without cold storage; the UI warns that
    # holding may not be possible at all.
    MARKET_PERISHABLE_COMMODITIES: str = "Tomato,Green Chilli,Sugarcane"

    @property
    def price_model_dir(self) -> Path:
        path = Path(self.PRICE_MODEL_DIR)
        return path if path.is_absolute() else ROOT_DIR / "backend" / path

    @property
    def market_price_provider_order(self) -> list[str]:
        return _csv(self.MARKET_PRICE_PROVIDERS)

    @property
    def market_price_states(self) -> list[str]:
        return _csv(self.MARKET_PRICE_STATES)

    @property
    def market_price_commodities(self) -> list[str]:
        return _csv(self.MARKET_PRICE_COMMODITIES)

    @property
    def market_holding_costs(self) -> dict[str, float]:
        costs = {}
        for pair in _csv(self.MARKET_HOLDING_COST_PCT):
            name, _, pct = pair.rpartition(":")
            if name.strip():
                costs[name.strip()] = float(pct)
        return costs

    @property
    def market_perishable_commodities(self) -> list[str]:
        return _csv(self.MARKET_PERISHABLE_COMMODITIES)

    @property
    def gemini_api_keys(self) -> list[str]:
        return _csv(self.GEMINI_API_KEYS)

    @property
    def gemini_models(self) -> list[str]:
        models = [self.GEMINI_MODEL.strip(), *_csv(self.GEMINI_FALLBACK_MODELS)]
        return list(dict.fromkeys(m for m in models if m))


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

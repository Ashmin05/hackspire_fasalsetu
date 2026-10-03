"""NewsAPI.org client -- location-based farming/agriculture news for the
dashboard's news page.

https://newsapi.org/v2/everything, needs a free API key (NEWS_API_KEY).
Results are cached per query in-process for NEWS_CACHE_MINUTES, the same
module-level-singleton pattern AdvisorService uses for its rate limiter --
there's no Redis in this stack yet, and a per-process cache is enough to
keep a scrolling news page from burning through the free tier's daily
request cap.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx
from tenacity import AsyncRetrying, RetryError, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

USER_AGENT = "FasalSetu/0.1 (agricultural decision-support app)"
DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_WAIT = wait_exponential(multiplier=2, min=2, max=15)
PAGE_SIZE = 20
# NewsAPI fetches more than PAGE_SIZE so location-relevant articles (see
# _rank_by_location) have a real pool to surface from before truncating.
FETCH_SIZE = 60

# Searched with qInTitle (title only) so every result is actually *about*
# one of these, not just an article that happens to mention "farmer" in
# passing (e.g. farmer-vote political coverage). NewsAPI's /everything
# quietly treats q + qInTitle as OR, not AND (contrary to its docs), so
# location can't be folded into the same request as a hard filter -- see
# _rank_by_location for how location relevance is applied instead.
TOPIC_TERMS = (
    "agriculture OR farming OR farmer OR farmers OR crop OR crops OR irrigation OR "
    "monsoon OR rainfall OR drought OR harvest OR sowing OR mandi OR \"crop prices\" OR "
    "\"weather forecast\" OR \"crop damage\" OR \"farm produce\""
)


class NewsError(Exception):
    """Base class for news-client errors."""


class NewsNotConfiguredError(NewsError):
    """Raised when NEWS_API_KEY isn't set -- callers turn this into a clean
    empty feed rather than a 503, since "no key configured" isn't really a
    failure the user needs to see."""


class NewsRequestError(NewsError):
    """Raised when the request fails after retries or NewsAPI rejects it."""


@dataclass
class NewsArticle:
    title: str
    description: str | None
    url: str
    source: str
    image_url: str | None
    published_at: str  # ISO datetime, as returned by NewsAPI


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


class NewsClient:
    """Async client for NewsAPI.org's `/everything` search endpoint."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        cache_minutes: int,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.cache_seconds = cache_minutes * 60
        self.max_attempts = max_attempts
        self._client = client or httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self._owns_client = client is None
        self._cache: dict[str, tuple[float, list[NewsArticle]]] = {}

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def get_farming_news(self, *, location: str) -> list[NewsArticle]:
        """Farming/weather/agriculture news -- every result is on-topic (see
        TOPIC_TERMS), ranked so articles mentioning `location` (typically
        "<district>, <state>") come first, newest-first within each group.
        Raises NewsNotConfiguredError if no API key is set, NewsRequestError
        on a live failure -- an expired cache entry is still served if the
        live refetch fails. Cached per location since the ranking (not just
        the fetch) depends on it."""
        if not self.api_key:
            raise NewsNotConfiguredError("NEWS_API_KEY is not configured")

        query = location.strip()
        cached = self._cache.get(query)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self.cache_seconds:
            return cached[1]

        try:
            articles = await self._fetch()
        except NewsRequestError:
            if cached is not None:
                logger.warning("News refetch failed -- serving stale cache for %r", query)
                return cached[1]
            raise

        ranked = _rank_by_location(articles, query)[:PAGE_SIZE]
        self._cache[query] = (now, ranked)
        return ranked

    async def _fetch(self) -> list[NewsArticle]:
        params = {
            "qInTitle": TOPIC_TERMS,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": FETCH_SIZE,
            "apiKey": self.api_key,
        }

        async def attempt() -> httpx.Response:
            response = await self._client.get(f"{self.base_url}/everything", params=params)
            response.raise_for_status()
            return response

        try:
            response = None
            async for try_ in AsyncRetrying(
                retry=retry_if_exception(_is_retryable),
                stop=stop_after_attempt(self.max_attempts),
                wait=DEFAULT_WAIT,
                reraise=False,
            ):
                with try_:
                    response = await attempt()
        except RetryError as exc:
            last = exc.last_attempt.exception()
            raise NewsRequestError(f"News request failed after {self.max_attempts} attempts: {last}") from last
        except httpx.HTTPStatusError as exc:
            raise NewsRequestError(f"NewsAPI rejected the request (HTTP {exc.response.status_code})") from exc

        assert response is not None
        try:
            body = response.json()
        except ValueError as exc:
            raise NewsRequestError(f"NewsAPI returned a non-JSON response (HTTP {response.status_code})") from exc

        return _parse_articles(body)


def _parse_articles(body: dict) -> list[NewsArticle]:
    raw_articles = body.get("articles")
    if not isinstance(raw_articles, list):
        raise NewsRequestError("NewsAPI response is missing the 'articles' list")

    articles: list[NewsArticle] = []
    for item in raw_articles:
        url = item.get("url")
        title = item.get("title")
        if not url or not title:
            continue
        source = item.get("source") or {}
        articles.append(
            NewsArticle(
                title=title,
                description=item.get("description"),
                url=url,
                source=source.get("name") or "Unknown source",
                image_url=item.get("urlToImage"),
                published_at=item.get("publishedAt") or "",
            )
        )
    return articles


def _rank_by_location(articles: list[NewsArticle], location: str) -> list[NewsArticle]:
    """Stable-sorts `articles` (already newest-first, already on-topic) so
    ones mentioning `location`'s district/state come first. Never drops an
    article for lacking a location match -- national agriculture/weather
    coverage is still relevant even when it doesn't name the farm's
    district, and dropping it would often leave the feed empty."""
    terms = [p.strip().lower() for p in location.split(",") if p.strip()]
    if not terms:
        return articles

    def mentions_location(article: NewsArticle) -> bool:
        haystack = f"{article.title} {article.description or ''}".lower()
        return any(term in haystack for term in terms)

    return sorted(articles, key=lambda a: not mentions_location(a))


def _build_client() -> NewsClient:
    from app.core.config import settings

    return NewsClient(
        api_key=settings.NEWS_API_KEY,
        base_url=settings.NEWS_API_BASE_URL,
        cache_minutes=settings.NEWS_CACHE_MINUTES,
    )


# Module-level singleton, same pattern as open_meteo_client.
news_client = _build_client()

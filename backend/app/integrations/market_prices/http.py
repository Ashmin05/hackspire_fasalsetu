"""HTTP plumbing shared by the providers: timeouts, retries with exponential
backoff on transient failures, and a consistent error type."""

import logging

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import wait_base

from app.integrations.market_prices.base import ProviderError

logger = logging.getLogger(__name__)

# Identify ourselves honestly. Agmarknet's nginx rejects generic library
# user agents (python-httpx/requests) with 403 but accepts a descriptive one.
USER_AGENT = "FasalSetu/0.1 (agricultural decision-support app)"
DEFAULT_TIMEOUT = httpx.Timeout(90.0, connect=15.0)
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_WAIT = wait_exponential(multiplier=2, min=2, max=60)


def is_retryable(exc: BaseException) -> bool:
    """Network errors, timeouts, 429 and 5xx are worth retrying; any other
    4xx (bad key, bad params) will fail the same way every time."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    source: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    wait: wait_base = DEFAULT_WAIT,
    retryable=is_retryable,
    **kwargs,
) -> tuple[httpx.Response, object]:
    """Send one request with retries; return (response, parsed JSON).

    Raises ProviderError when attempts run out, on a non-retryable HTTP
    error, or when the body isn't JSON. Error messages never include the
    request URL's query string or headers (API keys live there)."""

    async def attempt() -> httpx.Response:
        response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    try:
        response = None
        async for try_ in AsyncRetrying(
            retry=retry_if_exception(retryable),
            stop=stop_after_attempt(max_attempts),
            wait=wait,
            reraise=False,
        ):
            with try_:
                response = await attempt()
    except RetryError as exc:
        last = exc.last_attempt.exception()
        raise ProviderError(f"{source} request failed after {max_attempts} attempts: {_describe(last)}") from last
    except httpx.HTTPStatusError as exc:
        raise ProviderError(f"{source} rejected the request ({_describe(exc)})") from exc

    assert response is not None
    try:
        return response, response.json()
    except ValueError as exc:
        raise ProviderError(f"{source} returned a non-JSON response (HTTP {response.status_code})") from exc


def _describe(exc: BaseException | None) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} for {exc.request.method} {exc.request.url.path}"
    if exc is None:
        return "unknown error"
    return f"{type(exc).__name__}: {exc}"

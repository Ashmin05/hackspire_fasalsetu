"""Thin wrapper around Google's Gen AI SDK (`google-genai`) for the AI
Advisor / KrishiBot. Tries every configured GEMINI_API_KEYS entry in turn --
several free-tier keys quota-exhaust independently, so a 429/auth/other
failure on one key falls through to the next rather than failing the whole
request; a transient 5xx gets one short in-place retry first since it's the
model that's overloaded, not the key. If GEMINI_MODEL itself is overloaded
or retired, the same keys are tried again on each GEMINI_FALLBACK_MODELS
entry (free-tier quota is per model, so that's fresh quota too). See
app/services/advisor_service.py
for the caller, which falls back to a scripted (non-LLM) reply whenever
every key ultimately fails -- not just when no key is configured at all.
"""

import logging
import threading
import time
from typing import TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Retried in place on the same key before moving on to the next one: these
# are momentary overload on Google's side (the model itself, not this key),
# so a short backoff on the SAME key can clear it. A real farming answer
# takes longer to generate than a one-word greeting, so it has more time to
# get caught by one of these -- that's why short replies ("hi") were
# succeeding while longer ones consistently failed.
#
# 429 is deliberately NOT retried here: it means THIS key/project is
# rate-limited or has exhausted its free-tier quota (seen in practice:
# "GenerateRequestsPerDayPerProjectPerModel-FreeTier", limit 20/day), which a
# couple of seconds of backoff can't fix. Moving straight to the next key
# (a separate Google project/quota pool) is the only thing that helps.
_RETRYABLE_CODES = {500, 502, 503, 504}
_MAX_ATTEMPTS_PER_KEY = 2
_RETRY_BACKOFF_SECONDS = 1.5

# After a 429, a key is pushed to the back of the order for a while so later
# requests go straight to a key that still has quota instead of paying a
# failed round-trip on the exhausted one first. Daily free-tier quotas only
# reset once a day, so those cool down for longer; per-minute limits clear
# quickly. A cooling key is still tried last -- never skipped outright -- so
# a request can't fail just because every key happens to be cooling down.
_QUOTA_COOLDOWN_SECONDS = 300.0
_DAILY_QUOTA_COOLDOWN_SECONDS = 3600.0
_key_cooldown_until: dict[tuple[str, str], float] = {}
_cooldown_lock = threading.Lock()


def _is_retryable(exc: Exception) -> bool:
    return isinstance(exc, errors.APIError) and exc.code in _RETRYABLE_CODES


def _is_quota_error(exc: Exception) -> bool:
    return isinstance(exc, errors.APIError) and exc.code == 429


def _is_model_unavailable(exc: Exception) -> bool:
    # 404: the model is retired/unknown for these keys (e.g. gemini-2.5-flash
    # "is no longer available to new users") -- no other key will fare better.
    return isinstance(exc, errors.APIError) and exc.code == 404


def _mark_quota_exhausted(api_key: str, model: str, exc: Exception) -> None:
    # Free-tier quota is per project *per model*, so a key that's out of
    # quota on one model can still answer on another -- track them apart.
    cooldown = _DAILY_QUOTA_COOLDOWN_SECONDS if "PerDay" in str(exc) else _QUOTA_COOLDOWN_SECONDS
    with _cooldown_lock:
        _key_cooldown_until[(api_key, model)] = time.monotonic() + cooldown


def _ordered_keys(api_keys: list[str], model: str) -> list[tuple[int, str]]:
    """(original 1-based index, key) pairs, keys not in cooldown for `model`
    first, in their configured order; cooling keys after them, soonest-ready
    first."""
    now = time.monotonic()
    with _cooldown_lock:
        until = {key: _key_cooldown_until.get((key, model), 0.0) for key in api_keys}
    indexed = list(enumerate(api_keys, start=1))
    ready = [(i, k) for i, k in indexed if until[k] <= now]
    cooling = sorted(((i, k) for i, k in indexed if until[k] > now), key=lambda pair: until[pair[1]])
    return ready + cooling


class GeminiNotConfiguredError(Exception):
    """No GEMINI_API_KEYS are set. Callers should use a non-LLM fallback
    instead of treating this as a transient failure."""


class GeminiRequestError(Exception):
    """Every configured key failed, after retries (quota, overload, auth, or
    a genuine API error). AdvisorService.ask() catches this and falls back
    to a scripted (non-LLM) reply rather than erroring out to the client."""


def generate_structured(
    *,
    system_instruction: str,
    contents: str,
    response_model: type[T],
) -> T:
    """Runs one generateContent call asking for JSON matching
    `response_model`, trying each model (GEMINI_MODEL, then
    GEMINI_FALLBACK_MODELS) with each configured key until one succeeds.
    Raises GeminiNotConfiguredError if GEMINI_API_KEYS is empty,
    GeminiRequestError if every key failed on every model."""
    api_keys = settings.gemini_api_keys
    if not api_keys:
        raise GeminiNotConfiguredError("No GEMINI_API_KEYS configured.")

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=response_model,
    )

    models = settings.gemini_models
    last_error: Exception | None = None
    for model in models:
        for index, api_key in _ordered_keys(api_keys, model):
            outcome, result = _try_key(api_key, index, len(api_keys), model, contents, config)
            if outcome == "ok":
                if index != 1 or model != models[0]:
                    logger.info("Gemini answered with %s on key #%d/%d.", model, index, len(api_keys))
                return result
            last_error = result
            if outcome == "next_model":
                break

    raise GeminiRequestError(
        f"All {len(api_keys)} configured Gemini key(s) failed on every model ({', '.join(models)})."
    ) from last_error


def _try_key(
    api_key: str, index: int, key_count: int, model: str, contents: str, config: types.GenerateContentConfig
) -> tuple[str, object]:
    """One key on one model, with a short retry for transient overload.
    Returns ("ok", parsed), ("next_key", error) or ("next_model", error) --
    the last when the failure is the model's, not the key's (overloaded
    after retries, or retired/unknown for these keys), so trying the other
    keys on the same model would just waste time."""
    client = genai.Client(api_key=api_key)
    for attempt in range(1, _MAX_ATTEMPTS_PER_KEY + 1):
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
        except Exception as exc:  # noqa: BLE001 -- any SDK/auth/quota error on this key means "try the next one"
            retryable = _is_retryable(exc)
            if retryable and attempt < _MAX_ATTEMPTS_PER_KEY:
                next_step = "retrying"
            elif retryable or _is_model_unavailable(exc):
                next_step = "trying next model"
            else:
                next_step = "trying next key"
            if _is_quota_error(exc):
                _mark_quota_exhausted(api_key, model, exc)
            logger.warning(
                "Gemini %s key #%d/%d attempt %d/%d failed (%s: %s) -- %s.",
                model, index, key_count, attempt, _MAX_ATTEMPTS_PER_KEY, type(exc).__name__, exc, next_step,
            )
            if next_step == "retrying":
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
                continue
            return ("next_model" if next_step == "trying next model" else "next_key"), exc

        parsed = response.parsed
        if parsed is None:
            logger.warning(
                "Gemini %s key #%d/%d returned an unparsable response -- trying next key.", model, index, key_count
            )
            return "next_key", ValueError("Gemini response didn't match the requested schema.")
        return "ok", parsed
    raise AssertionError("unreachable")

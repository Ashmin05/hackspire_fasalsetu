"""AI Advisor / KrishiBot: answers a farmer's free-text question about ONE
farm using only that farm's already-stored data.

`AdvisorService.ask` gathers whatever real data currently exists for the
farm (satellite, alerts, season/crop-stage, environment, weather,
irrigation, mandi price -- each already computed by its own service, never
re-derived here) into a small JSON context block, tagged module-by-module
with a human label and an "as of" date, then asks Gemini to answer strictly
from that block (see _SYSTEM_INSTRUCTION). When GEMINI_API_KEYS is empty, or
every configured key fails, it falls back to a scripted (non-LLM) summary of
the same context instead of erroring -- KrishiBot should never go fully
silent just because no AI key is set.
"""

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone

from app.core.config import settings
from app.core.satellite_health import days_since
from app.integrations.gemini_client import (
    GeminiNotConfiguredError,
    GeminiRequestError,
    generate_structured,
)
from app.ml.crop_benchmarks import benchmark_ndvi_for_crop
from app.models.farm import Farm
from app.models.user import User
from app.schemas.advisor import AdvisorAskResponse, AdvisorLLMOutput, AdvisorSourceOut
from app.services.irrigation_service import IrrigationService, IrrigationServiceError
from app.services.market_prices.price_service import PriceService
from app.services.satellite_service import SatelliteService
from app.services.weather_service import WeatherService, WeatherServiceError

logger = logging.getLogger(__name__)


class AdvisorServiceError(Exception):
    """Gemini is configured but every key failed. Safe to return as a 503
    -- see app/routers/assistant.py."""


class AdvisorRateLimitError(Exception):
    """The user is over ADVISOR_RATE_LIMIT_PER_HOUR. Safe to return as a
    429 -- see app/routers/assistant.py."""


_SYSTEM_INSTRUCTION = """You are KrishiBot, an AI farming advisor inside the FasalSetu app. You answer
one farmer's question about ONE specific farm using ONLY the JSON "context" block given to you in this
turn -- real, already-fetched data for that farm (satellite crop health, alerts, season/crop-stage,
environment/soil, weather, irrigation status, mandi price). Never use outside knowledge, and never
invent numbers, dates, or values that are not present in the context.

Rules:
- If the context doesn't contain what's needed to answer, say so plainly (e.g. "I don't have that data
  for this farm yet") instead of guessing or reaching for general agronomy knowledge.
- Be practical and short -- a working farmer reading this on a phone, not an essay.
- Answer in the language the farmer wrote the question in (e.g. Bengali, Hindi or English). "language"
  in the input is only the app's UI language -- use it when the question's language is unclear. If
  you can't write fluently in that language, answer in English and say so in one short sentence.
- "action_points" are short, concrete next steps, only when the context actually supports them -- an
  empty list is correct for a purely informational question.
- "warnings" are genuine risks visible in the context (a critical alert, high water stress, a sell/hold
  warning) -- an empty list otherwise.
- "sources_used" must list ONLY the context module keys (e.g. "satellite", "weather") you actually drew
  on to answer -- never a module key that's absent from the context, never one you didn't use.
"""

# module key -> display label shown in the "Based on: ..." source line (see
# AdvisorSourceOut) -- "Agmarknet" rather than a generic "Mandi price" to
# match the attribution already shown elsewhere in the app (Market page).
_MODULE_LABELS: dict[str, str] = {
    "farm": "Farm profile",
    "season": "Season / crop stage",
    "satellite": "Satellite",
    "alerts": "Active alerts",
    "environment": "Environment (rainfall / temperature / soil)",
    "weather": "Weather forecast",
    "irrigation": "Irrigation status",
    "market_price": "Agmarknet",
}


class _RateLimiter:
    """Fixed-window per-user cap on POST /farms/{id}/ask. In-memory --
    there's no Redis (or any rate-limiting infra) in this stack yet, and a
    single-process in-memory window is enough for the current deployment;
    it resets on restart and isn't shared across workers."""

    def __init__(self, limit: int, window_seconds: float = 3600.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[uuid.UUID, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(self, user_id: uuid.UUID) -> bool:
        """Records this request and returns whether it's within the cap."""
        now = time.monotonic()
        async with self._lock:
            hits = self._hits[user_id]
            cutoff = now - self.window_seconds
            while hits and hits[0] < cutoff:
                hits.pop(0)
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


_rate_limiter = _RateLimiter(settings.ADVISOR_RATE_LIMIT_PER_HOUR)


class AdvisorService:
    def __init__(
        self,
        satellite_service: SatelliteService,
        weather_service: WeatherService,
        irrigation_service: IrrigationService,
        price_service: PriceService,
    ) -> None:
        self.satellite_service = satellite_service
        self.weather_service = weather_service
        self.irrigation_service = irrigation_service
        self.price_service = price_service

    async def ask(self, farm: Farm, user: User, *, question: str, language: str) -> AdvisorAskResponse:
        if not await _rate_limiter.check(user.id):
            raise AdvisorRateLimitError(
                f"You've reached the limit of {settings.ADVISOR_RATE_LIMIT_PER_HOUR} questions "
                "per hour for KrishiBot. Please try again shortly."
            )

        context = await self._build_context(farm)
        # The widget always sends the UI language ("en"); a question typed in
        # Bengali or Hindi script should still be answered in that language.
        language = _language_from_script(question) or language

        if not settings.gemini_api_keys:
            return _scripted_reply(context, language)

        contents = json.dumps(
            {"language": language, "question": question, "context": context},
            default=str,
        )
        try:
            # generate_structured is a blocking call (the SDK's HTTP client
            # is sync) and now also sleeps between retries on transient
            # errors -- run it off the event loop so one slow/retried
            # request doesn't stall every other request this process is
            # serving.
            llm_output = await asyncio.to_thread(
                generate_structured,
                system_instruction=_SYSTEM_INSTRUCTION,
                contents=contents,
                response_model=AdvisorLLMOutput,
            )
        except GeminiNotConfiguredError:
            return _scripted_reply(context, language)
        except GeminiRequestError as exc:
            # Every configured key failed (free-tier quota, overload, or a
            # genuine API error) -- answer from the scripted fallback rather
            # than erroring out to the user. KrishiBot should always give a
            # useful reply from the real farm data it already has, even when
            # Gemini itself is unavailable.
            logger.warning("All Gemini keys failed, using scripted fallback: %s", exc)
            return _scripted_reply(context, language, ai_unavailable=True)

        return _finalize(llm_output, context, language, is_scripted_fallback=False)

    async def _build_context(self, farm: Farm) -> dict:
        context: dict = {
            "farm": {
                "label": _MODULE_LABELS["farm"],
                "as_of": None,
                "name": farm.name,
                "crop": farm.crop,
                "variety": farm.variety,
                "sowing_date": farm.sowing_date,
                "irrigation_method": farm.irrigation_method,
                "area_ha": farm.area_ha,
                "state": farm.state,
                "district": farm.district,
            }
        }

        today = datetime.now(timezone.utc).date()
        days_elapsed = days_since(farm.sowing_date, today)
        if days_elapsed is not None:
            context["season"] = {
                "label": _MODULE_LABELS["season"],
                "as_of": today,
                "days_since_sowing": days_elapsed,
                "expected_ndvi_for_stage": round(benchmark_ndvi_for_crop(farm.crop, days_elapsed), 2),
            }

        satellite_obs = await self.satellite_service.get_latest(farm)
        if satellite_obs is not None:
            context["satellite"] = {
                "label": _MODULE_LABELS["satellite"],
                "as_of": satellite_obs.image_date,
                "source": "Sentinel-2",
                "ndvi_mean": round(satellite_obs.ndvi_mean, 3),
                "ndwi_mean": round(satellite_obs.ndwi_mean, 3),
                "health_score": satellite_obs.health_score,
                "healthy_pct": satellite_obs.healthy_pct,
                "stressed_pct": satellite_obs.stressed_pct,
                "cloud_pct": satellite_obs.cloud_pct,
            }

            alerts = await self.satellite_service.get_alerts(farm)
            if alerts:
                context["alerts"] = {
                    "label": _MODULE_LABELS["alerts"],
                    "as_of": alerts[0].detected_at,
                    "items": [
                        {
                            "type": a.alert_type,
                            "severity": a.severity,
                            "message": a.message,
                            "detected_at": a.detected_at,
                        }
                        for a in alerts[:5]
                    ],
                }

        environment = await self.satellite_service.get_environment(farm)
        if environment is not None:
            context["environment"] = {
                "label": _MODULE_LABELS["environment"],
                "as_of": environment.generated_at.date() if environment.generated_at else None,
                "rainfall_7d_mm": environment.rainfall_7d_mm,
                "rainfall_30d_mm": environment.rainfall_30d_mm,
                "mean_land_surface_temp_c": environment.mean_lst_c,
                "soil_moisture_m3_per_m3": environment.soil_moisture,
                "soil_ph": environment.soil_ph,
                "soil_texture_class": environment.soil_texture_class,
            }

        try:
            weather = await self.weather_service.get_weather(farm)
        except WeatherServiceError:
            weather = None
        if weather is not None and weather.daily:
            today_w = weather.daily[0]
            next3 = weather.daily[:3]
            context["weather"] = {
                "label": _MODULE_LABELS["weather"],
                "as_of": weather.provenance.fetched_at.date(),
                "today_temp_max_c": today_w.temp_max_c,
                "today_temp_min_c": today_w.temp_min_c,
                "today_rain_mm": today_w.precipitation_sum_mm,
                "today_rain_probability_pct": today_w.precipitation_probability_pct,
                "next_3_days_rain_mm": round(sum(d.precipitation_sum_mm or 0 for d in next3), 1),
                "heat_stress_next_3d": any(d.flags.heat_stress for d in next3),
                "heavy_rain_next_3d": any(d.flags.heavy_rain for d in next3),
            }

        try:
            irrigation_plan = await self.irrigation_service.get_plan(farm)
        except (IrrigationServiceError, WeatherServiceError):
            irrigation_plan = None
        if irrigation_plan is not None:
            context["irrigation"] = {
                "label": _MODULE_LABELS["irrigation"],
                "as_of": irrigation_plan.computed_through,
                "depletion_fraction_pct": round(irrigation_plan.depletion_fraction * 100, 1),
                "is_deficit": irrigation_plan.is_deficit,
                "next_irrigation_date": irrigation_plan.next_irrigation_date,
                "next_irrigation_depth_mm": irrigation_plan.next_irrigation_depth_mm,
            }

        try:
            price = await self.price_service.farm_forecast(farm)
        except Exception:  # noqa: BLE001 -- market context is best-effort; must never break the advisor
            price = None
        today_price = price.get("today") if price else None
        if today_price:
            recommendation = price.get("recommendation") or {}
            context["market_price"] = {
                "label": _MODULE_LABELS["market_price"],
                "as_of": today_price.get("as_of"),
                "market": today_price.get("market"),
                "modal_price_per_quintal": today_price.get("modal_price"),
                "recommendation_action": recommendation.get("action"),
                "recommendation_headline": recommendation.get("headline"),
                "recommendation_reason": recommendation.get("reason"),
            }

        return context


def _finalize(
    llm_output: AdvisorLLMOutput, context: dict, language: str, *, is_scripted_fallback: bool
) -> AdvisorAskResponse:
    sources = [
        AdvisorSourceOut(module=key, label=context[key]["label"], as_of=_as_date(context[key]["as_of"]))
        for key in llm_output.sources_used
        if key in context
    ]
    return AdvisorAskResponse(
        answer=llm_output.answer,
        action_points=llm_output.action_points,
        warnings=llm_output.warnings,
        sources_used=sources,
        language=language,
        is_scripted_fallback=is_scripted_fallback,
        generated_at=datetime.now(timezone.utc),
    )


def _language_from_script(text: str) -> str | None:
    """"bn"/"hi" when the text is mostly Bengali or Devanagari script, else
    None (Latin-script text is left to the caller's language)."""
    bengali = sum(1 for ch in text if "ঀ" <= ch <= "৿")
    devanagari = sum(1 for ch in text if "ऀ" <= ch <= "ॿ")
    letters = sum(1 for ch in text if ch.isalpha()) or 1
    if bengali / letters > 0.5:
        return "bn"
    if devanagari / letters > 0.5:
        return "hi"
    return None


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _scripted_reply(context: dict, language: str, *, ai_unavailable: bool = False) -> AdvisorAskResponse:
    """Non-LLM fallback used when GEMINI_API_KEYS is empty (or every key
    failed): a short, rule-based summary of the same context block, so
    KrishiBot still says something useful about the actual farm rather than
    going silent. Doesn't attempt to address the farmer's specific question
    -- that needs the model -- only reports what's known."""
    lines: list[str] = []
    action_points: list[str] = []
    warnings: list[str] = []
    sources_used: list[str] = []

    if "satellite" in context:
        s = context["satellite"]
        lines.append(f"Crop health score is {s['health_score']}/100 (NDVI {s['ndvi_mean']}) as of {s['as_of']}.")
        sources_used.append("satellite")

    if "irrigation" in context:
        i = context["irrigation"]
        if i["next_irrigation_date"]:
            depth = i["next_irrigation_depth_mm"]
            depth_text = f" (~{depth:.0f}mm)" if depth is not None else ""
            lines.append(f"Next irrigation is due {i['next_irrigation_date']}{depth_text}.")
            action_points.append(f"Plan to irrigate around {i['next_irrigation_date']}.")
        else:
            lines.append("No irrigation is due in the currently modelled window.")
        sources_used.append("irrigation")

    if "weather" in context:
        w = context["weather"]
        if w["heavy_rain_next_3d"]:
            warnings.append("Heavy rain is expected in the next 3 days.")
        if w["heat_stress_next_3d"]:
            warnings.append("Heat-stress conditions are expected in the next 3 days.")
        sources_used.append("weather")

    if "market_price" in context:
        m = context["market_price"]
        if m.get("modal_price_per_quintal") is not None:
            lines.append(
                f"Latest mandi price is Rs {m['modal_price_per_quintal']}/quintal at "
                f"{m.get('market')} ({m['as_of']})."
            )
        if m.get("recommendation_headline"):
            lines.append(str(m["recommendation_headline"]))
        sources_used.append("market_price")

    if "alerts" in context:
        for alert in context["alerts"]["items"]:
            if alert["severity"] == "critical":
                warnings.append(str(alert["message"]))
        sources_used.append("alerts")

    if not lines:
        answer = "I don't have enough data for this farm yet to answer that."
    else:
        answer = " ".join(lines)
    if ai_unavailable:
        # Gemini is configured but couldn't answer -- say so, otherwise a
        # farm summary in reply to e.g. "hello" reads like a broken bot.
        answer = (
            "KrishiBot AI is busy right now and couldn't answer your question directly -- "
            "please ask again in a minute. Meanwhile, here's the latest on your farm: " + answer
        )
    if language.strip().lower() not in ("en", "english", ""):
        answer += (
            " (KrishiBot is running in scripted mode right now, so this reply is in English only --"
            " full multi-language answers return once the AI advisor is configured.)"
        )

    return _finalize(
        AdvisorLLMOutput(answer=answer, action_points=action_points, warnings=warnings, sources_used=sources_used),
        context,
        language,
        is_scripted_fallback=True,
    )

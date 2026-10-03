"""Sell-or-hold suggestion for a farm's crop, built from stored forecasts.

PriceService.recommendation(farm) maps the farm's crop onto a mandi
commodity, picks the nearest *model-ready* mandi (one with a stored forecast
made from a recent price) and compares that mandi's latest modal price with
its 7/14/30-day estimates:

  * "Hold ~N days" only when the estimated rise at N days is larger than the
    model's typical error at that horizon PLUS the assumed cost of holding
    the crop that long (storage + losses, per commodity:
    settings.MARKET_HOLDING_COST_PCT);
  * otherwise "Sell now", with the reason.

Every number comes from stored prices, stored forecasts and the configured
cost assumption. Nothing is invented, and an estimate is never presented as
a guaranteed price. Perishables carry a warning that holding may not be
possible at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.market_prices.text import name_key
from app.models.farm import Farm
from app.models.market_price import Commodity, Market, PriceForecast
from app.services.market_prices import queries as q

HOLD_HORIZONS = (7, 14, 30)
HISTORY_DAYS = 90
NEARBY_RADIUS_KM = 100.0
RECOMMENDATION_DISCLAIMER = (
    "A suggestion from price estimates and an assumed holding cost -- not a guarantee. "
    "Check local conditions, your storage and your cash needs before deciding."
)


@dataclass(frozen=True)
class HoldingCost:
    pct_per_30_days: float
    perishable: bool
    configured: bool  # False = the default for unlisted commodities


def holding_cost_for(commodity_name: str) -> HoldingCost:
    costs = {name_key(k): v for k, v in settings.market_holding_costs.items()}
    perishables = {name_key(n) for n in settings.market_perishable_commodities}
    key = name_key(commodity_name)
    return HoldingCost(
        pct_per_30_days=costs.get(key, settings.MARKET_HOLDING_COST_DEFAULT_PCT),
        perishable=key in perishables,
        configured=key in costs,
    )


def _money(value: float) -> float:
    return round(value, 2)


def typical_error(base_price: float, model: dict | None) -> tuple[float | None, str | None]:
    """The model's validation error at this horizon, in Rs/quintal at this
    market's price level: MAPE x today's price (the models forecast
    relative moves across markets), else the pooled MAE."""
    if not model:
        return None, None
    validation = model.get("validation") or {}
    if validation.get("mape") is not None:
        return base_price * float(validation["mape"]) / 100, "mape"
    if validation.get("mae") is not None:
        return float(validation["mae"]), "mae"
    return None, None


def evaluate_horizons(base_price: float, forecasts: list[dict], models: list[dict], cost: HoldingCost) -> list[dict]:
    by_horizon = {m["horizon_days"]: m for m in models}
    options = []
    for f in sorted(forecasts, key=lambda f: f["horizon_days"]):
        h = f["horizon_days"]
        if h not in HOLD_HORIZONS:
            continue
        predicted = float(f["predicted_price"])
        gain = predicted - base_price
        hold_cost = base_price * cost.pct_per_30_days / 100 * h / 30
        error, error_basis = typical_error(base_price, by_horizon.get(h))
        low, high = f.get("lower_bound"), f.get("upper_bound")
        options.append(
            {
                "horizon_days": h,
                "forecast_date": f["forecast_date"],
                "predicted_price": _money(predicted),
                "expected_gain": _money(gain),
                "expected_gain_pct": round(gain / base_price * 100, 2),
                "holding_cost": _money(hold_cost),
                "net_gain": _money(gain - hold_cost),
                "typical_error": _money(error) if error is not None else None,
                "typical_error_basis": error_basis,
                "gain_range": [_money(float(low) - base_price), _money(float(high) - base_price)]
                if low is not None and high is not None else None,
                "worth_holding": error is not None and gain > error + hold_cost,
                "model_name": f["model_name"],
            }
        )
    return options


def _rs(value: float) -> str:
    return f"₹{abs(value):,.0f}"


def decide(
    *,
    commodity: str,
    base_price: float,
    base_date: date,
    forecasts: list[dict],
    models: list[dict],
    cost: HoldingCost,
    today: date,
) -> dict:
    """The sell/hold rule. Pure: everything it uses is passed in."""
    warning = (
        f"{commodity} is perishable: holding it may not be possible without cold storage, and losses can be far "
        f"larger than the assumed {cost.pct_per_30_days:g}% a month."
        if cost.perishable else None
    )
    holding = {"pct_per_30_days": cost.pct_per_30_days, "assumed": True, "configured": cost.configured}
    base = {"base_price": _money(base_price), "base_date": base_date, "perishable": cost.perishable, "warning": warning,
            "disclaimer": RECOMMENDATION_DISCLAIMER}

    if (today - base_date).days > q.STALE_AFTER_DAYS:
        return {**base, **_unavailable(f"The latest {commodity} price here is from {base_date:%d %b %Y}, too old to compare with."),
                "holding_cost": holding}
    options = evaluate_horizons(base_price, forecasts, models, cost)
    if not options:
        return {**base, **_unavailable("No 7, 14 or 30-day estimate is stored for this mandi."), "holding_cost": holding}

    def margin(o: dict) -> float:
        return o["net_gain"] - (o["typical_error"] if o["typical_error"] is not None else float("inf"))

    worth = [o for o in options if o["worth_holding"]]
    # Hold: the horizon that clears its error by the most. Sell: the most
    # optimistic estimate (largest rise, shortest horizon on ties), so the
    # reason shows that even the best case doesn't pay.
    best = max(worth, key=margin) if worth else max(options, key=lambda o: (o["expected_gain"], -o["horizon_days"]))
    holding = {**holding, "per_quintal": best["holding_cost"], "horizon_days": best["horizon_days"]}
    detail = {
        "expected_gain": {
            "per_quintal": best["expected_gain"], "pct": best["expected_gain_pct"],
            "horizon_days": best["horizon_days"], "by_date": best["forecast_date"],
            "predicted_price": best["predicted_price"],
        },
        "error_range": {
            "typical_error": best["typical_error"], "basis": best["typical_error_basis"],
            "low": best["gain_range"][0] if best["gain_range"] else None,
            "high": best["gain_range"][1] if best["gain_range"] else None,
            "level": 0.8,
        },
        "holding_cost": holding,
        "horizons": options,
    }

    if worth:
        h = best["horizon_days"]
        reason = (
            f"Estimated {_rs(best['expected_gain'])}/quintal rise by {best['forecast_date']:%d %b} beats the model's "
            f"±{_rs(best['typical_error'])} error plus ~{_rs(best['holding_cost'])} holding cost."
        )
        return {**base, **detail, "action": "hold", "hold_days": h, "headline": f"Hold ~{h} days", "reason": reason}

    if all(o["model_name"] == "naive" for o in options):
        reason = "No forecasting model beat 'price stays the same' for this crop, so there is no expected rise to wait for."
    elif max(o["expected_gain"] for o in options) <= 0:
        reason = "Prices are estimated to stay flat or fall over the next 30 days, so holding is unlikely to pay."
    elif best["expected_gain"] <= best["holding_cost"]:
        reason = (
            f"The estimated rise ({_rs(best['expected_gain'])}/quintal by {best['forecast_date']:%d %b}) doesn't cover "
            f"the ~{_rs(best['holding_cost'])} it would cost to hold."
        )
    elif best["typical_error"] is None:
        reason = "The model's error at these horizons isn't known, so holding isn't suggested."
    else:
        reason = (
            f"The estimated rise after holding cost ({_rs(best['net_gain'])}/quintal) is within the model's "
            f"±{_rs(best['typical_error'])} error, so it isn't reliable enough to wait for."
        )
    return {**base, **detail, "action": "sell_now", "hold_days": None, "headline": "Sell now", "reason": reason}


def _unavailable(reason: str) -> dict:
    return {
        "action": "unavailable", "hold_days": None, "headline": "No suggestion", "reason": reason,
        "expected_gain": None, "error_range": None, "horizons": [],
    }


def best_nearby_today(nearby: list[dict], *, selected_price: float | None, selected_market_id: int | None, today: date) -> dict | None:
    """Highest modal price among nearby mandis that reported within the
    freshness window. A comparison: transport and time aren't included."""
    fresh = [r for r in nearby if (today - r["as_of"]).days <= q.STALE_AFTER_DAYS]
    if not fresh:
        return None
    top = max(fresh, key=lambda r: r["modal_price"])
    price = float(top["modal_price"])
    return {
        "market_id": top["market_id"], "market": top["market"], "district": top["district"],
        "distance_km": top["distance_km"], "coordinate_precision": top["coordinate_precision"],
        "modal_price": _money(price), "as_of": top["as_of"],
        "is_selected": top["market_id"] == selected_market_id,
        "difference_vs_selected": _money(price - selected_price) if selected_price is not None else None,
        "note": "Before transport and handling costs.",
    }


class PriceService:
    def __init__(self, session: AsyncSession, *, today: date | None = None):
        self.session = session
        self.today = today or q.today_utc()

    async def recommendation(self, farm: Farm, *, commodity_id: int | None = None, market_id: int | None = None) -> dict:
        return (await self.farm_forecast(farm, commodity_id=commodity_id, market_id=market_id))["recommendation"]

    async def farm_forecast(
        self, farm: Farm, *, commodity_id: int | None = None, market_id: int | None = None,
        radius_km: float = NEARBY_RADIUS_KM,
    ) -> dict:
        """Everything the Market page shows for a farm: the crop's mandi
        commodity, the chosen mandi's live price, 90 days of history, the
        stored estimates, nearby mandis and the sell/hold suggestion.
        Raises q.NotFoundError for an unknown commodity_id / market_id."""
        ctx = await q.farm_context(self.session, farm)
        mapped: list[Commodity] = ctx["commodities"]

        async def nearby_for(c: Commodity) -> list[dict]:
            rows = await q.nearby(self.session, c, lat=farm.centroid_lat, lon=farm.centroid_lng, radius_km=radius_km,
                                  state=ctx["state"], district=ctx["district"], limit=25)
            ready = await self._model_ready(c, [r["market_id"] for r in rows])
            return [{**r, "model_ready": r["market_id"] in ready} for r in rows]

        commodity: Commodity | None = None
        nearby: list[dict] = []
        if commodity_id is not None:
            commodity = await q.resolve_commodity(self.session, commodity_id)
            nearby = await nearby_for(commodity)
        else:
            # The crop's first commodity with a model-ready mandi nearby, else
            # the first with any nearby price, else the first mapped.
            candidates = [(c, await nearby_for(c)) for c in mapped]
            chosen = next(((c, n) for c, n in candidates if any(r["model_ready"] for r in n)), None) \
                or next(((c, n) for c, n in candidates if n), None) \
                or (candidates[0] if candidates else None)
            if chosen:
                commodity, nearby = chosen

        market: Market | None = None
        if commodity is not None:
            if market_id is not None:
                market = await q.get_market(self.session, market_id)
            else:
                pick = next((r for r in nearby if r["model_ready"]), None) or (nearby[0] if nearby else None)
                market = await q.get_market(self.session, pick["market_id"]) if pick else None

        stats = forecast = None
        history: list[dict] = []
        market_info = None
        if commodity is not None and market is not None:
            stats = await q.market_stats(self.session, market, commodity)
            forecast = await q.forecast(self.session, market, commodity, horizons=list(HOLD_HORIZONS))
            history = await q.history(self.session, market, commodity,
                                      from_date=self.today - timedelta(days=HISTORY_DAYS), to_date=self.today)
            row = next((r for r in nearby if r["market_id"] == market.id), None)
            market_info = {
                **await q.market_out(self.session, market),
                "latest_date": stats["as_of"] if stats else None,
                "distance_km": row["distance_km"] if row else None,
                "model_ready": bool(forecast and forecast["available"]),
            }

        recommendation = self._recommend(commodity, market, stats, forecast, nearby)
        if not mapped and commodity is None:
            message = f"No mandi commodity is mapped for the crop {farm.crop!r}; choose a crop."
        elif market is None:
            message = "No recent mandi price is available near this farm for this crop."
        else:
            message = None
        return {
            "farm_id": str(farm.id),
            "crop": farm.crop,
            "commodities": [{"id": c.id, "name": c.name} for c in mapped],
            "selected_commodity": {"id": commodity.id, "name": commodity.name} if commodity else None,
            "state": ctx["state"].name if ctx["state"] else farm.state,
            "district": ctx["district"].name if ctx["district"] else farm.district,
            "market": market_info,
            "today": stats,
            "history": history,
            "forecast": forecast or {"available": False, "reason": recommendation["reason"], "generated_at": None,
                                     "forecasts": [], "models": [], "disclaimer": q.FORECAST_DISCLAIMER},
            "recommendation": recommendation,
            "nearby": nearby,
            "attribution": q.distance_attribution(nearby),
            "message": message,
        }

    def _recommend(self, commodity, market, stats, forecast, nearby) -> dict:
        cost = holding_cost_for(commodity.name) if commodity else None
        best = best_nearby_today(
            nearby, selected_price=float(stats["modal_price"]) if stats else None,
            selected_market_id=market.id if market else None, today=self.today,
        )
        if commodity is None or market is None:
            result = _unavailable("No mandi near this farm has reported this crop in the last 30 days.")
        elif not forecast or not forecast["available"]:
            result = _unavailable(forecast["reason"] if forecast else "No forecast is available for this mandi.")
        else:
            first = forecast["forecasts"][0]
            result = decide(
                commodity=commodity.name, base_price=float(first["base_price"]), base_date=first["base_date"],
                forecasts=forecast["forecasts"], models=forecast["models"], cost=cost, today=self.today,
            )
        if "base_price" not in result:
            result.update(base_price=None, base_date=None, perishable=bool(cost and cost.perishable),
                          warning=None, disclaimer=RECOMMENDATION_DISCLAIMER)
            if cost and cost.perishable:
                result["warning"] = f"{commodity.name} is perishable: holding it may not be possible without cold storage."
        result.setdefault("holding_cost", {"pct_per_30_days": cost.pct_per_30_days, "assumed": True,
                                           "configured": cost.configured} if cost else None)
        return {
            **result,
            "commodity": commodity.name if commodity else None,
            "market": market.name if market else None,
            "best_nearby": best,
        }

    async def _model_ready(self, commodity: Commodity, market_ids: list[int]) -> set[int]:
        """Markets with a stored estimate made from a recent price."""
        if not market_ids:
            return set()
        rows = await self.session.scalars(
            select(PriceForecast.market_id)
            .where(
                PriceForecast.commodity_id == commodity.id,
                PriceForecast.market_id.in_(market_ids),
                PriceForecast.base_date >= self.today - timedelta(days=q.STALE_AFTER_DAYS),
            )
            .distinct()
        )
        return set(rows.all())

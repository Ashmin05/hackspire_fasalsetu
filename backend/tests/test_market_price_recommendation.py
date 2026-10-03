"""Sell-or-hold suggestion: the pure rule, and GET /farms/{id}/market/forecast."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.farm import Farm
from app.models.market_price import Commodity, MarketState, PriceForecast, PriceForecastModel
from app.services.market_prices.price_service import HoldingCost, decide, holding_cost_for
from tests.test_market_price_api import client  # noqa: F401  (fixture)
from tests.test_market_price_ingestion import TODAY

BASE_DATE = date(2026, 9, 25)


def models(mape: float = 5.0, name: str = "lightgbm_huber") -> list[dict]:
    return [
        {"horizon_days": h, "model_name": name, "validation": {"mae": 80.0, "mape": mape}}
        for h in (7, 14, 30)
    ]


def forecasts(predicted: dict[int, float], base: float = 1900.0, name: str = "lightgbm_huber") -> list[dict]:
    return [
        {"horizon_days": h, "base_date": BASE_DATE, "base_price": Decimal(str(base)),
         "forecast_date": BASE_DATE + timedelta(days=h), "predicted_price": Decimal(str(p)),
         "lower_bound": Decimal(str(p * 0.95)), "upper_bound": Decimal(str(p * 1.05)), "model_name": name}
        for h, p in predicted.items()
    ]


POTATO = HoldingCost(pct_per_30_days=3.0, perishable=False, configured=True)


def run(predicted: dict[int, float], *, cost: HoldingCost = POTATO, mape: float = 5.0, name: str = "lightgbm_huber",
        commodity: str = "Potato", today: date = TODAY) -> dict:
    return decide(commodity=commodity, base_price=1900.0, base_date=BASE_DATE, forecasts=forecasts(predicted, name=name),
                  models=models(mape, name), cost=cost, today=today)


def test_hold_only_when_rise_beats_error_plus_holding_cost() -> None:
    # 30 days: +300 vs error 95 (5% of 1900) + holding 57 (3% of 1900) -> hold.
    result = run({7: 1920, 14: 1950, 30: 2200})
    assert (result["action"], result["hold_days"], result["headline"]) == ("hold", 30, "Hold ~30 days")
    assert result["expected_gain"]["per_quintal"] == 300.0 and result["expected_gain"]["pct"] == 15.79
    assert result["error_range"]["typical_error"] == 95.0 and result["error_range"]["basis"] == "mape"
    assert result["error_range"]["low"] == 190.0 and result["error_range"]["high"] == 410.0
    assert result["holding_cost"]["per_quintal"] == 57.0
    assert "beats the model's ±₹95 error plus ~₹57 holding cost" in result["reason"]
    assert [o["worth_holding"] for o in result["horizons"]] == [False, False, True]


def test_sell_now_when_rise_is_within_error() -> None:
    # +100 at 30 days < 95 + 57.
    result = run({7: 1920, 14: 1950, 30: 2000})
    assert result["action"] == "sell_now" and result["hold_days"] is None
    assert "within the model's ±₹95 error" in result["reason"]


def test_sell_now_when_rise_does_not_cover_holding_cost() -> None:
    result = run({7: 1905, 14: 1910, 30: 1950}, mape=0.1)
    assert result["action"] == "sell_now" and "doesn't cover" in result["reason"]


def test_sell_now_when_prices_fall_or_model_is_naive() -> None:
    assert "flat or fall" in run({7: 1880, 14: 1850, 30: 1800})["reason"]
    naive = run({7: 1900, 14: 1900, 30: 1900}, name="naive")
    assert naive["action"] == "sell_now" and "No forecasting model beat" in naive["reason"]


def test_higher_holding_cost_turns_hold_into_sell() -> None:
    # The same estimate that says hold for potato says sell for tomato.
    tomato = HoldingCost(pct_per_30_days=20.0, perishable=True, configured=True)
    result = run({7: 1920, 14: 1950, 30: 2200}, cost=tomato, commodity="Tomato")
    assert result["action"] == "sell_now"
    assert result["perishable"] is True and "holding it may not be possible" in result["warning"]


def test_stale_base_price_gives_no_suggestion() -> None:
    result = run({30: 2200}, today=BASE_DATE + timedelta(days=12))
    assert result["action"] == "unavailable" and "too old" in result["reason"]


def test_holding_costs_are_configured_per_commodity() -> None:
    tomato, wheat, unknown = holding_cost_for("Tomato"), holding_cost_for("wheat"), holding_cost_for("Brinjal")
    assert tomato.pct_per_30_days > wheat.pct_per_30_days
    assert tomato.perishable and not wheat.perishable
    assert (unknown.configured, unknown.pct_per_30_days) == (False, 3.0)


# ------------------------------------------------------------------- API


async def add_horizons(session, market, predicted: dict[int, float], *, base: float = 1900.0, mape: float = 5.0) -> None:
    potato = await session.scalar(select(Commodity).where(Commodity.name == "Potato"))
    state = await session.scalar(select(MarketState).where(MarketState.name == "West Bengal"))
    now = datetime.now(timezone.utc)
    for h, p in predicted.items():
        model = PriceForecastModel(
            commodity_id=potato.id, state_id=state.id, horizon_days=h, model_name="lightgbm_huber",
            model_version="20260926", train_start=date(2021, 1, 1), train_end=BASE_DATE, n_samples=1000, n_markets=3,
            features=[], mae=80.0, rmse=100.0, mape=mape, evaluation={"models": {"naive": {"mae": 90.0}}},
            interval_low_log=-0.05, interval_high_log=0.05, artifact_path="/nowhere", is_active=True,
        )
        session.add(model)
        await session.flush()
        session.add(PriceForecast(
            market_id=market.id, commodity_id=potato.id, model_id=model.id, base_date=BASE_DATE,
            base_price=Decimal(str(base)), forecast_date=BASE_DATE + timedelta(days=h), horizon_days=h,
            predicted_price=Decimal(str(p)), lower_bound=Decimal(str(p - 100)), upper_bound=Decimal(str(p + 100)),
            model_name="lightgbm_huber", model_version="20260926", generated_at=now,
        ))
    await session.commit()


@pytest.fixture
async def farm(client):  # noqa: F811
    farm = Farm(user_id=client.user.id, name="Plot", crop="Potato", sowing_date=TODAY, polygon_geojson={},
                area_ha=1.0, centroid_lat=22.57, centroid_lng=88.36, state="West Bengal", district="Kolkata")
    client.session.add(farm)
    await client.session.commit()
    return farm


async def test_no_forecast_means_no_suggestion(client, farm) -> None:  # noqa: F811
    body = (await client.get(f"/farms/{farm.id}/market/forecast")).json()
    assert body["selected_commodity"]["name"] == "Potato"
    assert body["market"]["name"] == "Bara Bazar (Posta Bazar) APMC" and body["market"]["model_ready"] is False
    assert body["today"]["modal_price"] == 1910.0 and len(body["history"]) > 0
    rec = body["recommendation"]
    assert rec["action"] == "unavailable" and "insufficient historical data" in rec["reason"]
    assert rec["best_nearby"]["market"] == "Bara Bazar (Posta Bazar) APMC" and rec["best_nearby"]["is_selected"]


async def test_picks_nearest_model_ready_mandi_and_suggests_hold(client, farm) -> None:  # noqa: F811
    burdwan = client.markets["Burdwan APMC"]
    await add_horizons(client.session, burdwan, {7: 1920, 14: 1950, 30: 2200})
    body = (await client.get(f"/farms/{farm.id}/market/forecast")).json()
    # Bara Bazar is closer but has no forecast; Burdwan (~88 km) does.
    assert body["market"]["name"] == "Burdwan APMC" and body["market"]["model_ready"] is True
    assert [f["horizon_days"] for f in body["forecast"]["forecasts"]] == [7, 14, 30]
    assert {m["model_version"] for m in body["forecast"]["models"]} == {"20260926"}
    assert [r["model_ready"] for r in body["nearby"] if r["market"] == "Burdwan APMC"] == [True]
    rec = body["recommendation"]
    assert (rec["action"], rec["hold_days"]) == ("hold", 30)
    assert rec["holding_cost"]["pct_per_30_days"] == 3.0 and rec["perishable"] is False
    # Best nearby today is Bara Bazar (₹1,910), ₹418 above Burdwan's latest price.
    assert rec["best_nearby"]["market"] == "Bara Bazar (Posta Bazar) APMC"
    assert rec["best_nearby"]["difference_vs_selected"] == 418.0

    # Choosing the mandi explicitly works too; an unknown one is a 404.
    chosen = (await client.get(f"/farms/{farm.id}/market/forecast",
                               params={"market_id": client.markets["Sheoraphuly APMC"].id})).json()
    assert chosen["market"]["name"] == "Sheoraphuly APMC" and chosen["recommendation"]["action"] == "unavailable"
    assert (await client.get(f"/farms/{farm.id}/market/forecast", params={"market_id": 999999})).status_code == 404


async def test_sell_now_via_api(client, farm) -> None:  # noqa: F811
    await add_horizons(client.session, client.markets["Bara Bazar (Posta Bazar) APMC"], {7: 1880, 14: 1870, 30: 1860})
    rec = (await client.get(f"/farms/{farm.id}/market/forecast")).json()["recommendation"]
    assert rec["action"] == "sell_now" and "flat or fall" in rec["reason"]
    assert "not a guarantee" in rec["disclaimer"]

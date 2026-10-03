"""/market-prices endpoints end to end over an in-memory DB."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import get_db
from app.core.deps import get_current_user
from app.integrations.market_prices.base import ProviderPriceBatch
from app.main import app
from app.models.farm import Farm
from app.models.market_price import Commodity, Market, MarketState, PriceForecast, PriceForecastModel
from app.models.user import User
from app.services.market_prices import queries
from app.services.market_prices.analytics import refresh_analytics
from app.services.market_prices.ingestion import MarketPriceIngestionService
from tests.test_market_price_ingestion import QUERY, TODAY, FakeProvider, loaded, record


def series(market: str, district: str, start: float, step: float, days: int = 35) -> list:
    last = date(2026, 9, 25)
    return [
        record(
            source_record_id=f"{market}:{i}", market=market, district=district,
            arrival_date=last - timedelta(days=days - 1 - i), modal_price=Decimal(str(start + step * i)),
            min_price=Decimal(str(start + step * i - 50)), max_price=Decimal(str(start + step * i + 50)),
        )
        for i in range(days)
    ]


@pytest.fixture
async def client(session, monkeypatch):
    monkeypatch.setattr(queries, "today_utc", lambda: TODAY)
    await loaded(session)
    records = (
        series("Bara Bazar (Posta Bazar) APMC", "Kolkata", 1400, 15)  # rising ~5%/week
        + series("Burdwan APMC", "Purba Bardhaman", 1900, -12)  # falling ~5%/week
        + series("Sheoraphuly APMC", "Hooghly", 1450, 0)  # flat
        # Stopped reporting in July -> left out of nearby comparisons.
        + [record(source_record_id="old", market="Alipurduar APMC", district="Alipurduar", arrival_date=date(2026, 7, 1))]
    )
    service = MarketPriceIngestionService(session, [FakeProvider(batches=[ProviderPriceBatch(records)])], today=TODAY)
    await service.ingest([QUERY], kind="current")
    await refresh_analytics(session, service.touched)
    markets = {m.name: m for m in (await session.scalars(select(Market).where(Market.name.in_(
        ["Bara Bazar (Posta Bazar) APMC", "Burdwan APMC", "Sheoraphuly APMC"])))).all()}
    markets["Bara Bazar (Posta Bazar) APMC"].latitude, markets["Bara Bazar (Posta Bazar) APMC"].longitude = 22.585, 88.356
    markets["Bara Bazar (Posta Bazar) APMC"].coordinate_precision = "place"
    markets["Burdwan APMC"].latitude, markets["Burdwan APMC"].longitude = 23.232, 87.862
    await session.commit()

    user = User(id=uuid.uuid4(), email="farmer@example.com", full_name="F", is_active=True)
    session.add(user)
    await session.commit()

    async def db():
        yield session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.markets = markets
        c.user = user
        c.session = session
        yield c
    app.dependency_overrides.clear()


async def test_catalogue_endpoints(client) -> None:
    commodities = (await client.get("/market-prices/commodities", params={"state": "West Bengal"})).json()
    assert [(c["name"], c["markets"]) for c in commodities] == [("Potato", 4)]

    locations = (await client.get("/market-prices/locations", params={"commodity": "potato"})).json()
    assert locations[0]["name"] == "West Bengal"
    assert {d["name"] for d in locations[0]["districts"]} == {"Kolkata", "Purba Bardhaman", "Hooghly", "Alipurduar"}

    markets = (await client.get("/market-prices/markets", params={"state": "West Bengal", "commodity": "Potato"})).json()
    assert len(markets) == 4 and sum(m["latest_date"] == "2026-09-25" for m in markets) == 3
    assert (await client.get("/market-prices/markets")).status_code == 422


async def test_latest_prices_with_analytics_and_provenance(client) -> None:
    body = (await client.get("/market-prices/latest", params={"commodity": "Potato", "state": "West Bengal"})).json()
    by_market = {p["market"]: p for p in body["prices"]}
    rising = by_market["Bara Bazar (Posta Bazar) APMC"]
    assert rising["modal_price"] == 1910.0 and rising["avg_7d"] == 1865.0  # 1400 + 15 x 34; mean of the last 7
    assert rising["trend"] == "increasing" and by_market["Burdwan APMC"]["trend"] == "decreasing"
    assert by_market["Sheoraphuly APMC"]["trend"] == "stable" and by_market["Sheoraphuly APMC"]["change_7d_pct"] == 0.0
    assert body["unit"] == "Rs/quintal"
    assert body["provenance"]["as_of"] == "2026-09-25" and body["provenance"]["is_stale"] is False
    assert body["provenance"]["sources"] == ["Agmarknet 2.0 (agmarknet.gov.in)"]


async def test_errors(client) -> None:
    assert (await client.get("/market-prices/latest")).status_code == 422
    missing = await client.get("/market-prices/latest", params={"commodity": "Unobtainium"})
    assert missing.status_code == 404 and "Unknown commodity" in missing.json()["detail"]
    assert (await client.get("/market-prices/latest", params={"commodity": "Potato", "state": "Atlantis"})).status_code == 404
    assert (await client.get("/market-prices/history", params={"market_id": 999999, "commodity": "Potato"})).status_code == 404
    assert (await client.get("/market-prices/forecast", params={"market_id": 1, "commodity": "Potato", "horizon": 10})).status_code == 422


async def test_raw_prices_paginate(client) -> None:
    body = (await client.get("/market-prices", params={"commodity": "Potato", "page_size": 10, "page": 2})).json()
    # Default window: 30 days back from today (2026-08-28..09-27); data ends 09-25 -> 29 days x 3 markets
    # (the fourth market's only report is from July).
    assert body["total"] == 3 * 29
    assert len(body["records"]) == 10 and body["records"][0]["unit"] == "Rs/quintal"


async def test_history(client) -> None:
    market_id = client.markets["Burdwan APMC"].id
    body = (await client.get("/market-prices/history", params={"market_id": market_id, "commodity": "Potato",
                                                               "from": "2026-09-20", "to": "2026-09-25"})).json()
    assert [p["date"] for p in body["series"]] == [f"2026-09-{d}" for d in range(20, 26)]
    assert body["market"]["district"] == "Purba Bardhaman"
    bad = await client.get("/market-prices/history", params={"market_id": market_id, "commodity": "Potato", "from": "2026-09-25", "to": "2026-09-01"})
    assert bad.status_code == 422


async def test_nearby(client) -> None:
    body = (await client.get("/market-prices/nearby", params={
        "commodity": "Potato", "lat": 22.5726, "lon": 88.3639, "radius_km": 50, "state": "West Bengal"})).json()
    assert [(m["market"], m["scope"]) for m in body["markets"]] == [
        ("Bara Bazar (Posta Bazar) APMC", "radius"), ("Sheoraphuly APMC", "state")]
    assert body["markets"][0]["distance_km"] < 3
    assert "OpenStreetMap" in body["attribution"] and "not necessarily the best market" in body["note"]
    assert (await client.get("/market-prices/nearby", params={"commodity": "Potato"})).status_code == 422
    assert (await client.get("/market-prices/nearby", params={"commodity": "Potato", "lat": 22.5})).status_code == 422


async def test_trends(client) -> None:
    body = (await client.get("/market-prices/trends", params={"commodity": "Potato", "state": "West Bengal"})).json()
    assert body["trend_counts"] == {"increasing": 1, "stable": 1, "decreasing": 1, "insufficient_data": 0}
    assert body["markets_stale"] == 1
    assert body["top_gainers"][0]["market"] == "Bara Bazar (Posta Bazar) APMC"
    assert body["top_decliners"][0]["market"] == "Burdwan APMC"


async def add_forecasts(session, market: Market, *, predicted: str) -> None:
    potato = await session.scalar(select(Commodity).where(Commodity.name == "Potato"))
    state = await session.scalar(select(MarketState).where(MarketState.name == "West Bengal"))
    model = PriceForecastModel(
        commodity_id=potato.id, state_id=state.id, horizon_days=7, model_name="lightgbm", model_version="v1",
        train_start=date(2021, 1, 1), train_end=date(2026, 9, 25), n_samples=1000, n_markets=3, features=[],
        mae=42.0, rmse=60.0, mape=3.1, evaluation={"models": {"naive": {"mae": 50.0}}, "selection_note": "lightgbm beat naive",
                                                   "interval": {"holdout_coverage": 0.79}, "validation": {"scheme": "rolling"}},
        interval_low_log=-0.05, interval_high_log=0.05, artifact_path="/nowhere", is_active=True,
    )
    session.add(model)
    await session.flush()
    session.add(PriceForecast(
        market_id=market.id, commodity_id=potato.id, model_id=model.id, base_date=date(2026, 9, 25),
        base_price=Decimal("1570"), forecast_date=date(2026, 10, 2), horizon_days=7,
        predicted_price=Decimal(predicted), lower_bound=Decimal("1500"), upper_bound=Decimal("1720"),
        model_name="lightgbm", model_version="v1", generated_at=datetime.now(timezone.utc),
    ))
    await session.commit()


async def test_forecast_unavailable_then_available(client) -> None:
    market = client.markets["Bara Bazar (Posta Bazar) APMC"]
    params = {"market_id": market.id, "commodity": "Potato"}
    none = (await client.get("/market-prices/forecast", params=params)).json()
    assert none["available"] is False and "insufficient historical data" in none["reason"]
    assert "not guaranteed" in none["disclaimer"]

    await add_forecasts(client.session, market, predicted="1640")
    body = (await client.get("/market-prices/forecast", params=params)).json()
    assert body["available"] is True
    point = body["forecasts"][0]
    assert (point["horizon_days"], point["predicted_price"], point["lower_bound"], point["upper_bound"]) == (7, 1640.0, 1500.0, 1720.0)
    assert point["change_pct"] == 4.46
    model = body["models"][0]
    assert model["validation"]["mae"] == 42.0 and model["validation"]["naive_mae"] == 50.0
    assert model["training_period"] == {"from": "2021-01-01", "to": "2026-09-25"}


async def test_analytics_outlook_is_derived_from_the_numbers(client) -> None:
    market = client.markets["Bara Bazar (Posta Bazar) APMC"]
    await add_forecasts(client.session, market, predicted="1640")
    body = (await client.get("/market-prices/analytics", params={"market_id": market.id, "commodity": "Potato"})).json()
    outlook = body["outlook"]
    assert outlook["label"] == "positive"
    assert outlook["statements"][0].startswith("Potato prices at Bara Bazar (Posta Bazar) APMC have increased")
    assert "rise of about 4.5%" in outlook["statements"][1] and "not guaranteed" in outlook["statements"][1]
    assert "currently has the highest modal price" in outlook["statements"][2]
    assert outlook["basis"]["trend"] == "increasing"


async def test_farm_market_prices(client) -> None:
    farm = Farm(user_id=client.user.id, name="Plot", crop="Potato", sowing_date=TODAY, polygon_geojson={},
                area_ha=1.0, centroid_lat=22.57, centroid_lng=88.36, state="West Bengal", district="Kolkata")
    other = Farm(user_id=uuid.uuid4(), name="Not mine", crop="Potato", sowing_date=TODAY, polygon_geojson={},
                 area_ha=1.0, centroid_lat=22.57, centroid_lng=88.36, state="West Bengal")
    client.session.add_all([farm, other])
    await client.session.commit()

    body = (await client.get(f"/farms/{farm.id}/market-prices")).json()
    assert body["selected_commodity"]["name"] == "Potato" and body["district"] == "Kolkata"
    assert body["nearby"][0]["market"] == "Bara Bazar (Posta Bazar) APMC" and body["message"] is None
    assert (await client.get(f"/farms/{other.id}/market-prices")).status_code == 404


async def test_quality_endpoint(client) -> None:
    body = (await client.get("/market-prices/quality")).json()
    assert body["stored_records"] == 106 and body["recent_runs"][0]["kind"] == "current"

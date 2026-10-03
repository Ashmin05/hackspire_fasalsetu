"""The nightly jobs share one DB session across every farm -- one farm's
failed commit must not poison it for the farms after it."""

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.jobs import scheduler
from app.models import Base
from app.models.farm import Farm
from app.models.user import User
from app.repositories.farm_repository import FarmRepository
from app.repositories.user_repository import UserRepository
from app.services.farm_service import FarmService
from app.services.satellite_service import SatelliteService

VALID_POLYGON = {
    "type": "Polygon",
    "coordinates": [[
        [73.789522, 19.989548],
        [73.790478, 19.989548],
        [73.790478, 19.990452],
        [73.789522, 19.990452],
        [73.789522, 19.989548],
    ]],
}


@pytest.fixture
async def session_factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", factory)
    monkeypatch.setattr(scheduler, "earth_engine_client", SimpleNamespace(configured=True))
    yield factory
    await engine.dispose()


async def _seed_three_farms(factory) -> None:
    async with factory() as session:
        users = UserRepository(session)
        user = await users.create(email="farmer@example.com", hashed_password="x")
        user = await users.update_profile(user, phone="9876543210", state="Maharashtra")
        farm_service = FarmService(FarmRepository(session))
        for name in ("Farm A", "Farm B", "Farm C"):
            await farm_service.create_farm(
                user, name=name, crop="Onion", variety=None, sowing_date=date(2026, 6, 10),
                irrigation_method=None, polygon_geojson=VALID_POLYGON, state="Maharashtra",
                district="Nashik", address=None,
            )


def _fail_first_farm_with_a_db_error(processed: list[str]):
    """Stands in for a per-farm refresh: the first farm hits a real failed
    commit (duplicate unique email -- like the Sentinel-2C column overflow
    did in production); every later farm runs a real query on the same
    shared session, which only works if the job reset it."""

    async def fake_refresh(self: SatelliteService, farm: Farm) -> None:
        session = self.satellite_repository.session
        if not processed:
            processed.append("failed")
            session.add(User(email="farmer@example.com", hashed_password="dup"))
            await session.commit()
        await session.execute(select(Farm).limit(1))
        processed.append(farm.name)

    return fake_refresh


@pytest.mark.parametrize(
    ("job", "method"),
    [
        (scheduler.run_nightly_timeseries_refresh, "build_timeseries"),
        (scheduler.run_nightly_environment_refresh, "refresh_environment"),
    ],
)
async def test_one_farms_db_error_does_not_skip_the_rest(session_factory, monkeypatch, job, method) -> None:
    await _seed_three_farms(session_factory)
    processed: list[str] = []
    monkeypatch.setattr(SatelliteService, method, _fail_first_farm_with_a_db_error(processed))

    await job()

    assert processed[0] == "failed"
    assert len(processed[1:]) == 2  # both remaining farms refreshed, not PendingRollbackError

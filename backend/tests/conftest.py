from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.repositories.environment_snapshot_repository import EnvironmentSnapshotRepository
from app.repositories.farm_alert_repository import FarmAlertRepository
from app.repositories.farm_repository import FarmRepository
from app.repositories.index_timeseries_repository import IndexTimeseriesRepository
from app.repositories.irrigation_log_repository import IrrigationLogRepository
from app.repositories.irrigation_plan_repository import IrrigationPlanRepository
from app.repositories.satellite_layer_repository import SatelliteLayerRepository
from app.repositories.satellite_repository import SatelliteRepository
from app.repositories.stress_zone_repository import StressZoneRepository
from app.repositories.user_repository import UserRepository
from app.repositories.weather_cache_repository import WeatherCacheRepository
from app.services.auth_service import AuthService
from app.services.farm_service import FarmService


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    """A fresh in-memory SQLite DB per test, matching the real ORM schema."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    await engine.dispose()


@pytest.fixture
def user_repository(session: AsyncSession) -> UserRepository:
    return UserRepository(session)


@pytest.fixture
def auth_service(user_repository: UserRepository) -> AuthService:
    return AuthService(user_repository)


@pytest.fixture
def farm_repository(session: AsyncSession) -> FarmRepository:
    return FarmRepository(session)


@pytest.fixture
def farm_service(farm_repository: FarmRepository) -> FarmService:
    return FarmService(farm_repository)


@pytest.fixture
def satellite_repository(session: AsyncSession) -> SatelliteRepository:
    return SatelliteRepository(session)


@pytest.fixture
def index_timeseries_repository(session: AsyncSession) -> IndexTimeseriesRepository:
    return IndexTimeseriesRepository(session)


@pytest.fixture
def farm_alert_repository(session: AsyncSession) -> FarmAlertRepository:
    return FarmAlertRepository(session)


@pytest.fixture
def satellite_layer_repository(session: AsyncSession) -> SatelliteLayerRepository:
    return SatelliteLayerRepository(session)


@pytest.fixture
def stress_zone_repository(session: AsyncSession) -> StressZoneRepository:
    return StressZoneRepository(session)


@pytest.fixture
def environment_snapshot_repository(session: AsyncSession) -> EnvironmentSnapshotRepository:
    return EnvironmentSnapshotRepository(session)


@pytest.fixture
def weather_cache_repository(session: AsyncSession) -> WeatherCacheRepository:
    return WeatherCacheRepository(session)


@pytest.fixture
def irrigation_plan_repository(session: AsyncSession) -> IrrigationPlanRepository:
    return IrrigationPlanRepository(session)


@pytest.fixture
def irrigation_log_repository(session: AsyncSession) -> IrrigationLogRepository:
    return IrrigationLogRepository(session)


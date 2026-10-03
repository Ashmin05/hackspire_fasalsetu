from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.integrations.earth_engine_client import earth_engine_client
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.routers import alerts, assistant, auth, farms, health, irrigation, market_prices, news, satellite, weather


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Never raises — an unconfigured or invalid Earth Engine key must not
    # stop the rest of the API from starting. See EarthEngineClient.initialize.
    earth_engine_client.initialize()
    # Registers the nightly satellite timeseries job; harmless to start even
    # when Earth Engine isn't configured -- the job itself checks and skips.
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="FasalSetu API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(farms.router)
app.include_router(satellite.router)
app.include_router(weather.router)
app.include_router(news.router)
app.include_router(irrigation.router)
app.include_router(alerts.router)
app.include_router(market_prices.router)
app.include_router(market_prices.farm_router)
app.include_router(assistant.router)

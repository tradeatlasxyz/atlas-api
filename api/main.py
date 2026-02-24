from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Configure root logger so all api.* module loggers emit to console
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from api.config import database_dsn_safe, running_in_hosted_env, settings
from api.execution.market_data import get_market_data
from api.execution.scheduler import get_scheduler
from api.routes import admin, health, pools, referrals, strategies, trading
from api.services.backfill import BackfillService


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger(__name__)
    logger.info("Database DSN: %s", database_dsn_safe())
    if running_in_hosted_env() and settings.database_url.startswith("sqlite"):
        logger.warning(
            "DATABASE_PRIVATE_URL/DATABASE_URL not set to Postgres in hosted env. "
            "Falling back to SQLite — data will NOT persist across deploys."
        )

    # --- database / backfill (non-fatal) ---
    try:
        backfill = BackfillService()
        if settings.backfill_on_startup:
            status = await backfill.check_backfill_status()
            needs_backfill = any(
                count == 0
                for asset_status in status.values()
                for count in asset_status.values()
            )
            if needs_backfill:
                await backfill.backfill_all()
    except Exception as exc:
        logger.error("Backfill/DB check failed on startup (non-fatal): %s", exc)

    market_data = get_market_data()
    await market_data.start_price_polling(interval_seconds=10)

    scheduler = get_scheduler()
    await scheduler.start()

    yield

    await scheduler.stop()
    await market_data.stop_price_polling()


app = FastAPI(
    title="Atlas API",
    description="Operational backend for Atlas vaults",
    version=settings.api_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["Health"])
app.include_router(strategies.router, prefix="/api", tags=["Strategies"])
app.include_router(pools.router, prefix="/api", tags=["Pools"])
app.include_router(referrals.router)
app.include_router(admin.router, tags=["Admin"])
app.include_router(trading.router)


@app.get("/")
async def root() -> dict:
    return {"message": "Atlas API", "docs": "/docs"}

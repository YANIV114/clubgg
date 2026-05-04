import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.session import engine
from app.ingestion.scheduler import shutdown_scheduler, start_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ClubGG backend")
    await start_scheduler()
    yield
    logger.info("Shutting down ClubGG backend")
    await shutdown_scheduler()
    await engine.dispose()

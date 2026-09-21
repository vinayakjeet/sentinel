import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.middleware import RequestIdMiddleware

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("startup", extra={"env": settings.app_env})
    yield
    logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="SENTINEL",
        description="Real-time application fraud detection for digital lending.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()

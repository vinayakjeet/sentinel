import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestIdMiddleware
from app.services.container import build_services

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger("app")


def _warm_embedder() -> None:
    """Load the case embedder before serving so the first decision doesn't stall on a model load/download."""
    try:
        from app.semantic.embedder import get_embedder

        get_embedder().encode("warm-up")
    except Exception:
        logger.warning("embedder warm-up failed; similar-cases will load it lazily", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.services = build_services(settings)
    await asyncio.to_thread(_warm_embedder)
    logger.info("startup", extra={"env": settings.app_env, "model_version": app.state.services.scorer.model_version})
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
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()

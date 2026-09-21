import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.db.session import engine
from app.schemas.health import HealthResponse, ReadyResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse, "description": "Database unreachable"}},
)
def ready(response: Response) -> ReadyResponse:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logger.warning("readiness check failed: database unreachable", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(status="unavailable", database="error")
    return ReadyResponse(status="ready", database="ok")

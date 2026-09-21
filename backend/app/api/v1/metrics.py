from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_user, require_admin
from app.db.session import get_db
from app.schemas.metrics import DriftStatus, MetricsResponse
from app.services.container import Services, get_services

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse)
def get_metrics(
    user: Principal = Depends(get_current_user), services: Services = Depends(get_services)
) -> MetricsResponse:
    return services.metrics.snapshot()


@router.get("/drift", response_model=DriftStatus)
def get_drift(
    user: Principal = Depends(get_current_user),
    services: Services = Depends(get_services),
    db: Session = Depends(get_db),
) -> DriftStatus:
    return services.drift.status(db)


@router.post("/drift/reset", response_model=DriftStatus, summary="Reset thresholds and detectors (admin)")
def reset_drift(
    user: Principal = Depends(require_admin),
    services: Services = Depends(get_services),
    db: Session = Depends(get_db),
) -> DriftStatus:
    return services.drift.reset(db, actor=user.username)

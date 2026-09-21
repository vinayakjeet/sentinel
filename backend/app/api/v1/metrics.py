from fastapi import APIRouter, Depends

from app.api.v1._stub import NOT_IMPLEMENTED, not_implemented
from app.core.security import Principal, get_current_user, require_admin
from app.schemas.metrics import DriftStatus, MetricsResponse

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse, responses=NOT_IMPLEMENTED)
def get_metrics(user: Principal = Depends(get_current_user)) -> MetricsResponse:
    not_implemented("metrics (A5)")


@router.get("/drift", response_model=DriftStatus, responses=NOT_IMPLEMENTED)
def get_drift(user: Principal = Depends(get_current_user)) -> DriftStatus:
    not_implemented("drift status (A5)")


@router.post("/drift/reset", response_model=DriftStatus, responses=NOT_IMPLEMENTED, summary="Reset thresholds (admin)")
def reset_drift(user: Principal = Depends(require_admin)) -> DriftStatus:
    not_implemented("drift reset (A5)")

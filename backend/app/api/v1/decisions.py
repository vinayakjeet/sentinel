import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_user
from app.db.session import get_db
from app.repositories import decision_repo
from app.schemas.application import ApplicationEvent
from app.schemas.common import ErrorResponse
from app.schemas.decision import Band, DecisionList, DecisionResponse
from app.services.container import Services, get_services
from app.services.decision_service import to_response

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.post(
    "/application",
    response_model=DecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Score a credit application and persist the decision",
)
def decide_application(
    event: ApplicationEvent,
    request: Request,
    db: Session = Depends(get_db),
    services: Services = Depends(get_services),
    user: Principal = Depends(get_current_user),
) -> DecisionResponse:
    return services.decisions.decide(
        db, event, actor=user.username, started_at=request.scope.get("state", {}).get("t0")
    )


@router.get(
    "/{decision_id}",
    response_model=DecisionResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_decision(
    decision_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: Principal = Depends(get_current_user),
) -> DecisionResponse:
    found = decision_repo.get_decision(db, decision_id)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "decision not found")
    return to_response(*found)


@router.get("", response_model=DecisionList)
def list_decisions(
    band: Band | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: Principal = Depends(get_current_user),
) -> DecisionList:
    rows, total = decision_repo.list_decisions(db, band.value if band else None, limit, offset)
    return DecisionList(items=[to_response(d, a) for d, a in rows], total=total, limit=limit, offset=offset)

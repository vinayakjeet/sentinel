import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_user
from app.db.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.graph import EntityGraphResponse
from app.services.container import Services, get_services

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get(
    "/{application_id}/graph",
    response_model=EntityGraphResponse,
    responses={404: {"model": ErrorResponse}},
    summary="2-hop application<->entity neighbourhood for the case graph",
)
def get_entity_graph(
    application_id: uuid.UUID,
    db: Session = Depends(get_db),
    services: Services = Depends(get_services),
    user: Principal = Depends(get_current_user),
) -> EntityGraphResponse:
    graph = services.graph.graph(db, application_id)
    if graph is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "application not found")
    return graph

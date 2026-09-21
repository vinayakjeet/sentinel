import uuid

from fastapi import APIRouter, Depends

from app.api.v1._stub import NOT_IMPLEMENTED, not_implemented
from app.core.security import Principal, get_current_user
from app.schemas.common import ErrorResponse
from app.schemas.graph import EntityGraphResponse

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get(
    "/{application_id}/graph",
    response_model=EntityGraphResponse,
    responses={404: {"model": ErrorResponse}, **NOT_IMPLEMENTED},
    summary="2-hop application<->entity neighbourhood for the case graph",
)
def get_entity_graph(
    application_id: uuid.UUID,
    user: Principal = Depends(get_current_user),
) -> EntityGraphResponse:
    not_implemented("entity graph (A4)")

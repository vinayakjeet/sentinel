"""Placeholders for Lane B routes so the frozen OpenAPI contract is complete.

Lane B's real routers (app.semantic.router, app.llm.router) replace these with the same paths and the
models in app.schemas.cases / app.schemas.copilot. When one lands, drop its stub from router.py.
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.api.v1._stub import NOT_IMPLEMENTED, not_implemented
from app.core.security import Principal, get_current_user
from app.schemas.cases import SimilarCasesResponse
from app.schemas.common import ErrorResponse
from app.schemas.copilot import CopilotAskRequest, CopilotAskResponse

cases_router = APIRouter(prefix="/cases", tags=["cases"])
copilot_router = APIRouter(prefix="/copilot", tags=["copilot"])


@cases_router.get(
    "/{decision_id}/similar",
    response_model=SimilarCasesResponse,
    responses={404: {"model": ErrorResponse}, **NOT_IMPLEMENTED},
    summary="Nearest past cases by narrative embedding",
)
def similar_cases(
    decision_id: uuid.UUID,
    k: int = Query(5, ge=1, le=20),
    user: Principal = Depends(get_current_user),
) -> SimilarCasesResponse:
    not_implemented("similar cases (Lane B, B5)")


@copilot_router.post(
    "/ask",
    response_model=CopilotAskResponse,
    responses={404: {"model": ErrorResponse}, **NOT_IMPLEMENTED},
    summary="Ask the read-only analyst copilot about a decision",
)
def copilot_ask(body: CopilotAskRequest, user: Principal = Depends(get_current_user)) -> CopilotAskResponse:
    not_implemented("copilot (Lane B, B6)")

"""POST /copilot/ask (DESIGN §9, §10).

Implements the contract in app/schemas/copilot.py, which Lane A owns. Replaces the stub in
app/api/v1/_contract_stubs.py with identical paths and models.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import Principal, get_current_user
from app.llm.service import ask
from app.schemas.common import ErrorResponse
from app.schemas.copilot import CopilotAskRequest, CopilotAskResponse

router = APIRouter(prefix="/copilot", tags=["copilot"])


@router.post(
    "/ask",
    response_model=CopilotAskResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Ask the read-only analyst copilot about a decision",
)
def copilot_ask(
    body: CopilotAskRequest,
    user: Principal = Depends(get_current_user),
) -> CopilotAskResponse:
    """Explain a decision that has already been made.

    Read-only by construction: the copilot reaches the database only through the tool registry in
    app/llm/tools.py, whose sessions run in a Postgres READ ONLY transaction that is always rolled
    back. There is no code path from here to a score or a decision (CLAUDE.md invariant 1).
    """
    result = ask(body.decision_id, body.question)
    return CopilotAskResponse(
        answer=result.answer,
        cited_reasons=result.cited_reasons,
        blocked=result.blocked,
        fallback_used=result.fallback_used,
    )

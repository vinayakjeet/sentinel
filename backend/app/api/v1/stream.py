from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.v1._stub import NOT_IMPLEMENTED, not_implemented
from app.core.security import Principal, get_current_user, get_current_user_sse, require_admin
from app.schemas.stream import StreamSource, StreamStatus

router = APIRouter(prefix="/stream", tags=["stream"])


class EventSourceResponse(StreamingResponse):
    media_type = "text/event-stream"


_SSE_DOC = {
    200: {
        "description": (
            "Server-Sent Events. `event: decision` carries a DecisionResponse JSON in `data`; "
            "`event: drift` carries a DriftEventOut JSON; `: ping` comments every 15 s keep the connection open."
        ),
        "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/DecisionResponse"}}},
    },
    **NOT_IMPLEMENTED,
}


@router.get(
    "",
    response_model=None,
    response_class=EventSourceResponse,
    responses=_SSE_DOC,
    summary="Live decision feed (SSE)",
)
def stream_decisions(user: Principal = Depends(get_current_user_sse)):
    not_implemented("decision stream (A5)")


@router.get("/status", response_model=StreamStatus, responses=NOT_IMPLEMENTED)
def stream_status(user: Principal = Depends(get_current_user)) -> StreamStatus:
    not_implemented("stream status (A5)")


@router.post("/switch", response_model=StreamStatus, responses=NOT_IMPLEMENTED, summary="Switch replay source (admin)")
def switch_source(
    source: StreamSource = Query(..., description="base = test months of Base; shift = variant file"),
    user: Principal = Depends(require_admin),
) -> StreamStatus:
    not_implemented("stream switch (A5)")


@router.post("/start", response_model=StreamStatus, responses=NOT_IMPLEMENTED, summary="Start replay (admin)")
def start_stream(user: Principal = Depends(require_admin)) -> StreamStatus:
    not_implemented("stream start (A5)")


@router.post("/stop", response_model=StreamStatus, responses=NOT_IMPLEMENTED, summary="Stop replay (admin)")
def stop_stream(user: Principal = Depends(require_admin)) -> StreamStatus:
    not_implemented("stream stop (A5)")

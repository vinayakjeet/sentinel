import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.security import Principal, get_current_user, get_current_user_sse, require_admin
from app.db.session import get_db
from app.repositories import audit_repo
from app.schemas.stream import StreamSource, StreamStatus
from app.services.broadcaster import TooManySubscribers
from app.services.container import Services, get_services

router = APIRouter(prefix="/stream", tags=["stream"])

HEARTBEAT_SECONDS = 15.0


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
}


@router.get(
    "",
    response_model=None,
    response_class=EventSourceResponse,
    responses=_SSE_DOC,
    summary="Live decision feed (SSE)",
)
async def stream_decisions(
    request: Request,
    user: Principal = Depends(get_current_user_sse),
    services: Services = Depends(get_services),
):
    try:
        queue = services.broadcaster.subscribe()
    except TooManySubscribers:
        raise HTTPException(status_code=429, detail="too many live-feed connections") from None

    async def events() -> AsyncIterator[str]:
        try:
            yield ": connected\n\n"
            while not await request.is_disconnected():
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"event: {event}\ndata: {data}\n\n"
        finally:
            services.broadcaster.unsubscribe(queue)

    return EventSourceResponse(events(), headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/status", response_model=StreamStatus)
def stream_status(
    user: Principal = Depends(get_current_user), services: Services = Depends(get_services)
) -> StreamStatus:
    return services.replay.status()


def _audit(db: Session, user: Principal, action: str, details: dict) -> None:
    audit_repo.write(db, actor=user.username, action=action, resource_type="stream", details=details)
    db.commit()


@router.post("/switch", response_model=StreamStatus, summary="Switch replay source (admin)")
async def switch_source(
    source: StreamSource = Query(..., description="base = test months of Base; shift = variant file"),
    user: Principal = Depends(require_admin),
    services: Services = Depends(get_services),
    db: Session = Depends(get_db),
) -> StreamStatus:
    status = await services.replay.switch(source)
    _audit(db, user, "stream.switch", {"source": source})
    return status


@router.post("/start", response_model=StreamStatus, summary="Start replay (admin)")
async def start_stream(
    user: Principal = Depends(require_admin),
    services: Services = Depends(get_services),
    db: Session = Depends(get_db),
) -> StreamStatus:
    status = await services.replay.start()
    _audit(db, user, "stream.start", {"source": status.source})
    return status


@router.post("/stop", response_model=StreamStatus, summary="Stop replay (admin)")
async def stop_stream(
    user: Principal = Depends(require_admin),
    services: Services = Depends(get_services),
    db: Session = Depends(get_db),
) -> StreamStatus:
    status = await services.replay.stop()
    _audit(db, user, "stream.stop", {"events_emitted": status.events_emitted})
    return status

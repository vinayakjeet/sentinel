"""Regression: slowapi's ASGI middleware must not break streaming responses (the SSE feed).

Found via the frontend: with the stock middleware the live feed sent ": connected" and then died with
"Expected ASGI message 'http.response.body', but got 'http.response.start'".
"""

import pytest
from slowapi import Limiter
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.util import get_remote_address
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.limits import StreamSafeSlowAPIMiddleware
from app.services.broadcaster import MAX_SUBSCRIBERS, Broadcaster, TooManySubscribers


def _app(middleware, limit: str = "1000/minute") -> Starlette:
    async def chunks():
        for i in range(3):
            yield f"event: decision\ndata: {i}\n\n"

    async def stream(request):
        return StreamingResponse(chunks(), media_type="text/event-stream")

    async def plain(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/api/v1/stream", stream), Route("/api/v1/other", plain)])
    app.state.limiter = Limiter(key_func=get_remote_address, default_limits=[limit])
    app.add_middleware(middleware)
    return app


def test_stock_slowapi_middleware_breaks_streaming():
    """Documents the upstream bug this middleware works around; if slowapi fixes it, this can go."""
    with pytest.raises((RuntimeError, AssertionError)):  # uvicorn raises the former, TestClient the latter
        TestClient(_app(SlowAPIASGIMiddleware)).get("/api/v1/stream")


def test_stream_route_streams_every_chunk():
    res = TestClient(_app(StreamSafeSlowAPIMiddleware)).get("/api/v1/stream")
    assert res.status_code == 200
    assert res.text.count("event: decision") == 3


def test_other_routes_are_still_rate_limited():
    client = TestClient(_app(StreamSafeSlowAPIMiddleware, limit="2/minute"))
    assert [client.get("/api/v1/other").status_code for _ in range(3)] == [200, 200, 429]


def test_subscriber_cap():
    b = Broadcaster()
    queues = [b.subscribe() for _ in range(MAX_SUBSCRIBERS)]
    with pytest.raises(TooManySubscribers):
        b.subscribe()
    b.unsubscribe(queues[0])
    b.subscribe()  # a freed slot is reusable

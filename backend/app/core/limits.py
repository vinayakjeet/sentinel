"""Rate limiting (slowapi) and request body size cap."""

import json

from slowapi import Limiter
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.security import decode_token


def rate_key(request: Request) -> str:
    """Per authenticated user when a valid token is presented, else per client IP.

    Every local caller (frontend, loader, curl) shares one IP, so keying on IP alone would let a bulk load
    starve the analyst console.
    """
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("token")
    principal = decode_token(token) if token else None
    return f"user:{principal.username}" if principal else f"ip:{get_remote_address(request)}"


_settings = get_settings()
limiter = Limiter(key_func=rate_key, default_limits=[_settings.rate_limit_default])

LOGIN_LIMIT = _settings.rate_limit_login
DECISIONS_LIMIT = _settings.rate_limit_decisions
login_key = get_remote_address


class StreamSafeSlowAPIMiddleware(SlowAPIASGIMiddleware):
    """SlowAPIASGIMiddleware, except it stays out of the way of the SSE route.

    slowapi wraps `send` to inject X-RateLimit-* headers and re-sends its buffered `http.response.start` on the
    first body chunk, which uvicorn rejects on a streaming response ("Expected ASGI message 'http.response.body',
    but got 'http.response.start'"). The client sees the stream close right after the first frame. The stream is
    one long-lived request per subscriber, so per-request limiting adds nothing; concurrent subscribers are
    capped in the Broadcaster instead.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].endswith("/stream"):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


class BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """413 for request bodies over `max_bytes`, whether declared (Content-Length) or streamed (chunked)."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        seen = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if not started:
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps({"detail": f"request body exceeds {self.max_bytes} bytes"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})

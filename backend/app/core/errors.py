import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_ctx

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str | None:
    # The contextvar is already reset when an error reaches the outermost handler; the scope state survives.
    return request_id_ctx.get() or request.scope.get("state", {}).get("request_id")


def _error(request: Request, status_code: int, detail, headers: dict | None = None) -> JSONResponse:
    rid = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder({"detail": detail, "request_id": rid}),
        headers={**(headers or {}), **({"X-Request-ID": rid} if rid else {})},
    )


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Never echo submitted values back: they can be passwords or applicant PII. Keep only where/what failed.
    errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
    return _error(request, status.HTTP_422_UNPROCESSABLE_ENTITY, errors)


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _error(request, exc.status_code, exc.detail, headers=getattr(exc, "headers", None))


async def _rate_limited(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return _error(request, status.HTTP_429_TOO_MANY_REQUESTS, f"rate limit exceeded: {exc.detail}",
                  headers={"Retry-After": "60"})


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    # Full traceback goes to the server log only; the client gets an opaque message + request_id to quote.
    logger.error("unhandled error", exc_info=exc, extra={"path": request.url.path, "request_id": _request_id(request)})
    return _error(request, status.HTTP_500_INTERNAL_SERVER_ERROR, "internal server error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RateLimitExceeded, _rate_limited)
    app.add_exception_handler(Exception, _unhandled)

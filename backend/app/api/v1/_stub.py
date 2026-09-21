"""Helpers for contract routes that exist (final request/response models) before their implementation lands."""

from typing import NoReturn

from fastapi import HTTPException, status

from app.schemas.common import ErrorResponse

NOT_IMPLEMENTED = {501: {"model": ErrorResponse, "description": "Not implemented yet"}}


def not_implemented(what: str) -> NoReturn:
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, f"{what} not implemented yet")

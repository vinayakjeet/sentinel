from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str
    request_id: str | None = None

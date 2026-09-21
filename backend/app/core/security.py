from typing import Literal

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

Role = Literal["analyst", "admin"]

bearer_scheme = HTTPBearer(auto_error=False, description="JWT from POST /api/v1/auth/login")


class Principal(BaseModel):
    username: str
    role: Role


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    # A6 replaces this with JWT verification (401 on missing/invalid token).
    return Principal(username="anonymous", role="admin")


def require_admin(user: Principal = Depends(get_current_user)) -> Principal:
    # A6: 403 unless user.role == "admin".
    return user

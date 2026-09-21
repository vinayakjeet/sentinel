import logging
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Literal

import bcrypt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)

Role = Literal["analyst", "admin"]

bearer_scheme = HTTPBearer(auto_error=False, description="JWT from POST /api/v1/auth/login")


class Principal(BaseModel):
    username: str
    role: Role


class UserRecord(BaseModel):
    username: str
    password_hash: bytes
    role: Role


@lru_cache
def _user_store() -> dict[str, UserRecord]:
    """Demo users come from env only (DEMO_*_USERNAME/PASSWORD); passwords are bcrypt-hashed in memory."""
    s = get_settings()
    users: dict[str, UserRecord] = {}
    for username, password, role in (
        (s.demo_analyst_username, s.demo_analyst_password, "analyst"),
        (s.demo_admin_username, s.demo_admin_password, "admin"),
    ):
        if username and password:
            pw_hash = bcrypt.hashpw(password.get_secret_value().encode(), bcrypt.gensalt())
            users[username] = UserRecord(username=username, password_hash=pw_hash, role=role)
    if not users:
        logger.warning("no demo users configured; every login will fail")
    return users


_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt())


def authenticate(username: str, password: str) -> Principal | None:
    user = _user_store().get(username)
    # Always run one bcrypt check so unknown usernames take as long as wrong passwords.
    ok = bcrypt.checkpw(password.encode(), user.password_hash if user else _DUMMY_HASH)
    return Principal(username=user.username, role=user.role) if (user and ok) else None


def _secret() -> str:
    secret = get_settings().jwt_secret
    if secret is None:
        raise RuntimeError("JWT_SECRET is not configured")
    return secret.get_secret_value()


def create_access_token(principal: Principal) -> tuple[str, int]:
    s = get_settings()
    expires_in = s.jwt_expire_minutes * 60
    now = datetime.now(UTC)
    claims = {
        "sub": principal.username,
        "role": principal.role,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(claims, _secret(), algorithm=s.jwt_algorithm), expires_in


def decode_token(token: str) -> Principal | None:
    try:
        claims = jwt.decode(token, _secret(), algorithms=[get_settings().jwt_algorithm])
        return Principal(username=claims["sub"], role=claims["role"])
    except (JWTError, KeyError, ValueError):
        return None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def _principal_from(token: str | None) -> Principal:
    if not token:
        raise _unauthorized("not authenticated")
    principal = decode_token(token)
    if principal is None:
        raise _unauthorized("invalid or expired token")
    return principal


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    """401 unless a valid, unexpired JWT is presented as `Authorization: Bearer <token>`."""
    return _principal_from(credentials.credentials if credentials else None)


def get_current_user_sse(
    token: str | None = Query(None, description="JWT; EventSource cannot send an Authorization header"),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    """Same as get_current_user, but also accepts ?token= because browsers' EventSource cannot set headers."""
    return _principal_from(credentials.credentials if credentials else token)


def require_admin(user: Principal = Depends(get_current_user)) -> Principal:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    return user

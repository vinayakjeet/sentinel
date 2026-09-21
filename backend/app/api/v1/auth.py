from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import authenticate, create_access_token
from app.db.session import get_db
from app.repositories import audit_repo
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.common import ErrorResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse, responses={401: {"model": ErrorResponse}})
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    principal = authenticate(body.username, body.password)
    audit_repo.write(
        db,
        actor=body.username,
        action="auth.login" if principal else "auth.login_failed",
        details={},
    )
    db.commit()
    if not principal:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    token, expires_in = create_access_token(principal)
    return TokenResponse(access_token=token, role=principal.role, expires_in=expires_in)

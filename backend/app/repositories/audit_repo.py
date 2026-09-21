from sqlalchemy.orm import Session

from app.core.logging import request_id_ctx
from app.models import AuditLog


def write(
    db: Session,
    *,
    actor: str,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            request_id=request_id_ctx.get(),
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )
    )

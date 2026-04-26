import json

from sqlalchemy.orm import Session

from onboarding_client.models import AuditLog


def log_audit(
    db: Session,
    *,
    actor: str,
    action: str,
    target_type: str,
    target_id: str,
    details: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=json.dumps(details or {}, ensure_ascii=True),
        )
    )

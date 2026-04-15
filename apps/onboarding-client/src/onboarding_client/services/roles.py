from sqlalchemy.orm import Session

from onboarding_client.models import Role
from onboarding_client.schemas import RoleCreate


def create_role(db: Session, payload: RoleCreate) -> Role:
    existing = db.query(Role).filter(Role.slug == payload.slug.strip().lower()).first()
    if existing:
        raise ValueError("Role already exists")
    role = Role(
        slug=payload.slug.strip().lower(),
        display_name=payload.display_name.strip(),
        description=payload.description,
    )
    db.add(role)
    db.flush()
    return role


def list_roles(db: Session) -> list[Role]:
    return db.query(Role).order_by(Role.slug.asc()).all()


def get_roles_by_slugs(db: Session, role_slugs: list[str]) -> list[Role]:
    normalized = [item.strip().lower() for item in role_slugs if item.strip()]
    if not normalized:
        return []
    roles = db.query(Role).filter(Role.slug.in_(normalized)).all()
    role_map = {role.slug: role for role in roles}
    missing = [slug for slug in normalized if slug not in role_map]
    if missing:
        raise ValueError(f"Unknown role(s): {', '.join(missing)}")
    return [role_map[slug] for slug in normalized]

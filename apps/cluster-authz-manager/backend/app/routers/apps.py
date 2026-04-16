from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from ..models.base import get_db
from ..models import authz as models
from ..schemas import authz as schemas

router = APIRouter(prefix="/api/apps", tags=["apps"])


@router.get("", response_model=List[schemas.AppProfile])
def list_apps(db: Session = Depends(get_db)):
    return db.query(models.AppProfile).all()


@router.get("/{slug}", response_model=schemas.AppProfile)
def get_app(slug: str, db: Session = Depends(get_db)):
    app = db.query(models.AppProfile).filter(models.AppProfile.slug == slug).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    return app


@router.get("/{slug}/roles", response_model=List[schemas.Role])
def list_roles(slug: str, db: Session = Depends(get_db)):
    app = get_app(slug, db)
    return app.roles


@router.post("/{slug}/roles", response_model=schemas.Role)
def create_role(slug: str, role_in: schemas.RoleCreate, db: Session = Depends(get_db)):
    app = get_app(slug, db)
    role_name = role_in.name.strip()
    if not role_name:
        raise HTTPException(status_code=400, detail="Role name is required")
    existing = (
        db.query(models.Role)
        .filter(
            models.Role.app_profile_id == app.id,
            models.Role.name == role_name,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400, detail="Role with this name already exists"
        )

    role = models.Role(
        name=role_name, description=role_in.description, app_profile_id=app.id
    )
    if role_in.permission_ids:
        perms = (
            db.query(models.Permission)
            .filter(
                models.Permission.app_profile_id == app.id,
                models.Permission.id.in_(role_in.permission_ids),
            )
            .all()
        )
        if len(perms) != len(set(role_in.permission_ids)):
            raise HTTPException(
                status_code=400,
                detail="One or more capabilities were not found for this app",
            )
        role.permissions = perms
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


@router.patch("/{slug}/roles/{role_id}", response_model=schemas.Role)
def update_role(
    slug: str, role_id: str, role_in: schemas.RoleUpdate, db: Session = Depends(get_db)
):
    app = get_app(slug, db)
    role = (
        db.query(models.Role)
        .filter(
            models.Role.id == role_id,
            models.Role.app_profile_id == app.id,
        )
        .first()
    )
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    update_data = role_in.dict(exclude_unset=True)
    if "name" in update_data:
        role_name = str(update_data.get("name") or "").strip()
        if not role_name:
            raise HTTPException(status_code=400, detail="Role name is required")
        duplicate = (
            db.query(models.Role)
            .filter(
                models.Role.app_profile_id == app.id,
                models.Role.name == role_name,
                models.Role.id != role.id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=400, detail="Role with this name already exists"
            )
        role.name = role_name

    if "description" in update_data:
        role.description = update_data.get("description")

    if "permission_ids" in update_data:
        permission_ids = update_data.get("permission_ids") or []
        perms = []
        if permission_ids:
            perms = (
                db.query(models.Permission)
                .filter(
                    models.Permission.app_profile_id == app.id,
                    models.Permission.id.in_(permission_ids),
                )
                .all()
            )
            if len(perms) != len(set(permission_ids)):
                raise HTTPException(
                    status_code=400,
                    detail="One or more capabilities were not found for this app",
                )
        role.permissions = perms

    db.commit()
    db.refresh(role)
    return role


@router.get("/{slug}/permissions", response_model=List[schemas.Permission])
def list_permissions(slug: str, db: Session = Depends(get_db)):
    app = get_app(slug, db)
    return app.permissions


@router.post("/{slug}/permissions", response_model=schemas.Permission)
def create_permission(
    slug: str, permission_in: schemas.PermissionCreate, db: Session = Depends(get_db)
):
    app = get_app(slug, db)
    permission_name = permission_in.name.strip()
    if not permission_name:
        raise HTTPException(status_code=400, detail="Capability name is required")

    existing = (
        db.query(models.Permission)
        .filter(
            models.Permission.app_profile_id == app.id,
            models.Permission.name == permission_name,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400, detail="Capability with this name already exists"
        )

    permission = models.Permission(
        app_profile_id=app.id,
        name=permission_name,
        description=permission_in.description,
    )
    db.add(permission)
    db.commit()
    db.refresh(permission)
    return permission


@router.patch("/{slug}/permissions/{permission_id}", response_model=schemas.Permission)
def update_permission(
    slug: str,
    permission_id: str,
    permission_in: schemas.PermissionUpdate,
    db: Session = Depends(get_db),
):
    app = get_app(slug, db)
    permission = (
        db.query(models.Permission)
        .filter(
            models.Permission.id == permission_id,
            models.Permission.app_profile_id == app.id,
        )
        .first()
    )
    if not permission:
        raise HTTPException(status_code=404, detail="Capability not found")

    update_data = permission_in.dict(exclude_unset=True)
    if "name" in update_data:
        permission_name = str(update_data.get("name") or "").strip()
        if not permission_name:
            raise HTTPException(status_code=400, detail="Capability name is required")
        duplicate = (
            db.query(models.Permission)
            .filter(
                models.Permission.app_profile_id == app.id,
                models.Permission.name == permission_name,
                models.Permission.id != permission.id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=400, detail="Capability with this name already exists"
            )
        permission.name = permission_name

    if "description" in update_data:
        permission.description = update_data.get("description")

    db.commit()
    db.refresh(permission)
    return permission


@router.get("/{slug}/bindings/groups", response_model=List[schemas.GroupBinding])
def list_group_bindings(slug: str, db: Session = Depends(get_db)):
    app = get_app(slug, db)
    return app.group_bindings


@router.post("/{slug}/bindings/groups", response_model=schemas.GroupBinding)
def create_group_binding(
    slug: str, binding_in: schemas.GroupBindingCreate, db: Session = Depends(get_db)
):
    app = get_app(slug, db)
    binding = models.GroupRoleBinding(**binding_in.dict(), app_profile_id=app.id)
    db.add(binding)
    db.commit()
    db.refresh(binding)
    return binding


@router.get("/{slug}/bindings/users", response_model=List[schemas.UserBinding])
def list_user_bindings(slug: str, db: Session = Depends(get_db)):
    app = get_app(slug, db)
    return app.user_bindings


@router.post("/{slug}/bindings/users", response_model=schemas.UserBinding)
def create_user_binding(
    slug: str, binding_in: schemas.UserBindingCreate, db: Session = Depends(get_db)
):
    app = get_app(slug, db)
    binding = models.UserRoleBinding(**binding_in.dict(), app_profile_id=app.id)
    db.add(binding)
    db.commit()
    db.refresh(binding)
    return binding


@router.post("", response_model=schemas.AppProfile)
def create_app(app_in: schemas.AppProfileCreate, db: Session = Depends(get_db)):
    existing = (
        db.query(models.AppProfile)
        .filter(models.AppProfile.slug == app_in.slug)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="App with this slug already exists")
    app = models.AppProfile(**app_in.dict())
    db.add(app)
    db.commit()
    db.refresh(app)
    return app


@router.delete("/{slug}/roles/{role_id}")
def delete_role(slug: str, role_id: str, db: Session = Depends(get_db)):
    app = get_app(slug, db)
    role = (
        db.query(models.Role)
        .filter(
            models.Role.id == role_id,
            models.Role.app_profile_id == app.id,
        )
        .first()
    )
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    db.delete(role)
    db.commit()
    return {"status": "deleted"}


@router.delete("/{slug}/permissions/{permission_id}")
def delete_permission(slug: str, permission_id: str, db: Session = Depends(get_db)):
    app = get_app(slug, db)
    permission = (
        db.query(models.Permission)
        .filter(
            models.Permission.id == permission_id,
            models.Permission.app_profile_id == app.id,
        )
        .first()
    )
    if not permission:
        raise HTTPException(status_code=404, detail="Capability not found")
    permission.roles = []
    db.delete(permission)
    db.commit()
    return {"status": "deleted"}


@router.delete("/{slug}/bindings/groups/{binding_id}")
def delete_group_binding(slug: str, binding_id: str, db: Session = Depends(get_db)):
    binding = (
        db.query(models.GroupRoleBinding)
        .filter(models.GroupRoleBinding.id == binding_id)
        .first()
    )
    if not binding:
        raise HTTPException(status_code=404, detail="Binding not found")
    db.delete(binding)
    db.commit()
    return {"status": "deleted"}


@router.delete("/{slug}/bindings/users/{binding_id}")
def delete_user_binding(slug: str, binding_id: str, db: Session = Depends(get_db)):
    binding = (
        db.query(models.UserRoleBinding)
        .filter(models.UserRoleBinding.id == binding_id)
        .first()
    )
    if not binding:
        raise HTTPException(status_code=404, detail="Binding not found")
    db.delete(binding)
    db.commit()
    return {"status": "deleted"}

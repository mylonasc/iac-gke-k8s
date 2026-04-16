from fastapi import HTTPException, Request, Depends
from sqlalchemy.orm import Session
from ..models.base import get_db
from ..models import authz as models

def require_permission(permission_name: str):
    def dependency(request: Request, db: Session = Depends(get_db)):
        subject = request.headers.get("x-auth-request-user")
        email = request.headers.get("x-auth-request-email")
        
        if not subject and not email:
            # For local testing if auth is disabled
            import os
            if os.getenv("AUTH_ENABLED", "true").lower() == "false":
                return True
            raise HTTPException(status_code=401, detail="Authentication required")
            
        # Check if user has permission for the manager app itself
        manager_app = db.query(models.AppProfile).filter(models.AppProfile.slug == "cluster-authz-manager").first()
        if not manager_app:
            return True # If not bootstrapped yet, allow
            
        if subject:
            user = db.query(models.KnownUser).filter(models.KnownUser.subject == subject).first()
            if user and not user.is_active:
                raise HTTPException(status_code=403, detail="User account is disabled in the registry")
                
        # Check user bindings
        user_roles = []
        if subject:
            bindings = db.query(models.UserRoleBinding).filter(
                models.UserRoleBinding.app_profile_id == manager_app.id,
                models.UserRoleBinding.user_identifier == subject,
                models.UserRoleBinding.identifier_type == "sub"
            ).all()
            user_roles.extend([b.role for b in bindings])
            
        if email:
            bindings = db.query(models.UserRoleBinding).filter(
                models.UserRoleBinding.app_profile_id == manager_app.id,
                models.UserRoleBinding.user_identifier == email,
                models.UserRoleBinding.identifier_type == "email"
            ).all()
            user_roles.extend([b.role for b in bindings])
            
        # Check group bindings (placeholder if groups are in headers)
        groups_raw = request.headers.get("x-auth-request-groups", "")
        if groups_raw:
            groups = [g.strip() for g in groups_raw.split(",") if g.strip()]
            for g in groups:
                bindings = db.query(models.GroupRoleBinding).filter(
                    models.GroupRoleBinding.app_profile_id == manager_app.id,
                    models.GroupRoleBinding.group_name == g
                ).all()
                user_roles.extend([b.role for b in bindings])
                
        # Check if any role has the required permission
        for role in user_roles:
            for perm in role.permissions:
                if perm.name == permission_name:
                    return True
                    
        raise HTTPException(status_code=403, detail=f"Permission denied: {permission_name} required")
        
    return dependency

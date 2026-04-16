import yaml
from sqlalchemy.orm import Session
from ..models.authz import AppProfile, Role, Permission, role_permissions
from ..models.base import engine, Base

DEFAULT_SRA_POLICY = """
version: 1
roles:
  anonymous:
    capabilities:
      - terminal.open
      - sandbox.mode.cluster
      - sandbox.profile.transient
      - sandbox.execution_model.session
  authenticated:
    capabilities:
      - terminal.open
      - sandbox.mode.cluster
      - sandbox.profile.persistent_workspace
      - sandbox.profile.transient
      - sandbox.execution_model.session
      - sandbox.execution_model.ephemeral
      - sandbox.template.python-runtime-template-small
      - sandbox.template.python-runtime-template
      - sandbox.template.python-runtime-template-large
  terminal_user:
    capabilities:
      - terminal.open
  pydata_user:
    capabilities:
      - sandbox.template.python-runtime-template-pydata
  ops_admin:
    capabilities:
      - admin.ops.read
      - admin.ops.write
      - authz.policy.manage
feature_rules:
  terminal.open:
    any_capabilities:
      - terminal.open
  admin.ops.read:
    any_capabilities:
      - admin.ops.read
  admin.ops.write:
    any_capabilities:
      - admin.ops.write
  authz.policy.manage:
    any_capabilities:
      - authz.policy.manage
sandbox_rules:
  templates:
    python-runtime-template-pydata:
      any_capabilities:
        - sandbox.template.python-runtime-template-pydata
  modes:
    cluster: {}
    local:
      any_capabilities:
        - sandbox.mode.local
  profiles:
    persistent_workspace:
      any_capabilities:
        - sandbox.profile.persistent_workspace
    transient:
      any_capabilities:
        - sandbox.profile.transient
  execution_models:
    session:
      any_capabilities:
        - sandbox.execution_model.session
    ephemeral:
      any_capabilities:
        - sandbox.execution_model.ephemeral
"""

def bootstrap_sra_profile(db: Session):
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    existing = db.query(AppProfile).filter(AppProfile.slug == "sandboxed-react-agent").first()
    if existing:
        return
        
    data = yaml.safe_load(DEFAULT_SRA_POLICY)
    
    app = AppProfile(
        slug="sandboxed-react-agent",
        name="Sandboxed React Agent",
        description="Bootstrap profile for SRA",
        config_rules={
            "feature_rules": data.get("feature_rules", {}),
            "sandbox_rules": data.get("sandbox_rules", {})
        }
    )
    db.add(app)
    db.flush()
    
    # Add permissions and roles
    perms_map = {}
    for role_name, role_data in data.get("roles", {}).items():
        role = Role(name=role_name, app_profile_id=app.id)
        db.add(role)
        db.flush()
        
        for cap in role_data.get("capabilities", []):
            if cap not in perms_map:
                p = Permission(name=cap, app_profile_id=app.id)
                db.add(p)
                db.flush()
                perms_map[cap] = p
            role.permissions.append(perms_map[cap])
            
    db.commit()

def bootstrap_manager_profile(db: Session):
    existing = db.query(AppProfile).filter(AppProfile.slug == "cluster-authz-manager").first()
    if existing:
        return

    app = AppProfile(
        slug="cluster-authz-manager",
        name="Cluster Authz Manager",
        description="Self-management profile"
    )
    db.add(app)
    db.flush()

    admin_role = Role(name="admin", description="Manager Administrator", app_profile_id=app.id)
    db.add(admin_role)
    db.flush()

    admin_perm = Permission(name="cluster-auth-admin", description="Full access to authz manager", app_profile_id=app.id)
    db.add(admin_perm)
    db.flush()

    admin_role.permissions.append(admin_perm)
    
    from ..models.authz import UserRoleBinding
    binding = UserRoleBinding(
        app_profile_id=app.id,
        user_identifier="mylonas.charilaos@gmail.com",
        identifier_type="email",
        role_id=admin_role.id
    )
    db.add(binding)
    db.commit()

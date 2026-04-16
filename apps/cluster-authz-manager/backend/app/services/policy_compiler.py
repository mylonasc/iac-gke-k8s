import hashlib
import yaml
from sqlalchemy.orm import Session
from ..models.authz import AppProfile, Role, Permission, GroupRoleBinding, UserRoleBinding

class PolicyCompiler:
    @staticmethod
    def compile_to_sra_yaml(db: Session, app_slug: str) -> dict:
        app = db.query(AppProfile).filter(AppProfile.slug == app_slug).first()
        if not app:
            raise ValueError(f"App profile not found: {app_slug}")
            
        policy = {
            "version": 1,
            "default_roles": {
                "authenticated": ["authenticated"],
                "unauthenticated": ["anonymous"]
            },
            "role_mappings": {
                "groups": {},
                "user_ids": {},
                "emails": {}
            },
            "roles": {},
            "feature_rules": app.config_rules.get("feature_rules", {}),
            "sandbox_rules": app.config_rules.get("sandbox_rules", {})
        }
        
        # 1. Compile Roles and their Capabilities
        for role in app.roles:
            policy["roles"][role.name] = {
                "capabilities": [p.name for p in role.permissions]
            }
            
        # 2. Compile Group Mappings
        for binding in app.group_bindings:
            role_names = policy["role_mappings"]["groups"].setdefault(binding.group_name, [])
            if binding.role.name not in role_names:
                role_names.append(binding.role.name)
                
        # 3. Compile User Mappings
        for binding in app.user_bindings:
            mapping_key = "user_ids" if binding.identifier_type == "sub" else "emails"
            user_roles = policy["role_mappings"][mapping_key].setdefault(binding.user_identifier, [])
            if binding.role.name not in user_roles:
                user_roles.append(binding.role.name)
                
        yaml_text = yaml.dump(policy, sort_keys=False)
        sha256 = hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()
        
        return {
            "policy_yaml": yaml_text,
            "sha256": sha256,
            "version": app.updated_at.isoformat()
        }

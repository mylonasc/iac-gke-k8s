import yaml
from app.services.bootstrap import bootstrap_sra_profile
from app.services.policy_compiler import PolicyCompiler
from app.models.authz import AppProfile, Role, UserRoleBinding

def test_bootstrap_creates_sra_profile(db_session):
    bootstrap_sra_profile(db_session)
    
    app = db_session.query(AppProfile).filter(AppProfile.slug == "sandboxed-react-agent").first()
    assert app is not None
    assert app.name == "Sandboxed React Agent"
    
    # Check if roles were created
    roles = db_session.query(Role).filter(Role.app_profile_id == app.id).all()
    assert len(roles) > 0
    role_names = [r.name for r in roles]
    assert "ops_admin" in role_names
    assert "authenticated" in role_names

def test_policy_compiler_output(db_session):
    bootstrap_sra_profile(db_session)
    app = db_session.query(AppProfile).filter(AppProfile.slug == "sandboxed-react-agent").first()
    
    # Add a user binding
    role = db_session.query(Role).filter(Role.name == "ops_admin").first()
    binding = UserRoleBinding(
        app_profile_id=app.id,
        user_identifier="test-user@example.com",
        identifier_type="email",
        role_id=role.id
    )
    db_session.add(binding)
    db_session.commit()
    
    result = PolicyCompiler.compile_to_sra_yaml(db_session, "sandboxed-react-agent")
    
    assert "policy_yaml" in result
    assert "sha256" in result
    
    parsed = yaml.safe_load(result["policy_yaml"])
    assert parsed["version"] == 1
    assert "test-user@example.com" in parsed["role_mappings"]["emails"]
    assert "ops_admin" in parsed["role_mappings"]["emails"]["test-user@example.com"]
    assert "ops_admin" in parsed["roles"]
    assert "admin.ops.read" in parsed["roles"]["ops_admin"]["capabilities"]

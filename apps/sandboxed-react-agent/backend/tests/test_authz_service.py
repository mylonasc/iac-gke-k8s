from pathlib import Path

from app.authz.service import AuthorizationPolicyService


def test_authz_service_builds_context_from_groups(tmp_path: Path) -> None:
    service = AuthorizationPolicyService(
        policy_path=str(tmp_path / "policy.yaml"),
    )
    context = service.build_access_context(
        user_id="user-1",
        claims={"sub": "user-1", "groups": ["sra-terminal"]},
        authenticated=True,
    )
    assert "authenticated" in context.roles
    assert "terminal_user" in context.roles
    assert "terminal.open" in context.capabilities


def test_authz_service_filters_pydata_template_without_role(tmp_path: Path) -> None:
    service = AuthorizationPolicyService(
        policy_path=str(tmp_path / "policy.yaml"),
    )
    context = service.build_access_context(
        user_id="user-1",
        claims={"sub": "user-1", "groups": []},
        authenticated=True,
    )
    filtered = service.filter_sandbox_values(
        context,
        category="templates",
        values=[
            "python-runtime-template-small",
            "python-runtime-template-pydata",
        ],
    )
    assert "python-runtime-template-small" in filtered
    assert "python-runtime-template-pydata" not in filtered

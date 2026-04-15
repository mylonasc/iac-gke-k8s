from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from onboarding_client.database import Base, get_db
from onboarding_client.deps import get_email_sender, get_runtime_principal
from onboarding_client.integrations.resend_client import SentEmail
from onboarding_client.main import app
from onboarding_client.models import (
    AuditLog,
    DeliveryAttempt,
    Invitation,
    Profile,
    VerificationToken,
)
from onboarding_client.schemas import RuntimePrincipal


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_invitation(
        self, *, recipient: str, confirmation_url: str, invitation_id: int
    ) -> SentEmail:
        self.sent.append(
            {
                "recipient": recipient,
                "confirmation_url": confirmation_url,
                "invitation_id": invitation_id,
            }
        )
        return SentEmail(message_id=f"msg-{invitation_id}")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def fake_email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def client(session_factory, fake_email_sender) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_email_sender] = lambda: fake_email_sender
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_role(client: TestClient, slug: str) -> None:
    response = client.post(
        "/api/admin/roles",
        json={"slug": slug, "display_name": slug.replace("-", " ").title()},
    )
    assert response.status_code == 201, response.text


def test_create_role_and_list_roles(client: TestClient) -> None:
    _create_role(client, "cluster-reader")
    _create_role(client, "support-operator")

    response = client.get("/api/admin/roles")
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 1,
            "slug": "cluster-reader",
            "display_name": "Cluster Reader",
            "description": None,
            "created_at": response.json()[0]["created_at"],
        },
        {
            "id": 2,
            "slug": "support-operator",
            "display_name": "Support Operator",
            "description": None,
            "created_at": response.json()[1]["created_at"],
        },
    ]


def test_invitation_confirmation_profile_submission_and_approval(
    client: TestClient,
    fake_email_sender: FakeEmailSender,
    session_factory,
) -> None:
    _create_role(client, "cluster-reader")
    _create_role(client, "support-operator")

    invite_response = client.post(
        "/api/admin/invitations",
        json={
            "email": "new.user@example.com",
            "requested_by": "admin@example.com",
            "role_slugs": ["cluster-reader", "support-operator"],
            "ttl_seconds": 3600,
        },
    )
    assert invite_response.status_code == 201, invite_response.text
    invite_payload = invite_response.json()
    assert invite_payload["status"] == "sent"
    assert sorted(invite_payload["role_slugs"]) == [
        "cluster-reader",
        "support-operator",
    ]
    assert invite_payload["confirmation_url"].startswith("/confirm/")
    assert fake_email_sender.sent[0]["recipient"] == "new.user@example.com"
    token = invite_payload["confirmation_url"].split("/confirm/", 1)[1]

    confirm_response = client.get(invite_payload["confirmation_url"])
    assert confirm_response.status_code == 200
    assert (
        "Invitation for <strong>new.user@example.com</strong>" in confirm_response.text
    )

    submit_response = client.post(
        f"/profile/{token}",
        data={
            "full_name": "New User",
            "username": "nuser",
            "organization": "Acme",
            "team": "Platform",
            "justification": "Needs cluster access",
        },
    )
    assert submit_response.status_code == 200
    assert "pending admin approval" in submit_response.text

    profiles_response = client.get("/api/admin/profiles")
    assert profiles_response.status_code == 200
    profiles = profiles_response.json()
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile["email"] == "new.user@example.com"
    assert profile["status"] == "submitted"
    assert profile["role_slugs"] == []

    approve_response = client.post(
        f"/api/admin/profiles/{profile['id']}/approve",
        json={"role_slugs": ["support-operator"]},
    )
    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["status"] == "approved"
    assert approved["role_slugs"] == ["support-operator"]

    with session_factory() as db:
        invitation = db.query(Invitation).first()
        assert invitation is not None
        assert invitation.status.value == "submitted"
        token_record = db.query(VerificationToken).first()
        assert token_record is not None
        assert token_record.token_hash != token
        assert token_record.consumed_at is not None
        delivery = db.query(DeliveryAttempt).first()
        assert delivery is not None
        assert delivery.provider_message_id == "msg-1"
        audit_entries = db.query(AuditLog).all()
        assert len(audit_entries) >= 3


def test_runtime_roles_bind_subject_and_return_approved_roles(
    client: TestClient,
    fake_email_sender: FakeEmailSender,
) -> None:
    _create_role(client, "cluster-reader")
    invite_response = client.post(
        "/api/admin/invitations",
        json={
            "email": "approved@example.com",
            "requested_by": "admin@example.com",
            "role_slugs": ["cluster-reader"],
            "ttl_seconds": 3600,
        },
    )
    token = invite_response.json()["confirmation_url"].split("/confirm/", 1)[1]
    client.get(f"/confirm/{token}")
    client.post(
        f"/profile/{token}",
        data={"full_name": "Approved User", "username": "approved"},
    )
    profiles_response = client.get("/api/admin/profiles")
    profile_id = profiles_response.json()[0]["id"]
    client.post(
        f"/api/admin/profiles/{profile_id}/approve",
        json={"role_slugs": ["cluster-reader"]},
    )

    app.dependency_overrides[get_runtime_principal] = lambda: RuntimePrincipal(
        subject="dex-subject-1",
        email="approved@example.com",
        username="approved",
    )
    try:
        me_response = client.get("/api/runtime/me")
        assert me_response.status_code == 200
        assert me_response.json()["profile_status"] == "approved"

        roles_response = client.get("/api/runtime/me/roles")
        assert roles_response.status_code == 200
        assert roles_response.json() == {
            "subject": "dex-subject-1",
            "email": "approved@example.com",
            "roles": ["cluster-reader"],
        }
    finally:
        app.dependency_overrides.pop(get_runtime_principal, None)


def test_runtime_roles_empty_for_unapproved_profile(
    client: TestClient,
) -> None:
    _create_role(client, "cluster-reader")
    invite_response = client.post(
        "/api/admin/invitations",
        json={
            "email": "pending@example.com",
            "requested_by": "admin@example.com",
            "role_slugs": ["cluster-reader"],
            "ttl_seconds": 3600,
        },
    )
    token = invite_response.json()["confirmation_url"].split("/confirm/", 1)[1]
    client.get(f"/confirm/{token}")
    client.post(
        f"/profile/{token}",
        data={"full_name": "Pending User", "username": "pending"},
    )

    app.dependency_overrides[get_runtime_principal] = lambda: RuntimePrincipal(
        subject="dex-subject-2",
        email="pending@example.com",
        username="pending",
    )
    try:
        response = client.get("/api/runtime/me/roles")
        assert response.status_code == 200
        assert response.json()["roles"] == []
    finally:
        app.dependency_overrides.pop(get_runtime_principal, None)


def test_invalid_token_is_rejected(client: TestClient) -> None:
    response = client.get("/confirm/not-a-real-token")
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid token"


def test_token_cannot_be_reused_after_profile_submission(client: TestClient) -> None:
    _create_role(client, "cluster-reader")
    invite_response = client.post(
        "/api/admin/invitations",
        json={
            "email": "reuse@example.com",
            "requested_by": "admin@example.com",
            "role_slugs": ["cluster-reader"],
            "ttl_seconds": 3600,
        },
    )
    token = invite_response.json()["confirmation_url"].split("/confirm/", 1)[1]
    client.get(f"/confirm/{token}")
    submit_response = client.post(
        f"/profile/{token}",
        data={"full_name": "Reuse User", "username": "reuse"},
    )
    assert submit_response.status_code == 200

    reuse_response = client.get(f"/profile/{token}")
    assert reuse_response.status_code == 400
    assert reuse_response.json()["detail"] == "Token already consumed"


def test_unknown_role_on_invitation_returns_error(client: TestClient) -> None:
    response = client.post(
        "/api/admin/invitations",
        json={
            "email": "bad-role@example.com",
            "requested_by": "admin@example.com",
            "role_slugs": ["missing-role"],
            "ttl_seconds": 3600,
        },
    )
    assert response.status_code == 400
    assert "Unknown role" in response.json()["detail"]


def test_duplicate_role_creation_conflicts(client: TestClient) -> None:
    _create_role(client, "cluster-reader")
    response = client.post(
        "/api/admin/roles",
        json={"slug": "cluster-reader", "display_name": "Cluster Reader"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Role already exists"


def test_list_invitations_returns_requested_roles(client: TestClient) -> None:
    _create_role(client, "cluster-reader")
    invite_response = client.post(
        "/api/admin/invitations",
        json={
            "email": "list@example.com",
            "requested_by": "admin@example.com",
            "role_slugs": ["cluster-reader"],
            "ttl_seconds": 3600,
        },
    )
    assert invite_response.status_code == 201

    response = client.get("/api/admin/invitations")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["email"] == "list@example.com"
    assert payload[0]["role_slugs"] == ["cluster-reader"]


def test_runtime_me_handles_principal_without_matching_profile(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_runtime_principal] = lambda: RuntimePrincipal(
        subject="orphan-subject",
        email="orphan@example.com",
        username="orphan",
    )
    try:
        response = client.get("/api/runtime/me")
        assert response.status_code == 200
        assert response.json() == {
            "subject": "orphan-subject",
            "email": "orphan@example.com",
            "username": "orphan",
            "profile_status": None,
        }
    finally:
        app.dependency_overrides.pop(get_runtime_principal, None)

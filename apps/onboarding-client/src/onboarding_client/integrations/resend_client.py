from dataclasses import dataclass
from typing import Protocol

from onboarding_client.config import get_settings


@dataclass(slots=True)
class SentEmail:
    message_id: str | None


class EmailSender(Protocol):
    def send_invitation(
        self, *, recipient: str, confirmation_url: str, invitation_id: int
    ) -> SentEmail: ...


class ResendEmailSender:
    def send_invitation(
        self, *, recipient: str, confirmation_url: str, invitation_id: int
    ) -> SentEmail:
        settings = get_settings()
        if not settings.resend_api_key:
            raise RuntimeError("RESEND_API_KEY is not configured")
        if not settings.resend_from_email:
            raise RuntimeError("RESEND_FROM_EMAIL is not configured")

        import resend

        resend.api_key = settings.resend_api_key
        payload: resend.Emails.SendParams = {
            "from": settings.resend_from_email,
            "to": [recipient],
            "subject": "Complete your onboarding",
            "html": (
                "<p>Your onboarding link is ready.</p>"
                f'<p><a href="{confirmation_url}">Confirm your email and continue</a></p>'
            ),
            "text": f"Complete onboarding: {confirmation_url}",
            "tags": [
                {"name": "flow", "value": "onboarding"},
                {"name": "invitation_id", "value": str(invitation_id)},
            ],
            "headers": {"Idempotency-Key": f"invitation-{invitation_id}"},
        }
        if settings.resend_reply_to:
            payload["reply_to"] = settings.resend_reply_to

        response = resend.Emails.send(payload)
        message_id = None
        if isinstance(response, dict):
            message_id = response.get("id")
        else:  # pragma: no cover
            message_id = getattr(response, "id", None)
        return SentEmail(message_id=message_id)

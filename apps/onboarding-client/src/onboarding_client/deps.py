from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from onboarding_client.database import get_db
from onboarding_client.dex import get_dex_verifier
from onboarding_client.integrations.resend_client import EmailSender, ResendEmailSender
from onboarding_client.schemas import RuntimePrincipal


def get_email_sender() -> EmailSender:
    return ResendEmailSender()


def get_runtime_principal(
    authorization: Annotated[str | None, Header()] = None,
) -> RuntimePrincipal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    token = authorization.split(" ", 1)[1].strip()
    verifier = get_dex_verifier()
    return verifier.verify_token(token)


DbSession = Annotated[Session, Depends(get_db)]
CurrentPrincipal = Annotated[RuntimePrincipal, Depends(get_runtime_principal)]
EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]

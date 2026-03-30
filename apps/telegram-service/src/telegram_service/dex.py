from functools import lru_cache

import jwt
from fastapi import HTTPException, status

from telegram_service.config import get_settings
from telegram_service.schemas import RuntimePrincipal


class DexVerifier:
    def __init__(
        self,
        jwks_url: str,
        audience: str | None,
        issuers: list[str],
        email_allowlist: set[str],
        required_group: str | None,
    ) -> None:
        self.jwks_client = jwt.PyJWKClient(jwks_url)
        self.audience = audience
        self.issuers = issuers
        self.email_allowlist = email_allowlist
        self.required_group = required_group

    def verify_token(self, token: str) -> RuntimePrincipal:
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience=self.audience or None,
                options={"verify_aud": bool(self.audience)},
            )
        except Exception as exc:  # pragma: no cover - error details vary by provider
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
            ) from exc

        issuer = payload.get("iss")
        if self.issuers and issuer not in self.issuers:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token issuer not allowed",
            )

        subject = payload.get("sub")
        if not subject:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token subject missing"
            )

        email = str(payload.get("email") or "").strip().lower()
        if self.email_allowlist and email not in self.email_allowlist:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email is not allowed",
            )

        if self.required_group:
            groups_claim = payload.get("groups")
            groups: set[str] = set()
            if isinstance(groups_claim, list):
                groups = {
                    str(item).strip() for item in groups_claim if str(item).strip()
                }
            elif isinstance(groups_claim, str):
                groups = {
                    item.strip() for item in groups_claim.split(",") if item.strip()
                }

            if self.required_group not in groups:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Required group '{self.required_group}' is missing",
                )

        return RuntimePrincipal(
            subject=subject,
            username=payload.get("preferred_username"),
            email=payload.get("email"),
        )


@lru_cache(maxsize=1)
def get_dex_verifier() -> DexVerifier:
    settings = get_settings()
    if not settings.dex_jwks_url:
        raise RuntimeError("DEX_JWKS_URL is required for runtime JWT validation")

    issuers = [item.strip() for item in settings.dex_issuers.split(",") if item.strip()]
    email_allowlist = {
        item.strip().lower()
        for item in settings.dex_email_allowlist.split(",")
        if item.strip()
    }
    required_group = settings.dex_required_group.strip() or None
    return DexVerifier(
        settings.dex_jwks_url,
        settings.dex_audience or None,
        issuers,
        email_allowlist,
        required_group,
    )

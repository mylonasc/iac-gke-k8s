from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import HTTPException, Request


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class AuthConfig:
    enabled: bool
    issuer: str
    audience: str | None
    jwks_url: str
    user_id_claim: str
    algorithms: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "AuthConfig":
        enabled = _as_bool(os.getenv("AUTH_ENABLED"), default=False)
        issuer = (os.getenv("AUTH_ISSUER") or "").strip()
        audience = (os.getenv("AUTH_AUDIENCE") or "").strip() or None
        jwks_url = (os.getenv("AUTH_JWKS_URL") or "").strip()
        if not jwks_url:
            jwks_url = (os.getenv("DEX_JWKS_URL") or "").strip()
        if not jwks_url and issuer:
            jwks_url = issuer.rstrip("/") + "/jwks"
        algorithms_raw = (os.getenv("AUTH_ALGORITHMS") or "RS256").strip()
        algorithms = tuple(
            item.strip() for item in algorithms_raw.split(",") if item.strip()
        ) or ("RS256",)
        return cls(
            enabled=enabled,
            issuer=issuer,
            audience=audience,
            jwks_url=jwks_url,
            user_id_claim=(os.getenv("AUTH_USER_ID_CLAIM") or "sub").strip() or "sub",
            algorithms=algorithms,
        )


class TokenVerifier:
    def __init__(self, config: AuthConfig) -> None:
        self.config = config
        self._jwk_client = jwt.PyJWKClient(config.jwks_url) if config.jwks_url else None

    def verify(self, token: str) -> dict[str, Any]:
        if not self._jwk_client:
            raise HTTPException(status_code=500, detail="JWT verifier is not configured")
        signing_key = self._jwk_client.get_signing_key_from_jwt(token)
        options = {"verify_aud": self.config.audience is not None}
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=list(self.config.algorithms),
            issuer=self.config.issuer or None,
            audience=self.config.audience,
            options=options,
        )
        return claims


def extract_bearer_token(request: Request) -> str | None:
    header = (request.headers.get("authorization") or "").strip()
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        return token or None
    forwarded = (request.headers.get("x-auth-request-access-token") or "").strip()
    return forwarded or None


def _claims_groups(claims: dict[str, Any]) -> list[str]:
    raw = claims.get("groups")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        return [item.strip() for item in raw.split(",") if item.strip()]
    return []


def _state_identity_from_headers(request: Request) -> bool:
    subject = (request.headers.get("x-auth-request-user") or "").strip()
    email = (request.headers.get("x-auth-request-email") or "").strip().lower()
    groups_raw = (request.headers.get("x-auth-request-groups") or "").strip()
    groups = [item.strip() for item in groups_raw.split(",") if item.strip()]
    if not subject and not email:
        return False
    request.state.auth_subject = subject or (f"email:{email}" if email else "")
    request.state.auth_email = email
    request.state.auth_groups = groups
    request.state.auth_claims = {
        "sub": request.state.auth_subject,
        "email": email,
        "groups": groups,
    }
    return True


async def authenticate_request(
    request: Request,
    *,
    config: AuthConfig,
    verifier: TokenVerifier,
) -> dict[str, Any] | None:
    if not config.enabled:
        _state_identity_from_headers(request)
        return None

    token = extract_bearer_token(request)
    if token:
        try:
            claims = verifier.verify(token)
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid token") from exc
        subject = str(
            claims.get(config.user_id_claim)
            or claims.get("sub")
            or claims.get("email")
            or ""
        ).strip()
        if not subject:
            raise HTTPException(status_code=401, detail="Missing token subject")
        request.state.auth_subject = subject
        request.state.auth_email = str(claims.get("email") or "").strip().lower()
        request.state.auth_groups = _claims_groups(claims)
        request.state.auth_claims = claims
        return claims

    if _state_identity_from_headers(request):
        return None

    return None

import logging
import os
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import HTTPException, Request


logger = logging.getLogger(__name__)


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
    algorithms: tuple[str, ...]
    exempt_prefixes: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "AuthConfig":
        enabled = _as_bool(os.getenv("AUTH_ENABLED"), default=False)
        issuer = (os.getenv("AUTH_ISSUER") or "").strip()
        audience = (os.getenv("AUTH_AUDIENCE") or "").strip() or None
        jwks_url = (os.getenv("AUTH_JWKS_URL") or "").strip()
        if not jwks_url and issuer:
            jwks_url = issuer.rstrip("/") + "/.well-known/jwks.json"

        algorithms_raw = (os.getenv("AUTH_ALGORITHMS") or "RS256").strip()
        algorithms = tuple(
            item.strip() for item in algorithms_raw.split(",") if item.strip()
        ) or ("RS256",)

        exempt_raw = (
            os.getenv("AUTH_EXEMPT_PATH_PREFIXES") or "/api/health,/api/public/"
        ).strip()
        exempt_prefixes = tuple(
            item.strip() for item in exempt_raw.split(",") if item.strip()
        )

        config = cls(
            enabled=enabled,
            issuer=issuer,
            audience=audience,
            jwks_url=jwks_url,
            algorithms=algorithms,
            exempt_prefixes=exempt_prefixes,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.enabled:
            return
        if not self.issuer:
            raise RuntimeError("AUTH_ISSUER must be set when AUTH_ENABLED=1")
        if not self.jwks_url:
            raise RuntimeError("AUTH_JWKS_URL must be set when AUTH_ENABLED=1")


class TokenVerifier:
    def __init__(self, config: AuthConfig) -> None:
        self.config = config
        self._jwk_client = jwt.PyJWKClient(config.jwks_url) if config.enabled else None

    def verify(self, token: str) -> dict[str, Any]:
        if not self.config.enabled:
            return {}
        assert self._jwk_client is not None
        signing_key = self._jwk_client.get_signing_key_from_jwt(token)
        options = {"verify_aud": self.config.audience is not None}
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=list(self.config.algorithms),
            issuer=self.config.issuer,
            audience=self.config.audience,
            options=options,
        )
        return claims


def extract_bearer_token(request: Request) -> str:
    header = (request.headers.get("authorization") or "").strip()
    if not header:
        forwarded = (request.headers.get("x-auth-request-access-token") or "").strip()
        if forwarded:
            return forwarded
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    prefix = "bearer "
    if not header.lower().startswith(prefix):
        raise HTTPException(status_code=401, detail="Expected Bearer token")
    token = header[len(prefix) :].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty Bearer token")
    return token


def should_skip_auth(path: str, config: AuthConfig) -> bool:
    if not path.startswith("/api/"):
        return True
    return any(path.startswith(prefix) for prefix in config.exempt_prefixes)


async def authenticate_request(
    request: Request,
    *,
    config: AuthConfig,
    verifier: TokenVerifier,
) -> dict[str, Any] | None:
    if not config.enabled or should_skip_auth(request.url.path, config):
        return None
    token = extract_bearer_token(request)
    try:
        claims = verifier.verify(token)
    except jwt.PyJWTError as exc:
        logger.warning(
            "auth.token_invalid",
            extra={
                "event": "auth.token_invalid",
                "path": request.url.path,
                "error": str(exc),
            },
        )
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    request.state.auth_claims = claims
    request.state.auth_subject = str(
        claims.get("sub")
        or claims.get("email")
        or claims.get("preferred_username")
        or ""
    )
    return claims

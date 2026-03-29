import logging
import hmac
import os
import secrets
import uuid
from hashlib import sha256
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
    user_id_claim: str

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
            user_id_claim=(os.getenv("AUTH_USER_ID_CLAIM") or "sub").strip() or "sub",
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


@dataclass
class AnonymousIdentityConfig:
    enabled: bool
    cookie_name: str
    secret: str
    secure_cookie: bool
    same_site: str

    @classmethod
    def from_env(cls) -> "AnonymousIdentityConfig":
        enabled_default = not _as_bool(os.getenv("AUTH_ENABLED"), default=False)
        enabled = _as_bool(os.getenv("ANON_IDENTITY_ENABLED"), default=enabled_default)
        same_site = (
            (os.getenv("ANON_IDENTITY_COOKIE_SAMESITE") or "lax").strip().lower()
        )
        if same_site not in {"lax", "strict", "none"}:
            same_site = "lax"

        raw_secret = (os.getenv("ANON_IDENTITY_SECRET") or "").strip()
        if enabled and not raw_secret:
            raw_secret = secrets.token_urlsafe(32)
            logger.warning(
                "auth.anon_identity_ephemeral_secret",
                extra={"event": "auth.anon_identity_ephemeral_secret"},
            )

        return cls(
            enabled=enabled,
            cookie_name=(
                os.getenv("ANON_IDENTITY_COOKIE_NAME") or "sra_anon_uid"
            ).strip(),
            secret=raw_secret,
            secure_cookie=_as_bool(
                os.getenv("ANON_IDENTITY_COOKIE_SECURE"), default=False
            ),
            same_site=same_site,
        )


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
    user_id = str(claims.get(config.user_id_claim) or "").strip()
    if not user_id:
        user_id = str(
            claims.get("sub")
            or claims.get("email")
            or claims.get("preferred_username")
            or ""
        ).strip()
    request.state.auth_user_id = user_id
    request.state.auth_subject = user_id
    return claims


def _sign_user_id(user_id: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), user_id.encode("utf-8"), sha256
    ).hexdigest()
    return digest


def encode_signed_user_id(user_id: str, secret: str) -> str:
    return f"{user_id}.{_sign_user_id(user_id, secret)}"


def decode_signed_user_id(token: str, secret: str) -> str | None:
    if not token or "." not in token:
        return None
    user_id, signature = token.rsplit(".", 1)
    if not user_id or not signature:
        return None
    expected = _sign_user_id(user_id, secret)
    if not hmac.compare_digest(signature, expected):
        return None
    return user_id


def ensure_anonymous_user_id(
    request: Request,
    *,
    config: AnonymousIdentityConfig,
) -> tuple[str, str | None]:
    if not config.enabled:
        return "", None

    cookie_value = (request.cookies.get(config.cookie_name) or "").strip()
    user_id = (
        decode_signed_user_id(cookie_value, config.secret) if cookie_value else None
    )
    if user_id:
        return user_id, None

    generated_user_id = f"anon-{uuid.uuid4().hex}"
    signed_value = encode_signed_user_id(generated_user_id, config.secret)
    return generated_user_id, signed_value

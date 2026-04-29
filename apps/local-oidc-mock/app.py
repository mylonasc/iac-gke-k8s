from __future__ import annotations

import base64
import os
import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


ISSUER = str(os.getenv("OIDC_ISSUER") or "http://local-oidc:9000").strip()
DEFAULT_AUDIENCE = str(os.getenv("OIDC_DEFAULT_AUDIENCE") or "local-dev").strip()
TOKEN_TTL_SECONDS = max(60, int(os.getenv("OIDC_TOKEN_TTL_SECONDS") or "3600"))
SIGNING_KID = str(os.getenv("OIDC_SIGNING_KID") or "local-dev-rs256").strip()

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = PRIVATE_KEY.public_key()
PUBLIC_NUMBERS = PUBLIC_KEY.public_numbers()

JWK = {
    "kty": "RSA",
    "alg": "RS256",
    "use": "sig",
    "kid": SIGNING_KID,
    "n": _b64url_uint(PUBLIC_NUMBERS.n),
    "e": _b64url_uint(PUBLIC_NUMBERS.e),
}


class TokenRequest(BaseModel):
    subject: str = Field(default="local-dev-user", min_length=1)
    email: str = Field(default="local-dev@example.com", min_length=3)
    groups: list[str] = Field(default_factory=list)
    audience: str | None = None
    expires_in: int | None = None
    extra_claims: dict[str, Any] = Field(default_factory=dict)


app = FastAPI(title="local-oidc-mock", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/.well-known/openid-configuration")
def openid_configuration() -> dict[str, Any]:
    return {
        "issuer": ISSUER,
        "jwks_uri": f"{ISSUER}/jwks",
        "token_endpoint": f"{ISSUER}/token",
        "id_token_signing_alg_values_supported": ["RS256"],
        "subject_types_supported": ["public"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


@app.get("/jwks")
def jwks() -> dict[str, list[dict[str, str]]]:
    return {"keys": [JWK]}


@app.post("/token")
def mint_token(payload: TokenRequest) -> dict[str, Any]:
    subject = str(payload.subject or "").strip()
    email = str(payload.email or "").strip().lower()
    if not subject:
        raise HTTPException(status_code=400, detail="subject is required")
    if not email:
        raise HTTPException(status_code=400, detail="email is required")

    now = int(time.time())
    requested_expires = int(payload.expires_in or TOKEN_TTL_SECONDS)
    expires_in = max(60, min(requested_expires, 60 * 60 * 24 * 7))
    audience = str(payload.audience or DEFAULT_AUDIENCE).strip() or DEFAULT_AUDIENCE

    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": subject,
        "aud": audience,
        "iat": now,
        "nbf": now,
        "exp": now + expires_in,
        "jti": uuid.uuid4().hex,
        "email": email,
        "groups": [str(group).strip() for group in payload.groups if str(group).strip()],
    }
    for key, value in (payload.extra_claims or {}).items():
        if str(key).strip():
            claims[str(key)] = value

    token = jwt.encode(
        claims,
        PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": SIGNING_KID},
    )
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "issuer": ISSUER,
        "audience": audience,
    }

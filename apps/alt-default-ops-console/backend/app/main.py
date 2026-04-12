from __future__ import annotations

import asyncio
import os
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from kubernetes import client, config
from kubernetes.client import ApiException
from pydantic import BaseModel, Field


class Settings(BaseModel):
    target_namespace: str = Field(
        default_factory=lambda: os.getenv("TARGET_NAMESPACE", "alt-default")
    )
    managed_deployments: set[str] = Field(
        default_factory=lambda: {
            x.strip()
            for x in os.getenv(
                "MANAGED_DEPLOYMENTS",
                "sandboxed-react-agent-backend,sandboxed-react-agent-frontend,sandbox-router-deployment",
            ).split(",")
            if x.strip()
        }
    )
    jwt_jwks_url: str = Field(
        default_factory=lambda: os.getenv(
            "JWT_JWKS_URL", "https://www.googleapis.com/oauth2/v3/certs"
        )
    )
    jwt_issuers: set[str] = Field(
        default_factory=lambda: {
            x.strip()
            for x in os.getenv(
                "JWT_ISSUERS",
                "https://accounts.google.com,accounts.google.com",
            ).split(",")
            if x.strip()
        }
    )
    jwt_audience: str = Field(default_factory=lambda: os.getenv("JWT_AUDIENCE", ""))
    jwt_email_allowlist: set[str] = Field(
        default_factory=lambda: {
            x.strip().lower()
            for x in os.getenv("JWT_EMAIL_ALLOWLIST", "").split(",")
            if x.strip()
        }
    )
    jwt_required_group: str = Field(
        default_factory=lambda: os.getenv("JWT_REQUIRED_GROUP", "").strip()
    )
    mock_cluster: bool = Field(
        default_factory=lambda: (
            os.getenv("MOCK_CLUSTER", "0").strip().lower() in {"1", "true", "yes", "on"}
        )
    )
    oauth_client_id: str = Field(
        default_factory=lambda: os.getenv("OAUTH_CLIENT_ID", "").strip()
    )
    oauth_client_secret: str = Field(
        default_factory=lambda: os.getenv("OAUTH_CLIENT_SECRET", "").strip()
    )
    oauth_redirect_uri: str = Field(
        default_factory=lambda: os.getenv(
            "OAUTH_REDIRECT_URI", "http://localhost/auth2/callback"
        ).strip()
    )
    oauth_scopes: str = Field(
        default_factory=lambda: os.getenv(
            "OAUTH_SCOPES", "openid email profile"
        ).strip()
    )
    cookie_secure: bool = Field(
        default_factory=lambda: (
            os.getenv("COOKIE_SECURE", "0").strip().lower()
            in {"1", "true", "yes", "on"}
        )
    )
    app_base_path: str = Field(
        default_factory=lambda: os.getenv("APP_BASE_PATH", "").strip()
    )
    sra_admin_api_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "SRA_ADMIN_API_BASE_URL",
            "http://sandboxed-react-agent-backend.alt-default.svc.cluster.local",
        ).strip()
    )
    sra_admin_api_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("SRA_ADMIN_API_TIMEOUT_SECONDS", "4"))
    )
    sra_admin_enabled: bool = Field(
        default_factory=lambda: (
            os.getenv("SRA_ADMIN_ENABLED", "1").strip().lower()
            in {"1", "true", "yes", "on"}
        )
    )
    sra_admin_analytics_days: int = Field(
        default_factory=lambda: int(os.getenv("SRA_ADMIN_ANALYTICS_DAYS", "14"))
    )
    sra_admin_recent_limit: int = Field(
        default_factory=lambda: int(os.getenv("SRA_ADMIN_RECENT_LIMIT", "200"))
    )


@dataclass(frozen=True)
class JwtVerifier:
    jwks_url: str
    issuers: frozenset[str]
    audience: str


class ScaleRequest(BaseModel):
    replicas: int = Field(ge=0, le=20)


class CreateClaimRequest(BaseModel):
    template_name: str = Field(default="python-runtime-template", min_length=1)
    claim_name: str | None = None


class WarmPoolUpsertRequest(BaseModel):
    warm_pool_name: str = Field(default="python-sandbox-warmpool", min_length=1)
    template_name: str = Field(default="python-runtime-template", min_length=1)
    replicas: int = Field(default=1, ge=0, le=5)


class WarmPoolScaleRequest(BaseModel):
    replicas: int = Field(ge=0, le=5)


settings = Settings()


# Price references (USD) for europe-west4 (Netherlands), sourced from
# Google Cloud pricing pages and Cloud Billing SKU catalog.
# - E2 core on-demand: 0.02401338 / vCPU-hour
# - E2 RAM on-demand: 0.00321816 / GiB-hour
# - E2 core spot: 0.0095 / vCPU-hour
# - E2 RAM spot: 0.001272 / GiB-hour
# - GKE cluster management fee: 0.10 / cluster-hour
# - PD Standard: 0.044 / GiB-month
# - PD Balanced: 0.11 / GiB-month
_E2_CORE_ONDEMAND_USD_PER_HOUR = 0.02401338
_E2_RAM_ONDEMAND_USD_PER_GIB_HOUR = 0.00321816
_E2_CORE_SPOT_USD_PER_HOUR = 0.0095
_E2_RAM_SPOT_USD_PER_GIB_HOUR = 0.001272
_GKE_CLUSTER_FEE_USD_PER_HOUR = 0.10
_MONTH_HOURS = 730.0
_PVC_USD_PER_GIB_MONTH_BY_CLASS = {
    "standard": 0.044,
    "standard-rwo": 0.044,
    "balanced": 0.11,
    "balanced-rwo": 0.11,
}


def _normalize_base_path(path: str) -> str:
    value = path.strip()
    if not value or value == "/":
        return ""
    if not value.startswith("/"):
        value = f"/{value}"
    return value.rstrip("/")


def _external_path(path: str) -> str:
    normalized = _normalize_base_path(settings.app_base_path)
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{normalized}{suffix}" if normalized else suffix


def _to_utc_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: Any) -> str | None:
    parsed = _to_utc_datetime(value)
    if parsed is None:
        return None
    return parsed.isoformat()


def _age_seconds(created: Any, *, now: datetime) -> int | None:
    created_dt = _to_utc_datetime(created)
    if created_dt is None:
        return None
    diff = int((now - created_dt).total_seconds())
    if diff < 0:
        return 0
    return diff


def _conditions_summary(conditions: Any) -> list[dict[str, Any]]:
    if not isinstance(conditions, list):
        return []
    summary: list[dict[str, Any]] = []
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        summary.append(
            {
                "type": str(condition.get("type") or ""),
                "status": str(condition.get("status") or ""),
                "reason": str(condition.get("reason") or ""),
                "message": str(condition.get("message") or ""),
                "last_transition_time": _iso(condition.get("lastTransitionTime")),
            }
        )
    return summary


def _is_ready_from_conditions(conditions: list[dict[str, Any]]) -> bool | None:
    for condition in conditions:
        if str(condition.get("type") or "") == "Ready":
            return str(condition.get("status") or "").lower() == "true"
    return None


use_mock_cluster = settings.mock_cluster
core_api: client.CoreV1Api | None = None
apps_api: client.AppsV1Api | None = None
custom_api: client.CustomObjectsApi | None = None

if not use_mock_cluster:
    try:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        core_api = client.CoreV1Api()
        apps_api = client.AppsV1Api()
        custom_api = client.CustomObjectsApi()
    except Exception:
        use_mock_cluster = True

mock_state: dict[str, Any] = {
    "deployments": {
        name: {"desired": 1, "ready": 1, "available": 1, "updated": 1}
        for name in sorted(settings.managed_deployments)
    },
    "claims": [],
    "sandboxes": [],
    "warm_pools": {
        "python-sandbox-warmpool": {
            "replicas": 2,
            "template": "python-runtime-template",
        }
    },
}

app = FastAPI(title="alt-default-ops-console", version="0.1.0")
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)


class JwksCache:
    def __init__(self) -> None:
        self._keys_by_url: dict[str, dict[str, dict[str, Any]]] = {}
        self._last_fetch_by_url: dict[str, float] = {}
        self._ttl_seconds = 900

    async def get_keys(
        self, jwks_url: str, force_refresh: bool = False
    ) -> dict[str, dict[str, Any]]:
        now = time.time()
        cached_keys = self._keys_by_url.get(jwks_url, {})
        last_fetch = self._last_fetch_by_url.get(jwks_url, 0.0)
        if not force_refresh and cached_keys and (now - last_fetch) < self._ttl_seconds:
            return cached_keys
        async with httpx.AsyncClient(timeout=5.0) as http_client:
            response = await http_client.get(jwks_url)
            response.raise_for_status()
            payload = response.json()
        keys: dict[str, dict[str, Any]] = {}
        for item in payload.get("keys", []):
            kid = item.get("kid")
            if kid:
                keys[kid] = item
        if not keys:
            raise HTTPException(status_code=503, detail="No JWKS keys available")
        self._keys_by_url[jwks_url] = keys
        self._last_fetch_by_url[jwks_url] = now
        return keys


jwks_cache = JwksCache()


def _extract_token(
    authorization: str | None,
    x_forwarded_access_token: str | None,
) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    if x_forwarded_access_token:
        return x_forwarded_access_token.strip()
    raise HTTPException(status_code=401, detail="Missing access token")


def _extract_token_optional(
    authorization: str | None,
    x_forwarded_access_token: str | None,
    cookie_token: str | None,
) -> tuple[str, str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip(), "authorization"
    if x_forwarded_access_token:
        return x_forwarded_access_token.strip(), "x-forwarded-access-token"
    if cookie_token:
        return cookie_token.strip(), "ops_access_token_cookie"
    return "", "none"


def _jwt_segments(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        return {"error": "Token is not a JWT with 3 segments"}
    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:
        header = {"_error": str(exc)}
    try:
        claims = jwt.get_unverified_claims(token)
    except Exception as exc:
        claims = {"_error": str(exc)}
    return {
        "header": header,
        "claims": claims,
    }


def _claim_email(claims: dict[str, Any]) -> str:
    value = (
        claims.get("email")
        or claims.get("upn")
        or claims.get("preferred_username")
        or ""
    )
    return str(value).strip().lower()


def _claim_groups(claims: dict[str, Any]) -> set[str]:
    raw = claims.get("groups")
    if isinstance(raw, list):
        return {str(x).strip() for x in raw if str(x).strip()}
    if isinstance(raw, str) and raw.strip():
        return {x.strip() for x in raw.split(",") if x.strip()}
    return set()


def _check_audience(claims: dict[str, Any], audience: str) -> bool:
    if not audience:
        return True
    aud = claims.get("aud")
    if isinstance(aud, str):
        return aud == audience
    if isinstance(aud, list):
        return audience in [str(x) for x in aud]
    return False


def _select_verifier(unverified_claims: dict[str, Any]) -> JwtVerifier:
    issuer = str(unverified_claims.get("iss", "")).strip()
    google_issuers = frozenset({"https://accounts.google.com", "accounts.google.com"})
    if issuer in google_issuers:
        return JwtVerifier(
            jwks_url="https://www.googleapis.com/oauth2/v3/certs",
            issuers=google_issuers,
            audience=settings.oauth_client_id,
        )

    return JwtVerifier(
        jwks_url=settings.jwt_jwks_url,
        issuers=frozenset(settings.jwt_issuers),
        audience=settings.jwt_audience,
    )


def _check_authorization(claims: dict[str, Any]) -> None:
    email = _claim_email(claims)
    groups = _claim_groups(claims)
    by_email = (
        bool(settings.jwt_email_allowlist) and email in settings.jwt_email_allowlist
    )
    by_group = (
        bool(settings.jwt_required_group) and settings.jwt_required_group in groups
    )
    if not settings.jwt_email_allowlist and not settings.jwt_required_group:
        return
    if by_email or by_group:
        return
    raise HTTPException(
        status_code=403, detail="Token is valid but not authorized for ops actions"
    )


def _upstream_auth_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    authorization = (request.headers.get("authorization") or "").strip()
    if authorization:
        headers["Authorization"] = authorization
        return headers

    forwarded_token = (request.headers.get("x-forwarded-access-token") or "").strip()
    if forwarded_token:
        headers["Authorization"] = f"Bearer {forwarded_token}"
        return headers

    cookie_token = (request.cookies.get("ops_access_token") or "").strip()
    if cookie_token:
        headers["Authorization"] = f"Bearer {cookie_token}"
        return headers
    return headers


async def _fetch_sra_admin_payload(request: Request) -> dict[str, Any]:
    if not settings.sra_admin_enabled:
        return {
            "enabled": False,
            "reachable": False,
            "index": {},
            "analytics": {},
            "error": "SRA admin integration is disabled",
        }

    base_url = settings.sra_admin_api_base_url.rstrip("/")
    if not base_url:
        return {
            "enabled": True,
            "reachable": False,
            "index": {},
            "analytics": {},
            "error": "SRA_ADMIN_API_BASE_URL is empty",
        }

    headers = _upstream_auth_headers(request)
    params = {
        "days": max(1, min(int(settings.sra_admin_analytics_days), 90)),
        "limit": max(1, min(int(settings.sra_admin_recent_limit), 2000)),
    }

    timeout = max(float(settings.sra_admin_api_timeout_seconds), 1.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            index_response, analytics_response = await asyncio.gather(
                http_client.get(
                    f"{base_url}/api/admin/ops/sandbox-index",
                    headers=headers,
                    params={"limit": params["limit"]},
                ),
                http_client.get(
                    f"{base_url}/api/admin/ops/lease-analytics",
                    headers=headers,
                    params=params,
                ),
            )
        index_response.raise_for_status()
        analytics_response.raise_for_status()
        return {
            "enabled": True,
            "reachable": True,
            "index": index_response.json(),
            "analytics": analytics_response.json(),
            "error": "",
        }
    except Exception as exc:
        return {
            "enabled": True,
            "reachable": False,
            "index": {},
            "analytics": {},
            "error": str(exc),
        }


async def _fetch_sra_admin_users(
    request: Request,
    *,
    query: str,
    limit: int,
) -> dict[str, Any]:
    if not settings.sra_admin_enabled:
        raise HTTPException(status_code=503, detail="SRA admin integration is disabled")

    base_url = settings.sra_admin_api_base_url.rstrip("/")
    if not base_url:
        raise HTTPException(status_code=503, detail="SRA_ADMIN_API_BASE_URL is empty")

    headers = _upstream_auth_headers(request)
    timeout = max(float(settings.sra_admin_api_timeout_seconds), 1.0)
    safe_limit = min(max(int(limit), 1), 100)
    safe_query = str(query or "").strip()

    try:
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            response = await http_client.get(
                f"{base_url}/api/admin/ops/users/search",
                headers=headers,
                params={"q": safe_query, "limit": safe_limit},
            )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip() or str(exc)
        raise HTTPException(
            status_code=exc.response.status_code, detail=detail
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch users from sandboxed-react-agent admin API: {exc}",
        ) from exc

    users = payload.get("users") if isinstance(payload, dict) else []
    return {
        "source": "sra-admin",
        "query": safe_query,
        "limit": safe_limit,
        "users": users if isinstance(users, list) else [],
        "upstream": payload if isinstance(payload, dict) else {},
    }


async def require_auth(
    authorization: str | None = Header(default=None),
    x_forwarded_access_token: str | None = Header(default=None),
    ops_access_token: str | None = Cookie(default=None),
    ops_google_access_token: str | None = Cookie(default=None),
) -> dict[str, Any]:
    token = (
        _extract_token(authorization, x_forwarded_access_token)
        if (authorization or x_forwarded_access_token)
        else (ops_access_token or "")
    )
    if not token:
        raise HTTPException(status_code=401, detail="Missing access token")

    return await _verify_token(token, access_token=ops_google_access_token)


async def _verify_token(token: str, access_token: str | None = None) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=401, detail=f"Invalid JWT header: {exc}"
        ) from exc
    try:
        unverified_claims = jwt.get_unverified_claims(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=401, detail=f"Invalid JWT claims: {exc}"
        ) from exc

    verifier = _select_verifier(unverified_claims)
    kid = header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="JWT header missing kid")
    keys = await jwks_cache.get_keys(verifier.jwks_url)
    key_data = keys.get(kid)
    if not key_data:
        keys = await jwks_cache.get_keys(verifier.jwks_url, force_refresh=True)
        key_data = keys.get(kid)
    if not key_data:
        raise HTTPException(status_code=401, detail="JWT key id not found in JWKS")

    algorithm = key_data.get("alg") or header.get("alg")
    if not algorithm:
        raise HTTPException(status_code=401, detail="JWT algorithm not specified")

    try:
        decode_options: dict[str, Any] = {"verify_aud": False}
        decode_kwargs: dict[str, Any] = {}
        if access_token:
            decode_kwargs["access_token"] = access_token
        else:
            decode_options["verify_at_hash"] = False

        claims = jwt.decode(
            token,
            key_data,
            algorithms=[algorithm],
            options=decode_options,
            **decode_kwargs,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=401, detail=f"JWT verification failed: {exc}"
        ) from exc

    issuer = str(claims.get("iss", "")).strip()
    if verifier.issuers and issuer not in verifier.issuers:
        raise HTTPException(status_code=401, detail="JWT issuer is not allowed")
    if not _check_audience(claims, verifier.audience):
        raise HTTPException(status_code=401, detail="JWT audience is not allowed")

    _check_authorization(claims)
    return claims


@app.get("/api/token-inspect")
async def token_inspect(
    authorization: str | None = Header(default=None),
    x_forwarded_access_token: str | None = Header(default=None),
    ops_access_token: str | None = Cookie(default=None),
    ops_google_access_token: str | None = Cookie(default=None),
) -> dict[str, Any]:
    token, source = _extract_token_optional(
        authorization, x_forwarded_access_token, ops_access_token
    )
    if not token:
        return {
            "token_found": False,
            "source": source,
            "verified": False,
            "verify_error": "No token was found in Authorization header, X-Forwarded-Access-Token, or ops_access_token cookie",
            "decoded": {},
        }

    decoded = _jwt_segments(token)
    try:
        claims = await _verify_token(token, access_token=ops_google_access_token)
        return {
            "token_found": True,
            "source": source,
            "verified": True,
            "verify_error": "",
            "decoded": decoded,
            "verified_claims": claims,
        }
    except HTTPException as exc:
        return {
            "token_found": True,
            "source": source,
            "verified": False,
            "verify_error": exc.detail,
            "decoded": decoded,
        }


def _deployment_status(deploy: Any, *, now: datetime) -> dict[str, Any]:
    spec_replicas = int(deploy.spec.replicas or 0)
    status = deploy.status
    created_at = _iso(deploy.metadata.creation_timestamp)
    return {
        "name": deploy.metadata.name,
        "desired": spec_replicas,
        "ready": int(status.ready_replicas or 0),
        "available": int(status.available_replicas or 0),
        "updated": int(status.updated_replicas or 0),
        "created_at": created_at,
        "age_seconds": _age_seconds(deploy.metadata.creation_timestamp, now=now),
        "conditions": [
            {
                "type": str(condition.type or ""),
                "status": str(condition.status or ""),
                "reason": str(condition.reason or ""),
                "message": str(condition.message or ""),
            }
            for condition in (status.conditions or [])
        ],
        "manageable": deploy.metadata.name in settings.managed_deployments,
    }


def _pod_status(pod: Any, *, now: datetime) -> dict[str, Any]:
    return {
        "name": pod.metadata.name,
        "phase": pod.status.phase,
        "node": pod.spec.node_name,
        "ready": any((c.ready for c in (pod.status.container_statuses or []))),
        "created_at": _iso(pod.metadata.creation_timestamp),
        "age_seconds": _age_seconds(pod.metadata.creation_timestamp, now=now),
    }


def _warm_pool_status(warm_pool: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    metadata = warm_pool.get("metadata") or {}
    spec = warm_pool.get("spec") or {}
    status = warm_pool.get("status") or {}
    template_ref = spec.get("sandboxTemplateRef") or {}
    conditions = _conditions_summary(status.get("conditions"))
    ready_condition = _is_ready_from_conditions(conditions)
    created_at = _iso(metadata.get("creationTimestamp"))
    return {
        "name": metadata.get("name"),
        "replicas": int(spec.get("replicas") or 0),
        "template": template_ref.get("name") or "",
        "ready": int(status.get("readyReplicas") or 0),
        "ready_condition": ready_condition,
        "conditions": conditions,
        "created_at": created_at,
        "age_seconds": _age_seconds(metadata.get("creationTimestamp"), now=now),
    }


def _warm_pool_category(template_name: str) -> str:
    lowered = str(template_name or "").strip().lower()
    if "pydata" in lowered:
        return "pydata"
    if "large" in lowered:
        return "large"
    if "small" in lowered:
        return "small"
    return "default"


def _default_warm_pool_name(template_name: str) -> str:
    cleaned = "".join(
        char if (char.isalnum() or char == "-") else "-"
        for char in str(template_name or "sandbox")
    ).strip("-")
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    cleaned = cleaned.lower()[:50] or "sandbox"
    return f"{cleaned}-warmpool"


def _build_warm_pool_profiles(
    templates: list[str],
    warm_pools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_templates = sorted(
        str(item).strip() for item in templates if str(item).strip()
    )
    normalized_pools: list[dict[str, Any]] = []
    for item in warm_pools:
        if not isinstance(item, dict):
            continue
        normalized_pools.append(
            {
                "name": str(item.get("name") or ""),
                "template": str(item.get("template") or ""),
                "replicas": int(item.get("replicas") or 0),
                "ready": int(item.get("ready") or 0),
            }
        )

    profiles: list[dict[str, Any]] = []
    for template_name in normalized_templates:
        matching = [
            pool
            for pool in normalized_pools
            if str(pool.get("template") or "") == template_name
        ]
        matching.sort(key=lambda row: str(row.get("name") or ""))

        profiles.append(
            {
                "template_name": template_name,
                "category": _warm_pool_category(template_name),
                "default_warm_pool_name": (
                    str(matching[0].get("name") or "")
                    if matching
                    else _default_warm_pool_name(template_name)
                ),
                "pool_count": len(matching),
                "total_replicas": sum(
                    int(pool.get("replicas") or 0) for pool in matching
                ),
                "total_ready": sum(int(pool.get("ready") or 0) for pool in matching),
                "pools": matching,
            }
        )
    return profiles


def _claim_status(
    claim: dict[str, Any],
    *,
    now: datetime,
    claim_owner_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    metadata = claim.get("metadata") or {}
    spec = claim.get("spec") or {}
    status = claim.get("status") or {}
    template_ref = spec.get("sandboxTemplateRef") or {}
    conditions = _conditions_summary(status.get("conditions"))
    ready_condition = _is_ready_from_conditions(conditions)
    name = str(metadata.get("name") or "")
    owner = claim_owner_index.get(name) or {}
    return {
        "name": name,
        "namespace": str(metadata.get("namespace") or ""),
        "uid": str(metadata.get("uid") or ""),
        "template": str(template_ref.get("name") or ""),
        "created_at": _iso(metadata.get("creationTimestamp")),
        "age_seconds": _age_seconds(metadata.get("creationTimestamp"), now=now),
        "generation": int(metadata.get("generation") or 0),
        "phase": str(status.get("phase") or ""),
        "claim_status": str(status.get("status") or ""),
        "ready_condition": ready_condition,
        "conditions": conditions,
        "owner": {
            "lease_id": owner.get("lease_id"),
            "session_id": owner.get("session_id"),
            "user_id": owner.get("user_id"),
            "status": owner.get("status"),
            "workspace_status": owner.get("workspace_status"),
            "expires_at": owner.get("expires_at"),
            "expires_soon": owner.get("expires_soon"),
            "last_used_at": owner.get("last_used_at"),
            "known": bool(owner),
        },
    }


def _sandbox_status(
    sandbox: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    metadata = sandbox.get("metadata") or {}
    spec = sandbox.get("spec") or {}
    status = sandbox.get("status") or {}
    claim_ref = spec.get("sandboxClaimRef") or status.get("sandboxClaimRef") or {}
    conditions = _conditions_summary(status.get("conditions"))
    ready_condition = _is_ready_from_conditions(conditions)
    return {
        "name": str(metadata.get("name") or ""),
        "namespace": str(metadata.get("namespace") or ""),
        "uid": str(metadata.get("uid") or ""),
        "created_at": _iso(metadata.get("creationTimestamp")),
        "age_seconds": _age_seconds(metadata.get("creationTimestamp"), now=now),
        "phase": str(status.get("phase") or ""),
        "ready_condition": ready_condition,
        "conditions": conditions,
        "claim_name": str(claim_ref.get("name") or ""),
        "template": str((spec.get("sandboxTemplateRef") or {}).get("name") or ""),
    }


def _node_ready(node: Any) -> bool:
    for condition in node.status.conditions or []:
        if condition.type == "Ready":
            return str(condition.status).lower() == "true"
    return False


def _node_instance_type(node: Any) -> str:
    labels = node.metadata.labels or {}
    return (
        labels.get("node.kubernetes.io/instance-type")
        or labels.get("beta.kubernetes.io/instance-type")
        or "unknown"
    )


def _node_pool(node: Any) -> str:
    labels = node.metadata.labels or {}
    return labels.get("cloud.google.com/gke-nodepool") or "unknown"


def _node_is_spot(node: Any) -> bool:
    labels = node.metadata.labels or {}
    value = str(labels.get("cloud.google.com/gke-spot") or "").strip().lower()
    return value == "true"


def _e2_machine_shape(instance_type: str) -> tuple[int, float] | None:
    machine = instance_type.strip().lower()
    if machine == "e2-medium":
        return (2, 4.0)
    if machine == "e2-small":
        return (2, 2.0)
    if machine == "e2-micro":
        return (2, 1.0)
    if machine.startswith("e2-standard-"):
        try:
            cores = int(machine.split("e2-standard-", 1)[1])
            if cores > 0:
                return (cores, float(cores * 4))
        except Exception:
            return None
    return None


def _estimate_node_hourly_cost_usd(instance_type: str, is_spot: bool) -> float | None:
    shape = _e2_machine_shape(instance_type)
    if not shape:
        return None
    cores, memory_gib = shape
    if is_spot:
        return (cores * _E2_CORE_SPOT_USD_PER_HOUR) + (
            memory_gib * _E2_RAM_SPOT_USD_PER_GIB_HOUR
        )
    return (cores * _E2_CORE_ONDEMAND_USD_PER_HOUR) + (
        memory_gib * _E2_RAM_ONDEMAND_USD_PER_GIB_HOUR
    )


def _parse_quantity_gib(quantity: str | None) -> float:
    if not quantity:
        return 0.0
    raw = str(quantity).strip()
    if not raw:
        return 0.0
    units = [
        ("Ki", 1.0 / (1024 * 1024)),
        ("Mi", 1.0 / 1024),
        ("Gi", 1.0),
        ("Ti", 1024.0),
        ("Pi", 1024.0 * 1024.0),
        ("Ei", 1024.0 * 1024.0 * 1024.0),
        ("K", 1.0 / (1000 * 1000)),
        ("M", 1.0 / 1000),
        ("G", 1.0),
        ("T", 1000.0),
        ("P", 1000.0 * 1000.0),
        ("E", 1000.0 * 1000.0 * 1000.0),
    ]
    for suffix, factor in units:
        if raw.endswith(suffix):
            number = raw[: -len(suffix)]
            try:
                return float(number) * factor
            except Exception:
                return 0.0
    try:
        return float(raw) / (1024.0**3)
    except Exception:
        return 0.0


def _pvc_cost_rate_usd_per_gib_hour(storage_class: str) -> float | None:
    key = storage_class.strip().lower()
    monthly = _PVC_USD_PER_GIB_MONTH_BY_CLASS.get(key)
    if monthly is not None:
        return monthly / _MONTH_HOURS
    if "standard" in key:
        return _PVC_USD_PER_GIB_MONTH_BY_CLASS["standard"] / _MONTH_HOURS
    if "balanced" in key:
        return _PVC_USD_PER_GIB_MONTH_BY_CLASS["balanced"] / _MONTH_HOURS
    return None


def _pvc_storage_class(pvc: Any) -> str:
    if pvc.spec.storage_class_name:
        return str(pvc.spec.storage_class_name)
    annotations = pvc.metadata.annotations or {}
    return str(annotations.get("volume.beta.kubernetes.io/storage-class") or "")


def _cost_estimate(
    nodes: list[dict[str, Any]], pvcs: list[dict[str, Any]], cluster_count: int = 1
) -> dict[str, Any]:
    node_breakdown: dict[tuple[str, bool], dict[str, Any]] = {}
    node_total = 0.0

    for node in nodes:
        instance_type = str(node.get("instance_type") or "unknown")
        is_spot = bool(node.get("spot"))
        hourly_each = _estimate_node_hourly_cost_usd(instance_type, is_spot)
        key = (instance_type, is_spot)
        entry = node_breakdown.setdefault(
            key,
            {
                "instance_type": instance_type,
                "spot": is_spot,
                "count": 0,
                "hourly_each_usd": hourly_each,
                "hourly_total_usd": 0.0,
            },
        )
        entry["count"] = int(entry["count"] or 0) + 1
        if hourly_each is not None:
            entry["hourly_total_usd"] = (
                float(entry["hourly_total_usd"] or 0.0) + hourly_each
            )
            node_total += hourly_each

    pvc_breakdown: list[dict[str, Any]] = []
    pvc_total = 0.0
    for pvc in pvcs:
        storage_class = str(pvc.get("storage_class") or "")
        size_gib = float(pvc.get("requested_gib") or 0.0)
        hourly_rate = _pvc_cost_rate_usd_per_gib_hour(storage_class)
        hourly_total = (hourly_rate * size_gib) if hourly_rate is not None else None
        pvc_breakdown.append(
            {
                "name": str(pvc.get("name") or ""),
                "storage_class": storage_class,
                "requested_gib": size_gib,
                "hourly_usd": hourly_total,
            }
        )
        if hourly_total is not None:
            pvc_total += hourly_total

    gke_fee = float(max(cluster_count, 0)) * _GKE_CLUSTER_FEE_USD_PER_HOUR
    total = node_total + pvc_total + gke_fee

    return {
        "currency": "USD",
        "period": "hour",
        "region": "europe-west4",
        "node_hourly_total_usd": node_total,
        "pvc_hourly_total_usd": pvc_total,
        "gke_cluster_fee_hourly_usd": gke_fee,
        "total_hourly_usd": total,
        "node_breakdown": sorted(
            node_breakdown.values(),
            key=lambda x: (str(x.get("instance_type") or ""), bool(x.get("spot"))),
        ),
        "pvc_breakdown": sorted(
            pvc_breakdown,
            key=lambda x: str(x.get("name") or ""),
        ),
        "pricing_source": {
            "compute": "https://cloud.google.com/compute/all-pricing",
            "gke": "https://cloud.google.com/kubernetes-engine/pricing",
        },
        "notes": [
            "Estimate includes nodes, PVC capacity, and one GKE cluster management fee.",
            "Unknown machine/storage classes are excluded from numeric totals.",
            "Prices are list prices for europe-west4 and may differ with discounts or custom contracts.",
        ],
    }


def _node_summary(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    type_counts: dict[str, int] = {}
    pool_counts: dict[str, int] = {}
    ready_count = 0
    for node in nodes:
        if node.get("ready"):
            ready_count += 1
        node_type = str(node.get("instance_type") or "unknown")
        node_pool = str(node.get("node_pool") or "unknown")
        type_counts[node_type] = type_counts.get(node_type, 0) + 1
        pool_counts[node_pool] = pool_counts.get(node_pool, 0) + 1
    return {
        "total": len(nodes),
        "ready": ready_count,
        "types": [
            {"name": name, "count": count}
            for name, count in sorted(type_counts.items(), key=lambda x: x[0])
        ],
        "pools": [
            {"name": name, "count": count}
            for name, count in sorted(pool_counts.items(), key=lambda x: x[0])
        ],
    }


async def _overview_data(request: Request) -> dict[str, Any]:
    ns = settings.target_namespace
    now = datetime.now(UTC)
    sra_admin = await _fetch_sra_admin_payload(request)
    sra_index = (
        sra_admin.get("index") if isinstance(sra_admin.get("index"), dict) else {}
    )
    sra_analytics = (
        sra_admin.get("analytics")
        if isinstance(sra_admin.get("analytics"), dict)
        else {}
    )
    claim_owner_index = (
        sra_index.get("claim_owner_index")
        if isinstance(sra_index.get("claim_owner_index"), dict)
        else {}
    )

    if use_mock_cluster:
        mock_nodes = [
            {
                "name": "mock-node-local-a",
                "ready": True,
                "instance_type": "e2-standard-4",
                "node_pool": "default-pool",
                "pod_count": 2,
                "phase_counts": {"Running": 2},
            },
            {
                "name": "mock-node-local-b",
                "ready": True,
                "instance_type": "e2-standard-2",
                "node_pool": "gvisor-sandbox-pool",
                "pod_count": 1,
                "phase_counts": {"Running": 1},
            },
        ]
        claims_detailed = [
            {
                "name": name,
                "namespace": ns,
                "uid": f"mock-{name}",
                "template": "python-runtime-template",
                "created_at": _iso(now),
                "age_seconds": 0,
                "generation": 1,
                "phase": "Ready",
                "claim_status": "ready",
                "ready_condition": True,
                "conditions": [],
                "owner": {
                    "lease_id": None,
                    "session_id": None,
                    "user_id": None,
                    "status": None,
                    "workspace_status": None,
                    "expires_at": None,
                    "expires_soon": False,
                    "last_used_at": None,
                    "known": False,
                },
            }
            for name in sorted(mock_state["claims"])
        ]
        sandboxes_detailed = [
            {
                "name": name,
                "namespace": ns,
                "uid": f"mock-sandbox-{name}",
                "created_at": _iso(now),
                "age_seconds": 0,
                "phase": "Running",
                "ready_condition": True,
                "conditions": [],
                "claim_name": name,
                "template": "python-runtime-template",
            }
            for name in sorted(mock_state["sandboxes"])
        ]
        mock_templates = [
            "python-runtime-template-small",
            "python-runtime-template",
            "python-runtime-template-large",
            "python-runtime-template-pydata",
        ]
        mock_warm_pools = [
            {
                "name": name,
                "replicas": int(state.get("replicas") or 0),
                "template": str(state.get("template") or ""),
                "ready": int(state.get("replicas") or 0),
                "ready_condition": True,
                "conditions": [],
                "created_at": _iso(now),
                "age_seconds": 0,
            }
            for name, state in sorted(mock_state["warm_pools"].items())
        ]
        return {
            "cluster_mode": "mock",
            "namespace": ns,
            "deployments": [
                {
                    "name": name,
                    **state,
                    "created_at": _iso(now),
                    "age_seconds": 0,
                    "conditions": [],
                    "manageable": name in settings.managed_deployments,
                }
                for name, state in sorted(mock_state["deployments"].items())
            ],
            "pods": [
                {
                    "name": "mock-backend-pod",
                    "phase": "Running",
                    "node": "mock-node-local",
                    "ready": True,
                    "created_at": _iso(now),
                    "age_seconds": 0,
                }
            ],
            "services": ["alt-default-ops-console"],
            "sandboxclaims": sorted(mock_state["claims"]),
            "sandboxes": sorted(mock_state["sandboxes"]),
            "sandboxclaims_detailed": claims_detailed,
            "sandboxes_detailed": sandboxes_detailed,
            "sandboxwarmpools": mock_warm_pools,
            "sandboxtemplates": mock_templates,
            "warm_pool_profiles": _build_warm_pool_profiles(
                mock_templates,
                mock_warm_pools,
            ),
            "nodes": mock_nodes,
            "node_summary": _node_summary(mock_nodes),
            "pvcs": [
                {
                    "name": "sandboxed-react-agent-backend-data",
                    "status": "Bound",
                    "storage_class": "standard",
                    "requested": "5Gi",
                    "requested_gib": 5.0,
                    "access_modes": ["ReadWriteOnce"],
                    "volume": "pvc-mock-123",
                }
            ],
            "resource_summary": {
                "running_nodes": sum(1 for n in mock_nodes if n.get("ready")),
                "total_nodes": len(mock_nodes),
                "bound_pvcs": 1,
                "pending_pvcs": 0,
                "pvc_requested_gib": 5.0,
            },
            "cost_estimate": _cost_estimate(
                nodes=[{**node, "spot": False} for node in mock_nodes],
                pvcs=[
                    {
                        "name": "sandboxed-react-agent-backend-data",
                        "storage_class": "standard",
                        "requested_gib": 5.0,
                    }
                ],
                cluster_count=1,
            ),
            "workspace_session_health": sra_index.get("summary") or {},
            "lease_analytics": sra_analytics,
            "ops_integration": {
                "sra_admin": {
                    "enabled": bool(sra_admin.get("enabled")),
                    "reachable": bool(sra_admin.get("reachable")),
                    "error": str(sra_admin.get("error") or ""),
                }
            },
        }

    if not apps_api or not core_api or not custom_api:
        raise HTTPException(status_code=500, detail="Kubernetes API is not initialized")

    deployments = apps_api.list_namespaced_deployment(namespace=ns).items
    pods = core_api.list_namespaced_pod(namespace=ns).items
    services = core_api.list_namespaced_service(namespace=ns).items
    try:
        pvcs = core_api.list_namespaced_persistent_volume_claim(namespace=ns).items
    except ApiException:
        pvcs = []
    try:
        nodes = core_api.list_node().items
    except ApiException:
        nodes = []

    claims = custom_api.list_namespaced_custom_object(
        group="extensions.agents.x-k8s.io",
        version="v1alpha1",
        namespace=ns,
        plural="sandboxclaims",
    ).get("items", [])
    sandboxes = custom_api.list_namespaced_custom_object(
        group="agents.x-k8s.io",
        version="v1alpha1",
        namespace=ns,
        plural="sandboxes",
    ).get("items", [])
    warm_pools = custom_api.list_namespaced_custom_object(
        group="extensions.agents.x-k8s.io",
        version="v1alpha1",
        namespace=ns,
        plural="sandboxwarmpools",
    ).get("items", [])
    templates = custom_api.list_namespaced_custom_object(
        group="extensions.agents.x-k8s.io",
        version="v1alpha1",
        namespace=ns,
        plural="sandboxtemplates",
    ).get("items", [])

    pod_count_by_node: dict[str, int] = {}
    phase_counts_by_node: dict[str, dict[str, int]] = {}
    for pod in pods:
        node_name = str(pod.spec.node_name or "unscheduled")
        phase = str(pod.status.phase or "Unknown")
        pod_count_by_node[node_name] = pod_count_by_node.get(node_name, 0) + 1
        phase_counts = phase_counts_by_node.setdefault(node_name, {})
        phase_counts[phase] = phase_counts.get(phase, 0) + 1

    node_rows = [
        {
            "name": node.metadata.name,
            "ready": _node_ready(node),
            "instance_type": _node_instance_type(node),
            "node_pool": _node_pool(node),
            "spot": _node_is_spot(node),
            "pod_count": int(pod_count_by_node.get(node.metadata.name, 0)),
            "phase_counts": phase_counts_by_node.get(node.metadata.name, {}),
        }
        for node in nodes
    ]

    if not node_rows and pod_count_by_node:
        node_rows = [
            {
                "name": name,
                "ready": False,
                "instance_type": "unknown",
                "node_pool": "unknown",
                "spot": False,
                "pod_count": int(count),
                "phase_counts": phase_counts_by_node.get(name, {}),
            }
            for name, count in sorted(pod_count_by_node.items(), key=lambda x: x[0])
        ]

    pvc_rows = [
        {
            "name": pvc.metadata.name,
            "status": str(pvc.status.phase or ""),
            "storage_class": _pvc_storage_class(pvc),
            "requested": str(
                (pvc.spec.resources.requests or {}).get("storage") or "0Gi"
            ),
            "requested_gib": _parse_quantity_gib(
                str((pvc.spec.resources.requests or {}).get("storage") or "0Gi")
            ),
            "access_modes": list(pvc.spec.access_modes or []),
            "volume": str(pvc.spec.volume_name or ""),
        }
        for pvc in pvcs
    ]

    resource_summary = {
        "running_nodes": sum(1 for node in node_rows if node.get("ready")),
        "total_nodes": len(node_rows),
        "bound_pvcs": sum(1 for pvc in pvc_rows if pvc.get("status") == "Bound"),
        "pending_pvcs": sum(1 for pvc in pvc_rows if pvc.get("status") == "Pending"),
        "pvc_requested_gib": sum(
            float(pvc.get("requested_gib") or 0.0) for pvc in pvc_rows
        ),
    }

    cost_estimate = _cost_estimate(node_rows, pvc_rows, cluster_count=1)

    claims_detailed = sorted(
        (
            _claim_status(
                claim,
                now=now,
                claim_owner_index=claim_owner_index,
            )
            for claim in claims
        ),
        key=lambda item: str(item.get("name") or ""),
    )
    sandboxes_detailed = sorted(
        (_sandbox_status(sandbox, now=now) for sandbox in sandboxes),
        key=lambda item: str(item.get("name") or ""),
    )
    warm_pool_rows = sorted(
        (_warm_pool_status(w, now=now) for w in warm_pools),
        key=lambda x: str(x.get("name") or ""),
    )
    template_names = sorted(
        [t.get("metadata", {}).get("name") for t in templates if t.get("metadata")]
    )

    return {
        "cluster_mode": "live",
        "namespace": ns,
        "deployments": sorted(
            (_deployment_status(d, now=now) for d in deployments),
            key=lambda x: x["name"],
        ),
        "pods": sorted(
            (_pod_status(p, now=now) for p in pods),
            key=lambda x: x["name"],
        ),
        "services": sorted((s.metadata.name for s in services)),
        "sandboxclaims": [c.get("metadata", {}).get("name") for c in claims],
        "sandboxes": [s.get("metadata", {}).get("name") for s in sandboxes],
        "sandboxclaims_detailed": claims_detailed,
        "sandboxes_detailed": sandboxes_detailed,
        "sandboxwarmpools": warm_pool_rows,
        "sandboxtemplates": template_names,
        "warm_pool_profiles": _build_warm_pool_profiles(template_names, warm_pool_rows),
        "nodes": sorted(node_rows, key=lambda x: str(x.get("name") or "")),
        "node_summary": _node_summary(node_rows),
        "pvcs": sorted(pvc_rows, key=lambda x: str(x.get("name") or "")),
        "resource_summary": resource_summary,
        "cost_estimate": cost_estimate,
        "workspace_session_health": sra_index.get("summary") or {},
        "lease_analytics": sra_analytics,
        "ops_integration": {
            "sra_admin": {
                "enabled": bool(sra_admin.get("enabled")),
                "reachable": bool(sra_admin.get("reachable")),
                "error": str(sra_admin.get("error") or ""),
            }
        },
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "cluster_mode": "mock" if use_mock_cluster else "live"}


@app.get("/auth2/login")
async def auth2_login() -> RedirectResponse:
    if not settings.oauth_client_id or not settings.oauth_client_secret:
        raise HTTPException(status_code=503, detail="OAuth client is not configured")

    state = secrets.token_urlsafe(24)
    query = urlencode(
        {
            "client_id": settings.oauth_client_id,
            "redirect_uri": settings.oauth_redirect_uri,
            "response_type": "code",
            "scope": settings.oauth_scopes,
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    response = RedirectResponse(
        url=f"https://accounts.google.com/o/oauth2/v2/auth?{query}", status_code=302
    )
    response.set_cookie(
        key="ops_oauth_state",
        value=state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=600,
        path="/",
    )
    return response


@app.get("/auth2/callback")
async def auth2_callback(
    code: str | None = None,
    state: str | None = None,
    ops_oauth_state: str | None = Cookie(default=None),
) -> RedirectResponse:
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    if not state or not ops_oauth_state or state != ops_oauth_state:
        raise HTTPException(status_code=400, detail="OAuth state mismatch")

    async with httpx.AsyncClient(timeout=10.0) as http_client:
        token_response = await http_client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.oauth_client_id,
                "client_secret": settings.oauth_client_secret,
                "redirect_uri": settings.oauth_redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if token_response.status_code >= 400:
        raise HTTPException(
            status_code=401,
            detail=f"OAuth token exchange failed: {token_response.text}",
        )

    token_payload = token_response.json()
    id_token = token_payload.get("id_token")
    access_token = token_payload.get("access_token")
    if not isinstance(id_token, str) or not id_token:
        raise HTTPException(
            status_code=401, detail="OAuth token response missing id_token"
        )

    await _verify_token(
        id_token, access_token=access_token if isinstance(access_token, str) else None
    )

    response = RedirectResponse(url=_external_path("/admin"), status_code=302)
    response.delete_cookie("ops_oauth_state", path="/")
    response.set_cookie(
        key="ops_access_token",
        value=id_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=3600,
        path="/",
    )
    if isinstance(access_token, str) and access_token:
        response.set_cookie(
            key="ops_google_access_token",
            value=access_token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=3600,
            path="/",
        )
    return response


@app.get("/oauth2/callback")
async def oauth2_callback_alias(
    code: str | None = None,
    state: str | None = None,
    ops_oauth_state: str | None = Cookie(default=None),
) -> RedirectResponse:
    return await auth2_callback(code=code, state=state, ops_oauth_state=ops_oauth_state)


@app.post("/auth2/logout")
def auth2_logout() -> RedirectResponse:
    response = RedirectResponse(url=_external_path("/"), status_code=302)
    response.delete_cookie("ops_access_token", path="/")
    response.delete_cookie("ops_google_access_token", path="/")
    response.delete_cookie("ops_oauth_state", path="/")
    return response


@app.get("/api/me")
async def me(claims: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    return {
        "email": _claim_email(claims),
        "issuer": claims.get("iss"),
        "audience": claims.get("aud"),
        "groups": sorted(_claim_groups(claims)),
    }


@app.get("/api/overview")
async def overview(
    request: Request,
    _: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    return await _overview_data(request)


@app.get("/api/users/search")
async def search_users(
    request: Request,
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    _: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    return await _fetch_sra_admin_users(request, query=q, limit=limit)


@app.get("/api/sandboxwarmpool-profiles")
async def sandbox_warm_pool_profiles(
    request: Request,
    _: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    overview_payload = await _overview_data(request)
    profiles = overview_payload.get("warm_pool_profiles") or []

    return {
        "namespace": str(
            overview_payload.get("namespace") or settings.target_namespace
        ),
        "profiles": profiles,
        "limits": {
            "replicas_min": 0,
            "replicas_max": 5,
        },
    }


@app.get("/api/sandboxes")
async def list_sandboxes(_: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    if use_mock_cluster:
        return {
            "claims": [{"metadata": {"name": name}} for name in mock_state["claims"]],
            "sandboxes": [
                {"metadata": {"name": name}} for name in mock_state["sandboxes"]
            ],
        }

    if not custom_api:
        raise HTTPException(status_code=500, detail="Kubernetes API is not initialized")

    ns = settings.target_namespace
    claims = custom_api.list_namespaced_custom_object(
        group="extensions.agents.x-k8s.io",
        version="v1alpha1",
        namespace=ns,
        plural="sandboxclaims",
    ).get("items", [])
    sandboxes = custom_api.list_namespaced_custom_object(
        group="agents.x-k8s.io",
        version="v1alpha1",
        namespace=ns,
        plural="sandboxes",
    ).get("items", [])
    return {"claims": claims, "sandboxes": sandboxes}


@app.post("/api/sandboxclaims")
async def create_sandbox_claim(
    payload: CreateClaimRequest, _: dict[str, Any] = Depends(require_auth)
) -> dict[str, str]:
    ns = settings.target_namespace
    claim_name = (payload.claim_name or f"sandbox-claim-{uuid.uuid4().hex[:8]}").strip()

    if use_mock_cluster:
        if claim_name not in mock_state["claims"]:
            mock_state["claims"].append(claim_name)
        if claim_name not in mock_state["sandboxes"]:
            mock_state["sandboxes"].append(claim_name)
        return {"created": claim_name, "template": payload.template_name}

    if not custom_api:
        raise HTTPException(status_code=500, detail="Kubernetes API is not initialized")

    body = {
        "apiVersion": "extensions.agents.x-k8s.io/v1alpha1",
        "kind": "SandboxClaim",
        "metadata": {"name": claim_name, "namespace": ns},
        "spec": {"sandboxTemplateRef": {"name": payload.template_name}},
    }
    try:
        custom_api.create_namespaced_custom_object(
            group="extensions.agents.x-k8s.io",
            version="v1alpha1",
            namespace=ns,
            plural="sandboxclaims",
            body=body,
        )
    except ApiException as exc:
        raise HTTPException(status_code=exc.status or 500, detail=exc.body) from exc
    return {"created": claim_name, "template": payload.template_name}


@app.delete("/api/sandboxclaims/{claim_name}")
async def delete_sandbox_claim(
    claim_name: str, _: dict[str, Any] = Depends(require_auth)
) -> dict[str, str]:
    if use_mock_cluster:
        if claim_name not in mock_state["claims"]:
            raise HTTPException(status_code=404, detail="SandboxClaim not found")
        mock_state["claims"] = [x for x in mock_state["claims"] if x != claim_name]
        mock_state["sandboxes"] = [
            x for x in mock_state["sandboxes"] if x != claim_name
        ]
        return {"deleted": claim_name}

    if not custom_api:
        raise HTTPException(status_code=500, detail="Kubernetes API is not initialized")

    ns = settings.target_namespace
    try:
        custom_api.delete_namespaced_custom_object(
            group="extensions.agents.x-k8s.io",
            version="v1alpha1",
            namespace=ns,
            plural="sandboxclaims",
            name=claim_name,
            body=client.V1DeleteOptions(),
        )
    except ApiException as exc:
        if exc.status == 404:
            raise HTTPException(
                status_code=404, detail="SandboxClaim not found"
            ) from exc
        raise HTTPException(status_code=exc.status or 500, detail=exc.body) from exc
    return {"deleted": claim_name}


@app.post("/api/sandboxwarmpools")
async def upsert_sandbox_warm_pool(
    payload: WarmPoolUpsertRequest,
    _: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    ns = settings.target_namespace
    warm_pool_name = payload.warm_pool_name.strip()

    if use_mock_cluster:
        mock_state["warm_pools"][warm_pool_name] = {
            "replicas": payload.replicas,
            "template": payload.template_name,
        }
        return {
            "warm_pool": warm_pool_name,
            "replicas": payload.replicas,
            "template": payload.template_name,
            "created": True,
        }

    if not custom_api:
        raise HTTPException(status_code=500, detail="Kubernetes API is not initialized")

    body = {
        "apiVersion": "extensions.agents.x-k8s.io/v1alpha1",
        "kind": "SandboxWarmPool",
        "metadata": {"name": warm_pool_name, "namespace": ns},
        "spec": {
            "replicas": payload.replicas,
            "sandboxTemplateRef": {"name": payload.template_name},
        },
    }

    created = False
    try:
        custom_api.get_namespaced_custom_object(
            group="extensions.agents.x-k8s.io",
            version="v1alpha1",
            namespace=ns,
            plural="sandboxwarmpools",
            name=warm_pool_name,
        )
    except ApiException as exc:
        if exc.status == 404:
            try:
                custom_api.create_namespaced_custom_object(
                    group="extensions.agents.x-k8s.io",
                    version="v1alpha1",
                    namespace=ns,
                    plural="sandboxwarmpools",
                    body=body,
                )
                created = True
            except ApiException as create_exc:
                raise HTTPException(
                    status_code=create_exc.status or 500, detail=create_exc.body
                ) from create_exc
        else:
            raise HTTPException(status_code=exc.status or 500, detail=exc.body) from exc

    if not created:
        patch_body = {
            "spec": {
                "replicas": payload.replicas,
                "sandboxTemplateRef": {"name": payload.template_name},
            }
        }
        try:
            custom_api.patch_namespaced_custom_object(
                group="extensions.agents.x-k8s.io",
                version="v1alpha1",
                namespace=ns,
                plural="sandboxwarmpools",
                name=warm_pool_name,
                body=patch_body,
            )
        except ApiException as exc:
            raise HTTPException(status_code=exc.status or 500, detail=exc.body) from exc

    return {
        "warm_pool": warm_pool_name,
        "replicas": payload.replicas,
        "template": payload.template_name,
        "created": created,
    }


@app.post("/api/sandboxwarmpools/{warm_pool_name}/scale")
async def scale_sandbox_warm_pool(
    warm_pool_name: str,
    payload: WarmPoolScaleRequest,
    _: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    ns = settings.target_namespace

    if use_mock_cluster:
        warm_pool = mock_state["warm_pools"].get(warm_pool_name)
        if not warm_pool:
            raise HTTPException(status_code=404, detail="SandboxWarmPool not found")
        warm_pool["replicas"] = payload.replicas
        return {
            "warm_pool": warm_pool_name,
            "replicas": payload.replicas,
            "template": str(warm_pool.get("template") or ""),
        }

    if not custom_api:
        raise HTTPException(status_code=500, detail="Kubernetes API is not initialized")

    patch_body = {"spec": {"replicas": payload.replicas}}
    try:
        custom_api.patch_namespaced_custom_object(
            group="extensions.agents.x-k8s.io",
            version="v1alpha1",
            namespace=ns,
            plural="sandboxwarmpools",
            name=warm_pool_name,
            body=patch_body,
        )
    except ApiException as exc:
        if exc.status == 404:
            raise HTTPException(
                status_code=404, detail="SandboxWarmPool not found"
            ) from exc
        raise HTTPException(status_code=exc.status or 500, detail=exc.body) from exc

    return {"warm_pool": warm_pool_name, "replicas": payload.replicas}


@app.post("/api/deployments/{deployment_name}/scale")
async def scale_deployment(
    deployment_name: str,
    payload: ScaleRequest,
    _: dict[str, Any] = Depends(require_auth),
) -> dict[str, Any]:
    if deployment_name not in settings.managed_deployments:
        raise HTTPException(
            status_code=403, detail="Deployment is not in managed allowlist"
        )

    if use_mock_cluster:
        if deployment_name not in mock_state["deployments"]:
            raise HTTPException(status_code=404, detail="Deployment not found")
        mock_state["deployments"][deployment_name]["desired"] = payload.replicas
        mock_state["deployments"][deployment_name]["ready"] = payload.replicas
        mock_state["deployments"][deployment_name]["available"] = payload.replicas
        mock_state["deployments"][deployment_name]["updated"] = payload.replicas
        return {"deployment": deployment_name, "replicas": payload.replicas}

    if not apps_api:
        raise HTTPException(status_code=500, detail="Kubernetes API is not initialized")

    ns = settings.target_namespace
    body = {"spec": {"replicas": payload.replicas}}
    try:
        apps_api.patch_namespaced_deployment_scale(
            name=deployment_name, namespace=ns, body=body
        )
    except ApiException as exc:
        if exc.status == 404:
            raise HTTPException(status_code=404, detail="Deployment not found") from exc
        raise HTTPException(status_code=exc.status or 500, detail=exc.body) from exc
    return {"deployment": deployment_name, "replicas": payload.replicas}


async def _optional_auth(request: Request) -> dict[str, Any] | None:
    authorization = request.headers.get("Authorization")
    forwarded = request.headers.get("X-Forwarded-Access-Token")
    cookie_token = request.cookies.get("ops_access_token")
    access_token = request.cookies.get("ops_google_access_token")

    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif forwarded:
        token = forwarded.strip()
    elif cookie_token:
        token = cookie_token

    if not token:
        return None

    try:
        return await _verify_token(token, access_token=access_token)
    except HTTPException:
        return None


@app.get("/")
async def root(request: Request):
    claims = await _optional_auth(request)
    if claims:
        return RedirectResponse(url=_external_path("/admin"), status_code=302)

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "oauth_enabled": bool(
                settings.oauth_client_id and settings.oauth_client_secret
            ),
            "login_path": _external_path("/auth2/login"),
        },
    )


@app.get("/admin")
async def admin(request: Request):
    claims = await _optional_auth(request)
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "email": _claim_email(claims) if claims else "",
            "issuer": (claims.get("iss", "") if claims else ""),
            "authorized": bool(claims),
            "namespace": settings.target_namespace,
            "base_path": _normalize_base_path(settings.app_base_path),
        },
    )

from __future__ import annotations

import os
import json
import secrets
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request
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


class ScaleRequest(BaseModel):
    replicas: int = Field(ge=0, le=20)


class CreateClaimRequest(BaseModel):
    template_name: str = Field(default="python-runtime-template", min_length=1)
    claim_name: str | None = None


settings = Settings()


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
}

app = FastAPI(title="alt-default-ops-console", version="0.1.0")
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)


class JwksCache:
    def __init__(self) -> None:
        self._keys: dict[str, dict[str, Any]] = {}
        self._last_fetch = 0.0
        self._ttl_seconds = 900

    async def get_keys(self, force_refresh: bool = False) -> dict[str, dict[str, Any]]:
        now = time.time()
        if (
            not force_refresh
            and self._keys
            and (now - self._last_fetch) < self._ttl_seconds
        ):
            return self._keys
        async with httpx.AsyncClient(timeout=5.0) as http_client:
            response = await http_client.get(settings.jwt_jwks_url)
            response.raise_for_status()
            payload = response.json()
        keys: dict[str, dict[str, Any]] = {}
        for item in payload.get("keys", []):
            kid = item.get("kid")
            if kid:
                keys[kid] = item
        if not keys:
            raise HTTPException(status_code=503, detail="No JWKS keys available")
        self._keys = keys
        self._last_fetch = now
        return self._keys


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


def _check_audience(claims: dict[str, Any]) -> bool:
    if not settings.jwt_audience:
        return True
    aud = claims.get("aud")
    if isinstance(aud, str):
        return aud == settings.jwt_audience
    if isinstance(aud, list):
        return settings.jwt_audience in [str(x) for x in aud]
    return False


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
    kid = header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="JWT header missing kid")
    keys = await jwks_cache.get_keys()
    key_data = keys.get(kid)
    if not key_data:
        keys = await jwks_cache.get_keys(force_refresh=True)
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
    if settings.jwt_issuers and issuer not in settings.jwt_issuers:
        raise HTTPException(status_code=401, detail="JWT issuer is not allowed")
    if not _check_audience(claims):
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


def _deployment_status(deploy: Any) -> dict[str, Any]:
    spec_replicas = int(deploy.spec.replicas or 0)
    status = deploy.status
    return {
        "name": deploy.metadata.name,
        "desired": spec_replicas,
        "ready": int(status.ready_replicas or 0),
        "available": int(status.available_replicas or 0),
        "updated": int(status.updated_replicas or 0),
        "manageable": deploy.metadata.name in settings.managed_deployments,
    }


def _pod_status(pod: Any) -> dict[str, Any]:
    return {
        "name": pod.metadata.name,
        "phase": pod.status.phase,
        "node": pod.spec.node_name,
        "ready": any((c.ready for c in (pod.status.container_statuses or []))),
    }


def _overview_data() -> dict[str, Any]:
    ns = settings.target_namespace
    if use_mock_cluster:
        return {
            "cluster_mode": "mock",
            "namespace": ns,
            "deployments": [
                {
                    "name": name,
                    **state,
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
                }
            ],
            "services": ["alt-default-ops-console"],
            "sandboxclaims": sorted(mock_state["claims"]),
            "sandboxes": sorted(mock_state["sandboxes"]),
            "sandboxwarmpools": ["python-sandbox-warmpool"],
            "sandboxtemplates": ["python-runtime-template"],
        }

    if not apps_api or not core_api or not custom_api:
        raise HTTPException(status_code=500, detail="Kubernetes API is not initialized")

    deployments = apps_api.list_namespaced_deployment(namespace=ns).items
    pods = core_api.list_namespaced_pod(namespace=ns).items
    services = core_api.list_namespaced_service(namespace=ns).items

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

    return {
        "cluster_mode": "live",
        "namespace": ns,
        "deployments": sorted(
            (_deployment_status(d) for d in deployments), key=lambda x: x["name"]
        ),
        "pods": sorted((_pod_status(p) for p in pods), key=lambda x: x["name"]),
        "services": sorted((s.metadata.name for s in services)),
        "sandboxclaims": [c.get("metadata", {}).get("name") for c in claims],
        "sandboxes": [s.get("metadata", {}).get("name") for s in sandboxes],
        "sandboxwarmpools": [w.get("metadata", {}).get("name") for w in warm_pools],
        "sandboxtemplates": [t.get("metadata", {}).get("name") for t in templates],
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
async def overview(_: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    return _overview_data()


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

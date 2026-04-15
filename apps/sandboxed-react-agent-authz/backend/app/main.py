from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


DEFAULT_POLICY = """
version: 1
default_roles:
  authenticated:
    - authenticated
  unauthenticated:
    - anonymous
role_mappings:
  groups:
    sra-admins:
      - ops_admin
    sra-pydata:
      - pydata_user
    sra-terminal:
      - terminal_user
roles:
  anonymous:
    capabilities:
      - terminal.open
      - sandbox.mode.cluster
      - sandbox.profile.transient
      - sandbox.execution_model.session
  authenticated:
    capabilities:
      - terminal.open
      - sandbox.mode.cluster
      - sandbox.profile.persistent_workspace
      - sandbox.profile.transient
      - sandbox.execution_model.session
      - sandbox.execution_model.ephemeral
      - sandbox.template.python-runtime-template-small
      - sandbox.template.python-runtime-template
      - sandbox.template.python-runtime-template-large
  terminal_user:
    capabilities:
      - terminal.open
  pydata_user:
    capabilities:
      - sandbox.template.python-runtime-template-pydata
  ops_admin:
    capabilities:
      - admin.ops.read
      - admin.ops.write
      - authz.policy.manage
feature_rules:
  terminal.open:
    any_capabilities:
      - terminal.open
  admin.ops.read:
    any_capabilities:
      - admin.ops.read
  admin.ops.write:
    any_capabilities:
      - admin.ops.write
  authz.policy.manage:
    any_capabilities:
      - authz.policy.manage
sandbox_rules:
  templates:
    python-runtime-template-pydata:
      any_capabilities:
        - sandbox.template.python-runtime-template-pydata
""".strip()


def _csv_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def _is_true(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _policy_path() -> Path:
    path = (os.getenv("AUTHZ_POLICY_PATH") or "/app/data/authz-policy.yaml").strip()
    return Path(path)


def _audit_log_path() -> Path:
    path = (
        os.getenv("AUTHZ_POLICY_AUDIT_LOG_PATH") or "/app/data/policy-audit.log"
    ).strip()
    return Path(path)


def _validate_policy_yaml(policy_yaml: str) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(policy_yaml)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="Policy root must be a mapping")
    if int(parsed.get("version") or 0) <= 0:
        raise HTTPException(status_code=400, detail="Policy must include version > 0")
    return parsed


def _ensure_policy_file() -> None:
    path = _policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_POLICY + "\n", encoding="utf-8")


def _read_policy_text() -> str:
    _ensure_policy_file()
    return _policy_path().read_text(encoding="utf-8")


def _write_policy_text(policy_yaml: str) -> None:
    _validate_policy_yaml(policy_yaml)
    path = _policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(policy_yaml.rstrip() + "\n", encoding="utf-8")


def _etag_for(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_if_match(value: str | None) -> str:
    if value is None:
        return ""
    normalized = value.strip()
    if normalized.startswith("W/"):
        normalized = normalized[2:].strip()
    if normalized.startswith('"') and normalized.endswith('"') and len(normalized) >= 2:
        normalized = normalized[1:-1]
    return normalized.strip()


def _request_actor(request: Request) -> dict[str, Any]:
    headers = request.headers
    user = str(headers.get("x-auth-request-user") or "").strip()
    email = str(headers.get("x-auth-request-email") or "").strip().lower()
    groups = _csv_set(headers.get("x-auth-request-groups"))
    return {
        "user": user,
        "email": email,
        "groups": sorted(groups),
        "remote_addr": (
            request.client.host
            if request.client is not None and request.client.host
            else None
        ),
    }


def _admin_group_allowlist() -> set[str]:
    default = "sra-admins"
    return _csv_set(os.getenv("AUTHZ_ADMIN_GROUP_ALLOWLIST", default))


def _admin_email_allowlist() -> set[str]:
    return _csv_set(os.getenv("AUTHZ_ADMIN_EMAIL_ALLOWLIST"))


def _admin_user_allowlist() -> set[str]:
    return _csv_set(os.getenv("AUTHZ_ADMIN_USER_ALLOWLIST"))


def _admin_bearer_token() -> str:
    return str(os.getenv("AUTHZ_ADMIN_BEARER_TOKEN") or "").strip()


def _is_admin_authorized(request: Request, actor: dict[str, Any]) -> bool:
    if _is_true(os.getenv("AUTHZ_ALLOW_ALL_WRITES")):
        return True

    configured_token = _admin_bearer_token()
    if configured_token:
        auth_header = str(request.headers.get("authorization") or "").strip()
        prefix = "bearer "
        if auth_header.lower().startswith(prefix):
            provided_token = auth_header[len(prefix) :].strip()
            if provided_token and provided_token == configured_token:
                return True

    user = str(actor.get("user") or "").strip().lower()
    email = str(actor.get("email") or "").strip().lower()
    groups = {str(item).strip().lower() for item in actor.get("groups") or []}

    if user and user in _admin_user_allowlist():
        return True
    if email and email in _admin_email_allowlist():
        return True
    if groups and _admin_group_allowlist().intersection(groups):
        return True
    return False


def _require_admin_write(request: Request) -> dict[str, Any]:
    actor = _request_actor(request)
    if _is_admin_authorized(request, actor):
        return actor
    raise HTTPException(status_code=403, detail="Not authorized to manage authz policy")


def _require_read_access(request: Request) -> dict[str, Any]:
    actor = _request_actor(request)
    if not _is_true(os.getenv("AUTHZ_REQUIRE_AUTH_FOR_READ")):
        return actor
    if actor.get("user") or actor.get("email"):
        return actor
    if _is_admin_authorized(request, actor):
        return actor
    raise HTTPException(status_code=401, detail="Authentication required")


def _append_audit_event(event: dict[str, Any]) -> None:
    path = _audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        **event,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def _recent_audit_events(*, limit: int) -> list[dict[str, Any]]:
    path = _audit_log_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    tail = lines[-limit:] if limit > 0 else []
    events: list[dict[str, Any]] = []
    for line in tail:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


class PolicyUpdateRequest(BaseModel):
    policy_yaml: str = Field(min_length=1)


class PolicyValidateRequest(BaseModel):
    policy_yaml: str = Field(min_length=1)


app = FastAPI(title="sandboxed-react-agent-authz", version="0.2.0")

cors_allow_origins = os.getenv("AUTHZ_CORS_ALLOW_ORIGINS", "").strip()
if cors_allow_origins:
    origins = [item.strip() for item in cors_allow_origins.split(",") if item.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/policy/current")
def get_policy(request: Request, response: Response) -> dict[str, Any]:
    _require_read_access(request)
    policy_yaml = _read_policy_text()
    parsed = _validate_policy_yaml(policy_yaml)
    sha256 = _etag_for(policy_yaml)
    response.headers["ETag"] = f'"{sha256}"'
    return {
        "version": int(parsed.get("version") or 1),
        "loaded_at": datetime.now(UTC).isoformat(),
        "sha256": sha256,
        "policy_yaml": policy_yaml,
    }


@app.put("/api/policy/current")
def update_policy(
    payload: PolicyUpdateRequest,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    actor = _require_admin_write(request)
    previous_yaml = _read_policy_text()
    previous_sha = _etag_for(previous_yaml)
    match_value = _normalize_if_match(if_match)
    if match_value and match_value != "*" and match_value != previous_sha:
        _append_audit_event(
            {
                "action": "policy.update",
                "result": "conflict",
                "reason": "if_match_mismatch",
                "actor": actor,
                "if_match": match_value,
                "current_sha256": previous_sha,
            }
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Policy was updated by another actor",
                "current_sha256": previous_sha,
            },
        )
    try:
        _write_policy_text(payload.policy_yaml)
    except HTTPException as exc:
        _append_audit_event(
            {
                "action": "policy.update",
                "result": "rejected",
                "actor": actor,
                "error": exc.detail,
            }
        )
        raise

    policy_yaml = _read_policy_text()
    parsed = _validate_policy_yaml(policy_yaml)
    sha256 = _etag_for(policy_yaml)
    response.headers["ETag"] = f'"{sha256}"'
    _append_audit_event(
        {
            "action": "policy.update",
            "result": "success",
            "actor": actor,
            "previous_sha256": previous_sha,
            "sha256": sha256,
            "version": int(parsed.get("version") or 1),
        }
    )
    return {
        "updated": True,
        "version": int(parsed.get("version") or 1),
        "sha256": sha256,
    }


@app.post("/api/policy/validate")
def validate_policy(payload: PolicyValidateRequest, request: Request) -> dict[str, Any]:
    actor = _require_admin_write(request)
    parsed = _validate_policy_yaml(payload.policy_yaml)
    sha256 = _etag_for(payload.policy_yaml)
    _append_audit_event(
        {
            "action": "policy.validate",
            "result": "success",
            "actor": actor,
            "sha256": sha256,
            "version": int(parsed.get("version") or 1),
        }
    )
    return {
        "valid": True,
        "version": int(parsed.get("version") or 1),
        "sha256": sha256,
    }


@app.get("/api/policy/audit")
def get_policy_audit(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    _require_admin_write(request)
    return {"events": _recent_audit_events(limit=limit)}

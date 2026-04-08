import asyncio
import logging
import os
import time
import uuid
from typing import Any

from assistant_stream import create_run
from assistant_stream.serialization import DataStreamResponse
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .app_factory import create_app_runtime
from .auth import (
    authenticate_request,
    ensure_anonymous_user_id,
)
from .logging_config import bind_context, configure_logging


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ConfigUpdateRequest(BaseModel):
    agent: dict[str, Any] | None = None
    toolkits: dict[str, Any] | None = None
    model: str | None = None
    max_tool_calls_per_turn: int | None = Field(default=None, ge=1, le=20)
    sandbox_mode: str | None = None
    sandbox_profile: str | None = None
    sandbox_api_url: str | None = None
    sandbox_template_name: str | None = None
    sandbox_namespace: str | None = None
    sandbox_server_port: int | None = Field(default=None, ge=1, le=65535)
    sandbox_max_output_chars: int | None = Field(default=None, ge=100, le=100000)
    sandbox_local_timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    sandbox_execution_model: str | None = None
    sandbox_session_idle_ttl_seconds: int | None = Field(default=None, ge=1, le=86400)


class MessagePart(BaseModel):
    type: str
    text: str | None = None
    image: str | None = None


class UserMessage(BaseModel):
    role: str = "user"
    parts: list[MessagePart] = Field(default_factory=list)
    content: list[MessagePart] = Field(default_factory=list)
    id: str | None = None


class AddMessageCommand(BaseModel):
    type: str = "add-message"
    message: UserMessage
    parentId: str | None = None
    sourceId: str | None = None


class AddToolResultCommand(BaseModel):
    type: str = "add-tool-result"
    toolCallId: str
    result: dict[str, Any]


class AssistantTransportRequest(BaseModel):
    commands: list[AddMessageCommand | AddToolResultCommand] = Field(
        default_factory=list
    )
    state: dict[str, Any] | None = None
    system: str | None = None
    tools: dict[str, Any] | None = None
    threadId: str | None = None
    runConfig: dict[str, Any] | None = None


class SessionCreateRequest(BaseModel):
    title: str | None = None


class SandboxReleaseResponse(BaseModel):
    lease_id: str
    released: bool


class WorkspaceEnsureRequest(BaseModel):
    wait: bool = False


class WorkspaceDeleteRequest(BaseModel):
    delete_data: bool = False


class SessionSandboxPolicyPatchRequest(BaseModel):
    clear: bool = False
    mode: str | None = None
    profile: str | None = None
    template_name: str | None = None
    namespace: str | None = None
    execution_model: str | None = None
    session_idle_ttl_seconds: int | None = Field(default=None, ge=1, le=86400)


class SessionSandboxActionRequest(BaseModel):
    action: str
    wait: bool = False


configure_logging()
logger = logging.getLogger(__name__)
runtime = create_app_runtime()
app = runtime.app
agent = runtime.agent
auth_config = runtime.auth_config
token_verifier = runtime.token_verifier
anon_identity_config = runtime.anon_identity_config


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env_set(name: str) -> set[str]:
    raw = str(os.getenv(name, "") or "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


OPS_ADMIN_USER_ID_ALLOWLIST = _csv_env_set("OPS_ADMIN_USER_ID_ALLOWLIST")
OPS_ADMIN_EMAIL_ALLOWLIST = _csv_env_set("OPS_ADMIN_EMAIL_ALLOWLIST")
OPS_ADMIN_GROUP_ALLOWLIST = _csv_env_set("OPS_ADMIN_GROUP_ALLOWLIST")
OPS_ADMIN_ALLOW_ALL_AUTHENTICATED = _as_bool(
    os.getenv("OPS_ADMIN_ALLOW_ALL_AUTHENTICATED"),
    default=False,
)


def _request_user_id(request: Request) -> str:
    user_id = str(getattr(request.state, "auth_user_id", "") or "").strip()
    if not user_id and not auth_config.enabled:
        user_id = (os.getenv("AUTH_DEV_USER_ID") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user identity")
    return user_id


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
        return {str(item).strip().lower() for item in raw if str(item).strip()}
    if isinstance(raw, str) and raw.strip():
        return {item.strip().lower() for item in raw.split(",") if item.strip()}
    return set()


def _require_ops_admin(request: Request) -> None:
    user_id = _request_user_id(request)
    if not auth_config.enabled:
        return
    if OPS_ADMIN_ALLOW_ALL_AUTHENTICATED:
        return

    claims = getattr(request.state, "auth_claims", {})
    claims_dict = claims if isinstance(claims, dict) else {}
    email = _claim_email(claims_dict)
    groups = _claim_groups(claims_dict)

    by_user_id = bool(OPS_ADMIN_USER_ID_ALLOWLIST) and (
        user_id.strip().lower() in OPS_ADMIN_USER_ID_ALLOWLIST
    )
    by_email = bool(OPS_ADMIN_EMAIL_ALLOWLIST) and (email in OPS_ADMIN_EMAIL_ALLOWLIST)
    by_group = bool(OPS_ADMIN_GROUP_ALLOWLIST) and bool(
        OPS_ADMIN_GROUP_ALLOWLIST.intersection(groups)
    )

    if by_user_id or by_email or by_group:
        return

    raise HTTPException(
        status_code=403,
        detail=(
            "Token is valid but not authorized for admin ops endpoints. "
            "Configure OPS_ADMIN_* allowlists."
        ),
    )


def _extract_transport_session_id(payload: AssistantTransportRequest) -> str | None:
    if isinstance(payload.state, dict):
        maybe_session_id = payload.state.get("session_id")
        if isinstance(maybe_session_id, str) and maybe_session_id:
            return maybe_session_id
    if isinstance(payload.threadId, str) and payload.threadId:
        return payload.threadId
    return None


def _asset_security_headers(asset: dict[str, Any]) -> dict[str, str]:
    if not str(asset.get("mime_type") or "").startswith("text/html"):
        return {}
    return {
        "Content-Security-Policy": (
            "default-src 'none'; "
            "script-src 'self' 'unsafe-inline' https:; "
            "style-src 'unsafe-inline' https:; "
            "img-src data: blob: https: http:; "
            "font-src data: https:; "
            "connect-src https: http:; "
            "frame-ancestors 'self'; "
            "base-uri 'none'; "
            "form-action 'none'"
        ),
        "X-Frame-Options": "SAMEORIGIN",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    try:
        if auth_config.enabled:
            await authenticate_request(
                request,
                config=auth_config,
                verifier=token_verifier,
            )
        elif request.url.path.startswith("/api/"):
            user_id, signed_cookie = ensure_anonymous_user_id(
                request,
                config=anon_identity_config,
            )
            request.state.auth_user_id = user_id
            request.state.auth_subject = user_id
            request.state.anon_identity_cookie = signed_cookie
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    response = await call_next(request)
    signed_cookie = str(getattr(request.state, "anon_identity_cookie", "") or "")
    if signed_cookie:
        response.set_cookie(
            key=anon_identity_config.cookie_name,
            value=signed_cookie,
            httponly=True,
            secure=anon_identity_config.secure_cookie,
            samesite=anon_identity_config.same_site,
            path="/",
            max_age=60 * 60 * 24 * 365,
        )
    return response


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request_start = time.perf_counter()
    client_ip = request.client.host if request.client else "unknown"

    with bind_context(request_id=request_id):
        logger.info(
            "request.start",
            extra={
                "event": "request.start",
                "method": request.method,
                "path": request.url.path,
                "client_ip": client_ip,
                "user_agent": request.headers.get("user-agent", ""),
            },
        )
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = int((time.perf_counter() - request_start) * 1000)
            logger.exception(
                "request.error",
                extra={
                    "event": "request.error",
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": elapsed_ms,
                },
            )
            raise

        elapsed_ms = int((time.perf_counter() - request_start) * 1000)
        response.headers["x-request-id"] = request_id
        logger.info(
            "request.end",
            extra={
                "event": "request.end",
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": elapsed_ms,
            },
        )
        return response


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(payload: ChatRequest, request: Request) -> dict:
    user_id = _request_user_id(request)
    try:
        with bind_context(session_id=payload.session_id):
            result = await asyncio.to_thread(
                agent.chat,
                user_message=payload.message,
                session_id=payload.session_id,
                user_id=user_id,
            )
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    logger.info(
        "chat.completed",
        extra={
            "event": "chat.completed",
            "session_id": result.get("session_id"),
            "has_error": bool(result.get("error")),
            "tool_call_count": len(result.get("tool_calls") or []),
            "reply_len": len(result.get("reply") or ""),
        },
    )
    return result


@app.post("/api/assistant")
async def assistant(payload: AssistantTransportRequest, request: Request):
    user_id = _request_user_id(request)
    existing_session_id = _extract_transport_session_id(payload)
    if existing_session_id and not agent.get_session(existing_session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found")

    async def run_callback(controller):
        await agent.run_assistant_transport(payload, controller, user_id)

    stream = create_run(run_callback, state=payload.state)
    return DataStreamResponse(stream)


@app.get("/api/state")
def state(request: Request) -> dict:
    user_id = _request_user_id(request)
    return agent.get_state_summary(user_id=user_id)


@app.get("/api/me")
def me(request: Request) -> dict[str, str]:
    user_id = _request_user_id(request)
    profile = agent.get_user_profile(user_id)
    return {
        "user_id": user_id,
        "tier": str(profile.get("tier") or "default"),
    }


@app.get("/api/config")
def get_config(request: Request) -> dict:
    user_id = _request_user_id(request)
    return agent.get_runtime_config(user_id)


@app.get("/api/workspace")
def get_workspace(request: Request) -> dict[str, Any]:
    user_id = _request_user_id(request)
    workspace = agent.get_workspace(user_id)
    return {"workspace": workspace}


@app.get("/api/workspace/status")
def get_workspace_status(request: Request) -> dict[str, Any]:
    user_id = _request_user_id(request)
    return agent.get_workspace_status(user_id)


@app.post("/api/workspace")
def ensure_workspace(
    payload: WorkspaceEnsureRequest, request: Request
) -> dict[str, Any]:
    user_id = _request_user_id(request)
    try:
        if payload.wait:
            workspace = agent.ensure_workspace(user_id)
            return {"workspace": workspace, "started": False}
        workspace, started = agent.ensure_workspace_async(user_id)
        return {"workspace": workspace, "started": started}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.delete("/api/workspace")
def delete_workspace(
    payload: WorkspaceDeleteRequest, request: Request
) -> dict[str, Any]:
    user_id = _request_user_id(request)
    try:
        deleted = agent.delete_workspace(user_id, delete_data=payload.delete_data)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"deleted": deleted, "delete_data": payload.delete_data}


@app.post("/api/config")
def update_config(payload: ConfigUpdateRequest, request: Request) -> dict:
    user_id = _request_user_id(request)
    try:
        result = agent.update_runtime_config(
            user_id=user_id,
            agent=payload.agent,
            toolkits=payload.toolkits,
            model=payload.model,
            max_tool_calls_per_turn=payload.max_tool_calls_per_turn,
            sandbox_mode=payload.sandbox_mode,
            sandbox_profile=payload.sandbox_profile,
            sandbox_api_url=payload.sandbox_api_url,
            sandbox_template_name=payload.sandbox_template_name,
            sandbox_namespace=payload.sandbox_namespace,
            sandbox_server_port=payload.sandbox_server_port,
            sandbox_max_output_chars=payload.sandbox_max_output_chars,
            sandbox_local_timeout_seconds=payload.sandbox_local_timeout_seconds,
            sandbox_execution_model=payload.sandbox_execution_model,
            sandbox_session_idle_ttl_seconds=payload.sandbox_session_idle_ttl_seconds,
        )
        logger.info(
            "config.updated",
            extra={
                "event": "config.updated",
                "updated_fields": [
                    key
                    for key, value in payload.model_dump().items()
                    if value is not None
                ],
            },
        )
        return result
    except ValueError as exc:
        logger.warning(
            "config.update_failed",
            extra={"event": "config.update_failed", "error": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/reset")
def reset_session(session_id: str, request: Request) -> dict:
    user_id = _request_user_id(request)
    removed = agent.reset_session(session_id, user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "reset": True}


@app.get("/api/sessions")
def list_sessions(request: Request) -> dict[str, Any]:
    user_id = _request_user_id(request)
    return {"sessions": agent.list_sessions(user_id)}


@app.post("/api/sessions")
def create_session(payload: SessionCreateRequest, request: Request) -> dict[str, Any]:
    user_id = _request_user_id(request)
    session = agent.create_session(title=payload.title, user_id=user_id)
    return {
        "session_id": session.session_id,
        "title": session.title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "messages": session.ui_messages,
    }


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict[str, Any]:
    user_id = _request_user_id(request)
    session = agent.get_session(session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.get("/api/sessions/{session_id}/sandbox")
def get_session_sandbox(session_id: str, request: Request) -> dict[str, Any]:
    user_id = _request_user_id(request)
    session = agent.get_session(session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "sandbox": agent.get_session_sandbox(session_id),
    }


@app.get("/api/sessions/{session_id}/sandbox/status")
def get_session_sandbox_status(session_id: str, request: Request) -> dict[str, Any]:
    user_id = _request_user_id(request)
    session = agent.get_session(session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return agent.get_session_sandbox_status(session_id, user_id)
    except PermissionError:
        raise HTTPException(status_code=404, detail="Session not found")


@app.get("/api/sessions/{session_id}/sandbox/policy")
def get_session_sandbox_policy(session_id: str, request: Request) -> dict[str, Any]:
    user_id = _request_user_id(request)
    session = agent.get_session(session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return {
            "session_id": session_id,
            "sandbox_policy": agent.get_session_sandbox_policy(session_id, user_id),
        }
    except PermissionError:
        raise HTTPException(status_code=404, detail="Session not found")


@app.patch("/api/sessions/{session_id}/sandbox/policy")
def patch_session_sandbox_policy(
    session_id: str,
    payload: SessionSandboxPolicyPatchRequest,
    request: Request,
) -> dict[str, Any]:
    user_id = _request_user_id(request)
    session = agent.get_session(session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        result = agent.update_session_sandbox_policy(
            session_id,
            user_id,
            payload.model_dump(exclude={"clear"}, exclude_none=True),
            clear=payload.clear,
        )
        result["status"] = agent.get_session_sandbox_status(session_id, user_id)
        return result
    except PermissionError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/sessions/{session_id}/sandbox/actions")
def session_sandbox_action(
    session_id: str,
    payload: SessionSandboxActionRequest,
    request: Request,
) -> dict[str, Any]:
    user_id = _request_user_id(request)
    session = agent.get_session(session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return agent.perform_session_sandbox_action(
            session_id,
            user_id,
            action=payload.action,
            wait=payload.wait,
        )
    except PermissionError:
        raise HTTPException(status_code=404, detail="Session not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/sessions/{session_id}/share")
def share_session(session_id: str, request: Request) -> dict[str, str]:
    user_id = _request_user_id(request)
    share_id = agent.create_share(session_id, user_id)
    if not share_id:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "share_id": share_id,
        "share_path": f"/public/{share_id}",
    }


@app.get("/api/public/{share_id}")
def get_public_session(share_id: str) -> dict[str, Any]:
    session = agent.get_shared_session(share_id)
    if not session:
        raise HTTPException(status_code=404, detail="Shared session not found")
    return session


@app.get("/api/public/{share_id}/markdown")
def get_public_session_markdown(share_id: str) -> PlainTextResponse:
    markdown = agent.get_shared_session_markdown(share_id)
    if markdown is None:
        raise HTTPException(status_code=404, detail="Shared session not found")
    return PlainTextResponse(markdown, media_type="text/markdown")


@app.get("/api/assets/{asset_id}")
def get_asset(asset_id: str, request: Request):
    user_id = _request_user_id(request)
    asset = agent.asset_manager.get_asset_for_user(asset_id, user_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    headers = _asset_security_headers(asset)
    return FileResponse(
        asset["storage_path"], media_type=asset["mime_type"], headers=headers
    )


@app.get("/api/assets/{asset_id}/download")
def download_asset(asset_id: str, request: Request):
    user_id = _request_user_id(request)
    asset = agent.asset_manager.get_asset_for_user(asset_id, user_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(
        asset["storage_path"],
        media_type=asset["mime_type"],
        filename=asset["filename"],
    )


@app.get("/api/admin/ops/sandbox-index")
def get_admin_sandbox_index(
    request: Request,
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, Any]:
    _require_ops_admin(request)
    return agent.get_admin_sandbox_index(limit=limit)


@app.get("/api/admin/ops/lease-analytics")
def get_admin_lease_analytics(
    request: Request,
    days: int = Query(default=14, ge=1, le=90),
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict[str, Any]:
    _require_ops_admin(request)
    return agent.get_admin_lease_analytics(days=days, limit=limit)


@app.get("/api/admin/ops/workspace-jobs")
def get_admin_workspace_jobs(
    request: Request,
    limit: int = Query(default=200, ge=1, le=2000),
    include_terminal: bool = Query(default=True),
) -> dict[str, Any]:
    _require_ops_admin(request)
    return agent.get_admin_workspace_jobs(
        limit=limit,
        include_terminal=include_terminal,
    )


@app.get("/api/public/{share_id}/assets/{asset_id}")
def get_public_asset(share_id: str, asset_id: str):
    asset = agent.asset_manager.get_asset_for_share(asset_id, share_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    headers = _asset_security_headers(asset)
    return FileResponse(
        asset["storage_path"], media_type=asset["mime_type"], headers=headers
    )


@app.get("/api/public/{share_id}/assets/{asset_id}/download")
def download_public_asset(share_id: str, asset_id: str):
    asset = agent.asset_manager.get_asset_for_share(asset_id, share_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(
        asset["storage_path"],
        media_type=asset["mime_type"],
        filename=asset["filename"],
    )


@app.get("/api/sandboxes")
def list_sandboxes() -> dict[str, Any]:
    """List active sandbox lease records."""
    return {"sandboxes": agent.list_sandboxes()}


@app.get("/api/sandboxes/{lease_id}")
def get_sandbox(lease_id: str) -> dict[str, Any]:
    """Fetch one sandbox lease record by id."""
    sandbox = agent.get_sandbox(lease_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox lease not found")
    return sandbox


@app.post("/api/sandboxes/{lease_id}/release", response_model=SandboxReleaseResponse)
def release_sandbox(lease_id: str) -> SandboxReleaseResponse:
    """Release a currently active sandbox lease."""
    released = agent.release_sandbox(lease_id)
    if not released:
        raise HTTPException(status_code=404, detail="Sandbox lease not found")
    return SandboxReleaseResponse(lease_id=lease_id, released=True)

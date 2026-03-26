import asyncio
import logging
import time
import uuid
from typing import Any

from assistant_stream import create_run
from assistant_stream.serialization import DataStreamResponse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .agent import SandboxedReactAgent
from .auth import AuthConfig, TokenVerifier, authenticate_request
from .logging_config import bind_context, configure_logging
from .tracing import init_tracing


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ConfigUpdateRequest(BaseModel):
    model: str | None = None
    max_tool_calls_per_turn: int | None = Field(default=None, ge=1, le=20)
    sandbox_mode: str | None = None
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


configure_logging()
logger = logging.getLogger(__name__)
agent = SandboxedReactAgent()
app = FastAPI(title="sandboxed-react-agent-backend", version="0.1.0")
init_tracing(app)
auth_config = AuthConfig.from_env()
token_verifier = TokenVerifier(auth_config)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    try:
        await authenticate_request(
            request,
            config=auth_config,
            verifier=token_verifier,
        )
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


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
async def chat(payload: ChatRequest) -> dict:
    with bind_context(session_id=payload.session_id):
        result = await asyncio.to_thread(
            agent.chat, user_message=payload.message, session_id=payload.session_id
        )

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
async def assistant(payload: AssistantTransportRequest):
    async def run_callback(controller):
        await agent.run_assistant_transport(payload, controller)

    stream = create_run(run_callback, state=payload.state)
    return DataStreamResponse(stream)


@app.get("/api/state")
def state() -> dict:
    return agent.get_state_summary()


@app.get("/api/config")
def get_config() -> dict:
    return agent.get_runtime_config()


@app.post("/api/config")
def update_config(payload: ConfigUpdateRequest) -> dict:
    try:
        result = agent.update_runtime_config(
            model=payload.model,
            max_tool_calls_per_turn=payload.max_tool_calls_per_turn,
            sandbox_mode=payload.sandbox_mode,
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
def reset_session(session_id: str) -> dict:
    removed = agent.reset_session(session_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "reset": True}


@app.get("/api/sessions")
def list_sessions() -> dict[str, Any]:
    return {"sessions": agent.list_sessions()}


@app.post("/api/sessions")
def create_session(payload: SessionCreateRequest) -> dict[str, Any]:
    session = agent.create_session(title=payload.title)
    return {
        "session_id": session.session_id,
        "title": session.title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "messages": session.ui_messages,
    }


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    session = agent.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.get("/api/sessions/{session_id}/sandbox")
def get_session_sandbox(session_id: str) -> dict[str, Any]:
    session = agent.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "sandbox": agent.get_session_sandbox(session_id),
    }


@app.post("/api/sessions/{session_id}/share")
def share_session(session_id: str) -> dict[str, str]:
    share_id = agent.create_share(session_id)
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
def get_asset(asset_id: str):
    asset = agent.asset_manager.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    headers: dict[str, str] = {}
    if str(asset.get("mime_type") or "").startswith("text/html"):
        headers = {
            "Content-Security-Policy": (
                "default-src 'none'; "
                "script-src 'unsafe-inline' https:; "
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
    return FileResponse(
        asset["storage_path"], media_type=asset["mime_type"], headers=headers
    )


@app.get("/api/assets/{asset_id}/download")
def download_asset(asset_id: str):
    asset = agent.asset_manager.get_asset(asset_id)
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

import asyncio
from typing import Any

from assistant_stream import create_run
from assistant_stream.serialization import DataStreamResponse
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .agent import SandboxedReactAgent


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


agent = SandboxedReactAgent()
app = FastAPI(title="sandboxed-react-agent-backend", version="0.1.0")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict:
    return await asyncio.to_thread(
        agent.chat, user_message=payload.message, session_id=payload.session_id
    )


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
        return agent.update_runtime_config(
            model=payload.model,
            max_tool_calls_per_turn=payload.max_tool_calls_per_turn,
            sandbox_mode=payload.sandbox_mode,
            sandbox_api_url=payload.sandbox_api_url,
            sandbox_template_name=payload.sandbox_template_name,
            sandbox_namespace=payload.sandbox_namespace,
            sandbox_server_port=payload.sandbox_server_port,
            sandbox_max_output_chars=payload.sandbox_max_output_chars,
            sandbox_local_timeout_seconds=payload.sandbox_local_timeout_seconds,
        )
    except ValueError as exc:
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
    return FileResponse(asset["storage_path"], media_type=asset["mime_type"])


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

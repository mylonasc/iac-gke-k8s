from fastapi import FastAPI, HTTPException
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


agent = SandboxedReactAgent()
app = FastAPI(title="sandboxed-react-agent-backend", version="0.1.0")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat")
def chat(payload: ChatRequest) -> dict:
    return agent.chat(user_message=payload.message, session_id=payload.session_id)


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

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from .sandbox_manager import SandboxManager


SYSTEM_PROMPT = (
    "You are a helpful coding agent. "
    "When the user asks to run code or inspect runtime behavior, prefer tools. "
    "Keep responses concise and include key findings from tool outputs. "
    "For simple computations, run one tool call at most, then provide the final answer."
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "sandbox_exec_python",
            "description": "Run Python code in an isolated Agent Sandbox runtime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute.",
                    }
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_exec_shell",
            "description": "Run a shell command in an isolated Agent Sandbox runtime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute.",
                    }
                },
                "required": ["command"],
            },
        },
    },
]


@dataclass
class SessionState:
    session_id: str
    created_at: str
    updated_at: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: int = 0
    last_error: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SandboxedReactAgent:
    def __init__(self) -> None:
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.max_tool_calls_per_turn = int(
            os.getenv("AGENT_MAX_TOOL_CALLS_PER_TURN", "4")
        )
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.sandbox_manager = SandboxManager()
        self.sessions: dict[str, SessionState] = {}

    def get_runtime_config(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tool_calls_per_turn": self.max_tool_calls_per_turn,
            "sandbox": self.sandbox_manager.get_config(),
        }

    def update_runtime_config(
        self,
        model: str | None = None,
        max_tool_calls_per_turn: int | None = None,
        sandbox_mode: str | None = None,
        sandbox_api_url: str | None = None,
        sandbox_template_name: str | None = None,
        sandbox_namespace: str | None = None,
        sandbox_server_port: int | None = None,
        sandbox_max_output_chars: int | None = None,
        sandbox_local_timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        if model is not None:
            self.model = model
        if max_tool_calls_per_turn is not None:
            if max_tool_calls_per_turn < 1:
                raise ValueError("max_tool_calls_per_turn must be >= 1")
            self.max_tool_calls_per_turn = max_tool_calls_per_turn

        self.sandbox_manager.update_config(
            mode=sandbox_mode,
            api_url=sandbox_api_url,
            template_name=sandbox_template_name,
            namespace=sandbox_namespace,
            server_port=sandbox_server_port,
            max_output_chars=sandbox_max_output_chars,
            local_timeout_seconds=sandbox_local_timeout_seconds,
        )

        return self.get_runtime_config()

    def create_session(self) -> SessionState:
        session_id = str(uuid.uuid4())
        now = _now_iso()
        state = SessionState(
            session_id=session_id,
            created_at=now,
            updated_at=now,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}],
        )
        self.sessions[session_id] = state
        return state

    def get_or_create_session(self, session_id: str | None) -> SessionState:
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        return self.create_session()

    def _run_tool(self, name: str, arguments_json: str) -> str:
        parsed = json.loads(arguments_json or "{}")
        if name == "sandbox_exec_python":
            code = parsed.get("code", "")
            return self.sandbox_manager.exec_python(code).as_tool_payload()
        if name == "sandbox_exec_shell":
            command = parsed.get("command", "")
            return self.sandbox_manager.exec_shell(command).as_tool_payload()
        return json.dumps({"ok": False, "error": f"Unsupported tool: {name}"})

    def chat(self, user_message: str, session_id: str | None = None) -> dict[str, Any]:
        state = self.get_or_create_session(session_id)
        state.updated_at = _now_iso()
        state.messages.append({"role": "user", "content": user_message})

        turn_tool_calls: list[dict[str, Any]] = []

        try:
            for _ in range(self.max_tool_calls_per_turn + 1):
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=state.messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.2,
                )

                assistant_message = completion.choices[0].message
                tool_calls = assistant_message.tool_calls or []

                if not tool_calls:
                    final_text = assistant_message.content or ""
                    state.messages.append({"role": "assistant", "content": final_text})
                    state.updated_at = _now_iso()
                    return {
                        "session_id": state.session_id,
                        "reply": final_text,
                        "tool_calls": turn_tool_calls,
                    }

                assistant_payload = {
                    "role": "assistant",
                    "content": assistant_message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
                state.messages.append(assistant_payload)

                for tc in tool_calls:
                    if len(turn_tool_calls) >= self.max_tool_calls_per_turn:
                        state.last_error = "Tool-calling loop exhausted max tool calls"
                        return {
                            "session_id": state.session_id,
                            "reply": "I hit the tool-calling safety limit for this turn.",
                            "tool_calls": turn_tool_calls,
                            "error": state.last_error,
                        }

                    output = self._run_tool(tc.function.name, tc.function.arguments)
                    turn_tool_calls.append(
                        {
                            "tool": tc.function.name,
                            "arguments": tc.function.arguments,
                            "result": output,
                        }
                    )
                    state.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": output,
                        }
                    )
                    state.tool_calls += 1

            state.last_error = "Tool-calling loop exhausted max iterations"
            return {
                "session_id": state.session_id,
                "reply": "I hit the tool-calling safety limit for this turn.",
                "tool_calls": turn_tool_calls,
                "error": state.last_error,
            }
        except Exception as exc:
            state.last_error = str(exc)
            return {
                "session_id": state.session_id,
                "reply": "The agent failed while processing your request.",
                "tool_calls": turn_tool_calls,
                "error": state.last_error,
            }

    def get_state_summary(self) -> dict[str, Any]:
        return {
            "session_count": len(self.sessions),
            "sessions": [
                {
                    "session_id": s.session_id,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                    "message_count": len(s.messages),
                    "tool_calls": s.tool_calls,
                    "last_error": s.last_error,
                }
                for s in self.sessions.values()
            ],
            "sandbox": {
                "mode": self.sandbox_manager.mode,
                "api_url": self.sandbox_manager.api_url,
                "template_name": self.sandbox_manager.template_name,
                "namespace": self.sandbox_manager.namespace,
                "execution_model": "ephemeral-per-tool-call",
            },
            "runtime_config": self.get_runtime_config(),
        }

    def reset_session(self, session_id: str) -> bool:
        if session_id not in self.sessions:
            return False
        del self.sessions[session_id]
        return True

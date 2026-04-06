import json
from datetime import datetime, timezone
from typing import Any, Callable

from .users import SQLiteUserStore


class SQLiteUserConfigStore:
    def __init__(
        self, connect: Callable[[], object], user_store: SQLiteUserStore
    ) -> None:
        self.connect = connect
        self.user_store = user_store

    def get_user_config(self, user_id: str) -> dict[str, Any] | None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM user_configs WHERE user_id = ?", (normalized_user_id,)
            ).fetchone()
        if not row:
            return None
        config_json = row["config_json"] if "config_json" in row.keys() else None
        if config_json:
            parsed = json.loads(config_json)
            if isinstance(parsed, dict):
                return parsed
        return self._legacy_runtime_config_from_row(row)

    def upsert_user_config(self, user_id: str, config: dict[str, Any]) -> None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        self.user_store.ensure_user(normalized_user_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        legacy = self._legacy_columns_from_runtime_config(config)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_configs (
                    user_id,
                    model,
                    max_tool_calls_per_turn,
                    sandbox_mode,
                    sandbox_api_url,
                    sandbox_template_name,
                    sandbox_namespace,
                    sandbox_server_port,
                    sandbox_max_output_chars,
                    sandbox_local_timeout_seconds,
                    sandbox_execution_model,
                    sandbox_session_idle_ttl_seconds,
                    config_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    model=excluded.model,
                    max_tool_calls_per_turn=excluded.max_tool_calls_per_turn,
                    sandbox_mode=excluded.sandbox_mode,
                    sandbox_api_url=excluded.sandbox_api_url,
                    sandbox_template_name=excluded.sandbox_template_name,
                    sandbox_namespace=excluded.sandbox_namespace,
                    sandbox_server_port=excluded.sandbox_server_port,
                    sandbox_max_output_chars=excluded.sandbox_max_output_chars,
                    sandbox_local_timeout_seconds=excluded.sandbox_local_timeout_seconds,
                    sandbox_execution_model=excluded.sandbox_execution_model,
                    sandbox_session_idle_ttl_seconds=excluded.sandbox_session_idle_ttl_seconds,
                    config_json=excluded.config_json,
                    updated_at=excluded.updated_at
                """,
                (
                    normalized_user_id,
                    str(legacy["model"]),
                    int(legacy["max_tool_calls_per_turn"]),
                    str(legacy["sandbox_mode"]),
                    str(legacy["sandbox_api_url"]),
                    str(legacy["sandbox_template_name"]),
                    str(legacy["sandbox_namespace"]),
                    int(legacy["sandbox_server_port"]),
                    int(legacy["sandbox_max_output_chars"]),
                    int(legacy["sandbox_local_timeout_seconds"]),
                    str(legacy["sandbox_execution_model"]),
                    int(legacy["sandbox_session_idle_ttl_seconds"]),
                    json.dumps(config, ensure_ascii=True),
                    now_iso,
                    now_iso,
                ),
            )

    def _legacy_runtime_config_from_row(self, row: Any) -> dict[str, Any]:
        return {
            "agent": {
                "model": row["model"],
                "max_tool_calls_per_turn": int(row["max_tool_calls_per_turn"]),
                "enabled_toolkits": ["sandbox"],
            },
            "toolkits": {
                "sandbox": {
                    "enabled": True,
                    "runtime": {
                        "mode": row["sandbox_mode"],
                        "api_url": row["sandbox_api_url"],
                        "template_name": row["sandbox_template_name"],
                        "namespace": row["sandbox_namespace"],
                        "server_port": int(row["sandbox_server_port"]),
                        "max_output_chars": int(row["sandbox_max_output_chars"]),
                        "local_timeout_seconds": int(
                            row["sandbox_local_timeout_seconds"]
                        ),
                    },
                    "lifecycle": {
                        "execution_model": row["sandbox_execution_model"],
                        "session_idle_ttl_seconds": int(
                            row["sandbox_session_idle_ttl_seconds"]
                        ),
                    },
                }
            },
        }

    def _legacy_columns_from_runtime_config(
        self, config: dict[str, Any]
    ) -> dict[str, Any]:
        if "agent" not in config or "toolkits" not in config:
            return {
                "model": config["model"],
                "max_tool_calls_per_turn": int(config["max_tool_calls_per_turn"]),
                "sandbox_mode": config["sandbox_mode"],
                "sandbox_api_url": config["sandbox_api_url"],
                "sandbox_template_name": config["sandbox_template_name"],
                "sandbox_namespace": config["sandbox_namespace"],
                "sandbox_server_port": int(config["sandbox_server_port"]),
                "sandbox_max_output_chars": int(config["sandbox_max_output_chars"]),
                "sandbox_local_timeout_seconds": int(
                    config["sandbox_local_timeout_seconds"]
                ),
                "sandbox_execution_model": config["sandbox_execution_model"],
                "sandbox_session_idle_ttl_seconds": int(
                    config["sandbox_session_idle_ttl_seconds"]
                ),
            }

        agent = config.get("agent") or {}
        sandbox = (config.get("toolkits") or {}).get("sandbox") or {}
        sandbox_runtime = sandbox.get("runtime") or {}
        sandbox_lifecycle = sandbox.get("lifecycle") or {}
        return {
            "model": str(agent.get("model") or "gpt-4o-mini"),
            "max_tool_calls_per_turn": int(agent.get("max_tool_calls_per_turn") or 4),
            "sandbox_mode": str(sandbox_runtime.get("mode") or "cluster"),
            "sandbox_api_url": str(sandbox_runtime.get("api_url") or ""),
            "sandbox_template_name": str(
                sandbox_runtime.get("template_name") or "python-runtime-template-small"
            ),
            "sandbox_namespace": str(sandbox_runtime.get("namespace") or "alt-default"),
            "sandbox_server_port": int(sandbox_runtime.get("server_port") or 8888),
            "sandbox_max_output_chars": int(
                sandbox_runtime.get("max_output_chars") or 6000
            ),
            "sandbox_local_timeout_seconds": int(
                sandbox_runtime.get("local_timeout_seconds") or 20
            ),
            "sandbox_execution_model": str(
                sandbox_lifecycle.get("execution_model") or "session"
            ),
            "sandbox_session_idle_ttl_seconds": int(
                sandbox_lifecycle.get("session_idle_ttl_seconds") or 1800
            ),
        }

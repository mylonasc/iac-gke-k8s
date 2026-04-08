import copy
from typing import Any, Callable

from ..agents.toolkits.base import ToolkitProvider
from ..repositories.user_config_repository import UserConfigRepository
from ..repositories.user_repository import UserRepository


class RuntimeConfigService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        user_config_repository: UserConfigRepository,
        toolkit_providers: list[ToolkitProvider],
        release_user_session_leases: Callable[[str], None],
        default_model: str,
        default_max_tool_calls_per_turn: int,
    ) -> None:
        self.user_repository = user_repository
        self.user_config_repository = user_config_repository
        self.toolkit_providers = toolkit_providers
        self.toolkit_provider_by_id = {
            provider.toolkit_id: provider for provider in toolkit_providers
        }
        self.release_user_session_leases = release_user_session_leases
        self.default_model = default_model
        self.default_max_tool_calls_per_turn = default_max_tool_calls_per_turn

    def default_runtime_config(self) -> dict[str, Any]:
        return {
            "agent": {
                "model": self.default_model,
                "max_tool_calls_per_turn": self.default_max_tool_calls_per_turn,
                "enabled_toolkits": [
                    provider.toolkit_id for provider in self.toolkit_providers
                ],
            },
            "toolkits": {
                provider.toolkit_id: provider.default_config()
                for provider in self.toolkit_providers
            },
        }

    def merge_runtime_config(
        self, defaults: dict[str, Any], stored: dict[str, Any]
    ) -> dict[str, Any]:
        merged = copy.deepcopy(defaults)
        merged_agent = merged.get("agent") or {}
        stored_agent = stored.get("agent") or {}
        merged_agent.update(
            {
                key: value
                for key, value in stored_agent.items()
                if value is not None and key != "enabled_toolkits"
            }
        )
        merged["agent"] = merged_agent

        merged_toolkits = merged.get("toolkits") or {}
        stored_toolkits = stored.get("toolkits") or {}
        for provider in self.toolkit_providers:
            toolkit_id = provider.toolkit_id
            merged_toolkits[toolkit_id] = provider.merge_config(
                copy.deepcopy(
                    merged_toolkits.get(toolkit_id) or provider.default_config()
                ),
                stored_toolkits.get(toolkit_id)
                if isinstance(stored_toolkits.get(toolkit_id), dict)
                else {},
            )
        merged["toolkits"] = merged_toolkits
        merged["agent"]["enabled_toolkits"] = [
            provider.toolkit_id for provider in self.toolkit_providers
        ]
        return merged

    def get_user_profile(self, user_id: str) -> dict[str, Any]:
        return self.user_repository.ensure_user(user_id)

    def resolve_user_runtime_config(self, user_id: str) -> dict[str, Any]:
        defaults = self.default_runtime_config()
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return defaults
        self.user_repository.ensure_user(normalized_user_id)
        stored = self.user_config_repository.get_config(normalized_user_id)
        if not stored:
            return defaults
        return self.merge_runtime_config(defaults, stored)

    def update_runtime_config(
        self,
        user_id: str,
        agent: dict[str, Any] | None = None,
        toolkits: dict[str, Any] | None = None,
        model: str | None = None,
        max_tool_calls_per_turn: int | None = None,
        sandbox_mode: str | None = None,
        sandbox_profile: str | None = None,
        sandbox_api_url: str | None = None,
        sandbox_template_name: str | None = None,
        sandbox_namespace: str | None = None,
        sandbox_server_port: int | None = None,
        sandbox_max_output_chars: int | None = None,
        sandbox_local_timeout_seconds: int | None = None,
        sandbox_execution_model: str | None = None,
        sandbox_session_idle_ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        current = self.resolve_user_runtime_config(user_id)
        updated = copy.deepcopy(current)

        agent_config = agent or {}
        updated_agent = updated["agent"]

        resolved_model = agent_config.get("model") if "model" in agent_config else model
        resolved_max_tool_calls = (
            agent_config.get("max_tool_calls_per_turn")
            if "max_tool_calls_per_turn" in agent_config
            else max_tool_calls_per_turn
        )

        if resolved_model is not None:
            updated_agent["model"] = resolved_model
        if resolved_max_tool_calls is not None:
            if resolved_max_tool_calls < 1:
                raise ValueError("max_tool_calls_per_turn must be >= 1")
            updated_agent["max_tool_calls_per_turn"] = resolved_max_tool_calls

        legacy_updates = {
            "sandbox_mode": sandbox_mode,
            "sandbox_profile": sandbox_profile,
            "sandbox_api_url": sandbox_api_url,
            "sandbox_template_name": sandbox_template_name,
            "sandbox_namespace": sandbox_namespace,
            "sandbox_server_port": sandbox_server_port,
            "sandbox_max_output_chars": sandbox_max_output_chars,
            "sandbox_local_timeout_seconds": sandbox_local_timeout_seconds,
            "sandbox_execution_model": sandbox_execution_model,
            "sandbox_session_idle_ttl_seconds": sandbox_session_idle_ttl_seconds,
        }
        toolkit_updates = toolkits or {}
        should_recycle = False
        for provider in self.toolkit_providers:
            toolkit_id = provider.toolkit_id
            previous_toolkit = copy.deepcopy(updated["toolkits"].get(toolkit_id) or {})
            updated_toolkit = provider.apply_updates(
                previous_toolkit,
                toolkit_updates=toolkit_updates.get(toolkit_id)
                if isinstance(toolkit_updates.get(toolkit_id), dict)
                else None,
                legacy_updates=legacy_updates,
            )
            updated["toolkits"][toolkit_id] = updated_toolkit
            if provider.requires_session_recycle(previous_toolkit, updated_toolkit):
                should_recycle = True

        self.user_config_repository.upsert_config(user_id, updated)
        if should_recycle:
            self.release_user_session_leases(user_id)

        return self.resolve_user_runtime_config(user_id)

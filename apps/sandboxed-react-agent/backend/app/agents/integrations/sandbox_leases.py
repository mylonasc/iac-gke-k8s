from typing import Any

from ...sandbox_lifecycle import SandboxLifecycleService
from ...sandbox_manager import SandboxExecutionResult


class SandboxLeaseFacade:
    """Session-aware facade over sandbox lease lifecycle operations."""

    def __init__(self, sandbox_lifecycle: SandboxLifecycleService) -> None:
        self.sandbox_lifecycle = sandbox_lifecycle

    def exec_python_for_session(
        self,
        session_id: str,
        code: str,
        *,
        runtime_config: dict[str, object] | None = None,
    ) -> SandboxExecutionResult:
        return self.sandbox_lifecycle.exec_python(
            session_id,
            code,
            runtime_config=runtime_config,
        )

    def exec_shell_for_session(
        self,
        session_id: str,
        command: str,
        *,
        runtime_config: dict[str, object] | None = None,
    ) -> SandboxExecutionResult:
        return self.sandbox_lifecycle.exec_shell(
            session_id,
            command,
            runtime_config=runtime_config,
        )

    def get_session_lease(self, session_id: str) -> dict[str, Any] | None:
        return self.sandbox_lifecycle.get_active_scope_lease("session", session_id)

    def release_session(self, session_id: str) -> bool:
        return self.sandbox_lifecycle.release_scope("session", session_id)

    def release_lease(self, lease_id: str) -> bool:
        return self.sandbox_lifecycle.release_sandbox(lease_id)

    def list_active_leases(self) -> list[dict[str, Any]]:
        return self.sandbox_lifecycle.list_sandboxes()

    def get_lease(self, lease_id: str) -> dict[str, Any] | None:
        return self.sandbox_lifecycle.get_sandbox(lease_id)

from typing import Any

from ...sandbox_lifecycle import SandboxLifecycleService
from ...sandbox_manager import SandboxExecutionResult


class SandboxLeaseFacade:
    """Session-aware facade over sandbox lease lifecycle operations."""

    def __init__(self, sandbox_lifecycle: SandboxLifecycleService) -> None:
        """Initialize the facade.

        Args:
            sandbox_lifecycle: Lifecycle service coordinating lease behavior.
        """
        self.sandbox_lifecycle = sandbox_lifecycle

    def exec_python_for_session(
        self,
        session_id: str,
        code: str,
        *,
        runtime_config: dict[str, object] | None = None,
    ) -> SandboxExecutionResult:
        """Execute Python for a specific session scope.

        Args:
            session_id: Session identifier.
            code: Python code to execute.
            runtime_config: Optional runtime overrides.

        Returns:
            Normalized execution result.
        """
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
        """Execute shell command for a specific session scope.

        Args:
            session_id: Session identifier.
            command: Shell command.
            runtime_config: Optional runtime overrides.

        Returns:
            Normalized execution result.
        """
        return self.sandbox_lifecycle.exec_shell(
            session_id,
            command,
            runtime_config=runtime_config,
        )

    def get_session_lease(self, session_id: str) -> dict[str, Any] | None:
        """Fetch active session lease metadata.

        Args:
            session_id: Session identifier.

        Returns:
            Lease record if active, otherwise ``None``.
        """
        return self.sandbox_lifecycle.get_active_scope_lease("session", session_id)

    def release_session(self, session_id: str) -> bool:
        """Release session-scoped lease.

        Args:
            session_id: Session identifier.

        Returns:
            ``True`` if a lease was released.
        """
        return self.sandbox_lifecycle.release_scope("session", session_id)

    def release_lease(self, lease_id: str) -> bool:
        """Release lease by lease identifier.

        Args:
            lease_id: Lease identifier.

        Returns:
            ``True`` if the lease was released.
        """
        return self.sandbox_lifecycle.release_sandbox(lease_id)

    def list_active_leases(self) -> list[dict[str, Any]]:
        """List active leases for admin/diagnostics views.

        Returns:
            Active lease records.
        """
        return self.sandbox_lifecycle.list_sandboxes()

    def list_all_leases(self, limit: int | None = None) -> list[dict[str, Any]]:
        """List all leases, including terminal states.

        Args:
            limit: Optional maximum row count.

        Returns:
            Lease records ordered by recency.
        """
        return self.sandbox_lifecycle.list_all_sandboxes(limit=limit)

    def get_lease(self, lease_id: str) -> dict[str, Any] | None:
        """Fetch lease metadata by identifier.

        Args:
            lease_id: Lease identifier.

        Returns:
            Lease record if present, otherwise ``None``.
        """
        return self.sandbox_lifecycle.get_sandbox(lease_id)

from ...sandbox_manager import SandboxExecutionResult, SandboxManager


class SandboxRuntimeFacade:
    """Execution-only facade over the sandbox runtime manager."""

    def __init__(self, sandbox_manager: SandboxManager) -> None:
        self.sandbox_manager = sandbox_manager

    def exec_python(
        self, code: str, *, runtime_config: dict[str, object] | None = None
    ) -> SandboxExecutionResult:
        return self.sandbox_manager.exec_python(code, runtime_config=runtime_config)

    def exec_shell(
        self, command: str, *, runtime_config: dict[str, object] | None = None
    ) -> SandboxExecutionResult:
        return self.sandbox_manager.exec_shell(command, runtime_config=runtime_config)

    def exec_python_with_sandbox(
        self,
        code: str,
        *,
        sandbox: object,
        lease_id: str,
        claim_name: str | None,
        runtime_config: dict[str, object] | None = None,
    ) -> SandboxExecutionResult:
        return self.sandbox_manager.exec_python_with_sandbox(
            code,
            sandbox=sandbox,
            lease_id=lease_id,
            claim_name=claim_name,
            runtime_config=runtime_config,
        )

    def exec_shell_with_sandbox(
        self,
        command: str,
        *,
        sandbox: object,
        lease_id: str,
        claim_name: str | None,
        runtime_config: dict[str, object] | None = None,
    ) -> SandboxExecutionResult:
        return self.sandbox_manager.exec_shell_with_sandbox(
            command,
            sandbox=sandbox,
            lease_id=lease_id,
            claim_name=claim_name,
            runtime_config=runtime_config,
        )

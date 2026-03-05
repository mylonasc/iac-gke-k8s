import json
import os
import shlex
import subprocess
import textwrap
from dataclasses import dataclass
from typing import Sequence

from k8s_agent_sandbox import SandboxClient


@dataclass
class SandboxExecutionResult:
    tool_name: str
    ok: bool
    stdout: str
    stderr: str
    error: str | None = None

    def as_tool_payload(self) -> str:
        payload = {
            "tool": self.tool_name,
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
        }
        return json.dumps(payload, ensure_ascii=True)


class SandboxManager:
    def __init__(self) -> None:
        self.mode = os.getenv("SANDBOX_MODE", "cluster").strip().lower()
        if self.mode not in {"cluster", "local"}:
            self.mode = "cluster"

        self.api_url = os.getenv(
            "SANDBOX_API_URL",
            "http://sandbox-router-svc.alt-default.svc.cluster.local:8080",
        )
        self.template_name = os.getenv(
            "SANDBOX_TEMPLATE_NAME", "python-runtime-template"
        )
        self.namespace = os.getenv("SANDBOX_NAMESPACE", "alt-default")
        self.server_port = int(os.getenv("SANDBOX_SERVER_PORT", "8888"))
        self.max_output_chars = int(os.getenv("SANDBOX_MAX_OUTPUT_CHARS", "6000"))
        self.local_timeout_seconds = int(
            os.getenv("SANDBOX_LOCAL_TIMEOUT_SECONDS", "20")
        )

    def get_config(self) -> dict[str, str | int]:
        return {
            "mode": self.mode,
            "api_url": self.api_url,
            "template_name": self.template_name,
            "namespace": self.namespace,
            "server_port": self.server_port,
            "max_output_chars": self.max_output_chars,
            "local_timeout_seconds": self.local_timeout_seconds,
        }

    def update_config(
        self,
        mode: str | None = None,
        api_url: str | None = None,
        template_name: str | None = None,
        namespace: str | None = None,
        server_port: int | None = None,
        max_output_chars: int | None = None,
        local_timeout_seconds: int | None = None,
    ) -> None:
        if mode is not None:
            normalized = mode.strip().lower()
            if normalized not in {"cluster", "local"}:
                raise ValueError("mode must be 'cluster' or 'local'")
            self.mode = normalized
        if api_url is not None:
            self.api_url = api_url
        if template_name is not None:
            self.template_name = template_name
        if namespace is not None:
            self.namespace = namespace
        if server_port is not None:
            if server_port <= 0:
                raise ValueError("server_port must be > 0")
            self.server_port = server_port
        if max_output_chars is not None:
            if max_output_chars < 100:
                raise ValueError("max_output_chars must be >= 100")
            self.max_output_chars = max_output_chars
        if local_timeout_seconds is not None:
            if local_timeout_seconds <= 0:
                raise ValueError("local_timeout_seconds must be > 0")
            self.local_timeout_seconds = local_timeout_seconds

    def _truncate(self, value: str) -> str:
        if len(value) <= self.max_output_chars:
            return value
        return value[: self.max_output_chars] + "\n...[truncated]"

    def _build_python_script(self, code: str) -> str:
        encoded = json.dumps(code)
        return textwrap.dedent(
            f"""
            import ast

            source = {encoded}
            tree = ast.parse(source, mode="exec")
            namespace = {{}}

            if tree.body and isinstance(tree.body[-1], ast.Expr):
                last_expr = tree.body.pop()
                module_obj = ast.Module(body=tree.body, type_ignores=[])
                exec(compile(module_obj, "<sandbox>", "exec"), namespace, namespace)
                result = eval(
                    compile(ast.Expression(last_expr.value), "<sandbox>", "eval"),
                    namespace,
                    namespace,
                )
                if result is not None:
                    print(result)
            else:
                exec(compile(tree, "<sandbox>", "exec"), namespace, namespace)
            """
        ).strip()

    def _run_cluster(self, command: str, tool_name: str) -> SandboxExecutionResult:
        try:
            with SandboxClient(
                template_name=self.template_name,
                api_url=self.api_url,
                namespace=self.namespace,
                server_port=self.server_port,
            ) as sandbox:
                result = sandbox.run(command)
                stdout = self._truncate(getattr(result, "stdout", ""))
                stderr = self._truncate(getattr(result, "stderr", ""))
                return SandboxExecutionResult(
                    tool_name=tool_name,
                    ok=True,
                    stdout=stdout,
                    stderr=stderr,
                )
        except Exception as exc:
            return SandboxExecutionResult(
                tool_name=tool_name,
                ok=False,
                stdout="",
                stderr="",
                error=str(exc),
            )

    def _run_local(
        self, command: str | Sequence[str], tool_name: str, shell: bool
    ) -> SandboxExecutionResult:
        try:
            completed = subprocess.run(
                command,
                shell=shell,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.local_timeout_seconds,
                executable="/bin/sh" if shell else None,
            )
            stdout = self._truncate(completed.stdout)
            stderr = self._truncate(completed.stderr)
            if completed.returncode != 0:
                stderr = self._truncate(
                    f"exit code {completed.returncode}\n{stderr}".rstrip()
                )
            return SandboxExecutionResult(
                tool_name=tool_name,
                ok=completed.returncode == 0,
                stdout=stdout,
                stderr=stderr,
            )
        except subprocess.TimeoutExpired as exc:
            stdout_value = exc.stdout or ""
            stderr_value = exc.stderr or ""
            if isinstance(stdout_value, bytes):
                stdout_value = stdout_value.decode(errors="replace")
            if isinstance(stderr_value, bytes):
                stderr_value = stderr_value.decode(errors="replace")
            stdout = self._truncate(stdout_value)
            stderr = self._truncate(stderr_value)
            return SandboxExecutionResult(
                tool_name=tool_name,
                ok=False,
                stdout=stdout,
                stderr=stderr,
                error=f"Local execution timed out after {self.local_timeout_seconds}s",
            )
        except Exception as exc:
            return SandboxExecutionResult(
                tool_name=tool_name,
                ok=False,
                stdout="",
                stderr="",
                error=str(exc),
            )

    def exec_python(self, code: str) -> SandboxExecutionResult:
        script = self._build_python_script(code)
        if self.mode == "local":
            command = ["python", "-c", script]
            return self._run_local(
                command=command,
                tool_name="sandbox_exec_python",
                shell=False,
            )

        command = f"python -c {shlex.quote(script)}"
        return self._run_cluster(command=command, tool_name="sandbox_exec_python")

    def exec_shell(self, shell_command: str) -> SandboxExecutionResult:
        if self.mode == "local":
            return self._run_local(
                command=shell_command,
                tool_name="sandbox_exec_shell",
                shell=True,
            )

        return self._run_cluster(command=shell_command, tool_name="sandbox_exec_shell")

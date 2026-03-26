import json
import logging
import os
import shlex
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from typing import Sequence

from k8s_agent_sandbox import SandboxClient

from .logging_config import get_request_id


logger = logging.getLogger(__name__)


@dataclass
class SandboxExecutionResult:
    """Normalized execution result shared across local and cluster runtimes."""

    tool_name: str
    ok: bool
    stdout: str
    stderr: str
    exit_code: int | None = None
    error: str | None = None
    assets: list[dict[str, str]] | None = None
    lease_id: str | None = None
    claim_name: str | None = None

    def as_tool_payload(self) -> str:
        """Serialize the result into a stable JSON payload for tool responses."""
        payload = {
            "tool": self.tool_name,
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "error": self.error,
            "assets": self.assets or [],
            "lease_id": self.lease_id,
            "claim_name": self.claim_name,
        }
        return json.dumps(payload, ensure_ascii=True)


class SandboxManager:
    """Executes python/shell workloads in local or cluster-backed sandboxes.

    The manager offers synchronous execution methods and focuses on command
    translation, output normalization, asset extraction, and logging.
    Lifecycle orchestration (lease reuse/release) is delegated to
    ``SandboxLifecycleService``.
    """

    def __init__(self) -> None:
        self.mode = os.getenv("SANDBOX_MODE", "cluster").strip().lower()
        if self.mode not in {"cluster", "local"}:
            self.mode = "cluster"

        self.api_url = os.getenv(
            "SANDBOX_API_URL",
            "http://sandbox-router-svc.alt-default.svc.cluster.local:8080",
        )
        self.template_name = os.getenv(
            "SANDBOX_TEMPLATE_NAME", "python-runtime-template-small"
        )
        self.namespace = os.getenv("SANDBOX_NAMESPACE", "alt-default")
        self.server_port = int(os.getenv("SANDBOX_SERVER_PORT", "8888"))
        self.sandbox_ready_timeout = int(
            os.getenv("SANDBOX_READY_TIMEOUT_SECONDS", "420")
        )
        self.gateway_ready_timeout = int(
            os.getenv("SANDBOX_GATEWAY_READY_TIMEOUT_SECONDS", "180")
        )
        self.max_output_chars = int(os.getenv("SANDBOX_MAX_OUTPUT_CHARS", "6000"))
        self.local_timeout_seconds = int(
            os.getenv("SANDBOX_LOCAL_TIMEOUT_SECONDS", "20")
        )
        self.command_preview_chars = int(os.getenv("LOG_COMMAND_PREVIEW_CHARS", "200"))
        logger.info(
            "sandbox_manager.initialized",
            extra={
                "event": "sandbox_manager.initialized",
                "sandbox_mode": self.mode,
                "sandbox_api_url": self.api_url,
                "sandbox_template_name": self.template_name,
                "sandbox_namespace": self.namespace,
                "sandbox_server_port": self.server_port,
            },
        )

    def _command_preview(self, command: str) -> str:
        """Return a bounded preview for logging potentially long commands."""
        if len(command) <= self.command_preview_chars:
            return command
        return command[: self.command_preview_chars] + "..."

    def get_config(self) -> dict[str, str | int]:
        """Return current sandbox manager runtime settings."""
        return {
            "mode": self.mode,
            "api_url": self.api_url,
            "template_name": self.template_name,
            "namespace": self.namespace,
            "server_port": self.server_port,
            "sandbox_ready_timeout": self.sandbox_ready_timeout,
            "gateway_ready_timeout": self.gateway_ready_timeout,
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
        sandbox_ready_timeout: int | None = None,
        gateway_ready_timeout: int | None = None,
        max_output_chars: int | None = None,
        local_timeout_seconds: int | None = None,
    ) -> None:
        """Apply runtime configuration updates with basic validation."""
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
        if sandbox_ready_timeout is not None:
            if sandbox_ready_timeout <= 0:
                raise ValueError("sandbox_ready_timeout must be > 0")
            self.sandbox_ready_timeout = sandbox_ready_timeout
        if gateway_ready_timeout is not None:
            if gateway_ready_timeout <= 0:
                raise ValueError("gateway_ready_timeout must be > 0")
            self.gateway_ready_timeout = gateway_ready_timeout
        if max_output_chars is not None:
            if max_output_chars < 100:
                raise ValueError("max_output_chars must be >= 100")
            self.max_output_chars = max_output_chars
        if local_timeout_seconds is not None:
            if local_timeout_seconds <= 0:
                raise ValueError("local_timeout_seconds must be > 0")
            self.local_timeout_seconds = local_timeout_seconds

    def _truncate(self, value: str) -> str:
        """Trim stdout/stderr to configured maximum output length."""
        if len(value) <= self.max_output_chars:
            return value
        return value[: self.max_output_chars] + "\n...[truncated]"

    def _extract_asset_markers(self, stdout: str) -> tuple[str, list[dict[str, str]]]:
        """Extract and remove asset marker lines emitted by sandbox helpers."""
        assets: list[dict[str, str]] = []
        cleaned_lines: list[str] = []
        for line in stdout.splitlines():
            if line.startswith(self.ASSET_MARKER):
                raw = line[len(self.ASSET_MARKER) :].strip()
                try:
                    parsed = json.loads(raw)
                    if (
                        isinstance(parsed, dict)
                        and isinstance(parsed.get("filename"), str)
                        and isinstance(parsed.get("mime_type"), str)
                        and isinstance(parsed.get("base64"), str)
                    ):
                        assets.append(
                            {
                                "filename": parsed["filename"],
                                "mime_type": parsed["mime_type"],
                                "base64": parsed["base64"],
                            }
                        )
                        continue
                except Exception:
                    pass
            cleaned_lines.append(line)
        cleaned_stdout = "\n".join(cleaned_lines)
        return cleaned_stdout, assets

    def _build_python_script(self, code: str) -> str:
        """Wrap user python code with helper utilities and auto-asset behavior."""
        encoded = json.dumps(code)
        return textwrap.dedent(
            f"""
            import ast
            import base64
            import pathlib
            import mimetypes
            import os
            import json
            import re
            from pathlib import Path

            source = {encoded}
            tree = ast.parse(source, mode="exec")
            namespace = {{}}
            _asset_marker = {json.dumps(self.ASSET_MARKER)}
            _exposed_assets = []
            _candidate_paths = []

            def expose_asset(path, filename=None, mime_type=None):
                p = Path(path)
                if not p.exists() or not p.is_file():
                    raise FileNotFoundError(f"Asset path not found: {{p}}")
                data = p.read_bytes()
                if len(data) > 5 * 1024 * 1024:
                    raise ValueError("Asset too large (max 5MB)")
                guessed_mime = mime_type or mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                _exposed_assets.append({{
                    "filename": filename or p.name,
                    "mime_type": guessed_mime,
                    "base64": base64.b64encode(data).decode("ascii"),
                }})

            namespace["expose_asset"] = expose_asset

            def expose_html_widget(html, filename="widget.html"):
                widget_path = Path(filename)
                widget_path.parent.mkdir(parents=True, exist_ok=True)
                widget_path.write_text(str(html), encoding="utf-8")
                expose_asset(str(widget_path), mime_type="text/html")

            namespace["expose_html_widget"] = expose_html_widget

            # Try to infer likely output files from string literals in source.
            _literal_paths = re.findall(r'[\"\\\']([^\"\\\']+\\.(?:png|jpg|jpeg|gif|webp|svg|pdf|csv|txt|json|zip|html|htm))[\"\\\']', source, flags=re.IGNORECASE)
            for _path in _literal_paths:
                try:
                    _candidate_paths.append(str(Path(_path)))
                except Exception:
                    pass

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

            # Guardrail: if no asset explicitly exposed, auto-expose any detected image/file paths.
            if not _exposed_assets:
                for _candidate in _candidate_paths:
                    try:
                        if Path(_candidate).exists() and Path(_candidate).is_file():
                            expose_asset(_candidate)
                    except Exception:
                        pass

            for _asset in _exposed_assets:
                print(_asset_marker + json.dumps(_asset))
            """
        ).strip()

    def _cluster_result_from_execution(
        self,
        *,
        tool_name: str,
        result: object,
        lease_id: str | None = None,
        claim_name: str | None = None,
    ) -> SandboxExecutionResult:
        """Convert low-level cluster execution output into normalized result."""
        full_stdout = str(getattr(result, "stdout", "") or "")
        clean_stdout, assets = self._extract_asset_markers(full_stdout)
        stdout = self._truncate(clean_stdout)
        stderr = self._truncate(str(getattr(result, "stderr", "") or ""))
        exit_code = int(getattr(result, "exit_code", -1))
        ok = exit_code == 0
        if not ok:
            stderr = self._truncate(f"exit code {exit_code}\n{stderr}".rstrip())

        return SandboxExecutionResult(
            tool_name=tool_name,
            ok=ok,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            assets=assets,
            lease_id=lease_id,
            claim_name=claim_name,
        )

    def _execute_cluster_with_client(
        self,
        *,
        sandbox: SandboxClient,
        command: str,
        tool_name: str,
        lease_id: str | None = None,
        claim_name: str | None = None,
    ) -> SandboxExecutionResult:
        """Execute a command using an already-initialized sandbox client."""
        result = sandbox.run(command)
        return self._cluster_result_from_execution(
            tool_name=tool_name,
            result=result,
            lease_id=lease_id,
            claim_name=claim_name,
        )

    def _run_cluster(
        self,
        command: str,
        tool_name: str,
        *,
        lease_id: str | None = None,
        claim_name: str | None = None,
        sandbox: SandboxClient | None = None,
    ) -> SandboxExecutionResult:
        """Execute a command in cluster mode using a fresh or provided client."""
        started = time.perf_counter()
        exec_result: SandboxExecutionResult | None = None
        logger.info(
            "sandbox.cluster.start",
            extra={
                "event": "sandbox.cluster.start",
                "tool_name": tool_name,
                "sandbox_mode": self.mode,
                "sandbox_api_url": self.api_url,
                "sandbox_template_name": self.template_name,
                "sandbox_namespace": self.namespace,
                "request_id": get_request_id(),
                "lease_id": lease_id,
                "claim_name": claim_name,
                "command_preview": self._command_preview(command),
                "command_len": len(command),
            },
        )
        try:
            if sandbox is not None:
                effective_claim = claim_name or getattr(sandbox, "claim_name", None)
                exec_result = self._execute_cluster_with_client(
                    sandbox=sandbox,
                    command=command,
                    tool_name=tool_name,
                    lease_id=lease_id,
                    claim_name=effective_claim,
                )
                return exec_result

            with SandboxClient(
                template_name=self.template_name,
                api_url=self.api_url,
                namespace=self.namespace,
                server_port=self.server_port,
                sandbox_ready_timeout=self.sandbox_ready_timeout,
                gateway_ready_timeout=self.gateway_ready_timeout,
            ) as owned_sandbox:
                effective_claim = claim_name or getattr(
                    owned_sandbox, "claim_name", None
                )
                exec_result = self._execute_cluster_with_client(
                    sandbox=owned_sandbox,
                    command=command,
                    tool_name=tool_name,
                    lease_id=lease_id,
                    claim_name=effective_claim,
                )
                return exec_result

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "sandbox.cluster.error",
                extra={
                    "event": "sandbox.cluster.error",
                    "tool_name": tool_name,
                    "sandbox_mode": self.mode,
                    "request_id": get_request_id(),
                    "lease_id": lease_id,
                    "claim_name": claim_name,
                    "duration_ms": elapsed_ms,
                    "error": str(exc),
                },
            )
            exec_result = SandboxExecutionResult(
                tool_name=tool_name,
                ok=False,
                stdout="",
                stderr="",
                exit_code=None,
                error=str(exc),
                lease_id=lease_id,
                claim_name=claim_name,
            )
            return exec_result
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "sandbox.cluster.end",
                extra={
                    "event": "sandbox.cluster.end",
                    "tool_name": tool_name,
                    "sandbox_mode": self.mode,
                    "request_id": get_request_id(),
                    "lease_id": lease_id,
                    "claim_name": claim_name,
                    "duration_ms": elapsed_ms,
                    "ok": exec_result.ok if exec_result else False,
                    "stdout_len": len(exec_result.stdout) if exec_result else 0,
                    "stderr_len": len(exec_result.stderr) if exec_result else 0,
                    "exit_code": exec_result.exit_code if exec_result else None,
                    "asset_count": len(exec_result.assets or []) if exec_result else 0,
                    "error": exec_result.error if exec_result else "unknown",
                },
            )

    def _run_local(
        self, command: str | Sequence[str], tool_name: str, shell: bool
    ) -> SandboxExecutionResult:
        """Execute a local command and normalize outputs consistently."""
        started = time.perf_counter()
        exec_result: SandboxExecutionResult | None = None
        if isinstance(command, str):
            preview_source = command
        else:
            preview_source = " ".join(str(part) for part in command)
        logger.info(
            "sandbox.local.start",
            extra={
                "event": "sandbox.local.start",
                "tool_name": tool_name,
                "sandbox_mode": self.mode,
                "request_id": get_request_id(),
                "command_preview": self._command_preview(preview_source),
                "command_len": len(preview_source),
                "shell": shell,
            },
        )
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
            clean_stdout, assets = self._extract_asset_markers(completed.stdout)
            stdout = self._truncate(clean_stdout)
            stderr = self._truncate(completed.stderr)
            if completed.returncode != 0:
                stderr = self._truncate(
                    f"exit code {completed.returncode}\n{stderr}".rstrip()
                )
            exec_result = SandboxExecutionResult(
                tool_name=tool_name,
                ok=completed.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=completed.returncode,
                assets=assets,
            )
            return exec_result
        except subprocess.TimeoutExpired as exc:
            stdout_value = exc.stdout or ""
            stderr_value = exc.stderr or ""
            if isinstance(stdout_value, bytes):
                stdout_value = stdout_value.decode(errors="replace")
            if isinstance(stderr_value, bytes):
                stderr_value = stderr_value.decode(errors="replace")
            stdout = self._truncate(stdout_value)
            stderr = self._truncate(stderr_value)
            exec_result = SandboxExecutionResult(
                tool_name=tool_name,
                ok=False,
                stdout=stdout,
                stderr=stderr,
                exit_code=None,
                error=f"Local execution timed out after {self.local_timeout_seconds}s",
            )
            return exec_result
        except Exception as exc:
            logger.exception(
                "sandbox.local.error",
                extra={
                    "event": "sandbox.local.error",
                    "tool_name": tool_name,
                    "sandbox_mode": self.mode,
                    "request_id": get_request_id(),
                    "error": str(exc),
                },
            )
            exec_result = SandboxExecutionResult(
                tool_name=tool_name,
                ok=False,
                stdout="",
                stderr="",
                exit_code=None,
                error=str(exc),
            )
            return exec_result
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "sandbox.local.end",
                extra={
                    "event": "sandbox.local.end",
                    "tool_name": tool_name,
                    "sandbox_mode": self.mode,
                    "request_id": get_request_id(),
                    "duration_ms": elapsed_ms,
                    "ok": exec_result.ok if exec_result else False,
                    "stdout_len": len(exec_result.stdout) if exec_result else 0,
                    "stderr_len": len(exec_result.stderr) if exec_result else 0,
                    "exit_code": exec_result.exit_code if exec_result else None,
                    "asset_count": len(exec_result.assets or []) if exec_result else 0,
                    "error": exec_result.error if exec_result else "unknown",
                },
            )

    def exec_python(self, code: str) -> SandboxExecutionResult:
        """Execute Python in local mode or in an ephemeral cluster sandbox."""
        logger.info(
            "sandbox.exec_python",
            extra={
                "event": "sandbox.exec_python",
                "sandbox_mode": self.mode,
                "request_id": get_request_id(),
                "code_len": len(code),
            },
        )
        script = self._build_python_script(code)
        if self.mode == "local":
            command = [sys.executable, "-c", script]
            return self._run_local(
                command=command,
                tool_name="sandbox_exec_python",
                shell=False,
            )

        command = f"python -c {shlex.quote(script)}"
        return self._run_cluster(command=command, tool_name="sandbox_exec_python")

    def exec_python_with_sandbox(
        self,
        code: str,
        *,
        sandbox: SandboxClient,
        lease_id: str,
        claim_name: str | None,
    ) -> SandboxExecutionResult:
        """Execute Python against an existing lease-backed cluster sandbox."""
        script = self._build_python_script(code)
        command = f"python -c {shlex.quote(script)}"
        return self._run_cluster(
            command=command,
            tool_name="sandbox_exec_python",
            lease_id=lease_id,
            claim_name=claim_name,
            sandbox=sandbox,
        )

    def exec_shell(self, shell_command: str) -> SandboxExecutionResult:
        """Execute shell in local mode or in an ephemeral cluster sandbox."""
        logger.info(
            "sandbox.exec_shell",
            extra={
                "event": "sandbox.exec_shell",
                "sandbox_mode": self.mode,
                "request_id": get_request_id(),
                "command_len": len(shell_command),
                "command_preview": self._command_preview(shell_command),
            },
        )
        if self.mode == "local":
            return self._run_local(
                command=shell_command,
                tool_name="sandbox_exec_shell",
                shell=True,
            )

        return self._run_cluster(command=shell_command, tool_name="sandbox_exec_shell")

    def exec_shell_with_sandbox(
        self,
        shell_command: str,
        *,
        sandbox: SandboxClient,
        lease_id: str,
        claim_name: str | None,
    ) -> SandboxExecutionResult:
        """Execute shell against an existing lease-backed cluster sandbox."""
        return self._run_cluster(
            command=shell_command,
            tool_name="sandbox_exec_shell",
            lease_id=lease_id,
            claim_name=claim_name,
            sandbox=sandbox,
        )

    ASSET_MARKER = "__ASSET__"

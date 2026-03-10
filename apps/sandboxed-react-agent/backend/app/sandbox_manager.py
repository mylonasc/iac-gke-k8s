import json
import os
import shlex
import subprocess
import sys
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
    assets: list[dict[str, str]] | None = None

    def as_tool_payload(self) -> str:
        payload = {
            "tool": self.tool_name,
            "ok": self.ok,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "assets": self.assets or [],
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

    def _extract_asset_markers(self, stdout: str) -> tuple[str, list[dict[str, str]]]:
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

            # Try to infer likely output files from string literals in source.
            _literal_paths = re.findall(r'[\"\\\']([^\"\\\']+\\.(?:png|jpg|jpeg|gif|webp|svg|pdf|csv|txt|json|zip))[\"\\\']', source, flags=re.IGNORECASE)
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

    def _run_cluster(self, command: str, tool_name: str) -> SandboxExecutionResult:
        try:
            with SandboxClient(
                template_name=self.template_name,
                api_url=self.api_url,
                namespace=self.namespace,
                server_port=self.server_port,
            ) as sandbox:
                result = sandbox.run(command)
                full_stdout = getattr(result, "stdout", "")
                clean_stdout, assets = self._extract_asset_markers(full_stdout)
                stdout = self._truncate(clean_stdout)
                stderr = self._truncate(getattr(result, "stderr", ""))
                return SandboxExecutionResult(
                    tool_name=tool_name,
                    ok=True,
                    stdout=stdout,
                    stderr=stderr,
                    assets=assets,
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
            clean_stdout, assets = self._extract_asset_markers(completed.stdout)
            stdout = self._truncate(clean_stdout)
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
                assets=assets,
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
            command = [sys.executable, "-c", script]
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

    ASSET_MARKER = "__ASSET__"

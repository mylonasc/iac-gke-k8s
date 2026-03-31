from typing import Any

from ..tool_payloads import ToolExecutionAsset, ToolExecutionPayload
from .assets import AssetFacade
from .sandbox_leases import SandboxLeaseFacade


class SessionSandboxFacade:
    """Facade that combines session execution and asset persistence."""

    def __init__(
        self, lease_facade: SandboxLeaseFacade, asset_facade: AssetFacade
    ) -> None:
        self.lease_facade = lease_facade
        self.asset_facade = asset_facade

    def run_python(
        self,
        *,
        session_id: str,
        tool_call_id: str | None,
        code: str,
        runtime_config: dict[str, Any],
        created_at: str,
    ) -> tuple[ToolExecutionPayload, list[dict[str, Any]]]:
        result = self.lease_facade.exec_python_for_session(
            session_id,
            code,
            runtime_config=runtime_config,
        )
        stored_assets = self.asset_facade.store_execution_assets(
            session_id=session_id,
            tool_call_id=tool_call_id,
            assets=result.assets,
            created_at=created_at,
        )
        return self._payload_from_result(result, stored_assets), stored_assets

    def run_shell(
        self,
        *,
        session_id: str,
        tool_call_id: str | None,
        command: str,
        runtime_config: dict[str, Any],
        created_at: str,
    ) -> tuple[ToolExecutionPayload, list[dict[str, Any]]]:
        result = self.lease_facade.exec_shell_for_session(
            session_id,
            command,
            runtime_config=runtime_config,
        )
        stored_assets = self.asset_facade.store_execution_assets(
            session_id=session_id,
            tool_call_id=tool_call_id,
            assets=result.assets,
            created_at=created_at,
        )
        return self._payload_from_result(result, stored_assets), stored_assets

    def _payload_from_result(
        self, result: Any, stored_assets: list[dict[str, Any]]
    ) -> ToolExecutionPayload:
        return ToolExecutionPayload(
            tool=result.tool_name,
            ok=result.ok,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            error=result.error,
            lease_id=result.lease_id,
            claim_name=result.claim_name,
            assets=[
                ToolExecutionAsset(
                    asset_id=asset["asset_id"],
                    filename=asset["filename"],
                    mime_type=asset["mime_type"],
                    view_url=asset["view_url"],
                    download_url=asset["download_url"],
                )
                for asset in stored_assets
            ],
        )

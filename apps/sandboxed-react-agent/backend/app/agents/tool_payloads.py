import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ToolExecutionAsset:
    asset_id: str
    filename: str
    mime_type: str
    view_url: str
    download_url: str


@dataclass
class ToolExecutionPayload:
    tool: str
    ok: bool
    stdout: str
    stderr: str
    exit_code: int | None = None
    error: str | None = None
    lease_id: str | None = None
    claim_name: str | None = None
    assets: list[ToolExecutionAsset] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=True)

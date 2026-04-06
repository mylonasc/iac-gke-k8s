import copy
import json
import re
import uuid
from typing import Any, Callable

from ..repositories.session_repository import SessionRepository
from .session_service import SessionService


def public_asset_url(share_id: str, asset_id: str, *, download: bool = False) -> str:
    base = f"/api/public/{share_id}/assets/{asset_id}"
    if download:
        return f"{base}/download"
    return base


class SharingService:
    def __init__(
        self,
        *,
        session_repository: SessionRepository,
        session_service: SessionService,
        get_session: Callable[[str, str], dict[str, Any] | None],
    ) -> None:
        self.session_repository = session_repository
        self.session_service = session_service
        self.get_session = get_session

    def create_share(self, session_id: str, user_id: str) -> str | None:
        session = self.session_service.sessions.get(session_id)
        if not session or session.user_id != user_id:
            return None
        if not session.share_id:
            session.share_id = uuid.uuid4().hex
            self.session_repository.set_share_id_for_user(
                session_id, user_id, session.share_id
            )
            self.session_service.persist_session(session)
        return session.share_id

    def _publicize_shared_session(
        self, session: dict[str, Any], share_id: str
    ) -> dict[str, Any]:
        rewritten = copy.deepcopy(session)
        for message in rewritten.get("messages", []):
            if not isinstance(message, dict):
                continue
            for part in message.get("content", []):
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "image":
                    image_url = str(part.get("image") or "")
                    match = re.fullmatch(r"/api/assets/([A-Za-z0-9_-]+)", image_url)
                    if match:
                        part["image"] = public_asset_url(share_id, match.group(1))
                if part.get("type") == "tool-call":
                    result = part.get("result")
                    if not isinstance(result, dict):
                        continue
                    assets = result.get("assets")
                    if not isinstance(assets, list):
                        continue
                    for asset in assets:
                        if not isinstance(asset, dict):
                            continue
                        asset_id = str(asset.get("asset_id") or "")
                        if not asset_id:
                            continue
                        asset["view_url"] = public_asset_url(share_id, asset_id)
                        asset["download_url"] = public_asset_url(
                            share_id, asset_id, download=True
                        )
        return rewritten

    def get_shared_session(self, share_id: str) -> dict[str, Any] | None:
        for session in self.session_service.sessions.values():
            if session.share_id == share_id:
                private_session = self.get_session(session.session_id, session.user_id)
                if not private_session:
                    return None
                return self._publicize_shared_session(private_session, share_id)

        record = self.session_repository.get_by_share_id(share_id)
        if not record:
            return None
        session = self.session_service.sessions.get(record["session_id"])
        if session is None:
            session = self.session_service.hydrate_session_record(record)
        private_session = self.get_session(session.session_id, session.user_id)
        if not private_session:
            return None
        return self._publicize_shared_session(private_session, share_id)

    def get_shared_session_markdown(self, share_id: str) -> str | None:
        session = self.get_shared_session(share_id)
        if not session:
            return None

        lines: list[str] = [f"# {session.get('title') or 'Shared Thread'}", ""]
        for message in session.get("messages", []):
            role = message.get("role", "assistant")
            header = "## Assistant" if role == "assistant" else "## User"
            lines.append(header)
            lines.append("")

            for part in message.get("content", []):
                part_type = part.get("type")
                if part_type == "text":
                    lines.append(part.get("text", ""))
                    lines.append("")
                elif part_type == "reasoning":
                    lines.append("> Thinking")
                    lines.append("")
                    lines.append(part.get("text", ""))
                    lines.append("")
                elif part_type == "image":
                    image = part.get("image", "")
                    if image:
                        lines.append(f"![uploaded-image]({image})")
                        lines.append("")
                elif part_type == "tool-call":
                    lines.append(f"### Tool: {part.get('toolName', 'tool')}")
                    lines.append("")
                    args_text = part.get("argsText") or json.dumps(
                        part.get("args", {}), ensure_ascii=True, indent=2
                    )
                    result_payload = part.get("result", "(pending)")
                    result_text = json.dumps(
                        result_payload, ensure_ascii=True, indent=2
                    )
                    lines.extend(
                        [
                            "```json",
                            args_text,
                            "```",
                            "",
                            "```json",
                            result_text,
                            "```",
                            "",
                        ]
                    )

                    assets = []
                    if isinstance(result_payload, dict):
                        maybe_assets = result_payload.get("assets")
                        if isinstance(maybe_assets, list):
                            assets = [a for a in maybe_assets if isinstance(a, dict)]

                    if assets:
                        lines.append("#### Tool assets")
                        lines.append("")
                        for asset in assets:
                            filename = str(asset.get("filename") or "asset")
                            view_url = str(asset.get("view_url") or "")
                            download_url = str(asset.get("download_url") or view_url)
                            mime_type = str(asset.get("mime_type") or "")

                            if view_url and mime_type.startswith("image/"):
                                lines.append(f"![{filename}]({view_url})")
                            if download_url:
                                lines.append(f"- [{filename}]({download_url})")
                            elif view_url:
                                lines.append(f"- [{filename}]({view_url})")
                        lines.append("")

            lines.extend(["---", ""])

        return "\n".join(lines).strip() + "\n"

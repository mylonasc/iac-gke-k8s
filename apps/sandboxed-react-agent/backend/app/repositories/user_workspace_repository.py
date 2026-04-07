from ..session_store import SessionStore
from ..services.workspace_models import WorkspaceRecord, now_iso


class UserWorkspaceRepository:
    def __init__(self, session_store: SessionStore) -> None:
        self.session_store = session_store

    def upsert(self, workspace: dict[str, object]) -> None:
        self.session_store.upsert_user_workspace(workspace)

    def get_by_user_id(self, user_id: str) -> dict[str, object] | None:
        return self.session_store.get_user_workspace(user_id)

    def get_by_workspace_id(self, workspace_id: str) -> dict[str, object] | None:
        return self.session_store.get_user_workspace_by_id(workspace_id)

    def list_workspaces(self) -> list[dict[str, object]]:
        return self.session_store.list_user_workspaces()

    def update_claim_binding(
        self, user_id: str, *, claim_name: str | None, claim_namespace: str | None
    ) -> bool:
        record = self.get_by_user_id(user_id)
        if not record:
            return False
        workspace = WorkspaceRecord.from_record(record)
        workspace.claim_name = claim_name
        workspace.claim_namespace = claim_namespace
        workspace.updated_at = now_iso()
        self.upsert(workspace.as_record())
        return True

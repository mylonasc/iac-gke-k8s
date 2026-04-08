from ..session_store import SessionStore
from ..services.workspace_models import WorkspaceRecord, now_iso


class UserWorkspaceRepository:
    """Persistence adapter for user workspace records."""

    def __init__(self, session_store: SessionStore) -> None:
        """Initialize the repository.

        Args:
            session_store: Shared persistence facade.
        """
        self.session_store = session_store

    def upsert(self, workspace: dict[str, object]) -> None:
        """Insert or update a workspace record.

        Args:
            workspace: Workspace record in storage schema.
        """
        self.session_store.upsert_user_workspace(workspace)

    def get_by_user_id(self, user_id: str) -> dict[str, object] | None:
        """Fetch workspace by user identifier.

        Args:
            user_id: User identifier.

        Returns:
            Workspace record if present, otherwise ``None``.
        """
        return self.session_store.get_user_workspace(user_id)

    def get_by_workspace_id(self, workspace_id: str) -> dict[str, object] | None:
        """Fetch workspace by workspace identifier.

        Args:
            workspace_id: Workspace identifier.

        Returns:
            Workspace record if found, otherwise ``None``.
        """
        return self.session_store.get_user_workspace_by_id(workspace_id)

    def list_workspaces(self) -> list[dict[str, object]]:
        """List all workspace records.

        Returns:
            Workspace records ordered by recency.
        """
        return self.session_store.list_user_workspaces()

    def update_claim_binding(
        self, user_id: str, *, claim_name: str | None, claim_namespace: str | None
    ) -> bool:
        """Update claim binding metadata for a user's workspace.

        Args:
            user_id: User identifier.
            claim_name: Active claim name or ``None``.
            claim_namespace: Claim namespace or ``None``.

        Returns:
            ``True`` when a workspace record was updated.
        """
        record = self.get_by_user_id(user_id)
        if not record:
            return False
        workspace = WorkspaceRecord.from_record(record)
        workspace.claim_name = claim_name
        workspace.claim_namespace = claim_namespace
        workspace.updated_at = now_iso()
        self.upsert(workspace.as_record())
        return True

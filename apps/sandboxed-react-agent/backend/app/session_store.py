import os
import sqlite3
from pathlib import Path
from typing import Any

from .persistence.assets import SQLiteAssetStore
from .persistence.sandbox_leases import SQLiteSandboxLeaseStore
from .persistence.schema import init_schema
from .persistence.sessions import SQLiteSessionStore
from .persistence.user_configs import SQLiteUserConfigStore
from .persistence.users import SQLiteUserStore
from .persistence.workspace_jobs import SQLiteWorkspaceJobStore
from .persistence.user_workspaces import SQLiteUserWorkspaceStore


class SessionStore:
    """Compatibility facade over focused SQLite persistence modules."""

    def __init__(self, db_path: str | None = None) -> None:
        default_path = os.getenv("SESSION_STORE_PATH", "/app/data/sessions.db")
        self.db_path = db_path or default_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        init_schema(self._connect)

        self.users = SQLiteUserStore(self._connect)
        self.user_configs = SQLiteUserConfigStore(self._connect, self.users)
        self.sessions = SQLiteSessionStore(self._connect)
        self.assets = SQLiteAssetStore(self._connect)
        self.sandbox_leases = SQLiteSandboxLeaseStore(self._connect)
        self.user_workspaces = SQLiteUserWorkspaceStore(self._connect)
        self.workspace_jobs = SQLiteWorkspaceJobStore(self._connect)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def ensure_user(self, user_id: str) -> dict[str, Any]:
        return self.users.ensure_user(user_id)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self.users.get_user(user_id)

    def search_users(self, query: str = "", *, limit: int = 20) -> list[dict[str, Any]]:
        return self.users.search_users(query=query, limit=limit)

    def get_user_config(self, user_id: str) -> dict[str, Any] | None:
        return self.user_configs.get_user_config(user_id)

    def upsert_user_config(self, user_id: str, config: dict[str, Any]) -> None:
        self.user_configs.upsert_user_config(user_id, config)

    def upsert_session(self, session: dict[str, Any]) -> None:
        self.sessions.upsert_session(session)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self.sessions.get_session(session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        return self.sessions.list_sessions()

    def list_sessions_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return self.sessions.list_sessions_for_user(user_id)

    def delete_session(self, session_id: str) -> bool:
        return self.sessions.delete_session(session_id)

    def delete_session_for_user(self, session_id: str, user_id: str) -> bool:
        return self.sessions.delete_session_for_user(session_id, user_id)

    def set_share_id(self, session_id: str, share_id: str) -> None:
        self.sessions.set_share_id(session_id, share_id)

    def set_share_id_for_user(
        self, session_id: str, user_id: str, share_id: str
    ) -> bool:
        return self.sessions.set_share_id_for_user(session_id, user_id, share_id)

    def get_session_for_user(
        self, session_id: str, user_id: str
    ) -> dict[str, Any] | None:
        return self.sessions.get_session_for_user(session_id, user_id)

    def get_by_share_id(self, share_id: str) -> dict[str, Any] | None:
        return self.sessions.get_by_share_id(share_id)

    def add_asset(self, asset: dict[str, Any]) -> None:
        self.assets.add_asset(asset)

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        return self.assets.get_asset(asset_id)

    def get_asset_for_user(self, asset_id: str, user_id: str) -> dict[str, Any] | None:
        return self.assets.get_asset_for_user(asset_id, user_id)

    def get_asset_for_share(
        self, asset_id: str, share_id: str
    ) -> dict[str, Any] | None:
        return self.assets.get_asset_for_share(asset_id, share_id)

    def upsert_sandbox_lease(self, lease: dict[str, Any]) -> None:
        self.sandbox_leases.upsert_sandbox_lease(lease)

    def get_sandbox_lease(self, lease_id: str) -> dict[str, Any] | None:
        return self.sandbox_leases.get_sandbox_lease(lease_id)

    def get_active_sandbox_lease(
        self, scope_type: str, scope_key: str
    ) -> dict[str, Any] | None:
        return self.sandbox_leases.get_active_sandbox_lease(scope_type, scope_key)

    def list_active_sandbox_leases(self) -> list[dict[str, Any]]:
        return self.sandbox_leases.list_active_sandbox_leases()

    def list_sandbox_leases(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self.sandbox_leases.list_sandbox_leases(limit=limit)

    def list_expired_sandbox_leases(self, now_iso: str) -> list[dict[str, Any]]:
        return self.sandbox_leases.list_expired_sandbox_leases(now_iso)

    def mark_sandbox_lease_released(
        self,
        lease_id: str,
        *,
        released_at: str,
        status: str = "released",
        last_error: str | None = None,
    ) -> None:
        self.sandbox_leases.mark_sandbox_lease_released(
            lease_id,
            released_at=released_at,
            status=status,
            last_error=last_error,
        )

    def upsert_user_workspace(self, workspace: dict[str, Any]) -> None:
        self.user_workspaces.upsert_user_workspace(workspace)

    def get_user_workspace(self, user_id: str) -> dict[str, Any] | None:
        return self.user_workspaces.get_user_workspace(user_id)

    def get_user_workspace_by_id(self, workspace_id: str) -> dict[str, Any] | None:
        return self.user_workspaces.get_user_workspace_by_id(workspace_id)

    def list_user_workspaces(self) -> list[dict[str, Any]]:
        return self.user_workspaces.list_user_workspaces()

    def insert_workspace_job(self, job: dict[str, Any]) -> None:
        self.workspace_jobs.insert_job(job)

    def enqueue_workspace_job_if_no_active(self, job: dict[str, Any]) -> bool:
        return self.workspace_jobs.enqueue_job_if_no_active(job)

    def get_workspace_job(self, job_id: str) -> dict[str, Any] | None:
        return self.workspace_jobs.get_job(job_id)

    def get_active_workspace_job_for_user(self, user_id: str) -> dict[str, Any] | None:
        return self.workspace_jobs.get_active_job_for_user(user_id)

    def claim_next_workspace_job(
        self,
        *,
        now_iso: str,
        lease_expires_at: str,
        worker_id: str,
    ) -> dict[str, Any] | None:
        return self.workspace_jobs.claim_next_job(
            now_iso=now_iso,
            lease_expires_at=lease_expires_at,
            worker_id=worker_id,
        )

    def heartbeat_workspace_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_expires_at: str,
        now_iso: str,
    ) -> bool:
        return self.workspace_jobs.heartbeat_job(
            job_id=job_id,
            worker_id=worker_id,
            lease_expires_at=lease_expires_at,
            now_iso=now_iso,
        )

    def retry_workspace_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        now_iso: str,
        not_before_at: str | None,
        last_error: str | None = None,
    ) -> bool:
        return self.workspace_jobs.retry_job(
            job_id=job_id,
            worker_id=worker_id,
            now_iso=now_iso,
            not_before_at=not_before_at,
            last_error=last_error,
        )

    def complete_workspace_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        status: str,
        now_iso: str,
        last_error: str | None = None,
    ) -> bool:
        return self.workspace_jobs.complete_job(
            job_id=job_id,
            worker_id=worker_id,
            status=status,
            now_iso=now_iso,
            last_error=last_error,
        )

    def list_active_workspace_jobs_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return self.workspace_jobs.list_active_jobs_for_user(user_id)

    def list_workspace_jobs(
        self,
        *,
        limit: int | None = None,
        include_terminal: bool = True,
    ) -> list[dict[str, Any]]:
        return self.workspace_jobs.list_jobs(
            limit=limit,
            include_terminal=include_terminal,
        )

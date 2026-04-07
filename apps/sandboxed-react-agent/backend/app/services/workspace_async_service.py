from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor

from .workspace_models import WorkspaceRecord
from .workspace_provisioning_service import WorkspaceProvisioningService


class WorkspaceAsyncService:
    def __init__(
        self,
        *,
        workspace_provisioning_service: WorkspaceProvisioningService,
        max_workers: int = 4,
    ) -> None:
        self.workspace_provisioning_service = workspace_provisioning_service
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="workspace-provisioner",
        )
        self._lock = threading.RLock()
        self._futures_by_user_id: dict[str, Future[WorkspaceRecord]] = {}

    def ensure_workspace_async(self, user_id: str) -> tuple[WorkspaceRecord, bool]:
        workspace = self.workspace_provisioning_service.prepare_workspace_for_user(
            user_id
        )
        if workspace.status == "ready":
            return workspace, False

        normalized_user_id = workspace.user_id
        with self._lock:
            future = self._futures_by_user_id.get(normalized_user_id)
            if future and not future.done():
                return workspace, False

            def _run() -> WorkspaceRecord:
                try:
                    return self.workspace_provisioning_service.provision_prepared_workspace(
                        workspace
                    )
                finally:
                    with self._lock:
                        self._futures_by_user_id.pop(normalized_user_id, None)

            self._futures_by_user_id[normalized_user_id] = self._executor.submit(_run)
        return workspace, True

    def get_pending_future(self, user_id: str) -> Future[WorkspaceRecord] | None:
        with self._lock:
            future = self._futures_by_user_id.get(user_id)
            if future and not future.done():
                return future
            return None

    def is_pending(self, user_id: str) -> bool:
        return self.get_pending_future(user_id) is not None

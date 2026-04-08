from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from ..repositories.workspace_job_repository import WorkspaceJobRepository

from .workspace_models import WorkspaceRecord
from .workspace_provisioning_service import WorkspaceProvisioningService


logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Return current timestamp in ISO-8601 UTC format.

    Returns:
        Current UTC timestamp as an ISO string.
    """
    return datetime.now(UTC).isoformat()


def _plus_seconds_iso(base_iso: str, seconds: float) -> str:
    """Add seconds to an ISO timestamp and return ISO output.

    Args:
        base_iso: Base timestamp in ISO-8601 format.
        seconds: Number of seconds to add.

    Returns:
        Updated timestamp in ISO-8601 format.
    """
    return (datetime.fromisoformat(base_iso) + timedelta(seconds=seconds)).isoformat()


class WorkspaceAsyncService:
    """Durable async orchestrator for workspace provisioning and reconcile jobs.

    The service persists jobs in SQLite, claims work with worker leases, and
    executes provisioning through a bounded thread pool.
    """

    def __init__(
        self,
        *,
        workspace_provisioning_service: WorkspaceProvisioningService,
        workspace_job_repository: WorkspaceJobRepository,
        max_workers: int = 4,
        job_lease_ttl_seconds: int = 90,
        poll_interval_seconds: float = 0.4,
        max_retry_attempts: int = 3,
        retry_backoff_seconds: float = 5.0,
    ) -> None:
        """Initialize async workspace orchestration service.

        Args:
            workspace_provisioning_service: Synchronous provisioning backend.
            workspace_job_repository: Durable repository for job queue state.
            max_workers: Maximum concurrent worker threads.
            job_lease_ttl_seconds: Worker lease TTL for running jobs.
            poll_interval_seconds: Dispatcher wake interval when queue is idle.
            max_retry_attempts: Maximum number of attempts per job before marking
                it failed.
            retry_backoff_seconds: Delay between retry attempts.
        """
        self.workspace_provisioning_service = workspace_provisioning_service
        self.workspace_job_repository = workspace_job_repository
        self.max_workers = max(1, int(max_workers))
        self.job_lease_ttl_seconds = max(15, int(job_lease_ttl_seconds))
        self.poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self.max_retry_attempts = max(1, int(max_retry_attempts))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.worker_id = f"workspace-job-worker-{uuid.uuid4().hex[:12]}"

        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="workspace-provisioner",
        )
        self._lock = threading.RLock()
        self._futures_by_user_id: dict[str, Future[WorkspaceRecord]] = {}
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._closed = False
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop,
            name="workspace-job-dispatcher",
            daemon=True,
        )
        self._dispatcher.start()

    def _active_future_count(self) -> int:
        """Count currently running futures tracked in-memory.

        Returns:
            Number of unfinished futures.
        """
        with self._lock:
            return sum(
                1 for future in self._futures_by_user_id.values() if not future.done()
            )

    def _cleanup_done_futures(self) -> None:
        """Remove completed futures from in-memory tracking map."""
        with self._lock:
            done_users = [
                user_id
                for user_id, future in self._futures_by_user_id.items()
                if future.done()
            ]
            for user_id in done_users:
                self._futures_by_user_id.pop(user_id, None)

    def _run_job(self, job: dict[str, object]) -> WorkspaceRecord:
        """Execute one claimed workspace job.

        Args:
            job: Claimed job payload.

        Returns:
            Resulting workspace record after provisioning.

        Raises:
            Exception: Re-raises provisioning exceptions after marking job failed.
        """
        job_id = str(job.get("job_id") or "")
        user_id = str(job.get("user_id") or "")
        heartbeat_stop = threading.Event()

        def _heartbeat() -> None:
            interval = max(1.0, self.job_lease_ttl_seconds / 2)
            while not heartbeat_stop.wait(interval):
                now_iso = _now_iso()
                ok = self.workspace_job_repository.heartbeat(
                    job_id=job_id,
                    worker_id=self.worker_id,
                    lease_expires_at=_plus_seconds_iso(
                        now_iso, self.job_lease_ttl_seconds
                    ),
                    now_iso=now_iso,
                )
                if not ok:
                    return

        heartbeat_thread = threading.Thread(
            target=_heartbeat,
            name=f"workspace-job-heartbeat-{job_id[:8]}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            workspace = self.workspace_provisioning_service.prepare_workspace_for_user(
                user_id
            )
            resolved = self.workspace_provisioning_service.provision_prepared_workspace(
                workspace
            )
            self.workspace_job_repository.complete(
                job_id=job_id,
                worker_id=self.worker_id,
                status="succeeded",
                now_iso=_now_iso(),
            )
            return resolved
        except Exception as exc:
            attempt_count = int(job.get("attempt_count") or 1)
            now_iso = _now_iso()
            should_retry = attempt_count < self.max_retry_attempts

            if should_retry:
                not_before_at = _plus_seconds_iso(now_iso, self.retry_backoff_seconds)
                retried = self.workspace_job_repository.retry(
                    job_id=job_id,
                    worker_id=self.worker_id,
                    now_iso=now_iso,
                    not_before_at=not_before_at,
                    last_error=str(exc),
                )
                if retried:
                    logger.warning(
                        "workspace.job.retry_scheduled",
                        extra={
                            "event": "workspace.job.retry_scheduled",
                            "job_id": job_id,
                            "user_id": user_id,
                            "attempt_count": attempt_count,
                            "max_retry_attempts": self.max_retry_attempts,
                            "retry_backoff_seconds": self.retry_backoff_seconds,
                            "error": str(exc),
                        },
                    )
                    existing = (
                        self.workspace_provisioning_service.get_workspace_for_user(
                            user_id
                        )
                    )
                    if existing is not None:
                        return existing
                    return (
                        self.workspace_provisioning_service.prepare_workspace_for_user(
                            user_id
                        )
                    )

            self.workspace_job_repository.complete(
                job_id=job_id,
                worker_id=self.worker_id,
                status="failed",
                now_iso=now_iso,
                last_error=str(exc),
            )
            logger.exception(
                "workspace.job.failed",
                extra={
                    "event": "workspace.job.failed",
                    "job_id": job_id,
                    "user_id": user_id,
                    "attempt_count": attempt_count,
                    "max_retry_attempts": self.max_retry_attempts,
                    "error": str(exc),
                },
            )
            raise
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1.0)

    def _dispatch_loop(self) -> None:
        """Continuously claim and dispatch jobs while the service is active."""
        while not self._stop_event.is_set():
            self._cleanup_done_futures()
            started_any = False
            while self._active_future_count() < self.max_workers:
                now_iso = _now_iso()
                job = self.workspace_job_repository.claim_next(
                    now_iso=now_iso,
                    lease_expires_at=_plus_seconds_iso(
                        now_iso, self.job_lease_ttl_seconds
                    ),
                    worker_id=self.worker_id,
                )
                if not job:
                    break
                user_id = str(job.get("user_id") or "")
                if not user_id:
                    continue
                future = self._executor.submit(self._run_job, job)
                with self._lock:
                    self._futures_by_user_id[user_id] = future
                started_any = True

            if started_any:
                continue

            self._wake_event.wait(self.poll_interval_seconds)
            self._wake_event.clear()

    def ensure_workspace_async(
        self, user_id: str, *, reconcile_ready: bool = False
    ) -> tuple[WorkspaceRecord, bool]:
        """Queue async workspace provisioning/reconciliation for a user.

        Args:
            user_id: User identifier.
            reconcile_ready: Whether to reconcile already-ready workspaces.

        Returns:
            Tuple of workspace snapshot and whether a new job was enqueued.
        """
        workspace = self.workspace_provisioning_service.prepare_workspace_for_user(
            user_id
        )
        if workspace.status == "ready" and not reconcile_ready:
            return workspace, False

        normalized_user_id = workspace.user_id
        with self._lock:
            future = self._futures_by_user_id.get(normalized_user_id)
            if future and not future.done():
                return workspace, False

        timestamp = _now_iso()
        started = self.workspace_job_repository.enqueue_if_no_active(
            {
                "job_id": f"wjob-{uuid.uuid4().hex}",
                "user_id": normalized_user_id,
                "workspace_id": workspace.workspace_id,
                "status": "queued",
                "reconcile_ready": bool(reconcile_ready),
                "attempt_count": 0,
                "last_error": None,
                "not_before_at": timestamp,
                "created_at": timestamp,
                "updated_at": timestamp,
                "started_at": None,
                "completed_at": None,
                "lease_expires_at": None,
                "worker_id": None,
            }
        )
        if not started:
            return workspace, False
        self._wake_event.set()
        return workspace, True

    def get_pending_future(self, user_id: str) -> Future[WorkspaceRecord] | None:
        """Return active in-memory future for a user, if any.

        Args:
            user_id: User identifier.

        Returns:
            Running future or ``None``.
        """
        with self._lock:
            future = self._futures_by_user_id.get(user_id)
            if future and not future.done():
                return future
            return None

    def is_pending(self, user_id: str) -> bool:
        """Check whether async workspace work is active for a user.

        Args:
            user_id: User identifier.

        Returns:
            ``True`` when there is an in-memory future or queued/running job.
        """
        if self.get_pending_future(user_id) is not None:
            return True
        return self.workspace_job_repository.get_active_for_user(user_id) is not None

    def shutdown(self, *, wait: bool = True, timeout_seconds: float = 5.0) -> None:
        """Stop dispatcher thread and worker pool.

        Args:
            wait: Whether to wait for running tasks to complete.
            timeout_seconds: Maximum wait time for dispatcher shutdown.
        """
        with self._shutdown_lock:
            if self._closed:
                return
            self._closed = True

        self._stop_event.set()
        self._wake_event.set()
        self._dispatcher.join(timeout=max(0.1, float(timeout_seconds)))
        self._executor.shutdown(wait=wait)

    def __del__(self) -> None:
        """Best-effort cleanup when service is garbage collected."""
        try:
            self.shutdown(wait=False, timeout_seconds=0.5)
        except Exception:
            pass

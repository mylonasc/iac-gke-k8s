from __future__ import annotations

from typing import Any

from ..session_store import SessionStore


class WorkspaceJobRepository:
    """Repository for durable workspace provisioning jobs."""

    def __init__(self, session_store: SessionStore) -> None:
        """Initialize the repository.

        Args:
            session_store: Shared persistence facade.
        """
        self.session_store = session_store

    def insert(self, job: dict[str, Any]) -> None:
        """Insert a job record without deduplication.

        Args:
            job: Workspace job payload.
        """
        self.session_store.insert_workspace_job(job)

    def enqueue_if_no_active(self, job: dict[str, Any]) -> bool:
        """Insert a job when no active job exists for the user.

        Args:
            job: Workspace job payload.

        Returns:
            ``True`` when a new job was enqueued, else ``False``.
        """
        return self.session_store.enqueue_workspace_job_if_no_active(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Fetch a job by identifier.

        Args:
            job_id: Job identifier.

        Returns:
            Job payload when found, otherwise ``None``.
        """
        return self.session_store.get_workspace_job(job_id)

    def get_active_for_user(self, user_id: str) -> dict[str, Any] | None:
        """Fetch one active job for a user.

        Args:
            user_id: User identifier.

        Returns:
            Active queued/running job, or ``None``.
        """
        return self.session_store.get_active_workspace_job_for_user(user_id)

    def claim_next(
        self,
        *,
        now_iso: str,
        lease_expires_at: str,
        worker_id: str,
    ) -> dict[str, Any] | None:
        """Claim the next runnable job for a worker.

        Args:
            now_iso: Current timestamp.
            lease_expires_at: New worker lease deadline.
            worker_id: Worker identifier.

        Returns:
            Claimed job payload, or ``None`` when queue is empty.
        """
        return self.session_store.claim_next_workspace_job(
            now_iso=now_iso,
            lease_expires_at=lease_expires_at,
            worker_id=worker_id,
        )

    def heartbeat(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_expires_at: str,
        now_iso: str,
    ) -> bool:
        """Refresh a running job lease for the worker.

        Args:
            job_id: Job identifier.
            worker_id: Worker identifier.
            lease_expires_at: Extended lease deadline.
            now_iso: Current timestamp.

        Returns:
            ``True`` when heartbeat was applied.
        """
        return self.session_store.heartbeat_workspace_job(
            job_id=job_id,
            worker_id=worker_id,
            lease_expires_at=lease_expires_at,
            now_iso=now_iso,
        )

    def retry(
        self,
        *,
        job_id: str,
        worker_id: str,
        now_iso: str,
        not_before_at: str | None,
        last_error: str | None = None,
    ) -> bool:
        """Move a running job back to queued state for retry.

        Args:
            job_id: Job identifier.
            worker_id: Worker identifier.
            now_iso: Current timestamp.
            not_before_at: Earliest retry claim timestamp.
            last_error: Optional error text from failed attempt.

        Returns:
            ``True`` when retry transition was applied.
        """
        return self.session_store.retry_workspace_job(
            job_id=job_id,
            worker_id=worker_id,
            now_iso=now_iso,
            not_before_at=not_before_at,
            last_error=last_error,
        )

    def complete(
        self,
        *,
        job_id: str,
        worker_id: str,
        status: str,
        now_iso: str,
        last_error: str | None = None,
    ) -> bool:
        """Mark a running job terminal for the current worker.

        Args:
            job_id: Job identifier.
            worker_id: Worker identifier.
            status: Terminal status.
            now_iso: Completion timestamp.
            last_error: Optional failure text.

        Returns:
            ``True`` when status transition succeeded.
        """
        return self.session_store.complete_workspace_job(
            job_id=job_id,
            worker_id=worker_id,
            status=status,
            now_iso=now_iso,
            last_error=last_error,
        )

    def list_active_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """List active jobs for a user.

        Args:
            user_id: User identifier.

        Returns:
            Active queued/running jobs ordered by creation time.
        """
        return self.session_store.list_active_workspace_jobs_for_user(user_id)

    def list_jobs(
        self,
        *,
        limit: int | None = None,
        include_terminal: bool = True,
    ) -> list[dict[str, Any]]:
        """List workspace jobs for admin and diagnostics views.

        Args:
            limit: Optional maximum number of jobs to return.
            include_terminal: Whether to include terminal states.

        Returns:
            Job records ordered by recency.
        """
        return self.session_store.list_workspace_jobs(
            limit=limit,
            include_terminal=include_terminal,
        )

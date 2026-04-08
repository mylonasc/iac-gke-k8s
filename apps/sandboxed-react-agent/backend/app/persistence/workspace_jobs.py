from __future__ import annotations

from typing import Any, Callable


class SQLiteWorkspaceJobStore:
    """SQLite persistence adapter for durable workspace job queue state."""

    def __init__(self, connect: Callable[[], object]) -> None:
        """Initialize store with a connection factory.

        Args:
            connect: Callable returning a SQLite connection.
        """
        self.connect = connect

    def _to_record(self, row: Any) -> dict[str, Any]:
        """Convert SQLite row to workspace job record.

        Args:
            row: SQLite row object.

        Returns:
            Normalized dictionary record.
        """
        return {
            "job_id": row["job_id"],
            "user_id": row["user_id"],
            "workspace_id": row["workspace_id"],
            "status": row["status"],
            "reconcile_ready": bool(row["reconcile_ready"]),
            "attempt_count": int(row["attempt_count"]),
            "last_error": row["last_error"],
            "not_before_at": row["not_before_at"]
            if "not_before_at" in row.keys()
            else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "lease_expires_at": row["lease_expires_at"],
            "worker_id": row["worker_id"],
        }

    def insert_job(self, job: dict[str, Any]) -> None:
        """Insert a workspace job row.

        Args:
            job: Job payload in storage format.
        """
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO workspace_jobs (
                    job_id,
                    user_id,
                    workspace_id,
                    status,
                    reconcile_ready,
                    attempt_count,
                    last_error,
                    not_before_at,
                    created_at,
                    updated_at,
                    started_at,
                    completed_at,
                    lease_expires_at,
                    worker_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job["job_id"],
                    job["user_id"],
                    job.get("workspace_id"),
                    job["status"],
                    1 if job.get("reconcile_ready") else 0,
                    int(job.get("attempt_count") or 0),
                    job.get("last_error"),
                    job.get("not_before_at"),
                    job["created_at"],
                    job["updated_at"],
                    job.get("started_at"),
                    job.get("completed_at"),
                    job.get("lease_expires_at"),
                    job.get("worker_id"),
                ),
            )

    def enqueue_job_if_no_active(self, job: dict[str, Any]) -> bool:
        """Insert a queued job only when no active job exists for user.

        Args:
            job: Job payload in storage format.

        Returns:
            ``True`` when a new job was inserted.
        """
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                """
                SELECT job_id
                FROM workspace_jobs
                WHERE user_id = ?
                  AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (job["user_id"],),
            ).fetchone()
            if active:
                connection.commit()
                return False

            connection.execute(
                """
                INSERT INTO workspace_jobs (
                    job_id,
                    user_id,
                    workspace_id,
                    status,
                    reconcile_ready,
                    attempt_count,
                    last_error,
                    not_before_at,
                    created_at,
                    updated_at,
                    started_at,
                    completed_at,
                    lease_expires_at,
                    worker_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job["job_id"],
                    job["user_id"],
                    job.get("workspace_id"),
                    job["status"],
                    1 if job.get("reconcile_ready") else 0,
                    int(job.get("attempt_count") or 0),
                    job.get("last_error"),
                    job.get("not_before_at"),
                    job["created_at"],
                    job["updated_at"],
                    job.get("started_at"),
                    job.get("completed_at"),
                    job.get("lease_expires_at"),
                    job.get("worker_id"),
                ),
            )
            connection.commit()
            return True

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Fetch job by identifier.

        Args:
            job_id: Job identifier.

        Returns:
            Job record when found, otherwise ``None``.
        """
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM workspace_jobs WHERE job_id = ? LIMIT 1",
                (job_id,),
            ).fetchone()
        return self._to_record(row) if row else None

    def get_active_job_for_user(self, user_id: str) -> dict[str, Any] | None:
        """Fetch active queued/running job for user.

        Args:
            user_id: User identifier.

        Returns:
            Oldest active job for user, or ``None``.
        """
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM workspace_jobs
                WHERE user_id = ?
                  AND status IN ('queued', 'running')
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return self._to_record(row) if row else None

    def claim_next_job(
        self,
        *,
        now_iso: str,
        lease_expires_at: str,
        worker_id: str,
    ) -> dict[str, Any] | None:
        """Claim next available or stale-running job for worker execution.

        Args:
            now_iso: Current timestamp.
            lease_expires_at: Lease deadline assigned to worker.
            worker_id: Worker identifier.

        Returns:
            Claimed job record, or ``None`` when nothing is claimable.
        """
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT *
                FROM workspace_jobs
                WHERE (status = 'queued' AND (not_before_at IS NULL OR not_before_at <= ?))
                   OR (status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?)
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (now_iso, now_iso),
            ).fetchone()
            if not row:
                connection.commit()
                return None

            job_id = row["job_id"]
            connection.execute(
                """
                UPDATE workspace_jobs
                SET
                    status = 'running',
                    attempt_count = COALESCE(attempt_count, 0) + 1,
                    updated_at = ?,
                    started_at = COALESCE(started_at, ?),
                    lease_expires_at = ?,
                    worker_id = ?,
                    not_before_at = NULL,
                    completed_at = NULL
                WHERE job_id = ?
                """,
                (now_iso, now_iso, lease_expires_at, worker_id, job_id),
            )
            claimed = connection.execute(
                "SELECT * FROM workspace_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            connection.commit()
        return self._to_record(claimed) if claimed else None

    def heartbeat_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_expires_at: str,
        now_iso: str,
    ) -> bool:
        """Update running job heartbeat and lease deadline.

        Args:
            job_id: Job identifier.
            worker_id: Worker identifier.
            lease_expires_at: Updated lease deadline.
            now_iso: Current timestamp.

        Returns:
            ``True`` when heartbeat succeeded.
        """
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE workspace_jobs
                SET
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE job_id = ?
                  AND status = 'running'
                  AND worker_id = ?
                """,
                (lease_expires_at, now_iso, job_id, worker_id),
            )
        return bool(getattr(cursor, "rowcount", 0))

    def retry_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        now_iso: str,
        not_before_at: str | None,
        last_error: str | None = None,
    ) -> bool:
        """Return a running job back to queued state for retry.

        Args:
            job_id: Job identifier.
            worker_id: Worker identifier that currently owns the job.
            now_iso: Current timestamp.
            not_before_at: Earliest timestamp the retry may be claimed.
            last_error: Optional error text from failed attempt.

        Returns:
            ``True`` when transition was applied.
        """
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE workspace_jobs
                SET
                    status = 'queued',
                    updated_at = ?,
                    lease_expires_at = NULL,
                    worker_id = NULL,
                    completed_at = NULL,
                    last_error = ?,
                    not_before_at = ?
                WHERE job_id = ?
                  AND status = 'running'
                  AND worker_id = ?
                """,
                (now_iso, last_error, not_before_at, job_id, worker_id),
            )
        return bool(getattr(cursor, "rowcount", 0))

    def complete_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        status: str,
        now_iso: str,
        last_error: str | None = None,
    ) -> bool:
        """Mark running job completed with terminal status.

        Args:
            job_id: Job identifier.
            worker_id: Worker identifier.
            status: Terminal status value.
            now_iso: Completion timestamp.
            last_error: Optional error text.

        Returns:
            ``True`` when transition was applied.
        """
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE workspace_jobs
                SET
                    status = ?,
                    updated_at = ?,
                    completed_at = ?,
                    lease_expires_at = NULL,
                    worker_id = ?,
                    last_error = ?
                WHERE job_id = ?
                  AND status = 'running'
                  AND worker_id = ?
                """,
                (status, now_iso, now_iso, worker_id, last_error, job_id, worker_id),
            )
        return bool(getattr(cursor, "rowcount", 0))

    def list_active_jobs_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """List active queued/running jobs for user.

        Args:
            user_id: User identifier.

        Returns:
            Active jobs ordered by creation time.
        """
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM workspace_jobs
                WHERE user_id = ?
                  AND status IN ('queued', 'running')
                ORDER BY created_at ASC
                """,
                (user_id,),
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def list_jobs(
        self,
        *,
        limit: int | None = None,
        include_terminal: bool = True,
    ) -> list[dict[str, Any]]:
        """List workspace jobs for diagnostics and admin endpoints.

        Args:
            limit: Optional row limit.
            include_terminal: Whether terminal jobs are included.

        Returns:
            Job records ordered by recency.
        """
        with self.connect() as connection:
            if include_terminal:
                if limit is None:
                    rows = connection.execute(
                        """
                        SELECT *
                        FROM workspace_jobs
                        ORDER BY created_at DESC
                        """
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT *
                        FROM workspace_jobs
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (int(limit),),
                    ).fetchall()
            else:
                if limit is None:
                    rows = connection.execute(
                        """
                        SELECT *
                        FROM workspace_jobs
                        WHERE status IN ('queued', 'running')
                        ORDER BY created_at DESC
                        """
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT *
                        FROM workspace_jobs
                        WHERE status IN ('queued', 'running')
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (int(limit),),
                    ).fetchall()
        return [self._to_record(row) for row in rows]

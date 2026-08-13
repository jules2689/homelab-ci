"""Read-only access to CI-Lite's SQLite job history."""

import sqlite3
from pathlib import Path


_STATUSES = {-2: "cancelled", -1: "pending", 0: "failed", 1: "passed"}


class JobStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise FileNotFoundError(f"CI-Lite database not found: {self.db_path}")
        connection = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _repository_parts(repository: str) -> tuple[str, str]:
        parts = (repository or "").strip().strip("/").split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError("repository must be in owner/repo format")
        return parts[0], parts[1]

    def list_jobs(self, repository: str, commit_sha: str) -> list[dict]:
        """List all CI jobs for an exact repository and commit, newest first."""
        owner, repo = self._repository_parts(repository)
        sha = (commit_sha or "").strip().lower()
        if len(sha) < 7:
            raise ValueError("commit_sha must contain at least 7 hexadecimal characters")
        try:
            int(sha, 16)
        except ValueError as exc:
            raise ValueError("commit_sha must be hexadecimal") from exc
        stored_sha = sha[:7]

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, owner, repo, sha, success, html_url, at, output,
                       branch, commit_message, started_at
                FROM runs
                WHERE owner = ? AND repo = ? AND lower(sha) = ?
                ORDER BY id DESC
                """,
                (owner, repo, stored_sha),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "repository": f'{row["owner"]}/{row["repo"]}',
                "commit_sha": row["sha"],
                "status": _STATUSES.get(row["success"], "unknown"),
                "branch": row["branch"] or "main",
                "commit_message": row["commit_message"] or "",
                "started_at": row["started_at"] or row["at"],
                "completed_at": None if row["success"] == -1 else row["at"],
                "github_url": row["html_url"] or "",
                "has_logs": bool(row["output"]),
            }
            for row in rows
        ]

    def read_job_logs(self, job_id: int, offset: int = 0, limit: int = 20_000) -> dict:
        """Read a bounded section of one job's stored output."""
        if job_id < 1:
            raise ValueError("job_id must be positive")
        if offset < 0:
            raise ValueError("offset cannot be negative")
        if not 1 <= limit <= 100_000:
            raise ValueError("limit must be between 1 and 100000")

        with self._connect() as connection:
            row = connection.execute(
                "SELECT owner, repo, sha, output FROM runs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"job {job_id} not found")

        logs = row["output"] or ""
        chunk = logs[offset : offset + limit]
        next_offset = offset + len(chunk)
        return {
            "job_id": job_id,
            "repository": f'{row["owner"]}/{row["repo"]}',
            "commit_sha": row["sha"],
            "offset": offset,
            "next_offset": next_offset,
            "total_length": len(logs),
            "truncated": next_offset < len(logs),
            "logs": chunk,
        }

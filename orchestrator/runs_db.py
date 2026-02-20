"""SQLite storage for run history (owner, repo, sha, success, html_url, at, output)."""
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Cap stored log size in DB (full logs for web UI; GitHub Checks API gets truncated separately)
MAX_OUTPUT_LEN = 1_000_000  # 1 MB per run


def _db_path() -> Path:
    path = os.environ.get("CI_LITE_DB")
    if path:
        return Path(path)
    data_dir = Path(os.path.expanduser(os.environ.get("CI_LITE_DATA_DIR", "~/.ci-lite")))
    return data_dir / "runs.db"


def init_db(path: Path | None = None) -> None:
    path = path or _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                repo TEXT NOT NULL,
                sha TEXT NOT NULL,
                success INTEGER NOT NULL,
                html_url TEXT NOT NULL,
                at TEXT NOT NULL,
                output TEXT NOT NULL DEFAULT ''
            )
        """)
        # Add output column if missing (existing DBs)
        info = conn.execute("PRAGMA table_info(runs)").fetchall()
        if not any(c[1] == "output" for c in info):
            conn.execute("ALTER TABLE runs ADD COLUMN output TEXT NOT NULL DEFAULT ''")
        if not any(c[1] == "branch" for c in info):
            conn.execute("ALTER TABLE runs ADD COLUMN branch TEXT NOT NULL DEFAULT 'main'")
        if not any(c[1] == "commit_message" for c in info):
            conn.execute("ALTER TABLE runs ADD COLUMN commit_message TEXT NOT NULL DEFAULT ''")
        if not any(c[1] == "started_at" for c in info):
            conn.execute("ALTER TABLE runs ADD COLUMN started_at TEXT NOT NULL DEFAULT ''")


# success: 1=pass, 0=fail, -1=pending, -2=cancelled (e.g. container restarted before job finished)
PENDING = -1
CANCELLED = -2


def record_pending_run(
    owner: str,
    repo: str,
    sha: str,
    html_url: str,
    at: str,
    branch: str = "main",
    commit_message: str = "",
) -> None:
    """Insert a run in pending state (job started, not yet completed)."""
    path = _db_path()
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO runs (owner, repo, sha, success, html_url, at, output, branch, commit_message, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (owner, repo, sha[:7], PENDING, html_url or "", at, "", branch or "main", (commit_message or "")[:2048], at),
        )


def record_run(
    owner: str,
    repo: str,
    sha: str,
    success: bool,
    html_url: str,
    at: str,
    output: str = "",
    branch: str = "main",
    commit_message: str = "",
) -> None:
    """Record completed run: update existing pending run for this owner/repo/sha, or insert."""
    path = _db_path()
    init_db(path)
    out = (output or "")[:MAX_OUTPUT_LEN]
    msg = (commit_message or "")[:2048]
    with sqlite3.connect(path) as conn:
        cur = conn.execute(
            "SELECT id FROM runs WHERE owner=? AND repo=? AND sha=? AND success=? ORDER BY id DESC LIMIT 1",
            (owner, repo, sha[:7], PENDING),
        )
        row = cur.fetchone()
        if row:
            # at = completed_at; started_at stays as set when pending was inserted
            conn.execute(
                "UPDATE runs SET success=?, html_url=?, at=?, output=?, branch=?, commit_message=? WHERE id=?",
                (1 if success else 0, html_url or "", at, out, branch or "main", msg, row[0]),
            )
        else:
            conn.execute(
                "INSERT INTO runs (owner, repo, sha, success, html_url, at, output, branch, commit_message, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (owner, repo, sha[:7], 1 if success else 0, html_url or "", at, out, branch or "main", msg, at),
            )


def get_runs(limit: int = 200) -> list[dict]:
    """Return recent runs (newest first) with owner, repo, sha, success, html_url, at, output, commit_message, started_at."""
    path = _db_path()
    if not path.exists():
        return []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT owner, repo, sha, success, html_url, at, output, commit_message, started_at FROM runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT owner, repo, sha, success, html_url, at, output FROM runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [
        {
            "owner": r["owner"],
            "repo": r["repo"],
            "sha": r["sha"],
            "success": None if r["success"] == PENDING else ("cancelled" if r["success"] == CANCELLED else bool(r["success"])),
            "html_url": r["html_url"] or "",
            "at": r["at"],
            "output": (r["output"] if "output" in r.keys() else "") or "",
            "commit_message": r["commit_message"] if "commit_message" in r.keys() else "",
            "started_at": r["started_at"] if "started_at" in r.keys() else r["at"],
        }
        for r in rows
    ]


def mark_pending_run_cancelled(owner: str, repo: str, sha: str) -> None:
    """Mark the most recent pending run for this owner/repo/sha as cancelled (e.g. before restarting the job)."""
    path = _db_path()
    if not path.exists():
        return
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE runs SET success=? WHERE owner=? AND repo=? AND sha=? AND success=?",
            (CANCELLED, owner, repo, sha[:7], PENDING),
        )


def get_pending_runs() -> list[dict]:
    """Return runs that are still pending (job was started but never completed, e.g. container killed)."""
    path = _db_path()
    if not path.exists():
        return []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT owner, repo, sha, branch FROM runs WHERE success=? ORDER BY id DESC",
                (PENDING,),
            ).fetchall()
        except sqlite3.OperationalError:
            # branch column may not exist yet
            rows = conn.execute(
                "SELECT owner, repo, sha FROM runs WHERE success=? ORDER BY id DESC",
                (PENDING,),
            ).fetchall()
    return [
        {
            "owner": r["owner"],
            "repo": r["repo"],
            "sha": r["sha"],
            "branch": r["branch"] if "branch" in r.keys() else "main",
        }
        for r in rows
    ]


def archive_runs_older_than(days: int) -> int:
    """Delete runs with `at` older than the given number of days. Returns number of rows deleted."""
    path = _db_path()
    if not path.exists():
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with sqlite3.connect(path) as conn:
        cur = conn.execute("DELETE FROM runs WHERE at < ?", (cutoff,))
        return cur.rowcount

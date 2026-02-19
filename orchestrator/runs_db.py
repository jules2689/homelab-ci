"""SQLite storage for run history (owner, repo, sha, success, html_url, at, output)."""
import sqlite3
import os
from pathlib import Path

# Cap stored log size (match GitHub Checks API limit)
MAX_OUTPUT_LEN = 65535


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


def record_run(
    owner: str,
    repo: str,
    sha: str,
    success: bool,
    html_url: str,
    at: str,
    output: str = "",
) -> None:
    path = _db_path()
    init_db(path)
    out = (output or "")[:MAX_OUTPUT_LEN]
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO runs (owner, repo, sha, success, html_url, at, output) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (owner, repo, sha[:7], 1 if success else 0, html_url or "", at, out),
        )


def get_runs(limit: int = 200) -> list[dict]:
    """Return recent runs (newest first) as list of dicts with owner, repo, sha, success, html_url, at, output."""
    path = _db_path()
    if not path.exists():
        return []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT owner, repo, sha, success, html_url, at, output FROM runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            has_output = True
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT owner, repo, sha, success, html_url, at FROM runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            has_output = False
    return [
        {
            "owner": r["owner"],
            "repo": r["repo"],
            "sha": r["sha"],
            "success": bool(r["success"]),
            "html_url": r["html_url"] or "",
            "at": r["at"],
            "output": (r["output"] if has_output and "output" in r.keys() else "") or "",
        }
        for r in rows
    ]

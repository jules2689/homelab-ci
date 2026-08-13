import sqlite3
import tempfile
import unittest
from pathlib import Path

from mcp_server.store import JobStore


class JobStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "runs.db"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner TEXT NOT NULL,
                    repo TEXT NOT NULL,
                    sha TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    html_url TEXT NOT NULL,
                    at TEXT NOT NULL,
                    output TEXT NOT NULL DEFAULT '',
                    branch TEXT NOT NULL DEFAULT 'main',
                    commit_message TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.executemany(
                """
                INSERT INTO runs
                    (owner, repo, sha, success, html_url, at, output, branch, commit_message, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("acme", "widget", "abcdef1", 0, "https://example.test/1", "2026-08-13T10:02:00Z", "first failure", "main", "Fix widget", "2026-08-13T10:00:00Z"),
                    ("acme", "widget", "abcdef1", 1, "https://example.test/2", "2026-08-13T10:05:00Z", "passed", "main", "Fix widget", "2026-08-13T10:04:00Z"),
                    ("other", "widget", "abcdef1", -1, "", "2026-08-13T10:06:00Z", "", "main", "Other", "2026-08-13T10:06:00Z"),
                ],
            )
        self.store = JobStore(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_list_jobs_filters_by_repository_and_commit_newest_first(self):
        jobs = self.store.list_jobs("acme/widget", "abcdef1234567890")

        self.assertEqual([job["id"] for job in jobs], [2, 1])
        self.assertEqual([job["status"] for job in jobs], ["passed", "failed"])
        self.assertEqual(jobs[0]["repository"], "acme/widget")
        self.assertTrue(jobs[0]["has_logs"])
        self.assertNotIn("logs", jobs[0])

    def test_list_jobs_rejects_repository_without_owner(self):
        with self.assertRaisesRegex(ValueError, "owner/repo"):
            self.store.list_jobs("widget", "abcdef1")

    def test_read_job_logs_returns_bounded_chunk_and_metadata(self):
        result = self.store.read_job_logs(1, offset=6, limit=7)

        self.assertEqual(result["logs"], "failure")
        self.assertEqual(result["offset"], 6)
        self.assertEqual(result["next_offset"], 13)
        self.assertEqual(result["total_length"], 13)
        self.assertFalse(result["truncated"])

    def test_read_job_logs_reports_missing_job(self):
        with self.assertRaisesRegex(LookupError, "not found"):
            self.store.read_job_logs(999)


if __name__ == "__main__":
    unittest.main()

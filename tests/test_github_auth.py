import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
import github_app
import github_checks
import github_api
import main
import runs_db


class GitHubAuthTest(unittest.TestCase):
    def setUp(self):
        github_app._installation_id_cache.clear()
        github_app._token_cache.clear()
        github_app._installation_id_cache[("acme", "widget")] = 42
        github_app._token_cache[42] = ("old-token", 2000)
        self.addCleanup(github_app._installation_id_cache.clear)
        self.addCleanup(github_app._token_cache.clear)

    def response(self, body):
        return io.BytesIO(json.dumps(body).encode())

    def unauthorized(self):
        return urllib.error.HTTPError(
            "https://api.github.com/repos/acme/widget/check-runs/7",
            401, "Unauthorized", {}, io.BytesIO(b'{"message":"Bad credentials"}'),
        )

    def complete(self):
        return github_checks.complete_check_run(
            "acme", "widget", 7, "abcdef", True, output_text="passed", token="old-token",
        )

    def test_completion_refreshes_expired_token_before_sending(self):
        sent = []
        def open_request(request, **kwargs):
            sent.append(request.get_header("Authorization"))
            return self.response({"id": 7})
        with patch.object(github_app.time, "time", return_value=2100), \
             patch.object(github_app, "_req_app", return_value={"token": "fresh-token", "expires_at": "2099-01-01T00:00:00Z"}) as mint, \
             patch("urllib.request.urlopen", side_effect=open_request):
            self.assertEqual(self.complete()["id"], 7)
        self.assertEqual(sent, ["Bearer fresh-token"])
        mint.assert_called_once()

    def test_completion_retries_same_check_once_after_401(self):
        sent = []
        def open_request(request, **kwargs):
            sent.append((request.full_url, request.method, request.data, request.get_header("Authorization")))
            if len(sent) == 1:
                raise self.unauthorized()
            return self.response({"id": 7})
        with patch.object(github_app.time, "time", return_value=1000), \
             patch.object(github_app, "_req_app", return_value={"token": "fresh-token", "expires_at": "2099-01-01T00:00:00Z"}) as mint, \
             patch("urllib.request.urlopen", side_effect=open_request):
            self.assertEqual(self.complete()["id"], 7)
        self.assertEqual([item[3] for item in sent], ["Bearer old-token", "Bearer fresh-token"])
        self.assertEqual(sent[0][:3], sent[1][:3])
        self.assertEqual(json.loads(sent[1][2])["conclusion"], "success")
        mint.assert_called_once()

    def test_permanent_401_stops_after_one_refresh_without_logging_tokens(self):
        sent = []
        def open_request(request, **kwargs):
            sent.append(request.get_header("Authorization"))
            raise self.unauthorized()
        with patch.object(github_app.time, "time", return_value=1000), \
             patch.object(github_app, "_req_app", return_value={"token": "fresh-token", "expires_at": "2099-01-01T00:00:00Z"}) as mint, \
             patch("urllib.request.urlopen", side_effect=open_request), \
             self.assertNoLogs(github_app.logger, level="DEBUG"), \
             self.assertRaises(urllib.error.HTTPError) as error:
            self.complete()
        self.assertEqual(error.exception.code, 401)
        self.assertNotIn("old-token", str(error.exception))
        self.assertNotIn("fresh-token", str(error.exception))
        self.assertEqual(sent, ["Bearer old-token", "Bearer fresh-token"])
        mint.assert_called_once()

    def test_commit_request_recovers_from_401(self):
        sent = []
        def open_request(request, **kwargs):
            sent.append(request.get_header("Authorization"))
            if len(sent) == 1:
                raise self.unauthorized()
            return self.response({"sha": "abcdef"})
        with patch.object(github_app.time, "time", return_value=1000), \
             patch.object(github_app, "_req_app", return_value={"token": "fresh-token", "expires_at": "2099-01-01T00:00:00Z"}), \
             patch("urllib.request.urlopen", side_effect=open_request):
            self.assertEqual(github_api.get_commit("acme", "widget", "abcdef", token="old-token"), {"sha": "abcdef"})
        self.assertEqual(sent, ["Bearer old-token", "Bearer fresh-token"])

    def test_non_auth_error_is_not_retried(self):
        error = urllib.error.HTTPError("https://api.github.com/", 403, "Forbidden", {}, io.BytesIO(b"{}"))
        with patch.object(github_app.time, "time", return_value=1000), \
             patch.object(github_app, "_req_app") as mint, \
             patch("urllib.request.urlopen", side_effect=error) as request, \
             self.assertRaises(urllib.error.HTTPError) as raised:
            self.complete()
        self.assertEqual(raised.exception.code, 403)
        self.assertEqual(request.call_count, 1)
        mint.assert_not_called()

    def test_malformed_key_is_not_disclosed_in_logs_or_error(self):
        secret = "sensitive-malformed-key-material"
        with patch.dict(os.environ, {"GITHUB_APP_PRIVATE_KEY": secret}), \
             self.assertLogs(github_app.logger, level="DEBUG") as logs, \
             self.assertRaises(ValueError) as error:
            github_app._load_private_key()
        self.assertNotIn(secret, str(error.exception))
        self.assertNotIn(secret, "\n".join(logs.output))

    def test_finished_result_survives_permanent_check_publication_failure(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"CI_LITE_DB": str(Path(directory) / "runs.db")}), \
             patch.object(main, "WORKSPACE_ROOT", directory), \
             patch.object(main, "get_repo_config", return_value={"command": "echo passed"}), \
             patch.object(main, "create_check_run", return_value={"id": 7, "html_url": "https://example.test/check/7"}), \
             patch.object(main, "run_job", return_value=(0, "passed")) as job, \
             patch.object(github_app.time, "time", return_value=1000), \
             patch.object(github_app, "_req_app", return_value={"token": "fresh-token", "expires_at": "2099-01-01T00:00:00Z"}), \
             patch("urllib.request.urlopen", side_effect=[self.unauthorized(), self.unauthorized()]) as request, \
             self.assertLogs(main.logger, level="ERROR"):
            result = main.run_one(
                {"owner": "acme", "repo": "widget", "branch": "main"},
                {"sha": "abcdef123", "commit": {"message": "Test commit"}}, token="old-token",
            )
            self.assertEqual(result, "https://example.test/check/7")
            self.assertEqual(runs_db.get_pending_runs(), [])
            runs = runs_db.get_runs()
            self.assertEqual(len(runs), 1)
            self.assertTrue(runs[0]["success"])
            self.assertEqual(runs[0]["output"], "passed")
            self.assertEqual(job.call_count, 1)
            self.assertEqual(request.call_count, 2)


    def test_batch_run_uses_current_cached_token_for_clone(self):
        github_app._token_cache[42] = ("fresh-token", 2000)
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"CI_LITE_DB": str(Path(directory) / "runs.db")}), \
             patch.object(main, "WORKSPACE_ROOT", directory), \
             patch.object(main, "get_repo_config", return_value={"command": "echo passed"}), \
             patch.object(main, "create_check_run", return_value={"id": 7}), \
             patch.object(main, "run_job", return_value=(0, "passed")) as job, \
             patch.object(github_app.time, "time", return_value=1000), \
             patch("urllib.request.urlopen", return_value=self.response({"id": 7})):
            main.run_one(
                {"owner": "acme", "repo": "widget", "branch": "main"},
                {"sha": "abcdef123", "commit": {"message": "Test commit"}}, token="old-token",
            )
        self.assertEqual(job.call_count, 1)
        self.assertEqual(
            job.call_args.kwargs["clone_url"],
            "https://x-access-token:fresh-token@github.com/acme/widget.git",
        )


if __name__ == "__main__":
    unittest.main()

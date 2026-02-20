"""GitHub Checks API: create and update check runs. Caller passes token (GitHub App installation token)."""
import json
import urllib.request
import urllib.error
from datetime import datetime


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    """Read error response body; GitHub returns JSON with 'message' and sometimes 'documentation_url'."""
    try:
        body = exc.fp.read().decode() if exc.fp else ""
        data = json.loads(body) if body else {}
        msg = data.get("message", body or exc.reason)
        doc = data.get("documentation_url", "")
        return f"{msg}" + (f" (see {doc})" if doc else "")
    except Exception:
        return exc.reason or "unknown"

API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"


def _req(method, path, body=None, *, token: str):
    url = f"{API_BASE}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = _read_error_body(e)
        raise urllib.error.HTTPError(req.full_url, e.code, f"{e.msg}: {detail}", e.headers, e.fp) from e


def create_check_run(owner: str, repo: str, head_sha: str, name: str = "ci-lite", *, token: str) -> dict:
    """Create a check run in queued state. Returns check run dict with id and html_url."""
    body = {
        "name": name,
        "head_sha": head_sha,
        "status": "in_progress",
        "started_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "output": {"title": name, "summary": "Running...", "text": ""},
    }
    return _req("POST", f"/repos/{owner}/{repo}/check-runs", body, token=token)


def update_check_run(
    owner: str,
    repo: str,
    check_run_id: int,
    head_sha: str,
    *,
    status: str = "in_progress",
    conclusion: str | None = None,
    output_title: str | None = None,
    output_summary: str | None = None,
    output_text: str | None = None,
    token: str,
) -> dict:
    """Update an existing check run. Use status='completed' and conclusion for final state."""
    body = {
        "name": "ci-lite",
        "head_sha": head_sha,
        "status": status,
    }
    # Never send started_at on update — it is set once in create_check_run and must not be overridden
    if conclusion and status == "completed":
        body["conclusion"] = conclusion
        body["completed_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    if output_title is not None or output_summary is not None or output_text is not None:
        body["output"] = {}
        if output_title is not None:
            body["output"]["title"] = output_title
        if output_summary is not None:
            body["output"]["summary"] = output_summary
        if output_text is not None:
            # GitHub has a 65535 character limit for output.text; send as markdown so **Command:** / **Output:** and code blocks render
            body["output"]["text"] = output_text[-65535:] if len(output_text) > 65535 else output_text
    return _req("PATCH", f"/repos/{owner}/{repo}/check-runs/{check_run_id}", body, token=token)


def complete_check_run(
    owner: str,
    repo: str,
    check_run_id: int,
    head_sha: str,
    success: bool,
    output_title: str = "ci-lite",
    output_summary: str = "",
    output_text: str = "",
    *,
    token: str,
) -> dict:
    """Mark check run as completed with success/failure and full output."""
    conclusion = "success" if success else "failure"
    return update_check_run(
        owner,
        repo,
        check_run_id,
        head_sha,
        status="completed",
        conclusion=conclusion,
        output_title=output_title,
        output_summary=output_summary or ("Completed successfully." if success else "Completed with failures."),
        output_text=output_text,
        token=token,
    )

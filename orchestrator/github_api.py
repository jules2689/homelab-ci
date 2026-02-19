"""GitHub API: list commits for branch (polling, no webhooks)."""
import json
import logging
import urllib.request
import urllib.parse
import urllib.error

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"
_REQUEST_TIMEOUT = 30


def get_latest_commit(owner: str, repo: str, branch: str, *, token: str) -> dict | None:
    """Get the latest commit SHA and info for the given branch. Returns None on error."""
    path = f"/repos/{owner}/{repo}/commits?sha={urllib.parse.quote(branch)}&per_page=1"
    url = f"{API_BASE}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            logger.warning("Commits API returned no list or empty for %s/%s branch %s", owner, repo, branch)
            return None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode() if e.fp else ""
        except Exception:
            pass
        msg = json.loads(body).get("message", body or e.reason) if body else e.reason
        logger.warning(
            "Commits API failed for %s/%s branch %s: %s %s",
            owner, repo, branch, e.code, msg,
        )
        return None


def get_file(owner: str, repo: str, ref: str, path: str, *, token: str) -> str | None:
    """Get raw file content from repo at ref. Returns None if not found."""
    # Use contents API: GET /repos/{owner}/{repo}/contents/{path}?ref={ref}
    url = f"{API_BASE}/repos/{owner}/{repo}/contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(ref)}"
    headers = {
        "Accept": "application/vnd.github.raw+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def list_branches(owner: str, repo: str, per_page: int = 100, *, token: str) -> list[dict]:
    """List all branches. Returns list of {name, commit: {sha}}. Paginates to get all."""
    out = []
    page = 1
    while True:
        path = f"/repos/{owner}/{repo}/branches?per_page={per_page}&page={page}"
        url = f"{API_BASE}{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            logger.warning("Branches API failed for %s/%s: %s %s", owner, repo, e.code, e.reason)
            return out
        if not isinstance(data, list) or len(data) == 0:
            break
        for b in data:
            if isinstance(b.get("commit"), dict) and b.get("commit", {}).get("sha"):
                out.append({"name": b["name"], "commit": {"sha": b["commit"]["sha"]}})
        if len(data) < per_page:
            break
        page += 1
    return out

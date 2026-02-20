"""GitHub API: get commit (for lazy commit message in web UI)."""
import json
import logging
import urllib.request
import urllib.parse
import urllib.error

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"
_REQUEST_TIMEOUT = 30


def get_commit(owner: str, repo: str, ref: str, *, token: str) -> dict | None:
    """Get a single commit by SHA or ref. Returns full commit object with commit.message or None."""
    path = f"/repos/{owner}/{repo}/commits/{urllib.parse.quote(ref)}"
    url = f"{API_BASE}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        logger.warning("Get commit failed for %s/%s ref %s: %s", owner, repo, ref[:7], e.code)
        return None

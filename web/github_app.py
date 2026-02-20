"""GitHub App auth: JWT and installation access tokens (for lazy commit message fetch)."""
import logging
import os
import time
import json
import urllib.request
from datetime import datetime
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"

_installation_id_cache: dict[tuple[str, str], int] = {}
_token_cache: dict[int, tuple[str, float]] = {}
_TOKEN_REFRESH_BUFFER = 300
_key_path_logged = False
_REQUEST_TIMEOUT = 30


def _load_private_key_pem() -> str:
    global _key_path_logged
    key = os.environ.get("GITHUB_APP_PRIVATE_KEY")
    if key:
        pem = key.replace("\\n", "\n").strip()
        logger.debug("Using key from GITHUB_APP_PRIVATE_KEY (%d chars)", len(pem))
        return pem
    path = os.environ.get("GITHUB_APP_KEY_PATH") or os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH")
    if path:
        key_path = Path(path)
        if not key_path.exists():
            logger.warning("GITHUB_APP_KEY_PATH does not exist: %s", path)
            raise FileNotFoundError(f"GitHub App key file not found: {path}")
        if not _key_path_logged:
            _key_path_logged = True
            logger.info("GITHUB_APP_KEY_PATH exists: %s", path)
        raw = key_path.read_text(encoding="utf-8")
        pem = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
        logger.debug("Read %d chars from key file", len(pem))
        return pem
    return ""


def _load_private_key():
    pem = _load_private_key_pem()
    if not pem:
        return None
    if "-----BEGIN" not in pem or "PRIVATE KEY" not in pem:
        preview = pem[:60].replace("\n", "\\n") if pem else "(empty)"
        raise ValueError(
            "GitHub App private key must be PEM (-----BEGIN ... PRIVATE KEY-----). "
            "Got %d chars starting with %r." % (len(pem), preview)
        )
    try:
        return load_pem_private_key(pem.encode("utf-8"), password=None)
    except Exception as e:
        raise ValueError(f"Invalid GitHub App private key PEM: {e}") from e


def _make_jwt() -> str:
    app_id = os.environ.get("GITHUB_APP_ID")
    if not app_id:
        raise ValueError("GITHUB_APP_ID is not set")
    key = _load_private_key()
    if key is None:
        raise ValueError("GITHUB_APP_PRIVATE_KEY or GITHUB_APP_KEY_PATH is not set")
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": app_id.strip()}
    return jwt.encode(payload, key, algorithm="RS256")


def _req_app(method: str, path: str, body: dict | None = None, jwt_token: str | None = None) -> dict:
    token = jwt_token or _make_jwt()
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
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def _get_installation_id(owner: str, repo: str) -> int:
    key = (owner, repo)
    if key in _installation_id_cache:
        return _installation_id_cache[key]
    data = _req_app("GET", f"/repos/{owner}/{repo}/installation")
    iid = data["id"]
    _installation_id_cache[key] = iid
    return iid


def _get_installation_token(installation_id: int) -> str:
    now = time.time()
    if installation_id in _token_cache:
        token, expires = _token_cache[installation_id]
        if expires > now + _TOKEN_REFRESH_BUFFER:
            return token
    data = _req_app("POST", f"/app/installations/{installation_id}/access_tokens", body={})
    token = data["token"]
    exp_str = data.get("expires_at", "")
    expires = time.time() + 3600
    if exp_str:
        try:
            dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
            expires = dt.timestamp()
        except Exception:
            pass
    _token_cache[installation_id] = (token, expires)
    return token


def get_installation_token_for_repo(owner: str, repo: str) -> str:
    installation_id = _get_installation_id(owner, repo)
    return _get_installation_token(installation_id)


def is_github_app_configured() -> bool:
    if not os.environ.get("GITHUB_APP_ID"):
        return False
    return bool(_load_private_key_pem())

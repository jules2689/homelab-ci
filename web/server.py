#!/usr/bin/env python3
"""Minimal web UI: serve runs list and link to GitHub check runs. No framework."""
import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = Path(os.path.expanduser(os.environ.get("CI_LITE_DATA_DIR", "~/.ci-lite")))
RUNS_DB_PATH = Path(os.environ.get("CI_LITE_DB") or str(_DEFAULT_DATA_DIR / "runs.db"))
PORT = int(os.environ.get("CI_LITE_WEB_PORT", "8080"))
VERSION = os.environ.get("CI_LITE_VERSION", "0.1.10")

try:
    from github_app import is_github_app_configured, get_installation_token_for_repo
    from github_api import get_commit as _github_get_commit
except ImportError:
    def is_github_app_configured():
        return False
    def get_installation_token_for_repo(owner, repo):
        return ""
    def _github_get_commit(owner, repo, ref, *, token):
        return None


def load_runs(page: int = 1, per_page: int = 10, skip_count: bool = False) -> dict:
    """Load runs for the given page. Returns { runs, total, page, per_page }. If skip_count=True, total is None (faster)."""
    if not RUNS_DB_PATH.exists():
        logger.debug("runs DB not found at %s", RUNS_DB_PATH)
        return {"runs": [], "total": 0, "page": page, "per_page": per_page}
    page = max(1, page)
    per_page = max(1, min(100, per_page))
    offset = (page - 1) * per_page
    try:
        with sqlite3.connect(RUNS_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            total = None if skip_count else conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            try:
                rows = conn.execute(
                    "SELECT owner, repo, sha, success, html_url, at, output, commit_message, started_at FROM runs ORDER BY id DESC LIMIT ? OFFSET ?",
                    (per_page, offset),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT owner, repo, sha, success, html_url, at, output FROM runs ORDER BY id DESC LIMIT ? OFFSET ?",
                    (per_page, offset),
                ).fetchall()
        runs = [
            {
                "owner": r["owner"],
                "repo": r["repo"],
                "sha": r["sha"],
                "success": None if r["success"] == -1 else ("cancelled" if r["success"] == -2 else bool(r["success"])),
                "html_url": r["html_url"] or "",
                "at": r["at"],
                "output": (r["output"] if "output" in r.keys() else "") or "",
                "commit_message": r["commit_message"] if "commit_message" in r.keys() else "",
                "started_at": r["started_at"] if "started_at" in r.keys() else r["at"],
            }
            for r in rows
        ]
        return {"runs": runs, "total": total, "page": page, "per_page": per_page}
    except Exception as e:
        logger.exception("failed to load runs from %s: %s", RUNS_DB_PATH, e)
        return {"runs": [], "total": 0, "page": page, "per_page": per_page}


def get_runs_total() -> int:
    """Return total number of runs (for pagination). Fast to call after runs are already shown."""
    if not RUNS_DB_PATH.exists():
        return 0
    try:
        with sqlite3.connect(RUNS_DB_PATH) as conn:
            return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    except Exception:
        return 0


def _sha7(sha: str) -> str:
    """Normalize to 7-char SHA as stored in DB."""
    return (sha or "").strip()[:7]


def get_stored_commit_message(owner: str, repo: str, sha: str) -> str | None:
    """Return stored commit_message for this run if any. Prefer DB so we skip the API when possible."""
    if not RUNS_DB_PATH.exists() or not owner or not repo or not sha:
        return None
    try:
        with sqlite3.connect(RUNS_DB_PATH) as conn:
            row = conn.execute(
                "SELECT commit_message FROM runs WHERE owner=? AND repo=? AND sha=? AND (commit_message IS NOT NULL AND commit_message != '') ORDER BY id DESC LIMIT 1",
                (owner, repo, _sha7(sha)),
            ).fetchone()
            if row and row[0]:
                return row[0].strip() or None
    except sqlite3.OperationalError:
        pass
    except Exception as e:
        logger.debug("get_stored_commit_message: %s", e)
    return None


def update_commit_message(owner: str, repo: str, sha: str, message: str) -> None:
    """Persist commit message for runs matching owner/repo/sha so we never have to call the API again."""
    if not message or not owner or not repo or not sha:
        return
    try:
        with sqlite3.connect(RUNS_DB_PATH) as conn:
            conn.execute(
                "UPDATE runs SET commit_message=? WHERE owner=? AND repo=? AND sha=?",
                (message[:2048].strip(), owner, repo, _sha7(sha)),
            )
            conn.commit()
    except sqlite3.OperationalError:
        pass
    except Exception as e:
        logger.warning("update_commit_message failed: %s", e)


def fetch_commit_message(owner: str, repo: str, sha: str, *, debug: bool = False) -> tuple[str | None, str | None]:
    """Fetch first line of commit message from GitHub via GitHub App.
    Returns (message_or_none, debug_reason_if_requested).
    """
    if not owner or not repo or not sha:
        return (None, "missing owner/repo/sha" if debug else None)
    if not is_github_app_configured():
        logger.info("commit message lazy-load: GitHub App not configured (set GITHUB_APP_ID and key for web)")
        return (None, "GitHub App not configured (set GITHUB_APP_ID and GITHUB_APP_KEY_PATH or GITHUB_APP_PRIVATE_KEY for web)" if debug else None)
    try:
        token = get_installation_token_for_repo(owner, repo)
        if not token:
            logger.warning("commit message lazy-load: no installation token for %s/%s", owner, repo)
            return (None, "no installation token (app not installed on this repo?)" if debug else None)
        data = _github_get_commit(owner, repo, sha, token=token)
        if not data:
            logger.warning("commit message lazy-load: get_commit returned None for %s/%s %s", owner, repo, sha[:7])
            return (None, "GitHub API get_commit returned None (404 or error)" if debug else None)
        commit_obj = data.get("commit")
        if not commit_obj:
            logger.warning("commit message lazy-load: no 'commit' in response for %s/%s %s", owner, repo, sha[:7])
            return (None, "no 'commit' in API response" if debug else None)
        msg = commit_obj.get("message") or ""
        first_line = (msg.strip().split("\n")[0] or "").strip()
        return (first_line or None, None)
    except Exception as e:
        logger.warning("commit message lazy-load %s/%s %s: %s", owner, repo, sha[:7], e)
        return (None, str(e) if debug else None)


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CI-Lite __VERSION__</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Outfit:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0c0e10;
      --surface: #14171a;
      --surface-hover: #1a1e24;
      --border: #252a32;
      --text: #e6edf3;
      --muted: #7d8590;
      --pass: #3fb950;
      --fail: #f85149;
      --accent: #58a6ff;
      --accent-hover: #79b8ff;
      --log-bg: #0d1117;
      --log-border: #30363d;
      --radius: 8px;
      --radius-sm: 4px;
    }
    * { box-sizing: border-box; }
    body {
      font-family: 'Outfit', sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      margin: 0;
      padding: 2rem 1.5rem;
      background-image: radial-gradient(ellipse 120% 80% at 50% -20%, rgba(56, 139, 253, 0.06), transparent);
    }
    .wrap { max-width: 1000px; margin: 0 auto; }
    h1 {
      font-family: 'JetBrains Mono', monospace;
      font-size: 1.75rem;
      font-weight: 600;
      letter-spacing: -0.02em;
      margin: 0 0 0.25rem 0;
      color: var(--text);
    }
    h1 .version {
      font-size: 0.65em;
      font-weight: 400;
      color: var(--muted);
      letter-spacing: 0;
    }
    .sub {
      font-size: 0.9375rem;
      color: var(--muted);
      margin-bottom: 1.75rem;
    }
    .table-wrap {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
    }
    table { width: 100%; border-collapse: collapse; }
    th {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.6875rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      text-align: left;
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--border);
      background: rgba(0,0,0,0.2);
    }
    td {
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--border);
      vertical-align: middle;
      font-size: 0.875rem;
    }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: var(--surface-hover); }
    tr { animation: rowIn 0.4s ease-out backwards; }
    tr:nth-child(1) { animation-delay: 0.05s; }
    tr:nth-child(2) { animation-delay: 0.1s; }
    tr:nth-child(3) { animation-delay: 0.15s; }
    tr:nth-child(4) { animation-delay: 0.2s; }
    tr:nth-child(5) { animation-delay: 0.25s; }
    tr:nth-child(n+6) { animation-delay: 0.3s; }
    @keyframes rowIn {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .repo { font-family: 'JetBrains Mono', monospace; color: var(--text); }
    .sha {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.8125rem;
      color: var(--muted);
    }
    .badge {
      display: inline-block;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.6875rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 0.25rem 0.5rem;
      border-radius: var(--radius-sm);
    }
    .badge.pass { background: rgba(63, 185, 80, 0.18); color: var(--pass); }
    .badge.fail { background: rgba(248, 81, 73, 0.18); color: var(--fail); }
    .badge.pending { background: rgba(125, 133, 144, 0.25); color: var(--muted); }
    .badge.cancelled { background: rgba(125, 133, 144, 0.2); color: var(--muted); }
    .time { color: var(--muted); font-size: 0.8125rem; }
    .msg { color: var(--muted); font-size: 0.8125rem; max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .msg-loading { color: var(--muted); }
    a.link {
      color: var(--accent);
      text-decoration: none;
      font-weight: 500;
      transition: color 0.15s;
    }
    a.link:hover { color: var(--accent-hover); }
    .btn-log {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.8125rem;
      color: var(--accent);
      background: none;
      border: none;
      cursor: pointer;
      padding: 0.25rem 0;
    }
    .btn-log:hover { color: var(--accent-hover); }
    .empty { color: var(--muted); font-size: 0.875rem; }
    .modal-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.7);
      z-index: 100;
      align-items: center;
      justify-content: center;
      padding: 2rem;
    }
    .modal-backdrop.is-open { display: flex; }
    .modal-backdrop.is-open { animation: fadeIn 0.15s ease-out; }
    @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
    .modal-panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      width: 100%;
      max-width: 90vw;
      max-height: 85vh;
      display: flex;
      flex-direction: column;
      box-shadow: 0 24px 48px rgba(0,0,0,0.4);
      animation: slideUp 0.2s ease-out;
    }
    @keyframes slideUp {
      from { opacity: 0; transform: translateY(12px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .modal-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 1rem 1.25rem;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }
    .modal-title {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.875rem;
      color: var(--text);
      margin: 0;
    }
    .modal-close {
      background: none;
      border: none;
      color: var(--muted);
      cursor: pointer;
      padding: 0.25rem;
      line-height: 1;
      font-size: 1.25rem;
      border-radius: var(--radius-sm);
    }
    .modal-close:hover { color: var(--text); background: var(--surface-hover); }
    .modal-body {
      padding: 1rem 1.25rem;
      overflow: auto;
      flex: 1;
      min-height: 0;
    }
    .modal-log {
      background: var(--log-bg);
      border: 1px solid var(--log-border);
      border-radius: var(--radius-sm);
      padding: 1rem 1.25rem;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.75rem;
      line-height: 1.5;
      color: var(--muted);
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      max-height: 70vh;
      overflow: auto;
    }
    .modal-log::-webkit-scrollbar { width: 8px; height: 8px; }
    .modal-log::-webkit-scrollbar-track { background: transparent; }
    .modal-log::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
    .pagination {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-top: 1rem;
      padding: 0.5rem 0;
      font-size: 0.875rem;
      color: var(--muted);
    }
    .pagination .nav {
      display: flex;
      gap: 0.5rem;
    }
    .pagination button {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.8125rem;
      color: var(--accent);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 0.35rem 0.75rem;
      cursor: pointer;
    }
    .pagination button:hover:not(:disabled) {
      color: var(--accent-hover);
      background: var(--surface-hover);
    }
    .pagination button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .loading-row td {
      text-align: center;
      padding: 2rem;
      color: var(--muted);
    }
    .spinner {
      display: inline-block;
      width: 20px;
      height: 20px;
      border: 2px solid var(--border);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>CI-Lite <span class="version">__VERSION__</span></h1>
    <p class="sub">Recent runs. Click "View log" to open job output.</p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Repo</th><th>SHA</th><th>Message</th><th>Result</th><th>Time</th><th>GitHub</th><th>Log</th></tr></thead>
        <tbody id="runs"></tbody>
      </table>
    </div>
    <div class="pagination" id="pagination"></div>
  </div>
  <div id="log-modal" class="modal-backdrop" aria-hidden="true">
    <div class="modal-panel" role="dialog" aria-labelledby="modal-title" onclick="event.stopPropagation()">
      <div class="modal-header">
        <h2 id="modal-title" class="modal-title"></h2>
        <button type="button" class="modal-close" aria-label="Close" id="modal-close">&times;</button>
      </div>
      <div class="modal-body">
        <pre id="modal-log" class="modal-log"></pre>
      </div>
    </div>
  </div>
  <script>
    function esc(s) {
      if (s == null) return '';
      var d = document.createElement('span');
      d.textContent = s;
      return d.innerHTML;
    }
    var backdrop = document.getElementById('log-modal');
    var modalTitle = document.getElementById('modal-title');
    var modalLog = document.getElementById('modal-log');
    function openLog(title, text) {
      modalTitle.textContent = title;
      modalLog.textContent = text || '';
      backdrop.classList.add('is-open');
      backdrop.setAttribute('aria-hidden', 'false');
    }
    function closeLog() {
      backdrop.classList.remove('is-open');
      backdrop.setAttribute('aria-hidden', 'true');
    }
    backdrop.addEventListener('click', closeLog);
    document.getElementById('modal-close').addEventListener('click', closeLog);
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && backdrop.classList.contains('is-open')) closeLog();
    });
    function parseISO(s) {
      if (!s) return NaN;
      var n = Date.parse(s);
      return isNaN(n) ? NaN : n;
    }
    function formatDuration(ms) {
      if (ms < 0 || !isFinite(ms)) return '—';
      var s = Math.floor(ms / 1000);
      if (s < 60) return s + 's';
      var m = Math.floor(s / 60);
      s = s % 60;
      if (m < 60) return s ? m + 'm ' + s + 's' : m + 'm';
      var h = Math.floor(m / 60);
      m = m % 60;
      return (h + 'h ' + (m ? m + 'm' : '')).trim();
    }
    function timeAgo(ms) {
      if (!isFinite(ms)) return '—';
      var sec = Math.round((Date.now() - ms) / 1000);
      if (sec < 60) return 'just now';
      var min = Math.floor(sec / 60);
      if (min < 60) return min + ' min ago';
      var h = Math.floor(min / 60);
      if (h < 24) return h + ' hr ago';
      var d = Math.floor(h / 24);
      return d + ' day' + (d !== 1 ? 's' : '') + ' ago';
    }
    function timeCell(r) {
      var started = parseISO(r.started_at);
      var at = parseISO(r.at);
      var pending = r.success === null || r.success === undefined;
      if (pending) {
        if (!isFinite(started)) return '—';
        return 'Running for ' + formatDuration(Date.now() - started);
      }
      if (!isFinite(at)) return esc(r.at || '—');
      var ago = timeAgo(at);
      if (!isFinite(started) || started >= at) return ago;
      return 'ran for ' + formatDuration(at - started) + ' ' + ago;
    }
    var perPage = 10;
    function renderRun(r, t) {
      var tr = document.createElement('tr');
      var logCell = document.createElement('td');
      if (r.output != null && r.output !== '') {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn-log';
        btn.textContent = 'View log';
        btn.addEventListener('click', function(ev) {
          ev.preventDefault();
          openLog((r.owner || '') + '/' + (r.repo || '') + ' @ ' + (r.sha || ''), r.output);
        });
        logCell.appendChild(btn);
      } else {
        logCell.innerHTML = '<span class="empty">—</span>';
      }
      var resultBadge = (r.success === null || r.success === undefined)
        ? '<span class="badge pending">pending</span>'
        : (r.success === 'cancelled'
          ? '<span class="badge cancelled">cancelled</span>'
          : '<span class="badge ' + (r.success ? 'pass' : 'fail') + '">' + (r.success ? 'pass' : 'fail') + '</span>');
      var msg = (r.commit_message || '').trim();
      var msgContent = msg
        ? esc(msg)
        : '<span class="msg-loading" data-owner="' + esc(r.owner) + '" data-repo="' + esc(r.repo) + '" data-sha="' + esc(r.sha) + '">…</span>';
      tr.innerHTML =
        '<td class="repo">' + esc(r.owner) + '/' + esc(r.repo) + '</td>' +
        '<td class="sha"><code>' + esc(r.sha) + '</code></td>' +
        '<td class="msg" title="' + esc(msg || '') + '">' + msgContent + '</td>' +
        '<td>' + resultBadge + '</td>' +
        '<td class="time">' + timeCell(r) + '</td>' +
        '<td><a class="link" href="' + esc(r.html_url || '#') + '" target="_blank" rel="noopener">GitHub</a></td>';
      tr.appendChild(logCell);
      t.appendChild(tr);
    }
    function lazyLoadMessages(container) {
      container.querySelectorAll('.msg-loading').forEach(function(el) {
        var owner = el.dataset.owner, repo = el.dataset.repo, sha = el.dataset.sha;
        if (!owner || !repo || !sha) return;
        fetch('/api/commit?owner=' + encodeURIComponent(owner) + '&repo=' + encodeURIComponent(repo) + '&sha=' + encodeURIComponent(sha))
          .then(function(res) { return res.json(); })
          .then(function(o) {
            var m = (o.commit_message || '').trim();
            var td = el.closest('td');
            if (m) { td.innerHTML = esc(m); td.title = m; }
            else { td.innerHTML = '<span class="empty">—</span>'; }
          })
          .catch(function() {});
      });
    }
    function showLoading(t) {
      t.innerHTML = '';
      var tr = document.createElement('tr');
      tr.className = 'loading-row';
      tr.innerHTML = '<td colspan="7"><div class="spinner"></div> Loading runs…</td>';
      t.appendChild(tr);
    }
    function renderPagination(data) {
      var total = data.total;
      var page = data.page || 1;
      var pp = data.per_page || perPage;
      var totalKnown = total != null && total !== undefined;
      var totalPages = totalKnown ? Math.max(1, Math.ceil(total / pp)) : null;
      var el = document.getElementById('pagination');
      el.innerHTML = '';
      var info = document.createElement('span');
      info.textContent = totalKnown ? ('Page ' + page + ' of ' + totalPages + ' (' + total + ' runs)') : ('Page ' + page + ' …');
      el.appendChild(info);
      var nav = document.createElement('div');
      nav.className = 'nav';
      var prev = document.createElement('button');
      prev.textContent = 'Previous';
      prev.disabled = page <= 1;
      prev.addEventListener('click', function() { if (page > 1) loadPage(page - 1); });
      var next = document.createElement('button');
      next.textContent = 'Next';
      next.disabled = totalKnown ? page >= totalPages : false;
      next.addEventListener('click', function() { if (!totalKnown || page < totalPages) loadPage(page + 1); });
      nav.appendChild(prev);
      nav.appendChild(next);
      el.appendChild(nav);
    }
    function loadPage(page) {
      var t = document.getElementById('runs');
      showLoading(t);
      fetch('/api/runs?page=' + encodeURIComponent(page) + '&per_page=' + encodeURIComponent(perPage) + '&skip_count=1')
        .then(function(res) { return res.json(); })
        .then(function(data) {
          t.innerHTML = '';
          var runs = data.runs || [];
          runs.forEach(function(r) { renderRun(r, t); });
          lazyLoadMessages(t);
          renderPagination(data);
          if (data.total == null) {
            fetch('/api/runs?count_only=1').then(function(r) { return r.json(); }).then(function(o) {
              data.total = o.total;
              renderPagination(data);
            }).catch(function() {});
          }
        })
        .catch(function() {
          t.innerHTML = '';
          var tr = document.createElement('tr');
          tr.className = 'loading-row';
          tr.innerHTML = '<td colspan="7">Failed to load runs.</td>';
          t.appendChild(tr);
          renderPagination({ total: 0, page: page, per_page: perPage });
        });
    }
    loadPage(1);
  </script>
</body>
</html>
"""
INDEX_HTML = INDEX_HTML.replace("__VERSION__", VERSION)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(INDEX_HTML.encode())
            return
        if self.path.startswith("/api/runs"):
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            count_only = (qs.get("count_only") or ["0"])[0].strip() in ("1", "true", "yes")
            if count_only:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"total": get_runs_total()}).encode())
                return
            try:
                page = int((qs.get("page") or ["1"])[0])
            except (ValueError, TypeError):
                page = 1
            try:
                per_page = int((qs.get("per_page") or ["10"])[0])
            except (ValueError, TypeError):
                per_page = 10
            skip_count = (qs.get("skip_count") or ["0"])[0].strip() in ("1", "true", "yes")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(load_runs(page=page, per_page=per_page, skip_count=skip_count)).encode())
            return
        if self.path.startswith("/api/commit"):
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            owner = (qs.get("owner") or [""])[0].strip()
            repo = (qs.get("repo") or [""])[0].strip()
            sha = (qs.get("sha") or [""])[0].strip()
            debug = (qs.get("debug") or ["0"])[0].strip() in ("1", "true", "yes")
            if owner and repo and sha:
                msg = get_stored_commit_message(owner, repo, sha)
                debug_reason = None
                if not msg:
                    msg, debug_reason = fetch_commit_message(owner, repo, sha, debug=debug)
                    if msg:
                        update_commit_message(owner, repo, sha, msg)
                out = {"commit_message": msg or ""}
                if debug and debug_reason:
                    out["debug"] = debug_reason
            else:
                out = {"commit_message": ""}
                if debug:
                    out["debug"] = "missing owner, repo, or sha"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(out).encode())
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        logger.info("%s - %s", self.address_string(), format % args)


def main():
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("CI_LITE_DEBUG") else logging.INFO,
        format="%(asctime)s UTC %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.Formatter.converter = time.gmtime
    logger.info("CI-Lite web UI http://0.0.0.0:%s", PORT)
    server = HTTPServer(("", PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()

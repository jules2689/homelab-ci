#!/usr/bin/env python3
"""Minimal web UI: serve runs list and link to GitHub check runs. No framework."""
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = Path(os.path.expanduser(os.environ.get("CI_LITE_DATA_DIR", "~/.ci-lite")))
RUNS_DB_PATH = Path(os.environ.get("CI_LITE_DB") or str(_DEFAULT_DATA_DIR / "runs.db"))
PORT = int(os.environ.get("CI_LITE_WEB_PORT", "8080"))


def load_runs():
    if not RUNS_DB_PATH.exists():
        logger.debug("runs DB not found at %s", RUNS_DB_PATH)
        return []
    try:
        with sqlite3.connect(RUNS_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT owner, repo, sha, success, html_url, at, output FROM runs ORDER BY id DESC LIMIT 200"
                ).fetchall()
                has_output = True
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT owner, repo, sha, success, html_url, at FROM runs ORDER BY id DESC LIMIT 200"
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
    except Exception as e:
        logger.exception("failed to load runs from %s: %s", RUNS_DB_PATH, e)
        return []


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CI-Lite</title>
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
    .time { color: var(--muted); font-size: 0.8125rem; }
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
  </style>
</head>
<body>
  <div class="wrap">
    <h1>CI-Lite</h1>
    <p class="sub">Recent runs. Click "View log" to open job output.</p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Repo</th><th>SHA</th><th>Result</th><th>Time</th><th>GitHub</th><th>Log</th></tr></thead>
        <tbody id="runs"></tbody>
      </table>
    </div>
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
    fetch('/api/runs').then(r => r.json()).then(runs => {
      var t = document.getElementById('runs');
      runs.forEach(function(r) {
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
        tr.innerHTML =
          '<td class="repo">' + esc(r.owner) + '/' + esc(r.repo) + '</td>' +
          '<td class="sha"><code>' + esc(r.sha) + '</code></td>' +
          '<td><span class="badge ' + (r.success ? 'pass' : 'fail') + '">' + (r.success ? 'pass' : 'fail') + '</span></td>' +
          '<td class="time">' + esc(r.at) + '</td>' +
          '<td><a class="link" href="' + esc(r.html_url || '#') + '" target="_blank" rel="noopener">GitHub</a></td>';
        tr.appendChild(logCell);
        t.appendChild(tr);
      });
    });
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(INDEX_HTML.encode())
            return
        if self.path == "/api/runs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(load_runs()).encode())
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

#!/usr/bin/env python3
"""Minimal web UI: serve runs list and link to GitHub check runs. No framework."""
import json
import os
import sqlite3
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

_DEFAULT_DATA_DIR = Path(os.path.expanduser(os.environ.get("CI_LITE_DATA_DIR", "~/.ci-lite")))
RUNS_DB_PATH = Path(os.environ.get("CI_LITE_DB") or str(_DEFAULT_DATA_DIR / "runs.db"))
PORT = int(os.environ.get("CI_LITE_WEB_PORT", "8080"))


def load_runs():
    if not RUNS_DB_PATH.exists():
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
    except Exception:
        return []


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>CI-Lite</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; }
    h1 { font-size: 1.5rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #eee; vertical-align: top; }
    .ok { color: #0a0; }
    .fail { color: #c00; }
    a { color: #0969da; }
    details { margin: 0; }
    details summary { cursor: pointer; }
    .log-pre { background: #f6f8fa; border: 1px solid #eee; border-radius: 4px; padding: 0.75rem; margin: 0.5rem 0; font-size: 0.85rem; overflow-x: auto; white-space: pre-wrap; word-break: break-all; max-height: 20rem; overflow-y: auto; }
  </style>
</head>
<body>
  <h1>CI-Lite</h1>
  <p>Recent runs. Expand "Log" to see job output.</p>
  <table>
    <thead><tr><th>Repo</th><th>SHA</th><th>Result</th><th>Time</th><th>GitHub</th><th>Log</th></tr></thead>
    <tbody id="runs"></tbody>
  </table>
  <script>
    fetch('/api/runs').then(r => r.json()).then(runs => {
      const t = document.getElementById('runs');
      runs.forEach(r => {
        const tr = document.createElement('tr');
        const logCell = document.createElement('td');
        if (r.output != null && r.output !== '') {
          const details = document.createElement('details');
          details.innerHTML = '<summary>View log</summary>';
          const pre = document.createElement('pre');
          pre.className = 'log-pre';
          pre.textContent = r.output;
          details.appendChild(pre);
          logCell.appendChild(details);
        } else {
          logCell.textContent = '—';
        }
        tr.innerHTML = '<td>' + r.owner + '/' + r.repo + '</td><td><code>' + r.sha + '</code></td>' +
          '<td class="' + (r.success ? 'ok' : 'fail') + '">' + (r.success ? 'pass' : 'fail') + '</td>' +
          '<td>' + r.at + '</td><td><a href="' + (r.html_url || '#') + '" target="_blank">GitHub</a></td>';
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
        pass


def main():
    server = HTTPServer(("", PORT), Handler)
    print(f"CI-Lite web UI http://0.0.0.0:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()

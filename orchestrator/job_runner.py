"""Run a job: clone repo at ref, run command in same process (deps + exec via run-in-repo.sh)."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable


class JobCancelledError(Exception):
    """Raised when the job was stopped via a cancel request (process group terminated)."""


def get_repo_config(owner: str, repo: str, ref: str, get_file_fn) -> dict:
    """Load .ci-lite.yml from repo at ref. Returns dict with 'command' or 'steps'. Uses get_file_fn(owner, repo, ref, path)."""
    raw = get_file_fn(owner, repo, ref, ".ci-lite.yml")
    if not raw or not raw.strip():
        return {"command": "true"}
    # Minimal YAML parse: we only need "command: bin/lint" or "steps: [{run: ...}]"
    import yaml
    try:
        data = yaml.safe_load(raw)
        if not data or not isinstance(data, dict):
            return {"command": "true"}
        if "command" in data and data["command"]:
            return data
        if "steps" in data and isinstance(data["steps"], list) and len(data["steps"]) > 0:
            first = data["steps"][0]
            if isinstance(first, dict) and "run" in first:
                return {"command": first["run"]}
            if isinstance(first, str):
                return {"command": first}
        return data if isinstance(data, dict) else {"command": "true"}
    except Exception:
        return {"command": "true"}


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_IN_REPO_SCRIPT = os.environ.get("CI_LITE_RUN_IN_REPO_SCRIPT") or os.path.join(_SCRIPT_DIR, "run-in-repo.sh")


def _stream_subprocess(
    cmd: list[str],
    cwd: str,
    on_output: Callable[[str], None] | None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[int, str]:
    """Run cmd with merged stdout/stderr; stream lines to on_output. Returns (returncode, full_output)."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    chunks: list[str] = []
    stop_watcher = threading.Event()
    user_cancelled = threading.Event()

    def reader() -> None:
        assert proc.stdout is not None
        try:
            for line in iter(proc.stdout.readline, ""):
                chunks.append(line)
                if on_output:
                    on_output(line)
        finally:
            proc.stdout.close()

    def watcher() -> None:
        if not should_cancel:
            return
        while not stop_watcher.is_set():
            if proc.poll() is not None:
                return
            try:
                if should_cancel():
                    if proc.poll() is not None:
                        return
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        return
                    user_cancelled.set()
                    return
            except Exception:
                pass
            time.sleep(0.4)

    t = threading.Thread(target=reader)
    t.start()
    wt: threading.Thread | None = None
    if should_cancel:
        wt = threading.Thread(target=watcher, daemon=True)
        wt.start()
    rc = proc.wait()
    stop_watcher.set()
    t.join()
    if wt is not None:
        wt.join(timeout=2.0)
    if user_cancelled.is_set():
        raise JobCancelledError()
    return rc, "".join(chunks)


def _git_step(
    label: str,
    cmd: list[str],
    cwd: str,
    on_output: Callable[[str], None] | None,
    should_cancel: Callable[[], bool] | None = None,
) -> str:
    if on_output:
        on_output(f"=== ci-lite: {label} ===\n")
    rc, out = _stream_subprocess(cmd, cwd, on_output, should_cancel)
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd, out)
    return out


def run_job(
    clone_url: str,
    branch: str,
    sha: str,
    command: str,
    workspace_dir: str,
    on_output: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[int, str]:
    """
    Clone repo (branch) into workspace_dir, checkout sha cleanly, run command in same container via run-in-repo.sh.
    clone_url should use the token for private repos.
    If on_output is set, stdout/stderr are streamed line-by-line (clone, checkout, then job).
    If should_cancel is set, it is polled ~every 400ms; when it returns True the process group is SIGTERM'd and JobCancelledError is raised.
    Returns (exit_code, combined_stdout_stderr).
    """
    repo_dir = os.path.join(workspace_dir, "repo")
    if os.path.isdir(repo_dir):
        shutil.rmtree(repo_dir)
    os.makedirs(repo_dir, exist_ok=True)

    _git_step(
        "git clone",
        ["git", "clone", "--depth", "50", "--branch", branch, clone_url, repo_dir],
        workspace_dir,
        on_output,
        should_cancel,
    )
    _git_step("git checkout", ["git", "checkout", "-f", sha], repo_dir, on_output, should_cancel)
    _git_step("git reset", ["git", "reset", "--hard", sha], repo_dir, on_output, should_cancel)
    _git_step("git clean", ["git", "clean", "-fd"], repo_dir, on_output, should_cancel)

    if on_output:
        on_output("=== ci-lite: job ===\n")

    if os.path.isfile(RUN_IN_REPO_SCRIPT):
        cmd = [RUN_IN_REPO_SCRIPT, repo_dir, "bash", "-c", command]
        cwd = workspace_dir
    else:
        cmd = ["bash", "-c", command]
        cwd = repo_dir

    rc, out = _stream_subprocess(cmd, cwd, on_output, should_cancel)
    return rc, out

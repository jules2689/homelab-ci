"""Run a job: clone repo at ref, run command in same process (deps + exec via run-in-repo.sh)."""
import os
import subprocess
import shutil


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


def run_job(
    clone_url: str,
    branch: str,
    sha: str,
    command: str,
    workspace_dir: str,
) -> tuple[int, str]:
    """
    Clone repo (branch) into workspace_dir, checkout sha cleanly, run command in same container via run-in-repo.sh.
    clone_url should use the token for private repos.
    Returns (exit_code, combined_stdout_stderr).
    """
    repo_dir = os.path.join(workspace_dir, "repo")
    if os.path.isdir(repo_dir):
        shutil.rmtree(repo_dir)
    os.makedirs(repo_dir, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth", "50", "--branch", branch, clone_url, repo_dir],
        check=True,
        capture_output=True,
        cwd=workspace_dir,
    )
    subprocess.run(
        ["git", "checkout", "-f", sha],
        check=True,
        capture_output=True,
        cwd=repo_dir,
    )
    subprocess.run(
        ["git", "reset", "--hard", sha],
        check=True,
        capture_output=True,
        cwd=repo_dir,
    )
    subprocess.run(
        ["git", "clean", "-fd"],
        check=True,
        capture_output=True,
        cwd=repo_dir,
    )
    if os.path.isfile(RUN_IN_REPO_SCRIPT):
        proc = subprocess.run(
            [RUN_IN_REPO_SCRIPT, repo_dir, "bash", "-c", command],
            capture_output=True,
            text=True,
        )
    else:
        proc = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            cwd=repo_dir,
        )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out

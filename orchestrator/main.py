#!/usr/bin/env python3
"""
CI-Lite: poll repos for new commits, run jobs in Docker, report to GitHub Checks.
No webhooks. Serial job execution. Auth: GitHub App (GITHUB_APP_ID + private key via GITHUB_APP_PRIVATE_KEY or GITHUB_APP_KEY_PATH).
"""
import logging
import os
import sys
import time
import json
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

from github_api import get_latest_commit, get_file, list_branches, get_commit, get_commits_between
from github_checks import create_check_run, complete_check_run
from github_app import is_github_app_configured, get_installation_token_for_repo
from job_runner import get_repo_config, run_job
from runs_db import (
    init_db,
    record_run as db_record_run,
    record_pending_run as db_record_pending_run,
    get_pending_runs,
    mark_pending_run_cancelled,
    archive_runs_older_than,
)


CONFIG_PATH = os.environ.get("CI_LITE_CONFIG", "config.yaml")

# Persistent defaults under ~/.ci-lite so state survives restarts and isn't cwd-dependent
_CI_LITE_DATA_DIR = os.path.expanduser(os.environ.get("CI_LITE_DATA_DIR", "~/.ci-lite"))
STATE_PATH = os.environ.get("CI_LITE_STATE") or os.path.join(_CI_LITE_DATA_DIR, "state.json")
WORKSPACE_ROOT = os.environ.get("CI_LITE_WORKSPACE") or os.path.join(_CI_LITE_DATA_DIR, "workspace")


def load_config():
    path = Path(CONFIG_PATH)
    if not path.exists():
        logger.error("Config not found: %s", CONFIG_PATH)
        sys.exit(1)
    with open(path) as f:
        config = yaml.safe_load(f)
    logger.debug("Loaded config from %s", CONFIG_PATH)
    return config


def load_state():
    path = Path(STATE_PATH)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_state(state):
    path = Path(STATE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def build_clone_url(owner: str, repo: str, *, token: str) -> str:
    return f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"


def _commit_message_first_line(commit: dict, *, owner: str, repo: str, token: str) -> str:
    """First line of commit message; fetches full commit if only sha is present."""
    msg = (commit.get("commit") or {}).get("message") or ""
    if not msg and commit.get("sha"):
        full = get_commit(owner, repo, commit["sha"], token=token)
        msg = (full.get("commit") or {}).get("message") or ""
    return (msg.strip().split("\n")[0] or "").strip()


def run_one(
    repo_config: dict,
    commit: dict,
    *,
    token: str,
    dry_run: bool = False,
) -> str | None:
    logger.info("Running one: %s", repo_config)
    owner = repo_config["owner"]
    repo = repo_config["repo"]
    branch = repo_config.get("branch", "main")
    sha = commit["sha"]
    commit_message = _commit_message_first_line(commit, owner=owner, repo=repo, token=token)
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def get_file_fn(o, r, ref, path):
        return get_file(o, r, ref, path, token=token)

    job_config = get_repo_config(owner, repo, sha, get_file_fn)
    # Per-repo command in config overrides .ci-lite.yml
    command = repo_config.get("command") or job_config.get("command", "true")
    if isinstance(command, list):
        command = " && ".join(command)

    if dry_run:
        logger.info("Would run: %s/%s branch %s @ %s (command: %s)", owner, repo, branch, sha[:7], command)
        return None

    check = create_check_run(owner, repo, sha, name="ci-lite", token=token)
    check_run_id = check["id"]
    html_url = check.get("html_url", "")
    db_record_pending_run(
        owner=owner,
        repo=repo,
        sha=sha,
        html_url=html_url,
        at=started_at,
        branch=branch,
        commit_message=commit_message,
    )

    clone_url = build_clone_url(owner, repo, token=token)
    # Repo copy under WORKSPACE_ROOT (e.g. /data/workspace when in Docker); job runs in that copy at exact commit
    workspace_dir = os.path.join(WORKSPACE_ROOT, f"{owner}_{repo}")
    os.makedirs(workspace_dir, exist_ok=True)

    logger.info("Starting job %s/%s @ %s (command: %s)", owner, repo, sha[:7], command)
    try:
        exit_code, output = run_job(
            clone_url=clone_url,
            branch=branch,
            sha=sha,
            command=command,
            workspace_dir=workspace_dir,
        )
    except Exception as e:
        logger.exception("Job failed for %s/%s @ %s", owner, repo, sha[:7])
        output = str(e)
        exit_code = 1

    run_output = output or "(no output)"
    check_summary = ("Success. Ran: `%s`" if exit_code == 0 else "Failed. Ran: `%s`") % command
    check_text = "**Command:** `%s`\n\n**Output:**\n\n```\n%s\n```" % (command, run_output)
    complete_check_run(
        owner=owner,
        repo=repo,
        check_run_id=check_run_id,
        head_sha=sha,
        success=(exit_code == 0),
        output_title="ci-lite",
        output_summary=check_summary,
        output_text=check_text,
        token=token,
    )
    db_record_run(
        owner=owner,
        repo=repo,
        sha=sha,
        success=(exit_code == 0),
        html_url=html_url,
        at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        output=run_output,
        branch=branch,
        commit_message=commit_message,
    )
    return html_url


def main():
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("CI_LITE_DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    logging.Formatter.converter = time.gmtime  # log timestamps in UTC

    dry_run = "--dry-run" in sys.argv or os.environ.get("CI_LITE_DRY_RUN", "").lower() in ("1", "true", "yes")
    if dry_run:
        logger.info("CI-Lite dry-run: only new commits (since last seen) would be run. No state changes, no jobs.")

    if not is_github_app_configured():
        logger.error(
            "Set GitHub App: GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY (or GITHUB_APP_KEY_PATH)"
        )
        sys.exit(1)

    def get_token(owner: str, repo: str) -> str:
        return get_installation_token_for_repo(owner, repo)

    config = load_config()
    repos = config.get("repos", [])
    poll_interval = config.get("poll_interval", 60)
    logger.info("Watching %d repo(s), poll_interval=%ds", len(repos), poll_interval)

    init_db()
    state = load_state()
    # state: { "owner/repo": { "branch": last_sha }, "last_archive_date": "YYYY-MM-DD" }
    for r in repos:
        key = f"{r['owner']}/{r['repo']}"
        if key not in state:
            state[key] = {}

    logger.info("State: %s", state)

    # Pending runs (container killed mid-job) will be re-run on first matching poll
    pending_retry = set()
    for r in get_pending_runs():
        mark_pending_run_cancelled(r["owner"], r["repo"], r["sha"])
        pending_retry.add((r["owner"], r["repo"], r["branch"], r["sha"]))
    if pending_retry:
        logger.info("Found %d pending run(s) to retry on next poll (marked previous as cancelled)", len(pending_retry))

    ARCHIVE_DAYS = 7

    while True:
        # Run archive once per day (first poll after midnight UTC)
        today_utc = time.strftime("%Y-%m-%d", time.gmtime())
        if state.get("last_archive_date") != today_utc and not dry_run:
            n = archive_runs_older_than(ARCHIVE_DAYS)
            if n > 0:
                logger.info("Archived %d run(s) older than %d days", n, ARCHIVE_DAYS)
            state["last_archive_date"] = today_utc
            save_state(state)

        for repo_config in repos:
            owner = repo_config["owner"]
            repo = repo_config["repo"]
            branch_cfg = repo_config.get("branch", "main")
            key = f"{owner}/{repo}"

            logger.info("Checking repo: %s %s", key, branch_cfg)

            token = get_token(owner, repo)
            # Resolve branches to check: one branch or all
            if branch_cfg == "*" or repo_config.get("branches") == "all":
                branch_list = list_branches(owner, repo, token=token)
                if not branch_list:
                    continue
                # List of (branch_name, commit_dict) for this repo
                to_check = [(b["name"], {"sha": b["commit"]["sha"]}) for b in branch_list]
            else:
                commit = get_latest_commit(owner, repo, branch_cfg, token=token)
                if not commit:
                    continue
                to_check = [(branch_cfg, commit)]

            logger.info("To check: %d commit(s)", len(to_check))

            for branch, commit in to_check:
                logger.info("Checking branch: %s %s", key, branch)
                sha = commit["sha"]
                last = state[key].get(branch)
                is_pending_retry = (owner, repo, branch, sha[:7]) in pending_retry
                if last == sha and not is_pending_retry:
                    continue
                # Build list of commits to run: every commit we haven't run yet (so every commit gets a check).
                if last is None:
                    to_run = [commit]
                else:
                    to_run = get_commits_between(owner, repo, last, sha, token=token)
                    if not to_run and last != sha:
                        to_run = [commit]
                if not to_run:
                    if not dry_run:
                        state[key][branch] = sha
                        save_state(state)
                    continue
                if is_pending_retry:
                    pending_retry.discard((owner, repo, branch, sha[:7]))
                    logger.info("Retrying pending job %s %s @ %s", key, branch, sha[:7])
                run_config = {**repo_config, "branch": branch}
                logger.info("Running for %d commit(s) on %s %s (every commit since last poll)", len(to_run), key, branch)
                for c in to_run:
                    c_sha = c["sha"]
                    if not dry_run:
                        run_one(run_config, c, token=token, dry_run=dry_run)
                        state[key][branch] = c_sha
                        save_state(state)
                    else:
                        logger.info("Would run %s/%s branch %s @ %s", owner, repo, branch, c_sha[:7])
                if not dry_run and to_run:
                    logger.info("Ran %d job(s) for %s %s, last @ %s", len(to_run), key, branch, to_run[-1]["sha"][:7])

        if dry_run:
            logger.info("Dry-run done (one pass). Exiting.")
            break
        logger.debug("Sleeping %ds until next poll", poll_interval)
        time.sleep(poll_interval)


if __name__ == "__main__":
    main()

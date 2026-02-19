# CI-Lite

Lightweight, Docker-based CI that **polls** your GitHub repos for new commits (no webhooks), runs a single job per commit in the same container, and reports results to the **GitHub Checks API**.

- **No webhooks** — poll-based; works anywhere you can run Docker and hit GitHub API.
- **Serial** — one job at a time; single container (orchestrator + runner combined).
- **Config per repo** — job command (e.g. `bin/lint`) and optional dependency install via `.ci-lite.yml`.
- **One image** — Python, git, Ruby, `pip`, `bundler`; deps (e.g. `bundle install`, `pip install -r requirements.txt`) are installed at run time in the repo dir before the command.

## Authentication

**Recommended: GitHub App** (full access to Checks API). Fine-grained PATs cannot create check runs; classic PATs cannot either. Use a GitHub App so CI-Lite can create and update check runs.

### Option A: GitHub App

1. **Create a GitHub App** (org or user): GitHub → Settings → Developer settings → GitHub Apps → New GitHub App.
   - Name, homepage, webhook: disable (leave URL blank).
   - **Repository permissions**: Contents = Read-only, Checks = Read & write.
   - Where can it be installed: Only on this account, or Any account.
   - Create the app.

2. **Generate a private key**: In the app → General → Private keys → Generate a private key. Save the `.pem` file.

3. **Install the app** on the org or repo you want to run CI for: use “Install App” from the app’s page, choose repos.

4. **Set env vars** (or `.env` for Docker Compose):
   - `GITHUB_APP_ID` — App ID from the app’s General page.
   - **Private key** (the `.pem` you download from GitHub): **`GITHUB_APP_PRIVATE_KEY`** — full PEM string (escape newlines as `\n` if needed), **or** **`GITHUB_APP_KEY_PATH`** — path to the `.pem` file.

## Quick start

1. **Copy config and set auth**

   ```bash
   cp config.example.yaml config.yaml
   # Edit config.yaml: set repos (owner, repo, branch).

   export GITHUB_APP_ID=123456
   export GITHUB_APP_KEY_PATH=/path/to/your-app.private-key.pem
   # or GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
   ```

2. **Run with Docker Compose** (single container: poll, clone, run jobs)

   ```bash
   docker compose up -d --build
   # With web UI (recent runs + links to GitHub):
   docker compose --profile web up -d
   ```

## Which branches are watched

In `config.yaml`, each repo has a `branch` (or `branches`):

- **Single branch**: `branch: main` — only that branch is polled.
- **All branches**: `branch: "*"` or `branches: all` — the orchestrator lists all branches via the GitHub API and polls each one. New commits on any branch trigger a job for that branch.

## Repo config: `.ci-lite.yml`

In the root of your repo, add:

```yaml
command: bin/lint
```

Or multiple steps (first `run` is used):

```yaml
steps:
  - run: bin/lint
```

If `.ci-lite.yml` is missing, the job runs `true` (no-op success). You can override the command per repo in `config.yaml` with `command: "make test"` (or any string) on the repo entry.

## Image (orchestrator + runner)

- **Base**: `python:3.12-alpine` with git, Ruby, bundler, Python, pip, bash.
- Jobs run in the same container: clone into `/data/workspace/<owner>_<repo>/repo`, install deps (bundle/pip) from the repo, then run the command.
- **Dependencies**: Installed **dynamically** in the container when the job runs:
  - `Gemfile` → `bundle install`
  - `requirements.txt` → `pip install -r requirements.txt`

So the image stays small and dependency sets stay per-repo.

## Where results show up

- **GitHub**: Each run creates/updates a **Check run** on the commit. Logs and pass/fail are in the GitHub UI (commit/PR checks).
- **Web UI** (optional): Simple page listing recent runs with links to the GitHub check run. Start with `docker compose --profile web up -d` and open `http://localhost:8080`.

## Dry-run

To see what **would** run without running jobs or updating state:

```bash
python main.py --dry-run
# or
CI_LITE_DRY_RUN=1 python main.py
```

Dry-run does one poll pass and prints lines like:

`Would run: owner/repo branch main @ abc1234 (command: bin/lint)`

Only **new** commits are considered: branches we’ve never seen are skipped (no “would run” for current HEAD on first run), and we only show commits that are newer than the last seen SHA in state. So you won’t get hundreds of “would run” lines on first run.

## Env vars

| Variable | Purpose |
|----------|---------|
| `GITHUB_APP_ID` | GitHub App ID (required). |
| `GITHUB_APP_PRIVATE_KEY` or `GITHUB_APP_KEY_PATH` | App **private key** (the `.pem` file): PEM string or path. |
| `CI_LITE_DRY_RUN` | Set to `1`, `true`, or `yes` (or pass `--dry-run`) to only print what would run; no state changes, no jobs. One pass then exit. |
| `CI_LITE_CONFIG` | Path to `config.yaml` (default: `config.yaml`). |
| `CI_LITE_DATA_DIR` | Persistent data directory (default: `~/.ci-lite`). State, DB, and workspace default to paths under this. |
| `CI_LITE_STATE` | Path to state file (default: `$CI_LITE_DATA_DIR/state.json`). |
| `CI_LITE_DB` | Path to SQLite DB for run history (default: `$CI_LITE_DATA_DIR/runs.db`). Web UI reads from this. |
| `CI_LITE_WORKSPACE` | Dir for clone + run (default: `$CI_LITE_DATA_DIR/workspace`). |
| `CI_LITE_WEB_PORT` | Web UI port (default: `8080`). |

## Cost / resource use

- Single process, serial jobs, no queue service.
- Poll interval is configurable (`poll_interval` in `config.yaml`); 60s is a reasonable default.
- Runner image is Alpine-based; job containers are short-lived. Tune `poll_interval` and number of repos to fit your budget.

#!/bin/bash
# Run from orchestrator: install deps in repo dir then exec command. Usage: run-in-repo.sh <repo_dir> <cmd> [args...]
set -e
REPO_DIR="$1"
shift
cd "$REPO_DIR"
if [ -f Gemfile ]; then
  bundle config set --local path /tmp/bundle
  bundle config set --local deployment true
  bundle install --jobs 4 --retry 2
fi
if [ -f requirements.txt ]; then
  pip install --no-cache-dir -r requirements.txt
fi
if [ -f pyproject.toml ] && ! grep -q '\[tool\.poetry\]' pyproject.toml 2>/dev/null; then
  pip install --no-cache-dir -e . 2>/dev/null || pip install --no-cache-dir . 2>/dev/null || true
fi
exec "$@"

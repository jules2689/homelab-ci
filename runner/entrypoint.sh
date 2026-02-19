#!/bin/bash
set -e
# Working dir is set by docker run -w (e.g. /data/workspace/owner_repo/repo); do not cd to /workspace
# Dynamic dependency install (no webhooks = no cache from repo; keep image small)
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

# Run the configured command (passed as args)
exec "$@"

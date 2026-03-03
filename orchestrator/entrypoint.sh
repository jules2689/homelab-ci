#!/bin/sh
set -e
# Only create ci user and drop privileges when we're root. If container runs as non-root, set HOME on /data (volume) so pip doesn't fill /tmp (64M tmpfs).
if [ "$(id -u)" != "0" ]; then
  if mkdir -p /data/ci-home 2>/dev/null && [ -w /data/ci-home ]; then
    export HOME=/data/ci-home
  else
    mkdir -p /tmp/ci-home 2>/dev/null || true
    export HOME=/tmp/ci-home
  fi
  export PATH="$HOME/.local/bin:$PATH"
  exec "$@"
fi
# Use in-container home for ci user so we don't need to create dirs on mounted /data
CI_HOME=/home/ci
if [ -n "$PUID" ] && [ -n "$PGID" ] && [ "$PUID" != "0" ] && [ "$PGID" != "0" ]; then
  need_user=1
  if id -u ci >/dev/null 2>&1; then
    [ "$(id -u ci)" = "$PUID" ] && [ "$(id -g ci)" = "$PGID" ] && need_user=0
  fi
  if [ "$need_user" = 1 ]; then
    deluser ci 2>/dev/null || true
    delgroup ci 2>/dev/null || true
    addgroup -g "$PGID" ci
    adduser -D -u "$PUID" -G ci -s /bin/sh -h "$CI_HOME" ci
  fi
  mkdir -p "$CI_HOME"
  chown -R ci:ci "$CI_HOME"
  export HOME="$CI_HOME"
  export PATH="$CI_HOME/.local/bin:$PATH"
  exec setpriv --reuid="$PUID" --regid="$PGID" --init-groups -- "$@"
else
  exec "$@"
fi

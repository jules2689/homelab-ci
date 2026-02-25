#!/bin/sh
set -e
if [ -n "$PUID" ] && [ -n "$PGID" ] && [ "$PUID" != "0" ] && [ "$PGID" != "0" ]; then
  need_user=1
  if id -u ci >/dev/null 2>&1; then
    [ "$(id -u ci)" = "$PUID" ] && [ "$(id -g ci)" = "$PGID" ] && need_user=0
  fi
  export HOME="${HOME:-/home/ci}"
  if [ "$need_user" = 1 ]; then
    deluser ci 2>/dev/null || true
    delgroup ci 2>/dev/null || true
    addgroup -g "$PGID" ci
    adduser -D -u "$PUID" -G ci -s /bin/sh -h "$HOME" ci
  fi
  mkdir -p "$HOME"
  chown -R ci:ci "$HOME"
  export PATH="$HOME/.local/bin:$PATH"
  exec setpriv --reuid="$PUID" --regid="$PGID" --init-groups -- "$@"
else
  exec "$@"
fi

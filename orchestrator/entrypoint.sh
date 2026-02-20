#!/bin/sh
set -e
if [ -n "$PUID" ] && [ -n "$PGID" ] && [ "$PUID" != "0" ] && [ "$PGID" != "0" ]; then
  need_user=1
  if id -u ci >/dev/null 2>&1; then
    [ "$(id -u ci)" = "$PUID" ] && [ "$(id -g ci)" = "$PGID" ] && need_user=0
  fi
  if [ "$need_user" = 1 ]; then
    deluser ci 2>/dev/null || true
    delgroup ci 2>/dev/null || true
    addgroup -g "$PGID" ci
    adduser -D -u "$PUID" -G ci -s /bin/sh -h /home/ci ci
  fi
  mkdir -p /home/ci
  chown -R ci:ci /home/ci
  export HOME=/home/ci
  export PATH="/home/ci/.local/bin:$PATH"
  exec setpriv --reuid="$PUID" --regid="$PGID" --init-groups -- "$@"
else
  exec "$@"
fi

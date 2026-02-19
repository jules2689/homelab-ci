#!/bin/sh
set -e
if [ -n "$PUID" ] && [ -n "$PGID" ] && [ "$PUID" != "0" ] && [ "$PGID" != "0" ]; then
  exec setpriv --reuid="$PUID" --regid="$PGID" --init-groups -- "$@"
else
  exec "$@"
fi

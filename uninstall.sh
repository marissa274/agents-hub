#!/bin/sh
# Désinstalle Agents Hub (hooks, agents et skill installés par install.sh).
SELF="$0"
while [ -h "$SELF" ]; do
  DIR=$(cd "$(dirname "$SELF")" && pwd)
  LINK=$(readlink "$SELF")
  case "$LINK" in /*) SELF="$LINK" ;; *) SELF="$DIR/$LINK" ;; esac
done
ROOT=$(cd "$(dirname "$SELF")" && pwd)
exec python3 "$ROOT/bin/install.py" uninstall "$@"

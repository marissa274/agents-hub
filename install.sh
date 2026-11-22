#!/bin/sh
# Installe Agents Hub : agents, skill « hub » et hooks Claude Code (et Codex s'il est détecté).
SELF="$0"
while [ -h "$SELF" ]; do
  DIR=$(cd "$(dirname "$SELF")" && pwd)
  LINK=$(readlink "$SELF")
  case "$LINK" in /*) SELF="$LINK" ;; *) SELF="$DIR/$LINK" ;; esac
done
ROOT=$(cd "$(dirname "$SELF")" && pwd)
exec python3 "$ROOT/bin/install.py" install "$@"

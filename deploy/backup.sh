#!/bin/sh
# Back up the Deol Tech database.
#
# Delegates to `deoltech backup`, which uses SQLite's online backup API,
# verifies the result with an integrity check before compressing it, and
# applies retention. Doing it in the application avoids depending on the
# sqlite3 CLI, which is not present in the slim container image.
#
#   ./deploy/backup.sh /var/backups/deoltech
set -eu

DEST="${1:-/var/backups/deoltech}"
COMPOSE_FILE="$(dirname "$0")/docker-compose.yml"

if [ -f "$COMPOSE_FILE" ] && command -v docker >/dev/null 2>&1 \
   && docker compose -f "$COMPOSE_FILE" ps --status running app >/dev/null 2>&1; then
  # Containerised: write inside the volume, then copy out to the host.
  docker compose -f "$COMPOSE_FILE" exec -T app \
      python -m deoltech backup /data/backups --keep-days "${KEEP_DAYS:-30}"
  mkdir -p "$DEST"
  docker compose -f "$COMPOSE_FILE" cp app:/data/backups/. "$DEST/"
  echo "copied to $DEST"
else
  PYTHONPATH="${PYTHONPATH:-src}" python3 -m deoltech backup "$DEST" \
      --keep-days "${KEEP_DAYS:-30}"
fi

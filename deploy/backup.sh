#!/bin/sh
# Back up the Deol Tech database safely.
#
# Copying a live SQLite file with `cp` can capture a torn write. `.backup` uses
# SQLite's own online backup API, which is consistent while the app keeps
# serving — the difference between a backup and a file that looks like one.
set -eu

DB="${DEOLTECH_DB:-/data/deoltech.db}"
DEST="${1:-/backups}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$DEST"

sqlite3 "$DB" ".backup '$DEST/deoltech-$STAMP.db'"
gzip -f "$DEST/deoltech-$STAMP.db"
echo "wrote $DEST/deoltech-$STAMP.db.gz"

# Keep 30 days; a backup policy with no retention is a disk-full incident.
find "$DEST" -name 'deoltech-*.db.gz' -mtime +30 -delete

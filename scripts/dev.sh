#!/usr/bin/env bash
# Boot the local dev server with a fresh prod DB snapshot.
#
# Syncs teacher + review data from ratebiph.com if the last sync was
# more than SYNC_MAX_AGE_HOURS ago (default: 6). Skip with --skip-sync
# (offline work). Force a fresh pull with --force-sync.
#
# Usage:
#   ./scripts/dev.sh                  # sync if stale, then uvicorn
#   ./scripts/dev.sh --skip-sync      # just boot, don't touch the DB
#   ./scripts/dev.sh --force-sync     # sync no matter how recent
set -euo pipefail
cd "$(dirname "$0")/.."

SKIP=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --skip-sync)  SKIP=1 ;;
    --force-sync) FORCE=1 ;;
    *) echo "Unknown arg: $arg (accepted: --skip-sync, --force-sync)"; exit 2 ;;
  esac
done

STAMP="backend/.last-prod-sync"
MAX_AGE_HOURS="${SYNC_MAX_AGE_HOURS:-6}"

need_sync() {
  [[ $SKIP -eq 1 ]] && return 1
  [[ $FORCE -eq 1 ]] && return 0
  [[ ! -f "$STAMP" ]] && return 0
  # stat is macOS `-f %m` / Linux `-c %Y`; try both.
  local mtime
  mtime=$(stat -f %m "$STAMP" 2>/dev/null || stat -c %Y "$STAMP" 2>/dev/null || echo 0)
  local age=$(( $(date +%s) - mtime ))
  local max=$(( MAX_AGE_HOURS * 3600 ))
  if [[ $age -lt $max ]]; then
    echo "[dev.sh] last sync $((age / 60))m ago (threshold ${MAX_AGE_HOURS}h) — skipping"
    return 1
  fi
  return 0
}

if need_sync; then
  echo "[dev.sh] syncing dev DB from ratebiph.com..."
  if ./venv/bin/python scripts/sync_prod.py --yes; then
    touch "$STAMP"
  else
    echo "[dev.sh] sync failed — booting with the existing local DB."
  fi
fi

echo "[dev.sh] booting uvicorn on http://127.0.0.1:8765"
exec ./venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8765 --reload

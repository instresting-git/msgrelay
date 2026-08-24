#!/bin/bash
# wacli cleanup script — keep only 14 days of WhatsApp history
# Runs daily at 3am via launchd
# Random delay to avoid clashing with sync jobs

set -euo pipefail

WACLI="$HOME/bin/wacli"
LOGDIR="$HOME/.wacli/logs"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

exec >> "$LOGDIR/cleanup.log" 2>&1

echo "=== [$TIMESTAMP] Starting cleanup ==="

# Random sleep 0-60s to avoid sync collision
SLEEP=$((RANDOM % 60))
echo "Waiting ${SLEEP}s to avoid sync collision..."
sleep "$SLEEP"

cleanup_account() {
    local account="$1"
    echo ""
    echo "--- $account account cleanup ---"
    if "$WACLI" --account "$account" store cleanup --days 14 --confirm; then
        echo "OK: $account cleanup completed"
        return 0
    else
        echo "FAILED: $account cleanup (exit code $?) — may retry tomorrow"
        return 1
    fi
}

FAILED=0
cleanup_account work || FAILED=1
cleanup_account personal || FAILED=1

echo ""
echo "=== [$TIMESTAMP] Cleanup complete (failures=$FAILED) ==="

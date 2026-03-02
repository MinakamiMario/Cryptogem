#!/usr/bin/env bash
# Cryptogem Lab daemon wrapper — called by launchd.
# On every (re)start: pull latest code, self-test, then run daemon.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

LOG_PREFIX="[lab-daemon]"

echo "$LOG_PREFIX Starting at $(date '+%Y-%m-%d %H:%M:%S')"

# ── Step 1: Pull latest code (best-effort) ────────────────
if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    echo "$LOG_PREFIX Pulling latest code..."
    git pull --ff-only origin master 2>&1 || echo "$LOG_PREFIX git pull failed (non-fatal)"
fi

# ── Step 2: Self-test (import + version check) ────────────
echo "$LOG_PREFIX Running self-test..."
VERSION=$(python3 -c "from lab.config import LAB_VERSION; print(LAB_VERSION)" 2>&1)
if [ $? -ne 0 ]; then
    echo "$LOG_PREFIX ❌ Self-test FAILED: cannot import lab.config"
    echo "$LOG_PREFIX Waiting 60s before retry..."
    sleep 60
    exit 1
fi
echo "$LOG_PREFIX ✅ Self-test passed — v${VERSION}"

# ── Step 3: Post TG reload-complete notification ───────────
# Signal 2: confirms reload succeeded (pair with "reload ontvangen")
echo "$LOG_PREFIX Loaded version: v${VERSION} — Self-test PASS"
python3 -c "
from lab.notifier import LabNotifier
n = LabNotifier(enabled=True)
if n.enabled:
    n._send('✅ Reload voltooid — v${VERSION} geladen\n\nSelf-test: PASS\nDaemon start nu.')
" 2>/dev/null || true

# ── Step 4: Run daemon (exec replaces this shell) ─────────
echo "$LOG_PREFIX Launching daemon v${VERSION}..."
exec python3 -m lab.main run

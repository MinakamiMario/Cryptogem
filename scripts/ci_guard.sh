#!/bin/bash
# CI Guard: detect GRID_BEST-critical file changes
# If any critical file changed since last commit → run full validation suite
#
# Usage:
#   bash scripts/ci_guard.sh              # compare HEAD~1..HEAD
#   bash scripts/ci_guard.sh main         # compare main..HEAD
#   bash scripts/ci_guard.sh abc123       # compare abc123..HEAD

set -euo pipefail

BASE="${1:-HEAD~1}"
GRID_FILES="grid_best_files.txt"

if [ ! -f "$GRID_FILES" ]; then
    echo "ERROR: $GRID_FILES not found"
    exit 1
fi

# Get changed files
CHANGED=$(git diff --name-only "$BASE" HEAD 2>/dev/null || echo "")

if [ -z "$CHANGED" ]; then
    echo "No changes detected (base=$BASE)"
    exit 0
fi

# Check each critical file
TRIGGERED=false
for f in $(grep -v '^#' "$GRID_FILES" | grep -v '^\s*$'); do
    if echo "$CHANGED" | grep -q "$f"; then
        echo "⚠️  GRID_BEST file changed: $f"
        TRIGGERED=true
    fi
done

if [ "$TRIGGERED" = true ]; then
    echo ""
    echo "🔒 GRID_BEST-critical files changed → running full validation suite"
    echo "=== make check ==="
    make check
    echo ""
    echo "=== make robustness ==="
    make robustness
    echo ""
    echo "✅ GRID_BEST validation passed"
else
    echo "✅ No GRID_BEST-critical files changed — skip full suite"
fi

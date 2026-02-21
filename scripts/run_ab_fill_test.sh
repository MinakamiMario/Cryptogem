#!/bin/bash
# A/B Fill Test Runner — HF-P2-LIVE-FILL
# Leg A: mid+TTL120 (already running as PID $1)
# Leg B: near_bid+TTL60 (starts after Leg A completes)
#
# Usage: bash scripts/run_ab_fill_test.sh <leg_a_pid>

set -euo pipefail

LEG_A_PID="${1:?Usage: $0 <leg_a_pid>}"
REPORT_DIR="/Users/oussama/Cryptogem/reports/hf"

echo "=== A/B Fill Test Runner ==="
echo "Leg A PID: $LEG_A_PID (mid+TTL120, 150 rounds)"
echo "Waiting for Leg A to complete..."

# Wait for Leg A
while kill -0 "$LEG_A_PID" 2>/dev/null; do
    sleep 60
    # Show progress
    ROUNDS=$(wc -l < "$REPORT_DIR/ab_leg_a_mid_ttl120_stdout.log" 2>/dev/null || echo "0")
    echo "  [$(date '+%H:%M')] Leg A still running... (~$ROUNDS lines of output)"
done

echo ""
echo "=== Leg A completed at $(date) ==="
echo ""

# Find Leg A JSONL (most recent live_fill_test_*.jsonl)
LEG_A_LOG=$(ls -t "$REPORT_DIR"/live_fill_test_20260219_081811.jsonl 2>/dev/null | head -1)
if [ -z "$LEG_A_LOG" ]; then
    echo "ERROR: Cannot find Leg A log file"
    exit 1
fi

echo "Leg A log: $LEG_A_LOG"
echo ""

# Checkpoint on Leg A
echo "=== Leg A Checkpoint ==="
python3 -m strategies.hf.screening.live_fill_test --checkpoint --output "$LEG_A_LOG"
echo ""

# Start Leg B
echo "=== Starting Leg B: near_bid+TTL60, 150 rounds ==="
PYTHONUNBUFFERED=1 python3 -m strategies.hf.screening.live_fill_test \
    --rounds 150 --order-usd 15 --strategy near_bid --ttl 60 \
    2>&1 | tee "$REPORT_DIR/ab_leg_b_nearbid_ttl60_stdout.log"

# Find Leg B JSONL
LEG_B_LOG=$(ls -t "$REPORT_DIR"/live_fill_test_*.jsonl | head -1)
echo ""
echo "=== Leg B Checkpoint ==="
python3 -m strategies.hf.screening.live_fill_test --checkpoint --output "$LEG_B_LOG"

echo ""
echo "=== A/B TEST COMPLETE ==="
echo "Leg A (mid+TTL120): $LEG_A_LOG"
echo "Leg B (near_bid+TTL60): $LEG_B_LOG"
echo ""
echo "Run full reports:"
echo "  python3 -m strategies.hf.screening.live_fill_test --report --output $LEG_A_LOG"
echo "  python3 -m strategies.hf.screening.live_fill_test --report --output $LEG_B_LOG"

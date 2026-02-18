#!/bin/bash
# Resilient MEXC v2 overnight pipeline.
# Handles CC API rate limits by waiting and retrying.
#
# Usage: nohup bash scripts/run_mexc_v2_overnight_resilient.sh > logs/mexc_v2_overnight.log 2>&1 &

set -e
cd /Users/oussama/Cryptogem

# Create logs directory
mkdir -p logs

echo "=== MEXC v2 Resilient Pipeline ==="
echo "Started: $(date)"
echo ""

# Phase 0: Wait for CC API rate limit to clear
echo "Phase 0: Checking CC API rate limit..."
MAX_RETRIES=12  # 12 x 5 min = 60 min max wait
for i in $(seq 1 $MAX_RETRIES); do
    RESULT=$(python3 -c "
import urllib.request, json
try:
    url = 'https://min-api.cryptocompare.com/data/v2/histohour?fsym=BTC&tsym=USDT&limit=5&aggregate=4&e=MEXC'
    req = urllib.request.Request(url, headers={'User-Agent': 'CryptogemBot/1.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    print(data.get('Response', 'Unknown'))
except Exception as e:
    print(f'Error: {e}')
" 2>&1)

    echo "  Check $i/$MAX_RETRIES: $RESULT ($(date))"

    if [ "$RESULT" = "Success" ]; then
        echo "  API ready!"
        break
    fi

    if [ $i -eq $MAX_RETRIES ]; then
        echo "ERROR: API still rate-limited after $MAX_RETRIES checks. Aborting."
        exit 1
    fi

    echo "  Waiting 5 minutes..."
    sleep 300
done

echo ""
echo "Phase 1-6: Running pipeline..."
PYTHONUNBUFFERED=1 python3 scripts/run_mexc_v2_overnight.py --skip-universe 2>&1

echo ""
echo "=== Pipeline Complete ==="
echo "Finished: $(date)"

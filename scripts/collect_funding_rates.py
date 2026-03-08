#!/usr/bin/env python3
"""
Collect MEXC USDT-M funding rate history for ms_018 universe.

Saves to ~/CryptogemData/derived/funding_rates/mexc/
One JSON file per symbol: {symbol}.json

Free MEXC API, no key needed.
"""

import sys, json, time, os
from pathlib import Path
from datetime import datetime, timezone
import urllib.request
import urllib.error

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "trading_bot"))
sys.path.insert(0, str(REPO_ROOT))

import importlib
_data_resolver = importlib.import_module("strategies.4h.data_resolver")

DATASET_ID = "4h_default"
MIN_BARS = 360
MEXC_ENDPOINT = "https://contract.mexc.com/api/v1/contract/funding_rate/history"
DATA_ROOT = Path(os.environ.get("DATA_ROOT", Path.home() / "CryptogemData"))
OUTPUT_DIR = DATA_ROOT / "derived" / "funding_rates" / "mexc"
PAGE_SIZE = 100  # max per page

# ── Helpers ──────────────────────────────────────────────────────

def kraken_to_mexc_perp(pair: str) -> str:
    """Convert 'BTC/USD' → 'BTC_USDT'."""
    base = pair.split("/")[0]
    return f"{base}_USDT"


def fetch_all_funding(symbol: str) -> list:
    """Fetch all funding rate records for a MEXC perp symbol."""
    all_records = []
    page = 1

    while True:
        url = f"{MEXC_ENDPOINT}?symbol={symbol}&page_num={page}&page_size={PAGE_SIZE}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError:
            return all_records
        except Exception:
            return all_records

        if not data.get("success") or not data.get("data"):
            return all_records

        results = data["data"].get("resultList", [])
        if not results:
            break

        all_records.extend(results)

        total_pages = data["data"].get("totalPage", 1)
        if page >= total_pages:
            break

        page += 1
        time.sleep(0.15)

    return all_records


def main():
    # Load universe
    path = _data_resolver.resolve_dataset(DATASET_ID)
    with open(path) as f:
        data = json.load(f)

    coins = [p for p in data if not p.startswith("_")
             and isinstance(data[p], list) and len(data[p]) >= MIN_BARS]
    print(f"Universe: {len(coins)} coins")

    # Get candle time range
    sample_ts = []
    for pair in coins[:20]:
        candles = data[pair]
        if candles:
            sample_ts.append(candles[0]["time"])
            sample_ts.append(candles[-1]["time"])
    start_dt = datetime.fromtimestamp(min(sample_ts), tz=timezone.utc)
    end_dt = datetime.fromtimestamp(max(sample_ts), tz=timezone.utc)
    print(f"Candle range: {start_dt:%Y-%m-%d} to {end_dt:%Y-%m-%d}")

    # Get available MEXC perps
    url = "https://contract.mexc.com/api/v1/contract/detail"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as resp:
        contract_data = json.loads(resp.read())
    mexc_perps = set(s["symbol"] for s in contract_data["data"])
    print(f"MEXC USDT perps available: {len(mexc_perps)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Map coins to MEXC perp symbols
    to_fetch = {}
    no_perp = 0
    for pair in coins:
        sym = kraken_to_mexc_perp(pair)
        if sym in mexc_perps:
            to_fetch[sym] = pair
        else:
            no_perp += 1

    # Always include BTC
    if "BTC_USDT" not in to_fetch:
        to_fetch["BTC_USDT"] = "BTC/USD"

    print(f"Coins with MEXC perps: {len(to_fetch)} | Without: {no_perp}")
    print(f"Collecting funding rates...\n")

    collected = 0
    total = len(to_fetch)

    for i, (symbol, kraken_pair) in enumerate(sorted(to_fetch.items())):
        outfile = OUTPUT_DIR / f"{symbol}.json"

        # Skip if already collected
        if outfile.exists():
            existing = json.loads(outfile.read_text())
            if len(existing) > 0:
                collected += 1
                continue

        records = fetch_all_funding(symbol)

        if records:
            # Filter to backtest period + 30 day buffer
            buffer_start_s = min(sample_ts) - 30 * 86400
            filtered = [r for r in records
                       if r["settleTime"] / 1000 >= buffer_start_s]
            with open(outfile, "w") as f:
                json.dump(filtered, f)
            collected += 1
            if (i + 1) % 25 == 0 or len(filtered) > 100:
                print(f"  [{i+1}/{total}] {symbol}: {len(filtered)} records")
        else:
            with open(outfile, "w") as f:
                json.dump([], f)

        time.sleep(0.2)

    print(f"\nDone: {collected}/{total} symbols collected")
    print(f"Saved to: {OUTPUT_DIR}")

    # Save summary
    summary = {
        "exchange": "mexc",
        "coins_with_perps": len(to_fetch),
        "coins_without_perps": no_perp,
        "collected": collected,
        "candle_range": f"{start_dt:%Y-%m-%d} to {end_dt:%Y-%m-%d}",
    }
    with open(OUTPUT_DIR / "_summary.json", "w") as f:
        json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()

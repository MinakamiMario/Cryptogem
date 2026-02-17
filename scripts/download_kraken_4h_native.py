#!/usr/bin/env python3
"""
Download native Kraken 4H OHLCV for a subset of coins.

Uses Kraken's own REST API (OHLC endpoint). Returns max 720 bars (~120 days).
This is the GROUND TRUTH for Kraken prices (native VWAP, exact timestamps).

Usage:
    python scripts/download_kraken_4h_native.py \
        --coins strategies/4h/kraken_confirm_coins.json \
        --output ~/CryptogemData/derived/candle_cache/kraken/4h/candle_cache_4h_kraken_native_confirm.json
"""
from __future__ import annotations

import json
import time
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
RATE_LIMIT_SEC = 1.5  # Kraken public rate limit
INTERVAL_MINUTES = 240  # 4H = 240 minutes


def _kraken_pair(pair: str) -> str:
    """Convert 'BTC/USD' -> 'XBTUSD' for Kraken API."""
    base, quote = pair.split("/")
    # Kraken naming quirks
    remap = {"BTC": "XBT", "DOGE": "XDG"}
    base = remap.get(base, base)
    return f"{base}{quote}"


def download_ohlc(pair: str, retries: int = 3) -> list[dict] | None:
    """Download 4H OHLC from Kraken for a single pair.

    Returns list of candle dicts or None on failure.
    Kraken OHLC returns: [time, open, high, low, close, vwap, volume, count]
    """
    kraken_pair = _kraken_pair(pair)
    url = f"{KRAKEN_OHLC_URL}?pair={kraken_pair}&interval={INTERVAL_MINUTES}"

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CryptogemBot/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())

            if data.get("error"):
                errors = data["error"]
                # "Unknown asset pair" = not available
                if any("Unknown" in str(e) for e in errors):
                    return None
                if attempt < retries - 1:
                    time.sleep(3 * (attempt + 1))
                    continue
                return None

            result = data.get("result", {})
            # Find the OHLC data key (exclude 'last')
            ohlc_key = None
            for k in result:
                if k != "last":
                    ohlc_key = k
                    break
            if not ohlc_key:
                return None

            raw = result[ohlc_key]
            candles = []
            for row in raw:
                # [time, open, high, low, close, vwap, volume, count]
                candles.append({
                    "time": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "vwap": float(row[5]),
                    "volume": float(row[6]),
                    "count": int(row[7]),
                })
            return candles

        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
            else:
                print(f"    ERROR: {pair} -> {e}")
                return None
        except Exception as e:
            print(f"    ERROR: {pair} -> {e}")
            return None

    return None


def main():
    parser = argparse.ArgumentParser(description="Download native Kraken 4H OHLCV for confirm subset")
    parser.add_argument("--coins", required=True, help="JSON file with coin list")
    parser.add_argument("--output", default=str(
        Path.home() / "CryptogemData/derived/candle_cache/kraken/4h/candle_cache_4h_kraken_native_confirm.json"
    ))
    args = parser.parse_args()

    # Load coin list
    with open(args.coins) as f:
        coin_data = json.load(f)
    coins = coin_data.get("coins", coin_data)
    if isinstance(coins, dict):
        coins = list(coins.keys())

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Kraken Native 4H Download (Confirm Subset)")
    print(f"{'='*60}")
    print(f"  Coins: {len(coins)}")
    print(f"  Output: {output_path}")
    print(f"  Max bars: 720 (~120 days)")
    print(f"  Rate limit: {RATE_LIMIT_SEC}s between calls")
    est_min = len(coins) * RATE_LIMIT_SEC / 60
    print(f"  Estimated time: {est_min:.1f} min")
    print()

    result = {}
    n_ok = n_fail = n_short = 0
    bars_counts = []
    t_start = time.time()

    for i, pair in enumerate(coins):
        elapsed = time.time() - t_start
        eta = (elapsed / max(1, i)) * (len(coins) - i) / 60 if i > 0 else 0
        print(f"  [{i:3d}/{len(coins)}] ({i/len(coins)*100:4.1f}%) {pair:<15s} ETA {eta:.0f}m", end="")

        candles = download_ohlc(pair)

        if candles is None:
            print(f"  -> FAILED")
            n_fail += 1
        else:
            n_bars = len(candles)
            bars_counts.append(n_bars)
            days = n_bars * 4 / 24
            tag = ""
            if n_bars < 500:
                tag = " [SHORT]"
                n_short += 1
            print(f"  -> {n_bars} bars ({days:.0f}d){tag}")
            result[pair] = candles
            n_ok += 1

        if i < len(coins) - 1:
            time.sleep(RATE_LIMIT_SEC)

    total_time = (time.time() - t_start) / 60

    # Add metadata
    import statistics
    result["_meta"] = {
        "source": "kraken_native_ohlc",
        "venue": "native",
        "timeframe": "4h",
        "interval_minutes": INTERVAL_MINUTES,
        "coins": n_ok,
        "failed": n_fail,
        "short": n_short,
        "bars_min": min(bars_counts) if bars_counts else 0,
        "bars_max": max(bars_counts) if bars_counts else 0,
        "bars_median": int(statistics.median(bars_counts)) if bars_counts else 0,
        "span_days": round(max(bars_counts) * 4 / 24, 1) if bars_counts else 0,
        "downloaded": datetime.now(timezone.utc).isoformat(),
        "has_native_vwap": True,
    }

    # Write output
    with open(output_path, "w") as f:
        json.dump(result, f)

    file_mb = output_path.stat().st_size / 1024 / 1024

    print(f"\n{'='*60}")
    print(f"  DOWNLOAD COMPLETE")
    print(f"{'='*60}")
    print(f"  Downloaded: {n_ok} coins")
    print(f"  Failed: {n_fail}")
    print(f"  Short (<500 bars): {n_short}")
    print(f"  Time: {total_time:.1f} min")
    if bars_counts:
        print(f"  Bars: min={min(bars_counts)}, max={max(bars_counts)}, median={int(statistics.median(bars_counts))}")
        # Date range
        all_times = []
        for pair in result:
            if pair.startswith("_"):
                continue
            candles = result[pair]
            if candles:
                all_times.extend([candles[0]["time"], candles[-1]["time"]])
        if all_times:
            earliest = datetime.fromtimestamp(min(all_times), tz=timezone.utc)
            latest = datetime.fromtimestamp(max(all_times), tz=timezone.utc)
            print(f"  Range: {earliest.date()} -> {latest.date()} ({(latest-earliest).days} days)")
    print(f"  File: {output_path} ({file_mb:.1f} MB)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

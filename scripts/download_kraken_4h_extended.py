#!/usr/bin/env python3
"""
Download extended 4H Kraken OHLC data via CryptoCompare — 360+ days

Kraken's own API only returns 720 bars (120 days). CryptoCompare provides
historical Kraken OHLC data with pagination support (500 bars/page).

Usage:
    python scripts/download_kraken_4h_extended.py
    python scripts/download_kraken_4h_extended.py --days 400 --dry-run
    python scripts/download_kraken_4h_extended.py --resume
    python scripts/download_kraken_4h_extended.py --max-coins 5  # test run

API: CryptoCompare histohour (aggregate=4, e=Kraken), free tier ~50 calls/sec.
Each call returns max 500 bars = ~83 days. For 400 days: 5 pages/coin.
526 coins × 5 pages = ~2630 calls ≈ 45 min (with safety margin).

Output: ~/CryptogemData/derived/candle_cache/kraken/4h/candle_cache_4h_kraken_v2.json
"""
from __future__ import annotations

import sys
import json
import time
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path.home() / 'CryptogemData'
OUTPUT_DIR = DATA_ROOT / 'derived' / 'candle_cache' / 'kraken' / '4h'
OUTPUT_FILE = OUTPUT_DIR / 'candle_cache_4h_kraken_v2.json'
PROGRESS_FILE = OUTPUT_DIR / '.download_progress.json'

CC_BASE_URL = 'https://min-api.cryptocompare.com/data/v2/histohour'
BARS_PER_PAGE = 2000  # Request limit (CC returns max ~500 actual)
AGGREGATE = 4  # 4-hour bars
EXCHANGE = 'Kraken'
RATE_LIMIT_SEC = 1.2  # CryptoCompare free tier limit
RETRY_DELAYS = [3, 10, 30]

EXISTING_CACHE = REPO_ROOT / 'trading_bot' / 'candle_cache_532.json'

# CryptoCompare uses slightly different symbols
SYMBOL_MAP = {
    'DOGE': 'DOGE',  # CC uses DOGE directly
}


def _cc_symbol(pair: str) -> str:
    """Convert 'BTC/USD' -> CryptoCompare symbol 'BTC'."""
    base = pair.replace('/USD', '')
    return SYMBOL_MAP.get(base, base)


def _api_call(url: str) -> dict | None:
    """Make a CryptoCompare API call with retries."""
    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay > 0:
            time.sleep(delay)
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'CryptogemBot/1.0')
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            if data.get('Response') == 'Error':
                return None
            return data
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt < len(RETRY_DELAYS):
                continue
            return None
    return None


def _fetch_coin_extended(pair: str, target_days: int) -> list[dict] | None:
    """Fetch extended 4H data for a single coin via CryptoCompare pagination."""
    sym = _cc_symbol(pair)
    all_candles = []
    toTs = None
    target_bars = target_days * 24 // 4
    max_pages = (target_bars // 450) + 2  # ~450 real bars per page, +buffer

    for page in range(max_pages):
        url = f'{CC_BASE_URL}?fsym={sym}&tsym=USD&limit={BARS_PER_PAGE}&aggregate={AGGREGATE}&e={EXCHANGE}'
        if toTs:
            url += f'&toTs={toTs}'

        time.sleep(RATE_LIMIT_SEC)
        data = _api_call(url)
        if not data or 'Data' not in data:
            break

        candles_raw = data['Data'].get('Data', [])
        if not candles_raw:
            break

        # Convert to our format (matching Kraken schema)
        page_candles = []
        for c in candles_raw:
            vol = c.get('volumefrom', 0) or 0
            vol_to = c.get('volumeto', 0) or 0
            if vol <= 0 and vol_to <= 0:
                continue  # Skip empty padding bars
            page_candles.append({
                'time': int(c['time']),
                'open': float(c['open']),
                'high': float(c['high']),
                'low': float(c['low']),
                'close': float(c['close']),
                'vwap': round((float(c['high']) + float(c['low']) + float(c['close'])) / 3, 6),
                'volume': float(vol),
                'count': 0,  # CC doesn't provide trade count
            })

        if not page_candles:
            break

        all_candles = page_candles + all_candles
        toTs = candles_raw[0]['time']

        # Stop if we have enough or hit the end of available data
        if len(all_candles) >= target_bars:
            break

    if not all_candles:
        return None

    # Deduplicate by time
    seen = set()
    deduped = []
    for c in all_candles:
        if c['time'] not in seen:
            seen.add(c['time'])
            deduped.append(c)
    deduped.sort(key=lambda c: c['time'])

    return deduped if deduped else None


def _load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {}


def _save_progress(completed: set, all_data: dict):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Save completed list + stats (not full data — too large for progress file)
    with open(PROGRESS_FILE, 'w') as f:
        json.dump({
            'completed': sorted(completed),
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'n_completed': len(completed),
        }, f)


def main():
    parser = argparse.ArgumentParser(description='Download extended 4H Kraken OHLC via CryptoCompare')
    parser.add_argument('--days', type=int, default=400, help='Target days (default: 400)')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--max-coins', type=int, default=None)
    args = parser.parse_args()

    print(f"Loading coin list from {EXISTING_CACHE}...")
    with open(EXISTING_CACHE) as f:
        existing = json.load(f)
    coins = sorted([k for k in existing if not k.startswith('_')])
    if args.max_coins:
        coins = coins[:args.max_coins]

    target_bars = args.days * 24 // 4
    pages_per_coin = (target_bars // 450) + 2
    total_calls = len(coins) * pages_per_coin
    est_minutes = total_calls * RATE_LIMIT_SEC / 60

    print(f"\n{'='*60}")
    print(f"  Kraken 4H Extended Download (via CryptoCompare)")
    print(f"{'='*60}")
    print(f"  Coins: {len(coins)}")
    print(f"  Target: {args.days} days ({target_bars} bars)")
    print(f"  Pages per coin: ~{pages_per_coin}")
    print(f"  Total API calls: ~{total_calls}")
    print(f"  Estimated time: ~{est_minutes:.0f} min")
    print(f"  Output: {OUTPUT_FILE}")

    if args.dry_run:
        print(f"\n  DRY RUN — no downloads")
        return

    # Resume support
    completed_coins = set()
    all_data = {}
    if args.resume:
        progress = _load_progress()
        completed_coins = set(progress.get('completed', []))
        # Load existing partial output if it exists
        if OUTPUT_FILE.exists():
            print(f"  Loading existing data for resume...")
            with open(OUTPUT_FILE) as f:
                saved = json.load(f)
            all_data = {k: v for k, v in saved.items() if not k.startswith('_')}
            print(f"  Loaded {len(all_data)} coins from previous run")
        if completed_coins:
            print(f"  Resuming: {len(completed_coins)} coins already done")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    n_done = len(completed_coins)
    n_total = len(coins)
    n_failed = 0
    n_short = 0
    t_start = time.time()
    initial_done = n_done

    print(f"\n  Starting download...\n")

    for i, pair in enumerate(coins):
        if pair in completed_coins:
            continue

        elapsed = time.time() - t_start
        new_done = n_done - initial_done
        if new_done > 0:
            rate = new_done / elapsed
            remaining = (n_total - n_done) / rate
            eta = f"ETA {remaining/60:.0f}m"
        else:
            eta = "ETA --"

        pct = n_done / n_total * 100
        print(f"  [{n_done:3d}/{n_total}] ({pct:4.1f}%) {pair:15s} {eta}", end="", flush=True)

        candles = _fetch_coin_extended(pair, args.days)
        if candles and len(candles) > 50:  # Minimum viable data
            all_data[pair] = candles
            days_got = (candles[-1]['time'] - candles[0]['time']) / 86400
            if days_got < args.days * 0.8:
                n_short += 1
                print(f"  → {len(candles)} bars ({days_got:.0f}d) [SHORT]")
            else:
                print(f"  → {len(candles)} bars ({days_got:.0f}d)")
            completed_coins.add(pair)
        else:
            print(f"  → FAILED")
            n_failed += 1

        n_done += 1

        # Checkpoint every 25 coins
        if (n_done - initial_done) % 25 == 0 and n_done > initial_done:
            _save_progress(completed_coins, all_data)
            # Also save partial output
            _save_output(all_data, args.days, partial=True)
            print(f"  [checkpoint: {len(completed_coins)} coins saved]")

    # Final save
    total_elapsed = time.time() - t_start
    _save_output(all_data, args.days, partial=False)
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()

    print(f"\n{'='*60}")
    print(f"  DOWNLOAD COMPLETE")
    print(f"{'='*60}")
    print(f"  Downloaded: {len(all_data)} coins")
    print(f"  Failed: {n_failed}")
    print(f"  Short (<{int(args.days*0.8)}d): {n_short}")
    print(f"  Time: {total_elapsed/60:.1f} min")

    if all_data:
        bar_counts = [len(v) for v in all_data.values()]
        all_starts = [v[0]['time'] for v in all_data.values() if v]
        all_ends = [v[-1]['time'] for v in all_data.values() if v]
        earliest = datetime.utcfromtimestamp(min(all_starts))
        latest = datetime.utcfromtimestamp(max(all_ends))
        span_days = (max(all_ends) - min(all_starts)) / 86400
        min_bars, max_bars, median_bars = min(bar_counts), max(bar_counts), sorted(bar_counts)[len(bar_counts)//2]

        print(f"  Bars: min={min_bars}, max={max_bars}, median={median_bars}")
        print(f"  Range: {earliest.date()} → {latest.date()} ({span_days:.0f} days)")
        size_mb = OUTPUT_FILE.stat().st_size / 1024 / 1024
        print(f"  File: {OUTPUT_FILE} ({size_mb:.1f} MB)")


def _save_output(all_data: dict, target_days: int, partial: bool = False):
    """Save the output file with metadata."""
    if not all_data:
        return
    bar_counts = [len(v) for v in all_data.values()]
    all_starts = [v[0]['time'] for v in all_data.values() if v]
    all_ends = [v[-1]['time'] for v in all_data.values() if v]
    earliest = datetime.utcfromtimestamp(min(all_starts))
    latest = datetime.utcfromtimestamp(max(all_ends))
    span_days = (max(all_ends) - min(all_starts)) / 86400

    output = {
        '_meta': {
            'source': 'cryptocompare_histohour_kraken',
            'exchange': 'kraken',
            'interval': '4h',
            'interval_min': 240,
            'coins': len(all_data),
            'target_days': target_days,
            'downloaded': datetime.now(timezone.utc).isoformat(),
            'partial': partial,
            'min_bars': min(bar_counts),
            'max_bars': max(bar_counts),
            'median_bars': sorted(bar_counts)[len(bar_counts)//2],
            'earliest': earliest.isoformat(),
            'latest': latest.isoformat(),
            'span_days': round(span_days, 1),
            'note': 'vwap = (H+L+C)/3 approximation (CryptoCompare has no native VWAP)',
        }
    }
    output.update(all_data)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f)


if __name__ == '__main__':
    main()

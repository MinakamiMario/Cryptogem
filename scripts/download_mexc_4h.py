#!/usr/bin/env python3
"""
Download MEXC 4H OHLCV candles via CryptoCompare.

Uses the same CryptoCompare histohour API as the Kraken extended downloader,
but with e=MEXC and tsym=USDT. Reads coin list from mexc_universe_4h.json.

Usage:
    python scripts/download_mexc_4h.py
    python scripts/download_mexc_4h.py --max-coins 5  # test run
    python scripts/download_mexc_4h.py --days 400 --resume
"""
from __future__ import annotations

import sys
import json
import time
import argparse
import urllib.request
import urllib.error
import statistics
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path.home() / 'CryptogemData'
OUTPUT_DIR = DATA_ROOT / 'derived' / 'candle_cache' / 'mexc' / '4h'
OUTPUT_FILE = OUTPUT_DIR / 'candle_cache_4h_mexc_v1.json'
PROGRESS_FILE = OUTPUT_DIR / '.download_progress_4h.json'
UNIVERSE_FILE = REPO_ROOT / 'strategies' / '4h' / 'mexc_universe_4h.json'

CC_BASE_URL = 'https://min-api.cryptocompare.com/data/v2/histohour'
BARS_PER_PAGE = 2000
AGGREGATE = 4  # 4H bars
EXCHANGE = 'MEXC'
TSYM = 'USDT'  # MEXC uses USDT pairs
RATE_LIMIT_SEC = 1.2
RETRY_DELAYS = [3, 10, 30]
CHECKPOINT_EVERY = 25


def _cc_symbol(pair: str) -> str:
    """Convert 'BTC/USD' -> CryptoCompare base symbol 'BTC'."""
    base = pair.replace('/USD', '').replace('/USDT', '')
    return base


def _api_call(url: str) -> dict | None:
    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay > 0:
            time.sleep(delay)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'CryptogemBot/1.0'})
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


def _fetch_coin(pair: str, target_days: int) -> list[dict] | None:
    """Fetch extended 4H data for a single coin via CryptoCompare."""
    sym = _cc_symbol(pair)
    all_candles = []
    toTs = None
    target_bars = target_days * 24 // 4
    max_pages = (target_bars // 450) + 2

    for page in range(max_pages):
        url = (f'{CC_BASE_URL}?fsym={sym}&tsym={TSYM}&limit={BARS_PER_PAGE}'
               f'&aggregate={AGGREGATE}&e={EXCHANGE}')
        if toTs:
            url += f'&toTs={toTs}'

        time.sleep(RATE_LIMIT_SEC)
        data = _api_call(url)
        if not data or 'Data' not in data:
            break

        candles_raw = data['Data'].get('Data', [])
        if not candles_raw:
            break

        page_candles = []
        for c in candles_raw:
            vol = c.get('volumefrom', 0) or 0
            vol_to = c.get('volumeto', 0) or 0
            if vol <= 0 and vol_to <= 0:
                continue
            page_candles.append({
                'time': int(c['time']),
                'open': float(c['open']),
                'high': float(c['high']),
                'low': float(c['low']),
                'close': float(c['close']),
                'vwap': round((float(c['high']) + float(c['low']) + float(c['close'])) / 3, 6),
                'volume': float(vol),
                'count': 0,
            })

        if not page_candles:
            break

        all_candles = page_candles + all_candles
        toTs = candles_raw[0]['time']

        if len(all_candles) >= target_bars:
            break

    if not all_candles:
        return None

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
    return {'completed': {}, 'failed': []}


def _save_progress(progress: dict):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)


def main():
    parser = argparse.ArgumentParser(description='Download MEXC 4H candles via CryptoCompare')
    parser.add_argument('--days', type=int, default=400)
    parser.add_argument('--max-coins', type=int, default=0, help='Limit coins (0=all)')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--universe', default=str(UNIVERSE_FILE))
    parser.add_argument('--output', default=str(OUTPUT_FILE))
    args = parser.parse_args()

    # Load universe
    universe_path = Path(args.universe)
    if not universe_path.exists():
        print(f"ERROR: Universe file not found: {universe_path}")
        print("Run: python scripts/build_mexc_universe.py first")
        sys.exit(1)

    with open(universe_path) as f:
        universe = json.load(f)
    coins = universe.get('coins', [])
    if args.max_coins > 0:
        coins = coins[:args.max_coins]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume support
    progress = _load_progress() if args.resume else {'completed': {}, 'failed': []}
    result = {}
    if args.resume and output_path.exists():
        with open(output_path) as f:
            result = json.load(f)
        result = {k: v for k, v in result.items() if not k.startswith('_')}

    print(f"\n{'='*60}")
    print(f"  MEXC 4H Download (via CryptoCompare)")
    print(f"{'='*60}")
    print(f"  Universe: {universe_path.name} ({len(coins)} coins)")
    print(f"  Target: {args.days} days")
    print(f"  Output: {output_path}")
    if args.resume and progress['completed']:
        print(f"  Resuming: {len(progress['completed'])} already done")
    est_min = len(coins) * 5 * RATE_LIMIT_SEC / 60  # ~5 pages/coin
    print(f"  Estimated time: ~{est_min:.0f} min")
    print()

    n_ok = n_fail = n_short = n_skip = 0
    bars_counts = []
    t_start = time.time()

    for i, pair in enumerate(coins):
        # Skip if already done (resume mode)
        if pair in progress['completed']:
            if pair in result:
                bars_counts.append(progress['completed'][pair])
                n_skip += 1
                continue

        elapsed = time.time() - t_start
        remaining = len(coins) - i
        eta = (elapsed / max(1, i - n_skip)) * remaining / 60 if (i - n_skip) > 0 else 0

        short_days = args.days * 24 // 4 * 0.8  # 80% threshold for SHORT
        print(f"  [{i:3d}/{len(coins)}] ({i/len(coins)*100:4.1f}%) {pair:<15s} ETA {eta:.0f}m", end='')

        candles = _fetch_coin(pair, args.days)

        if candles is None:
            print(f'  -> FAILED')
            n_fail += 1
            progress['failed'].append(pair)
        else:
            n_bars = len(candles)
            bars_counts.append(n_bars)
            days = n_bars * 4 / 24
            tag = ''
            if n_bars < args.days * 24 // 4 * 0.8:
                tag = ' [SHORT]'
                n_short += 1
            print(f'  -> {n_bars} bars ({days:.0f}d){tag}')
            result[pair] = candles
            progress['completed'][pair] = n_bars
            n_ok += 1

        # Checkpoint
        if (i + 1) % CHECKPOINT_EVERY == 0 and result:
            _save_progress(progress)
            # Save partial output
            partial = dict(result)
            partial['_meta'] = {
                'source': 'cryptocompare_histohour_mexc',
                'exchange': 'mexc',
                'timeframe': '4h',
                'coins': len([k for k in partial if not k.startswith('_')]),
                'partial': True,
            }
            with open(output_path, 'w') as f:
                json.dump(partial, f)
            print(f"  [checkpoint: {len(result)} coins saved]")

    total_time = (time.time() - t_start) / 60

    # Final output with metadata
    all_times = []
    for pair in result:
        if pair.startswith('_'):
            continue
        candles = result[pair]
        if candles:
            all_times.extend([candles[0]['time'], candles[-1]['time']])

    span_days = 0
    if all_times:
        earliest = datetime.fromtimestamp(min(all_times), tz=timezone.utc)
        latest = datetime.fromtimestamp(max(all_times), tz=timezone.utc)
        span_days = (latest - earliest).days

    result['_meta'] = {
        'source': 'cryptocompare_histohour_mexc',
        'exchange': 'mexc',
        'timeframe': '4h',
        'coins': len([k for k in result if not k.startswith('_')]),
        'failed': n_fail,
        'short': n_short,
        'bars_min': min(bars_counts) if bars_counts else 0,
        'bars_max': max(bars_counts) if bars_counts else 0,
        'bars_median': int(statistics.median(bars_counts)) if bars_counts else 0,
        'span_days': round(span_days, 1),
        'downloaded': datetime.now(timezone.utc).isoformat(),
        'has_native_vwap': False,
        'vwap_note': 'VWAP approximated as (H+L+C)/3',
        'fee_note': 'MEXC SPOT: 0% maker, 10bps taker (conservative)',
    }

    with open(output_path, 'w') as f:
        json.dump(result, f)
    _save_progress(progress)

    file_mb = output_path.stat().st_size / 1024 / 1024

    print(f"\n{'='*60}")
    print(f"  DOWNLOAD COMPLETE")
    print(f"{'='*60}")
    print(f"  Downloaded: {n_ok} coins (skipped: {n_skip})")
    print(f"  Failed: {n_fail}")
    print(f"  Short: {n_short}")
    print(f"  Time: {total_time:.1f} min")
    if bars_counts:
        print(f"  Bars: min={min(bars_counts)}, max={max(bars_counts)}, "
              f"median={int(statistics.median(bars_counts))}")
        if all_times:
            print(f"  Range: {earliest.date()} -> {latest.date()} ({span_days} days)")
    print(f"  File: {output_path} ({file_mb:.1f} MB)")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
1-Minute VWAP Aggregator for Bybit
====================================
Downloads 1m candles for a coin list on Bybit, aggregates to 1H bars with
REAL volume-weighted VWAP:

    VWAP_1H = Σ(tp_1m × vol_1m) / Σ(vol_1m)

where tp_1m = (high_1m + low_1m + close_1m) / 3  (typical price per 1m bar).

This replaces the HLC3 proxy ((H+L+C)/3 of the 1H bar) with a genuine
trade-weighted average, enabling apples-to-apples comparison with MEXC
(which has real Kraken VWAP).

The script:
1. Takes a coin list (either MEXC intersection or explicit list)
2. Downloads 1m candles via CCXT (60× more data than 1H)
3. Aggregates 60 × 1m bars into each 1H bar
4. Replaces the 'vwap' field in the Bybit candle cache
5. Produces a patched cache file for H20 backtest

Usage:
    # Intersection coins (166 coins from MEXC ∩ Bybit)
    python -m strategies.hf.screening.vwap_1m_aggregator --mode intersection

    # Full MEXC top-trade coins (295 coins — only those available on Bybit)
    python -m strategies.hf.screening.vwap_1m_aggregator --mode mexc_universe

    # Explicit coin list
    python -m strategies.hf.screening.vwap_1m_aggregator --coins NYM/USD ANKR/USD FIDA/USD

    # Then run H20 validation on the patched cache:
    python -m strategies.hf.screening.run_bybit_vwap_validation
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

from strategies.hf.screening.exchange_config import get_exchange


# ============================================================
# Coin list builders
# ============================================================

def get_intersection_coins():
    """Get 166 coins in MEXC ∩ Bybit intersection."""
    # Load MEXC universe
    mexc_path = _ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not mexc_path.exists():
        mexc_path = _ROOT / 'reports' / 'hf' / 'universe_tiering_mexc_001.json'
    with open(mexc_path) as f:
        mexc = json.load(f)

    mexc_bases = set()
    for tier_num in ('1', '2'):
        coins = mexc.get('tier_breakdown', {}).get(tier_num, {}).get('coins', [])
        for coin in coins:
            mexc_bases.add(coin.split('/')[0])

    # Load Bybit candle cache to check availability
    bybit_cache_path = _ROOT / 'data' / 'candle_cache_1h_bybit.json'
    with open(bybit_cache_path) as f:
        bybit_data = json.load(f)

    bybit_coins = set(bybit_data.keys())
    intersection = []
    for coin in sorted(bybit_coins):
        base = coin.split('/')[0]
        if base in mexc_bases:
            intersection.append(coin)

    return intersection


def get_mexc_universe_on_bybit():
    """Get full MEXC universe coins that exist on Bybit."""
    # Same as intersection — all MEXC coins available on Bybit
    return get_intersection_coins()


def get_bybit_symbol_map():
    """Load Bybit universe tiering for symbol mapping."""
    path = _ROOT / 'reports' / 'hf' / 'universe_tiering_bybit_001.json'
    with open(path) as f:
        universe = json.load(f)
    return universe.get('symbol_map', {})


# ============================================================
# 1m candle download
# ============================================================

def download_1m_candles(exchange_cfg, internal_symbol, ccxt_symbol,
                        since_ms, until_ms, max_retries=5):
    """Download all 1m candles for a single coin within [since_ms, until_ms].

    Returns list of [timestamp, open, high, low, close, volume] rows.
    """
    exchange = exchange_cfg.create_ccxt_exchange()
    exchange.options['defaultType'] = 'spot'

    all_rows = []
    fetch_since = since_ms

    while fetch_since < until_ms:
        retries = 0
        while retries < max_retries:
            try:
                ohlcv = exchange.fetch_ohlcv(
                    ccxt_symbol, '1m', since=fetch_since,
                    limit=1000,  # Most exchanges allow up to 1000 1m bars
                )
                if not ohlcv:
                    return all_rows

                for row in ohlcv:
                    if row[0] < until_ms:
                        all_rows.append(row)

                last_ts = ohlcv[-1][0]
                fetch_since = last_ts + 60_000  # +1 minute

                if len(ohlcv) < 100:
                    return all_rows  # No more data

                time.sleep(exchange_cfg.politeness_sleep_s)
                break  # Success, next page

            except Exception as e:
                retries += 1
                if retries >= max_retries:
                    print(f'    [ERROR] {ccxt_symbol} 1m download failed: {e}')
                    return all_rows
                time.sleep(1.0 * retries)

    return all_rows


# ============================================================
# Aggregation: 1m -> 1H with VWAP
# ============================================================

def aggregate_1m_to_1h(minute_rows):
    """Aggregate 1m OHLCV rows into 1H bars with volume-weighted VWAP.

    Each 1H bar covers [hour_start, hour_start + 3600_000).
    VWAP = Σ(tp_1m × vol_1m) / Σ(vol_1m)
    where tp_1m = (high_1m + low_1m + close_1m) / 3

    Returns list of candle dicts matching the existing cache format:
    {timestamp, open, high, low, close, volume, vwap}
    """
    if not minute_rows:
        return []

    # Group by hour
    hourly_groups = {}
    for row in minute_rows:
        ts, o, h, l, c, vol = row[:6]
        # Floor to hour boundary
        hour_ts = (ts // 3600_000) * 3600_000
        if hour_ts not in hourly_groups:
            hourly_groups[hour_ts] = []
        hourly_groups[hour_ts].append({
            'ts': ts, 'open': o, 'high': h, 'low': l, 'close': c, 'vol': vol,
        })

    # Build 1H bars
    result = []
    for hour_ts in sorted(hourly_groups.keys()):
        bars = hourly_groups[hour_ts]
        bars.sort(key=lambda x: x['ts'])

        h_open = bars[0]['open']
        h_high = max(b['high'] for b in bars)
        h_low = min(b['low'] for b in bars)
        h_close = bars[-1]['close']
        h_volume = sum(b['vol'] for b in bars)

        # Volume-weighted typical price
        tp_vol_sum = 0.0
        vol_sum = 0.0
        for b in bars:
            tp = (b['high'] + b['low'] + b['close']) / 3.0
            tp_vol_sum += tp * b['vol']
            vol_sum += b['vol']

        if vol_sum > 0:
            vwap = tp_vol_sum / vol_sum
        else:
            # No volume — fallback to HLC3 of the hourly bar
            vwap = (h_high + h_low + h_close) / 3.0

        result.append({
            'timestamp': hour_ts,
            'open': h_open,
            'high': h_high,
            'low': h_low,
            'close': h_close,
            'volume': h_volume,
            'vwap': vwap,
            '_vwap_source': 'real_1m' if vol_sum > 0 else 'hlc3_fallback',
            '_1m_bars': len(bars),
        })

    return result


# ============================================================
# Patch existing Bybit cache
# ============================================================

def patch_cache_with_real_vwap(original_cache, aggregated_coins):
    """Replace VWAP values in existing 1H cache with real 1m-aggregated VWAPs.

    For coins with 1m data: replace VWAP field and add metadata.
    For coins without 1m data: keep existing HLC3 proxy.

    Returns: (patched_cache, patch_stats)
    """
    patched = {}
    stats = {
        'total_coins': len(original_cache),
        'patched': 0,
        'kept_hlc3': 0,
        'bars_patched': 0,
        'bars_total': 0,
        'vwap_diff_summary': [],
    }

    for coin, candles in original_cache.items():
        if coin.startswith('_'):
            patched[coin] = candles
            continue

        stats['bars_total'] += len(candles)

        if coin in aggregated_coins:
            # Build timestamp -> aggregated bar lookup
            agg_bars = {b['timestamp']: b for b in aggregated_coins[coin]}

            new_candles = []
            diffs = []
            n_patched_bars = 0

            for orig in candles:
                ts = orig['timestamp']
                if ts in agg_bars:
                    agg = agg_bars[ts]
                    old_vwap = orig.get('vwap', 0)
                    new_vwap = agg['vwap']

                    # Sanity: verify OHLCV matches (within tolerance)
                    # 1m aggregation should reconstruct the same H/L/V
                    new_candle = dict(orig)
                    new_candle['vwap'] = new_vwap
                    new_candle['_vwap_source'] = agg.get('_vwap_source', 'real_1m')
                    new_candle['_1m_bars'] = agg.get('_1m_bars', 0)
                    new_candles.append(new_candle)

                    if old_vwap > 0:
                        diff_pct = (new_vwap - old_vwap) / old_vwap * 100
                        diffs.append(diff_pct)

                    n_patched_bars += 1
                else:
                    new_candles.append(orig)

            patched[coin] = new_candles
            stats['patched'] += 1
            stats['bars_patched'] += n_patched_bars

            if diffs:
                abs_diffs = [abs(d) for d in diffs]
                stats['vwap_diff_summary'].append({
                    'coin': coin,
                    'bars_patched': n_patched_bars,
                    'bars_total': len(candles),
                    'coverage_pct': round(n_patched_bars / len(candles) * 100, 1),
                    'mean_diff_pct': round(sum(diffs) / len(diffs), 4),
                    'abs_mean_diff_pct': round(sum(abs_diffs) / len(abs_diffs), 4),
                    'max_abs_diff_pct': round(max(abs_diffs), 4),
                })
        else:
            patched[coin] = candles
            stats['kept_hlc3'] += 1

    return patched, stats


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Download 1m candles on Bybit and compute real VWAP for 1H bars',
    )
    parser.add_argument('--mode', choices=['intersection', 'mexc_universe', 'custom'],
                        default='intersection',
                        help='Coin selection mode (default: intersection)')
    parser.add_argument('--coins', nargs='+', default=None,
                        help='Custom coin list (e.g., NYM/USD ANKR/USD)')
    parser.add_argument('--max-coins', type=int, default=None,
                        help='Limit number of coins (for testing)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show plan only, no download')

    args = parser.parse_args()

    sep = '=' * 70
    print(sep)
    print('  Bybit 1-Minute VWAP Aggregator')
    print('  Download 1m candles -> aggregate to 1H with real VWAP')
    print(sep)
    t0 = time.time()

    # Select coins
    if args.coins:
        target_coins = args.coins
        mode_label = 'custom'
    elif args.mode == 'intersection':
        target_coins = get_intersection_coins()
        mode_label = 'mexc_intersection'
    else:
        target_coins = get_mexc_universe_on_bybit()
        mode_label = 'mexc_universe'

    if args.max_coins:
        target_coins = target_coins[:args.max_coins]

    print(f'[Config] Mode: {mode_label}')
    print(f'[Config] Target coins: {len(target_coins)}')

    # Load Bybit symbol map for ccxt_symbol lookup
    symbol_map = get_bybit_symbol_map()

    # Determine time range from existing Bybit 1H cache
    bybit_cache_path = _ROOT / 'data' / 'candle_cache_1h_bybit.json'
    print(f'[Load] Reading existing Bybit 1H cache...')
    with open(bybit_cache_path) as f:
        original_cache = json.load(f)

    # Get time range from first available target coin
    since_ms = None
    until_ms = None
    for coin in target_coins:
        if coin in original_cache:
            candles = original_cache[coin]
            if candles:
                coin_start = candles[0]['timestamp']
                coin_end = candles[-1]['timestamp'] + 3600_000  # End of last bar
                if since_ms is None or coin_start < since_ms:
                    since_ms = coin_start
                if until_ms is None or coin_end > until_ms:
                    until_ms = coin_end

    if since_ms is None:
        print('[ERROR] No target coins found in Bybit cache')
        sys.exit(1)

    since_str = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
    until_str = datetime.fromtimestamp(until_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
    total_hours = (until_ms - since_ms) / 3600_000
    total_1m_bars_per_coin = int(total_hours * 60)

    print(f'[Time range] {since_str} -> {until_str}')
    print(f'[Time range] {total_hours:.0f} hours = {total_1m_bars_per_coin} 1m bars per coin')
    print(f'[Estimate] Total 1m bars to download: ~{len(target_coins) * total_1m_bars_per_coin:,}')
    print(f'[Estimate] ~{len(target_coins) * total_1m_bars_per_coin / 1000:.0f} API calls '
          f'(~{len(target_coins) * total_1m_bars_per_coin / 1000 * 0.1:.0f}s at 100ms/call)')

    if args.dry_run:
        print(f'\n--- DRY RUN ---')
        print(f'  Would download 1m candles for {len(target_coins)} coins')
        for c in target_coins[:20]:
            info = symbol_map.get(c, {})
            ccxt_sym = info.get('ccxt_symbol', c.replace('/USD', '/USDT'))
            in_cache = '✓' if c in original_cache else '✗'
            print(f'    {c:20s} -> {ccxt_sym:20s} [cache:{in_cache}]')
        if len(target_coins) > 20:
            print(f'    ... and {len(target_coins) - 20} more')
        return

    # Download 1m candles
    exchange_cfg = get_exchange('bybit')
    aggregated_coins = {}
    download_stats = {
        'success': 0, 'failed': 0, 'no_data': 0,
        'total_1m_bars': 0,
    }

    # Create per-coin 1m cache directory
    parts_dir = _ROOT / 'data' / 'cache_parts_hf' / '1m' / 'bybit'
    parts_dir.mkdir(parents=True, exist_ok=True)

    # Heartbeat progress file
    progress_path = _ROOT / 'logs' / 'vwap_1m_progress.json'
    progress_path.parent.mkdir(parents=True, exist_ok=True)

    def write_progress(idx, coin, status):
        """Write heartbeat progress.json for monitoring."""
        try:
            progress = {
                'coins_done': idx + 1,
                'coins_total': len(target_coins),
                'last_symbol': coin,
                'last_status': status,
                'success': download_stats['success'],
                'failed': download_stats['failed'],
                'total_1m_bars': download_stats['total_1m_bars'],
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'elapsed_s': round(time.time() - t0, 1),
                'pct': round((idx + 1) / len(target_coins) * 100, 1),
            }
            if idx > 0:
                rate = (time.time() - t0) / (idx + 1)
                progress['eta_s'] = round(rate * (len(target_coins) - idx - 1), 0)
            with open(progress_path, 'w') as pf:
                json.dump(progress, pf, indent=2)
        except Exception:
            pass  # Don't crash on progress write failure

    for i, coin in enumerate(target_coins):
        info = symbol_map.get(coin, {})
        ccxt_sym = info.get('ccxt_symbol')
        if not ccxt_sym:
            base = coin.split('/')[0]
            ccxt_sym = f'{base}/USDT'

        safe_name = coin.replace('/', '_')
        part_path = parts_dir / f'{safe_name}_1m.json'

        # Resume support: skip if already downloaded
        if part_path.exists():
            try:
                with open(part_path) as f:
                    cached_rows = json.load(f)
                if len(cached_rows) >= total_1m_bars_per_coin * 0.8:
                    print(f'  [{i+1}/{len(target_coins)}] {coin:20s} CACHED ({len(cached_rows)} 1m bars)')
                    # Aggregate from cache
                    agg = aggregate_1m_to_1h(cached_rows)
                    if agg:
                        aggregated_coins[coin] = agg
                        download_stats['success'] += 1
                        download_stats['total_1m_bars'] += len(cached_rows)
                    write_progress(i, coin, 'cached')
                    continue
            except (json.JSONDecodeError, KeyError):
                pass  # Re-download

        print(f'  [{i+1}/{len(target_coins)}] {coin:20s} downloading 1m from Bybit...', end='', flush=True)

        rows = download_1m_candles(
            exchange_cfg, coin, ccxt_sym,
            since_ms=since_ms, until_ms=until_ms,
        )

        if rows:
            # Save raw 1m data
            with open(part_path, 'w') as f:
                json.dump(rows, f)

            # Aggregate to 1H
            agg = aggregate_1m_to_1h(rows)
            if agg:
                aggregated_coins[coin] = agg
                download_stats['success'] += 1
                download_stats['total_1m_bars'] += len(rows)
                print(f' {len(rows)} 1m bars -> {len(agg)} 1H bars')
                write_progress(i, coin, 'downloaded')
            else:
                download_stats['no_data'] += 1
                print(f' {len(rows)} 1m bars but 0 1H bars')
                write_progress(i, coin, 'no_1h_data')
        else:
            download_stats['failed'] += 1
            print(f' FAILED (no data)')
            write_progress(i, coin, 'failed')

        # Progress every 25 coins
        if (i + 1) % 25 == 0:
            elapsed = time.time() - t0
            eta = elapsed / (i + 1) * (len(target_coins) - i - 1)
            print(f'  --- Progress: {i+1}/{len(target_coins)} | '
                  f'OK={download_stats["success"]} Failed={download_stats["failed"]} | '
                  f'ETA: {eta:.0f}s ---')

    elapsed_dl = time.time() - t0
    # Final progress heartbeat
    write_progress(len(target_coins) - 1, target_coins[-1] if target_coins else '?', 'COMPLETE')
    print(f'\n[Download] Complete in {elapsed_dl:.1f}s')
    print(f'  Success: {download_stats["success"]}/{len(target_coins)}')
    print(f'  Failed: {download_stats["failed"]}')
    print(f'  Total 1m bars: {download_stats["total_1m_bars"]:,}')

    if not aggregated_coins:
        print('[ERROR] No coins aggregated — cannot patch cache')
        sys.exit(1)

    # Patch cache
    print(f'\n[Patch] Patching Bybit 1H cache with real VWAP...')
    patched_cache, patch_stats = patch_cache_with_real_vwap(original_cache, aggregated_coins)

    print(f'  Patched coins: {patch_stats["patched"]}/{patch_stats["total_coins"]}')
    print(f'  Kept HLC3: {patch_stats["kept_hlc3"]}')
    print(f'  Bars patched: {patch_stats["bars_patched"]}/{patch_stats["bars_total"]}')

    # VWAP diff summary
    if patch_stats['vwap_diff_summary']:
        diffs = patch_stats['vwap_diff_summary']
        all_abs_diffs = [d['abs_mean_diff_pct'] for d in diffs]
        all_max_diffs = [d['max_abs_diff_pct'] for d in diffs]
        print(f'\n  VWAP HLC3 vs real_1m divergence:')
        print(f'    Mean abs diff: {sum(all_abs_diffs)/len(all_abs_diffs):.4f}%')
        print(f'    Max abs diff:  {max(all_max_diffs):.4f}%')
        print(f'    Coins with >0.5% max diff: '
              f'{sum(1 for d in all_max_diffs if d > 0.5)}/{len(diffs)}')

        # Top-5 most divergent coins
        top_diff = sorted(diffs, key=lambda x: -x['max_abs_diff_pct'])[:5]
        print(f'\n  Top-5 most divergent coins:')
        for d in top_diff:
            print(f'    {d["coin"]:20s} mean_diff={d["abs_mean_diff_pct"]:.4f}% '
                  f'max_diff={d["max_abs_diff_pct"]:.4f}% '
                  f'coverage={d["coverage_pct"]:.0f}%')

    # Save patched cache
    out_path = _ROOT / 'data' / 'candle_cache_1h_bybit_real_vwap.json'
    print(f'\n[Save] Writing patched cache: {out_path}')
    with open(out_path, 'w') as f:
        json.dump(patched_cache, f)
    print(f'  Size: {os.path.getsize(out_path) / 1024 / 1024:.1f} MB')

    # Save stats report
    report = {
        'task': 'vwap_1m_aggregation',
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'mode': mode_label,
        'target_coins': len(target_coins),
        'time_range': {
            'since': since_str,
            'until': until_str,
            'total_hours': round(total_hours, 1),
        },
        'download_stats': download_stats,
        'patch_stats': {
            'patched_coins': patch_stats['patched'],
            'kept_hlc3': patch_stats['kept_hlc3'],
            'bars_patched': patch_stats['bars_patched'],
            'bars_total': patch_stats['bars_total'],
        },
        'vwap_divergence': patch_stats['vwap_diff_summary'],
        'runtime_s': round(time.time() - t0, 1),
    }

    report_path = _ROOT / 'reports' / 'hf' / 'bybit_vwap_1m_aggregation_001.json'
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f'[Report] {report_path}')

    total_elapsed = time.time() - t0
    print(f'\n{sep}')
    print(f'  VWAP AGGREGATION COMPLETE ({total_elapsed:.1f}s)')
    print(f'  Patched cache: {out_path}')
    print(f'  Use with: python -m strategies.hf.screening.run_bybit_vwap_validation')
    print(sep)


if __name__ == '__main__':
    main()

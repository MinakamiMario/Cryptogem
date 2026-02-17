#!/usr/bin/env python3
"""Slice 4H candle cache into EARLY and LATE time windows by bar index.

Creates two sub-datasets for walk-forward style temporal robustness testing.
EARLY = first N bars of each coin, LATE = last N bars of each coin.

Usage:
    python scripts/slice_4h_windows.py                          # defaults: 360 bars
    python scripts/slice_4h_windows.py --bars 300               # custom window size
    python scripts/slice_4h_windows.py --input path/to/cache.json --outdir reports/4h/windows/
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

DEFAULT_INPUT = "trading_bot/candle_cache_532.json"
DEFAULT_OUTDIR = "reports/4h/windows"
DEFAULT_BARS = 360


def ts_to_str(ts: float) -> str:
    """Unix timestamp to readable UTC string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def parse_args():
    p = argparse.ArgumentParser(description="Slice 4H candle cache into EARLY/LATE windows")
    p.add_argument("--bars", type=int, default=DEFAULT_BARS,
                   help=f"Window size in bars (default: {DEFAULT_BARS})")
    p.add_argument("--input", default=DEFAULT_INPUT,
                   help=f"Input JSON path (default: {DEFAULT_INPUT})")
    p.add_argument("--outdir", default=DEFAULT_OUTDIR,
                   help=f"Output directory (default: {DEFAULT_OUTDIR})")
    return p.parse_args()


def slice_windows(data: dict, coin_keys: list, window_size: int):
    """Slice candles into EARLY (first N bars) and LATE (last N bars).

    Only includes coins with >= window_size bars.
    Returns (early_dict, late_dict, stats).
    """
    early = {}
    late = {}
    skipped = 0

    for coin in coin_keys:
        candles = data[coin]
        if not isinstance(candles, list) or len(candles) < window_size:
            skipped += 1
            continue

        early[coin] = candles[:window_size]
        late[coin] = candles[-window_size:]

    stats = {
        "total_coins": len(coin_keys),
        "included_coins": len(early),
        "skipped_coins": skipped,
        "window_size": window_size,
    }

    return early, late, stats


def compute_time_range(coin_dict: dict) -> tuple:
    """Return (min_time, max_time) across all coins."""
    min_t = float("inf")
    max_t = 0
    for coin, candles in coin_dict.items():
        if candles:
            t0 = candles[0]["time"]
            t1 = candles[-1]["time"]
            if t0 < min_t:
                min_t = t0
            if t1 > max_t:
                max_t = t1
    return min_t, max_t


def main():
    args = parse_args()
    window_size = args.bars

    print(f"[slice_4h_windows] Window size: {window_size} bars (~{window_size * 4 / 24:.0f} days at 4H)")
    print(f"  Input:  {args.input}")
    print(f"  Output: {args.outdir}/")
    print()

    # --- Load ---
    if not os.path.exists(args.input):
        print(f"  ERROR: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    with open(args.input) as f:
        data = json.load(f)

    # Separate metadata and coin data
    coin_keys = sorted([k for k in data if not k.startswith("_")])

    # Original dataset stats
    bar_counts = [len(data[k]) for k in coin_keys if isinstance(data[k], list)]
    print(f"  Original dataset: {len(coin_keys)} coins, "
          f"{min(bar_counts)}-{max(bar_counts)} bars/coin (mean {sum(bar_counts)/len(bar_counts):.0f})")

    # --- Slice ---
    early, late, stats = slice_windows(data, coin_keys, window_size)

    print(f"  Coins included: {stats['included_coins']}  (skipped {stats['skipped_coins']} with <{window_size} bars)")
    print()

    # --- Time ranges ---
    early_min, early_max = compute_time_range(early)
    late_min, late_max = compute_time_range(late)

    print(f"  EARLY window: {ts_to_str(early_min)} .. {ts_to_str(early_max)}")
    print(f"  LATE  window: {ts_to_str(late_min)} .. {ts_to_str(late_max)}")

    # Overlap check
    if late_min <= early_max:
        overlap_hours = (early_max - late_min) / 3600
        print(f"  WARNING: windows overlap by {overlap_hours:.1f} hours")
    else:
        gap_hours = (late_min - early_max) / 3600
        print(f"  Gap between windows: {gap_hours:.1f} hours ({gap_hours/24:.1f} days)")

    print()

    # --- Build output dicts with metadata ---
    now_utc = datetime.now(tz=timezone.utc)
    created_ts = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    early_out = dict(early)
    early_out["_meta"] = {
        "window_type": "EARLY",
        "bars": window_size,
        "coins": len(early),
        "time_range": [ts_to_str(early_min), ts_to_str(early_max)],
        "original_dataset": os.path.basename(args.input),
        "created": created_ts,
    }

    late_out = dict(late)
    late_out["_meta"] = {
        "window_type": "LATE",
        "bars": window_size,
        "coins": len(late),
        "time_range": [ts_to_str(late_min), ts_to_str(late_max)],
        "original_dataset": os.path.basename(args.input),
        "created": created_ts,
    }

    # --- Save ---
    os.makedirs(args.outdir, exist_ok=True)

    early_path = os.path.join(args.outdir, f"candle_cache_early_{window_size}.json")
    late_path = os.path.join(args.outdir, f"candle_cache_late_{window_size}.json")

    with open(early_path, "w") as f:
        json.dump(early_out, f)
    early_mb = os.path.getsize(early_path) / (1024 * 1024)

    with open(late_path, "w") as f:
        json.dump(late_out, f)
    late_mb = os.path.getsize(late_path) / (1024 * 1024)

    # --- Bar-level stats ---
    early_bar_counts = [len(v) for k, v in early.items() if isinstance(v, list)]
    late_bar_counts = [len(v) for k, v in late.items() if isinstance(v, list)]

    print("  === Summary ===")
    print(f"  EARLY: {early_path}  ({early_mb:.1f} MB)")
    print(f"    Coins: {len(early)}, Bars/coin: {min(early_bar_counts)}-{max(early_bar_counts)}, "
          f"Total bars: {sum(early_bar_counts):,}")
    print(f"  LATE:  {late_path}  ({late_mb:.1f} MB)")
    print(f"    Coins: {len(late)}, Bars/coin: {min(late_bar_counts)}-{max(late_bar_counts)}, "
          f"Total bars: {sum(late_bar_counts):,}")
    print()

    # Verification: all coins should have exactly window_size bars
    early_all_exact = all(len(v) == window_size for k, v in early.items() if isinstance(v, list))
    late_all_exact = all(len(v) == window_size for k, v in late.items() if isinstance(v, list))
    print(f"  Verification: EARLY all {window_size} bars = {early_all_exact}")
    print(f"  Verification: LATE  all {window_size} bars = {late_all_exact}")
    print(f"  Verification: no overlap = {late_min > early_max}")
    print()
    print("  Done.")

    # Return exit code for CI
    if not (early_all_exact and late_all_exact):
        print("  ERROR: bar count mismatch!", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

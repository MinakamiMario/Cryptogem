#!/usr/bin/env python3
"""Slice candle cache JSON to a date range.

Examples:
    # Last 60 days (default)
    python scripts/slice_candles.py

    # Last 30 days
    python scripts/slice_candles.py --days 30

    # Specific date range
    python scripts/slice_candles.py --start 2026-01-01 --end 2026-02-01

    # Custom input/output
    python scripts/slice_candles.py --days 45 --input trading_bot/candle_cache_532.json --output data/slice_45d.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

AMS = ZoneInfo("Europe/Amsterdam")

DEFAULT_INPUT = "trading_bot/candle_cache_532.json"
MIN_BARS_AFTER_SLICE = 10


def parse_args():
    p = argparse.ArgumentParser(description="Slice candle cache to a date range")
    p.add_argument("--days", type=int, default=60,
                   help="Keep last N days of data (default: 60)")
    p.add_argument("--input", default=DEFAULT_INPUT,
                   help=f"Input JSON path (default: {DEFAULT_INPUT})")
    p.add_argument("--output", default=None,
                   help="Output JSON path (default: data/candle_cache_last{N}d.json)")
    p.add_argument("--start", default=None,
                   help="Start date YYYY-MM-DD (overrides --days)")
    p.add_argument("--end", default=None,
                   help="End date YYYY-MM-DD (overrides --days)")
    return p.parse_args()


def date_to_ts(date_str: str) -> float:
    """Parse YYYY-MM-DD to unix timestamp (start of day, Amsterdam tz)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=AMS)
    return dt.timestamp()


def ts_to_str(ts: float) -> str:
    """Unix timestamp to readable string in Amsterdam tz."""
    return datetime.fromtimestamp(ts, tz=AMS).strftime("%Y-%m-%d %H:%M %Z")


def main():
    args = parse_args()
    now_ams = datetime.now(tz=AMS)

    print(f"[slice_candles] {now_ams.strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"  Input:  {args.input}")

    # --- Load ---
    if not os.path.exists(args.input):
        print(f"  ERROR: input file not found: {args.input}")
        sys.exit(1)

    with open(args.input) as f:
        data = json.load(f)

    # Separate metadata and coin data
    meta_keys = {k for k in data if k.startswith("_")}
    coin_keys = [k for k in data if k not in meta_keys]

    # Find global latest timestamp across all coins
    global_max_ts = 0
    global_min_ts = float("inf")
    total_bars_in = 0
    for coin in coin_keys:
        candles = data[coin]
        if not isinstance(candles, list) or len(candles) == 0:
            continue
        coin_max = max(c["time"] for c in candles)
        coin_min = min(c["time"] for c in candles)
        if coin_max > global_max_ts:
            global_max_ts = coin_max
        if coin_min < global_min_ts:
            global_min_ts = coin_min
        total_bars_in += len(candles)

    print(f"  Coins in file: {len(coin_keys)}")
    print(f"  Total bars in: {total_bars_in:,}")
    print(f"  Data range:    {ts_to_str(global_min_ts)} .. {ts_to_str(global_max_ts)}")

    # --- Determine cutoff timestamps ---
    if args.start or args.end:
        # Explicit date range
        cutoff_start = date_to_ts(args.start) if args.start else 0
        cutoff_end = date_to_ts(args.end) if args.end else float("inf")
        label = f"{args.start or 'earliest'}..{args.end or 'latest'}"
    else:
        # Last N days from the latest data point
        cutoff_end = float("inf")
        cutoff_start = global_max_ts - (args.days * 86400)
        label = f"last {args.days} days"

    print(f"  Slice mode:    {label}")
    print(f"  Cutoff:        {ts_to_str(cutoff_start)}"
          + (f" .. {ts_to_str(cutoff_end)}" if cutoff_end < float("inf") else " .. end"))

    # --- Slice ---
    sliced = {}
    total_bars_out = 0
    coins_skipped = 0
    slice_min_ts = float("inf")
    slice_max_ts = 0

    for coin in coin_keys:
        candles = data[coin]
        if not isinstance(candles, list):
            continue

        filtered = [c for c in candles if cutoff_start <= c["time"] <= cutoff_end]

        if len(filtered) < MIN_BARS_AFTER_SLICE:
            coins_skipped += 1
            continue

        sliced[coin] = filtered
        total_bars_out += len(filtered)

        f_min = filtered[0]["time"]
        f_max = filtered[-1]["time"]
        if f_min < slice_min_ts:
            slice_min_ts = f_min
        if f_max > slice_max_ts:
            slice_max_ts = f_max

    # --- Update metadata ---
    sliced["_timestamp"] = now_ams.timestamp()
    sliced["_date"] = now_ams.strftime("%Y-%m-%d %H:%M %Z")
    sliced["_coins"] = len([k for k in sliced if not k.startswith("_")])

    # --- Output path ---
    if args.output:
        out_path = args.output
    else:
        if args.start or args.end:
            tag = f"{args.start or 'start'}_{args.end or 'end'}".replace("-", "")
            out_path = f"data/candle_cache_{tag}.json"
        else:
            out_path = f"data/candle_cache_last{args.days}d.json"

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(sliced, f)

    file_size_mb = os.path.getsize(out_path) / (1024 * 1024)

    # --- Summary ---
    print()
    print("  === Summary ===")
    print(f"  Coins retained: {sliced['_coins']}  (skipped {coins_skipped} with <{MIN_BARS_AFTER_SLICE} bars)")
    print(f"  Bars:  {total_bars_in:,} -> {total_bars_out:,}  ({total_bars_out/max(total_bars_in,1)*100:.1f}%)")
    if total_bars_out > 0:
        avg_bars = total_bars_out / sliced["_coins"]
        print(f"  Avg bars/coin:  {avg_bars:.0f}")
        print(f"  Sliced range:   {ts_to_str(slice_min_ts)} .. {ts_to_str(slice_max_ts)}")
    print(f"  Output: {out_path}  ({file_size_mb:.1f} MB)")
    print("  Done.")


if __name__ == "__main__":
    main()

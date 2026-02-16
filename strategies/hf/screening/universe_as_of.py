#!/usr/bin/env python3
"""
Universe-as-of utilities for HF screening framework.
=====================================================
Provide point-in-time universe snapshots to detect survivorship bias and
universe drift over the data window.

Functions:
  - get_universe_at_bar(): which coins are tradeable at a specific bar?
  - compare_with_static_universe(): Jaccard similarity vs a fixed coin set
  - get_universe_timeline(): sequence of snapshots at regular intervals
  - survivorship_scan(): find short-lived or zero-vol-tail coins
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple


BARS_PER_DAY = 24
BARS_PER_WEEK = 168


def _coin_bar_stats(candles: list) -> dict:
    """Compute basic stats for a single coin candle array."""
    n = len(candles)
    if n == 0:
        return {"n": 0, "zero_vol_tail": 0, "first_ts": None, "last_ts": None}

    # Count trailing zero-volume bars
    zero_vol_tail = 0
    for i in range(n - 1, -1, -1):
        c = candles[i]
        vol = c.get("volume", c.get("v", 0)) or 0
        if vol == 0:
            zero_vol_tail += 1
        else:
            break

    first_ts = candles[0].get("timestamp", candles[0].get("t", None))
    last_ts = candles[-1].get("timestamp", candles[-1].get("t", None))

    return {
        "n": n,
        "zero_vol_tail": zero_vol_tail,
        "first_ts": first_ts,
        "last_ts": last_ts,
    }


def get_universe_at_bar(
    data: dict,
    bar: int,
    warmup: int = 50,
    max_zero_vol: int = 48,
    volume_pctl: float = 0.25,
) -> dict:
    """
    Determine which coins are available/tradeable at a given bar index.

    A coin is AVAILABLE at bar if:
      1. It has at least warmup candles before bar
      2. It has data up to at least bar
      3. It does not have a trailing zero-volume run >= max_zero_vol ending
         at or before bar

    Args:
        data: candle_cache dict {coin: [candle_dicts]}
        bar: the bar index to evaluate
        warmup: minimum bars of history required
        max_zero_vol: max consecutive zero-volume bars allowed at tail
        volume_pctl: volume percentile threshold (informational only)

    Returns:
        dict with universe snapshot at this bar
    """
    available = []
    short_history = []
    zero_vol = []
    no_data_at_bar = []

    for coin, candles in data.items():
        if coin.startswith("_"):
            continue
        n = len(candles)

        # Must have data up to the bar
        if n <= bar:
            no_data_at_bar.append(coin)
            continue

        # Must have enough warmup
        if bar < warmup:
            short_history.append(coin)
            continue

        # Check trailing zero-volume up to this bar
        zvt = 0
        for i in range(bar, max(bar - max_zero_vol - 1, -1), -1):
            c = candles[i]
            vol = c.get("volume", c.get("v", 0)) or 0
            if vol == 0:
                zvt += 1
            else:
                break

        if zvt >= max_zero_vol:
            zero_vol.append(coin)
            continue

        available.append(coin)

    return {
        "bar": bar,
        "available_coins": sorted(available),
        "n_available": len(available),
        "excluded_short_history": sorted(short_history),
        "excluded_zero_vol": sorted(zero_vol),
        "excluded_no_data_at_bar": sorted(no_data_at_bar),
        "total_in_data": sum(1 for k in data if not k.startswith("_")),
    }


def compare_with_static_universe(
    data: dict,
    static_coins: set,
    bar: int,
    warmup: int = 50,
    max_zero_vol: int = 48,
) -> dict:
    """
    Compare the point-in-time universe at bar with a static coin set.

    Returns Jaccard similarity, overlap stats, and asymmetric diffs.
    """
    snap = get_universe_at_bar(data, bar, warmup=warmup, max_zero_vol=max_zero_vol)
    available = set(snap["available_coins"])
    static = set(static_coins)

    intersection = available & static
    union = available | static
    jaccard = len(intersection) / len(union) if union else 0.0

    return {
        "bar": bar,
        "jaccard": round(jaccard, 4),
        "n_available": len(available),
        "n_static": len(static),
        "n_intersection": len(intersection),
        "n_union": len(union),
        "only_in_available": sorted(available - static),
        "only_in_static": sorted(static - available),
    }


def get_universe_timeline(
    data: dict,
    step: int = 168,
    warmup: int = 50,
    max_zero_vol: int = 48,
) -> list:
    """
    Build a timeline of universe snapshots at regular intervals.

    Args:
        data: candle_cache dict
        step: bar interval between snapshots (default 168 = 1 week)
        warmup: warmup bars for get_universe_at_bar
        max_zero_vol: zero-vol threshold

    Returns:
        list of dicts with bar index and universe stats per snapshot
    """
    max_bars = 0
    for coin, candles in data.items():
        if coin.startswith("_"):
            continue
        if len(candles) > max_bars:
            max_bars = len(candles)

    if max_bars == 0:
        return []

    snapshots = []
    bar = warmup
    while bar < max_bars:
        snap = get_universe_at_bar(data, bar, warmup=warmup, max_zero_vol=max_zero_vol)
        snapshots.append({
            "bar": bar,
            "week": round((bar - warmup) / BARS_PER_WEEK, 1),
            "n_available": snap["n_available"],
            "n_excluded_no_data": len(snap["excluded_no_data_at_bar"]),
            "n_excluded_zero_vol": len(snap["excluded_zero_vol"]),
            "n_excluded_short": len(snap["excluded_short_history"]),
        })
        bar += step

    return snapshots


def survivorship_scan(data: dict, min_bars: int = 200, max_zero_vol_tail: int = 48) -> dict:
    """
    Scan all coins for survivorship bias indicators.

    Returns dict with short_lived, zero_vol_tail, and healthy coin lists.
    """
    short_lived = []
    zero_vol_coins = []
    healthy = []

    for coin, candles in data.items():
        if coin.startswith("_"):
            continue
        stats = _coin_bar_stats(candles)
        n = stats["n"]
        zvt = stats["zero_vol_tail"]

        issues = []
        if n < min_bars:
            short_lived.append({"coin": coin, "bars": n})
            issues.append("short")
        if zvt >= max_zero_vol_tail:
            zero_vol_coins.append({"coin": coin, "bars": n, "zero_vol_tail": zvt})
            issues.append("zero_vol")
        if not issues:
            healthy.append(coin)

    return {
        "short_lived": sorted(short_lived, key=lambda x: x["bars"]),
        "zero_vol_tail": sorted(zero_vol_coins, key=lambda x: -x["zero_vol_tail"]),
        "healthy": sorted(healthy),
        "n_short": len(short_lived),
        "n_zero_vol": len(zero_vol_coins),
        "n_healthy": len(healthy),
        "total": len(short_lived) + len(zero_vol_coins) + len(healthy),
    }

#!/usr/bin/env python3
"""
build_tradeable_cache.py - Objective tradeability filter for Cryptogem research cache.

Reads data/candle_cache_research_all.json (2091 coins), applies 6 data-quality
filters, and writes data/candle_cache_tradeable.json + reports/tradeable_filter.md.

Filters (ALL must pass):
  1. Min coverage:     >=685 bars out of 721 (>=95%)
  2. Max gap rate:     <=2% of intervals are gaps (>1.5x expected)
  3. Min median volume: median(close*volume) > $100
  4. ATR% band:        0.2% <= median_atr_pct <= 8.0%
  5. No flatlines:     longest identical-close streak < 20
  6. Price sanity:     no candles with close <= 0

Usage:
    python3 scripts/build_tradeable_cache.py
"""

import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

AMS = ZoneInfo("Europe/Amsterdam")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SOURCE_CACHE = DATA_DIR / "candle_cache_research_all.json"
OUTPUT_CACHE = DATA_DIR / "candle_cache_tradeable.json"
LIVE_CACHE = ROOT / "trading_bot" / "candle_cache_532.json"
REPORT_PATH = ROOT / "reports" / "tradeable_filter.md"

# ---------------------------------------------------------------------------
# Filter thresholds
# ---------------------------------------------------------------------------
MAX_BARS = 721
MIN_BARS = 685
MAX_GAP_RATE = 0.02
EXPECTED_INTERVAL = 14400
GAP_THRESHOLD = EXPECTED_INTERVAL * 1.5
MIN_MEDIAN_VOLUME_USD = 100
ATR_PCT_MIN = 0.2
ATR_PCT_MAX = 8.0
ATR_PERIOD = 14
MAX_FLATLINE_STREAK = 20


def filter_coverage(candles):
    """Filter 1: minimum bar coverage."""
    n = len(candles)
    return n >= MIN_BARS, n


def filter_gaps(candles):
    """Filter 2: max gap rate."""
    if len(candles) < 2:
        return False, 1.0
    gaps = 0
    for i in range(1, len(candles)):
        dt = candles[i]["time"] - candles[i - 1]["time"]
        if dt > GAP_THRESHOLD:
            gaps += 1
    rate = gaps / (len(candles) - 1)
    return rate <= MAX_GAP_RATE, rate


def filter_volume(candles):
    """Filter 3: minimum median dollar volume."""
    volumes_usd = []
    for c in candles:
        vol = c.get("volume", 0) or 0
        close = c.get("close", 0) or 0
        volumes_usd.append(close * vol)
    if not volumes_usd:
        return False, 0.0
    med = median(volumes_usd)
    return med > MIN_MEDIAN_VOLUME_USD, med


def filter_atr_band(candles):
    """Filter 4: ATR% must be in [0.2%, 8.0%]."""
    if len(candles) < ATR_PERIOD + 1:
        return False, 0.0
    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    atr_pcts = []
    for i in range(ATR_PERIOD - 1, len(trs)):
        window = trs[i - ATR_PERIOD + 1 : i + 1]
        atr = sum(window) / ATR_PERIOD
        close = candles[i + 1]["close"]
        if close > 0:
            atr_pcts.append((atr / close) * 100)
    if not atr_pcts:
        return False, 0.0
    med_atr_pct = median(atr_pcts)
    return ATR_PCT_MIN <= med_atr_pct <= ATR_PCT_MAX, med_atr_pct


def filter_flatline(candles):
    """Filter 5: no extreme flatlines (identical close streak < 20)."""
    if not candles:
        return False, 0
    max_streak = 1
    streak = 1
    for i in range(1, len(candles)):
        if candles[i]["close"] == candles[i - 1]["close"]:
            streak += 1
            if streak > max_streak:
                max_streak = streak
        else:
            streak = 1
    return max_streak < MAX_FLATLINE_STREAK, max_streak


def filter_price_sanity(candles):
    """Filter 6: no candles with close <= 0."""
    bad = sum(1 for c in candles if (c.get("close", 0) or 0) <= 0)
    return bad == 0, bad


def main():
    t0 = time.time()

    print(f"Loading {SOURCE_CACHE} ...")
    with open(SOURCE_CACHE) as f:
        data = json.load(f)

    meta_sources = data.get("_sources", [])
    coin_keys = sorted(k for k in data.keys() if not k.startswith("_"))
    total_coins = len(coin_keys)
    print(f"  {total_coins} coins loaded in {time.time()-t0:.1f}s")

    live_coins = set()
    if LIVE_CACHE.exists():
        with open(LIVE_CACHE) as f:
            live_data = json.load(f)
        live_coins = set(k for k in live_data.keys() if not k.startswith("_"))
        del live_data
        print(f"  LIVE_CURRENT: {len(live_coins)} coins")

    print("\nApplying 6 tradeability filters ...")

    FILTER_NAMES = ["1_coverage", "2_gap_rate", "3_volume", "4_atr_band", "5_flatline", "6_price_sanity"]

    passed_coins = []
    rejected_coins = []
    filter_rejections = Counter()
    coin_stats = {}

    for idx, coin in enumerate(coin_keys):
        if (idx + 1) % 500 == 0:
            print(f"  ... processed {idx+1}/{total_coins} coins")
        candles = data[coin]
        stats = {}

        ok1, n_bars = filter_coverage(candles)
        stats["bars"] = n_bars
        if not ok1: filter_rejections["1_coverage"] += 1

        ok2, gap_rate = filter_gaps(candles)
        stats["gap_rate"] = gap_rate
        if not ok2: filter_rejections["2_gap_rate"] += 1

        ok3, med_vol = filter_volume(candles)
        stats["median_vol_usd"] = med_vol
        if not ok3: filter_rejections["3_volume"] += 1

        ok4, med_atr = filter_atr_band(candles)
        stats["median_atr_pct"] = med_atr
        if not ok4: filter_rejections["4_atr_band"] += 1

        ok5, max_streak = filter_flatline(candles)
        stats["max_flatline"] = max_streak
        if not ok5: filter_rejections["5_flatline"] += 1

        ok6, bad_prices = filter_price_sanity(candles)
        stats["bad_prices"] = bad_prices
        if not ok6: filter_rejections["6_price_sanity"] += 1

        all_pass = ok1 and ok2 and ok3 and ok4 and ok5 and ok6
        stats["passed"] = all_pass
        failed = []
        if not ok1: failed.append("1_coverage")
        if not ok2: failed.append("2_gap_rate")
        if not ok3: failed.append("3_volume")
        if not ok4: failed.append("4_atr_band")
        if not ok5: failed.append("5_flatline")
        if not ok6: failed.append("6_price_sanity")
        stats["failed_filters"] = failed

        coin_stats[coin] = stats
        if all_pass:
            passed_coins.append(coin)
        else:
            rejected_coins.append(coin)

    n_passed = len(passed_coins)
    n_rejected = len(rejected_coins)
    print(f"  Passed: {n_passed} | Rejected: {n_rejected} | Total: {total_coins}")

    print(f"\nBuilding tradeable cache ...")
    now = datetime.now(AMS)
    tradeable_cache = {
        "_timestamp": time.time(),
        "_date": now.strftime("%Y-%m-%d %H:%M CET"),
        "_universe": "tradeable",
        "_sources": meta_sources,
        "_coins": n_passed,
    }
    for coin in sorted(passed_coins):
        tradeable_cache[coin] = data[coin]

    del data

    print(f"Writing {OUTPUT_CACHE} ...")
    with open(OUTPUT_CACHE, "w") as f:
        json.dump(tradeable_cache, f)
    size_mb = os.path.getsize(OUTPUT_CACHE) / (1024 * 1024)
    print(f"  Written: {size_mb:.1f} MB")

    passed_set = set(passed_coins)
    overlap = live_coins & passed_set
    added = passed_set - live_coins
    lost = live_coins - passed_set

    def get_exchange(coin):
        return "kraken" if coin in live_coins else "mexc"

    rejected_exchanges = Counter()
    for coin in rejected_coins:
        rejected_exchanges[get_exchange(coin)] += 1

    lost_details = []
    for coin in sorted(lost):
        s = coin_stats.get(coin, {})
        lost_details.append({
            "coin": coin, "reasons": s.get("failed_filters", []),
            "bars": s.get("bars", 0), "gap_rate": s.get("gap_rate", 0),
            "median_vol_usd": s.get("median_vol_usd", 0),
            "median_atr_pct": s.get("median_atr_pct", 0),
            "max_flatline": s.get("max_flatline", 0),
            "bad_prices": s.get("bad_prices", 0),
        })

    added_details = []
    for coin in sorted(added):
        s = coin_stats.get(coin, {})
        added_details.append({
            "coin": coin, "bars": s.get("bars", 0),
            "median_vol_usd": s.get("median_vol_usd", 0),
            "median_atr_pct": s.get("median_atr_pct", 0),
            "max_flatline": s.get("max_flatline", 0),
        })
    added_details.sort(key=lambda x: x["median_vol_usd"], reverse=True)

    progressive = []
    remaining = set(coin_keys)
    for fname in FILTER_NAMES:
        removed = set()
        for coin in remaining:
            if fname in coin_stats[coin].get("failed_filters", []):
                removed.add(coin)
        remaining -= removed
        progressive.append({"filter": fname, "rejected": len(removed), "remaining": len(remaining)})

    print(f"\nWriting report to {REPORT_PATH} ...")
    write_report(total_coins, n_passed, n_rejected, filter_rejections, progressive,
                 len(live_coins), overlap, added, lost, lost_details, added_details,
                 rejected_exchanges, size_mb, time.time() - t0, live_coins, total_coins)

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"  TRADEABLE FILTER SUMMARY")
    print(f"{'='*60}")
    print(f"  Source:     {total_coins} coins")
    print(f"  Passed:     {n_passed} coins ({n_passed/total_coins*100:.1f}%)")
    print(f"  Rejected:   {n_rejected} coins ({n_rejected/total_coins*100:.1f}%)")
    print(f"  Output:     {OUTPUT_CACHE}")
    print(f"  Size:       {size_mb:.1f} MB")
    print()
    print(f"  Per-filter rejections (non-exclusive):")
    for fname in FILTER_NAMES:
        cnt = filter_rejections.get(fname, 0)
        print(f"    {fname:20s} -> {cnt:5d} coins rejected")
    print()
    print(f"  LIVE_CURRENT overlap:")
    print(f"    In both:    {len(overlap)} / {len(live_coins)} live coins")
    print(f"    Added new:  {len(added)} coins")
    print(f"    Lost:       {len(lost)} live coins filtered out")
    print()
    print(f"  Rejected by exchange:")
    for ex, cnt in sorted(rejected_exchanges.items()):
        print(f"    {ex:10s} -> {cnt}")
    print()
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"{'='*60}")


def write_report(total_coins, n_passed, n_rejected, filter_rejections, progressive,
                 live_count, overlap, added, lost, lost_details, added_details,
                 rejected_exchanges, size_mb, elapsed, live_coins, total_coins_count):
    lines = []
    a = lines.append

    a("# Tradeable Filter Report")
    a("")
    a(f"**Generated**: {datetime.now(AMS).strftime('%Y-%m-%d %H:%M CET')}")
    a(f"**Source**: `data/candle_cache_research_all.json` ({total_coins} coins)")
    a(f"**Output**: `data/candle_cache_tradeable.json` ({n_passed} coins, {size_mb:.1f} MB)")
    a(f"**Runtime**: {elapsed:.1f}s")
    a("")
    a("---")
    a("")

    a("## Filter Summary")
    a("")
    a("| # | Filter | Threshold | Coins Rejected | % of Total |")
    a("|---|--------|-----------|---------------:|----------:|")

    FNAMES = ["1_coverage", "2_gap_rate", "3_volume", "4_atr_band", "5_flatline", "6_price_sanity"]
    THRESHOLDS = {
        "1_coverage": f">={MIN_BARS} bars (>=95%)",
        "2_gap_rate": f"<={MAX_GAP_RATE*100:.0f}% gaps",
        "3_volume": f"median vol > ${MIN_MEDIAN_VOLUME_USD}",
        "4_atr_band": f"{ATR_PCT_MIN}% <= ATR% <= {ATR_PCT_MAX}%",
        "5_flatline": f"streak < {MAX_FLATLINE_STREAK} candles",
        "6_price_sanity": "close > 0",
    }
    for i, fname in enumerate(FNAMES, 1):
        cnt = filter_rejections.get(fname, 0)
        pct = cnt / total_coins * 100
        threshold = THRESHOLDS.get(fname, "")
        a(f"| {i} | {fname} | {threshold} | {cnt} | {pct:.1f}% |")
    a("")
    a(f"**Total unique coins rejected**: {n_rejected} ({n_rejected/total_coins*100:.1f}%)")
    a(f"**Total coins passed**: {n_passed} ({n_passed/total_coins*100:.1f}%)")
    a("")

    a("### Progressive Filter Application (sequential)")
    a("")
    a("| Step | Filter | Removed This Step | Remaining |")
    a("|------|--------|------------------:|----------:|")
    for i, p in enumerate(progressive, 1):
        a(f"| {i} | {p['filter']} | {p['rejected']} | {p['remaining']} |")
    a("")

    a("---")
    a("")
    a("## Overlap with LIVE_CURRENT (532 cache)")
    a("")
    a("```")
    a(f"  LIVE_CURRENT ({live_count} coins)")
    a(f"  +-----------------------------+")
    a(f"  |  Lost: {len(lost):4d}                |")
    a(f"  |         +--------------------+-----------------+")
    a(f"  |         | Overlap: {len(overlap):4d}     |                 |")
    a(f"  |         |                    |  Added: {len(added):4d}    |")
    a(f"  +---------+--------------------+                 |")
    a(f"            |          TRADEABLE ({n_passed} coins)     |")
    a(f"            +--------------------------------------+")
    a("```")
    a("")
    a(f"- **Overlap**: {len(overlap)} coins appear in both LIVE_CURRENT and tradeable")
    a(f"- **Added**: {len(added)} new coins passed all filters (not in LIVE_CURRENT)")
    a(f"- **Lost**: {len(lost)} LIVE_CURRENT coins failed tradeability filters")
    a("")

    a("---")
    a("")
    a("## Rejected Coins by Exchange")
    a("")
    a("| Exchange | Rejected | Exchange Total (est.) | % Rejected |")
    a("|----------|----------:|---------------------:|----------:|")
    kraken_in_research = len(live_coins)
    mexc_in_research = total_coins_count - kraken_in_research
    for ex in ["kraken", "mexc"]:
        cnt = rejected_exchanges.get(ex, 0)
        ex_total = kraken_in_research if ex == "kraken" else mexc_in_research
        pct = cnt / ex_total * 100 if ex_total > 0 else 0
        a(f"| {ex} | {cnt} | {ex_total} | {pct:.1f}% |")
    a("")

    a("---")
    a("")
    a("## Top 20 Notable Coins FILTERED OUT from LIVE_CURRENT")
    a("")
    if lost_details:
        a("| Coin | Failed Filter(s) | Bars | Gap% | Med Vol ($) | ATR% | Flatline | Bad Px |")
        a("|------|-------------------|-----:|-----:|------------:|-----:|---------:|-------:|")
        for d in lost_details[:20]:
            reasons = ", ".join(d["reasons"])
            a(f"| {d['coin']} | {reasons} | {d['bars']} | {d['gap_rate']*100:.1f}% | {d['median_vol_usd']:,.0f} | {d['median_atr_pct']:.2f}% | {d['max_flatline']} | {d['bad_prices']} |")
    else:
        a("*No LIVE_CURRENT coins were filtered out.*")
    a("")

    a("---")
    a("")
    a("## Top 20 Notable Coins ADDED (not in LIVE_CURRENT)")
    a("")
    a("Sorted by median dollar volume (highest first).")
    a("")
    if added_details:
        a("| Coin | Bars | Med Vol ($) | ATR% | Flatline |")
        a("|------|-----:|------------:|-----:|---------:|")
        for d in added_details[:20]:
            a(f"| {d['coin']} | {d['bars']} | {d['median_vol_usd']:,.0f} | {d['median_atr_pct']:.2f}% | {d['max_flatline']} |")
    else:
        a("*No new coins added.*")
    a("")

    a("---")
    a("")
    a("*Report generated by `scripts/build_tradeable_cache.py`*")
    a("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Data Quality Audit for candle_cache_research_all.json
Scores every coin on coverage, gaps, outliers, volume, spacing, price integrity.
Outputs: reports/data_quality.json + reports/data_quality_summary.md
"""

import json
import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

# --- Config ---
RESEARCH_CACHE = Path(__file__).parent.parent / "data" / "candle_cache_research_all.json"
KRAKEN_CACHE   = Path(__file__).parent.parent / "trading_bot" / "candle_cache_532.json"
OUT_JSON       = Path(__file__).parent.parent / "reports" / "data_quality.json"
OUT_MD         = Path(__file__).parent.parent / "reports" / "data_quality_summary.md"

INTERVAL       = 14400          # 4H in seconds
GAP_THRESHOLD  = INTERVAL * 1.5 # 21600s = 6 hours
MAX_BARS       = 721            # expected max bars in dataset
WEIGHTS        = {
    "coverage":  0.30,
    "gaps":      0.25,
    "outliers":  0.15,
    "volume":    0.15,
    "spacing":   0.15,
}


def audit_coin(symbol, candles):
    n = len(candles)
    result = {
        "quality_score": 0.0,
        "bars": n,
        "coverage_pct": round(n / MAX_BARS * 100, 2),
        "gap_count": 0,
        "max_gap_hours": 0.0,
        "outlier_count": 0,
        "zero_vol_bars": 0,
        "longest_flat_streak": 0,
        "spacing_stdev": 0.0,
        "price_issues": 0,
        "issues": [],
    }

    if n < 2:
        result["issues"].append("too_few_bars")
        return result

    times = [c["time"] for c in candles]
    intervals = [times[i+1] - times[i] for i in range(n - 1)]

    coverage_score = min(n / MAX_BARS, 1.0)

    gap_count = 0
    max_gap_s = 0
    for iv in intervals:
        if iv > GAP_THRESHOLD:
            gap_count += 1
            max_gap_s = max(max_gap_s, iv)
    result["gap_count"] = gap_count
    result["max_gap_hours"] = round(max_gap_s / 3600, 1)
    gap_score = 1.0 - min(gap_count / 20, 1.0)

    outlier_count = 0
    for c in candles:
        close = c["close"]
        if close and close != 0:
            wick_ratio = (c["high"] - c["low"]) / abs(close)
            if wick_ratio > 0.5:
                outlier_count += 1
    result["outlier_count"] = outlier_count
    outlier_score = 1.0 - min(outlier_count / 10, 1.0)

    zero_vol = 0
    cur_streak = 0
    max_streak = 0
    for c in candles:
        vol = c.get("volume", 0)
        if vol is None or vol < 1e-10:
            zero_vol += 1
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0
    result["zero_vol_bars"] = zero_vol
    result["longest_flat_streak"] = max_streak
    volume_score = 1.0 - min(zero_vol / max(n, 1), 1.0)

    if len(intervals) > 1:
        stdev = statistics.stdev(intervals)
    else:
        stdev = 0.0
    result["spacing_stdev"] = round(stdev, 1)
    if stdev < 7200:
        spacing_score = 1.0
    else:
        spacing_score = max(0.0, 1.0 - stdev / 72000)

    price_issues = 0
    for c in candles:
        for field in ("open", "high", "low", "close"):
            v = c.get(field)
            if v is None:
                price_issues += 1
            elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                price_issues += 1
            elif v <= 0:
                price_issues += 1
    result["price_issues"] = price_issues

    if coverage_score < 0.5:
        result["issues"].append("low_coverage ({:.0f}%)".format(result["coverage_pct"]))
    if gap_count > 5:
        result["issues"].append("many_gaps ({})".format(gap_count))
    if result["max_gap_hours"] > 48:
        result["issues"].append("large_gap ({}h)".format(result["max_gap_hours"]))
    if outlier_count > 3:
        result["issues"].append("outlier_wicks ({})".format(outlier_count))
    if max_streak > 20:
        result["issues"].append("flat_volume_streak ({})".format(max_streak))
    if zero_vol > n * 0.1:
        result["issues"].append("high_zero_vol ({}/{})".format(zero_vol, n))
    if stdev > 14400:
        result["issues"].append("irregular_spacing (stdev={:.0f}s)".format(stdev))
    if price_issues > 0:
        result["issues"].append("price_integrity ({})".format(price_issues))

    score = (
        WEIGHTS["coverage"]  * coverage_score  +
        WEIGHTS["gaps"]      * gap_score        +
        WEIGHTS["outliers"]  * outlier_score    +
        WEIGHTS["volume"]    * volume_score     +
        WEIGHTS["spacing"]   * spacing_score
    ) * 100

    if price_issues > 0:
        score *= max(0.5, 1.0 - price_issues / (n * 4))

    result["quality_score"] = round(score, 1)
    return result


def main():
    t0 = time.time()

    print("Loading {} ...".format(RESEARCH_CACHE.name))
    with open(RESEARCH_CACHE) as f:
        data = json.load(f)

    kraken_coins = set()
    if KRAKEN_CACHE.exists():
        with open(KRAKEN_CACHE) as f:
            kdata = json.load(f)
        kraken_coins = {k for k in kdata if not k.startswith("_")}
        print("Loaded {} Kraken coins for comparison".format(len(kraken_coins)))

    coin_keys = [k for k in data if not k.startswith("_")]
    print("Auditing {} coins ...".format(len(coin_keys)))

    coins_result = {}
    for sym in coin_keys:
        coins_result[sym] = audit_coin(sym, data[sym])

    scores = [v["quality_score"] for v in coins_result.values()]
    n = len(scores)

    avg_q   = statistics.mean(scores)
    med_q   = statistics.median(scores)
    min_q   = min(scores)
    max_q   = max(scores)
    below_30 = sum(1 for s in scores if s < 30)
    below_50 = sum(1 for s in scores if s < 50)
    below_70 = sum(1 for s in scores if s < 70)

    brackets = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
    for s in scores:
        if s < 20:
            brackets["0-20"] += 1
        elif s < 40:
            brackets["20-40"] += 1
        elif s < 60:
            brackets["40-60"] += 1
        elif s < 80:
            brackets["60-80"] += 1
        else:
            brackets["80-100"] += 1

    kraken_scores = [v["quality_score"] for k, v in coins_result.items() if k in kraken_coins]
    mexc_scores   = [v["quality_score"] for k, v in coins_result.items() if k not in kraken_coins]

    summary = {
        "avg_quality":    round(avg_q, 1),
        "median_quality": round(med_q, 1),
        "min_quality":    round(min_q, 1),
        "max_quality":    round(max_q, 1),
        "below_50":       below_50,
        "below_30":       below_30,
        "brackets":       brackets,
    }

    sorted_coins = dict(sorted(coins_result.items(), key=lambda x: x[1]["quality_score"]))

    report = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "total_coins": len(coin_keys),
        "summary": summary,
        "coins": sorted_coins,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote {} ({:.0f} KB)".format(OUT_JSON, OUT_JSON.stat().st_size / 1024))

    # --- Write Markdown ---
    worst_50 = list(sorted_coins.items())[:50]

    bar_max = max(brackets.values())
    hist_lines = []
    for bracket, count in brackets.items():
        bar_len = int(count / bar_max * 40) if bar_max > 0 else 0
        hist_lines.append("  {:>6}: {} {}".format(bracket, chr(9608) * bar_len, count))

    kr_avg = round(statistics.mean(kraken_scores), 1) if kraken_scores else 0
    kr_med = round(statistics.median(kraken_scores), 1) if kraken_scores else 0
    mx_avg = round(statistics.mean(mexc_scores), 1) if mexc_scores else 0
    mx_med = round(statistics.median(mexc_scores), 1) if mexc_scores else 0
    kr_below50 = sum(1 for s in kraken_scores if s < 50)
    mx_below50 = sum(1 for s in mexc_scores if s < 50)

    filter_30 = sum(1 for s in scores if s < 30)
    filter_50 = sum(1 for s in scores if s < 50)
    filter_70 = sum(1 for s in scores if s < 70)
    remain_30 = n - filter_30
    remain_50 = n - filter_50
    remain_70 = n - filter_70

    hist_block = "\n".join(hist_lines)

    offender_rows = []
    for i, (sym, info) in enumerate(worst_50, 1):
        issues_str = ", ".join(info["issues"][:3]) if info["issues"] else "-"
        offender_rows.append(
            "| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
                i, sym, info["quality_score"], info["bars"],
                info["gap_count"], info["max_gap_hours"], info["outlier_count"],
                info["zero_vol_bars"], info["longest_flat_streak"], issues_str
            )
        )
    offender_table = "\n".join(offender_rows)

    md = "# Data Quality Audit Report\n\n"
    md += "**Generated**: {}\n".format(report["generated"])
    md += "**Dataset**: `{}`\n".format(RESEARCH_CACHE.name)
    md += "**Coins audited**: {}\n\n".format(n)
    md += "---\n\n"
    md += "## Overview\n\n"
    md += "| Metric | Value |\n"
    md += "|--------|-------|\n"
    md += "| Average quality | {:.1f} |\n".format(avg_q)
    md += "| Median quality | {:.1f} |\n".format(med_q)
    md += "| Min quality | {:.1f} |\n".format(min_q)
    md += "| Max quality | {:.1f} |\n".format(max_q)
    md += "| Below 50 | {} ({:.1f}%) |\n".format(below_50, below_50/n*100)
    md += "| Below 30 | {} ({:.1f}%) |\n\n".format(below_30, below_30/n*100)
    md += "## Quality Distribution\n\n"
    md += "```\n{}\n```\n\n".format(hist_block)
    md += "| Bracket | Count | Percentage |\n"
    md += "|---------|-------|------------|\n"
    for bname in ["0-20", "20-40", "40-60", "60-80", "80-100"]:
        md += "| {} | {} | {:.1f}% |\n".format(bname, brackets[bname], brackets[bname]/n*100)
    md += "\n## Kraken vs MEXC Comparison\n\n"
    md += "| Metric | Kraken ({} coins) | MEXC ({} coins) |\n".format(len(kraken_scores), len(mexc_scores))
    md += "|--------|------|------|\n"
    md += "| Avg quality | {} | {} |\n".format(kr_avg, mx_avg)
    md += "| Median quality | {} | {} |\n".format(kr_med, mx_med)
    md += "| Below 50 | {} ({:.1f}%) | {} ({:.1f}%) |\n\n".format(
        kr_below50, kr_below50/max(len(kraken_scores),1)*100,
        mx_below50, mx_below50/max(len(mexc_scores),1)*100)
    md += "## Filtering Recommendations\n\n"
    md += "| Threshold | Filtered out | Remaining | % kept |\n"
    md += "|-----------|-------------|-----------|--------|\n"
    md += "| < 30 | {} | {} | {:.1f}% |\n".format(filter_30, remain_30, remain_30/n*100)
    md += "| < 50 | {} | {} | {:.1f}% |\n".format(filter_50, remain_50, remain_50/n*100)
    md += "| < 70 | {} | {} | {:.1f}% |\n\n".format(filter_70, remain_70, remain_70/n*100)
    md += "## Top 50 Worst Offenders\n\n"
    md += "| # | Coin | Score | Bars | Gaps | MaxGap(h) | Outliers | ZeroVol | FlatStreak | Issues |\n"
    md += "|---|------|-------|------|------|-----------|----------|---------|------------|--------|\n"
    md += offender_table + "\n\n"
    md += "---\n\n"
    md += "## Scoring Methodology\n\n"
    md += "Each coin is scored 0-100 based on weighted components:\n\n"
    md += "- **Coverage** (30%): `bars / {}` -- how many of the expected bars are present\n".format(MAX_BARS)
    md += "- **Gaps** (25%): `1 - min(gap_count / 20, 1)` -- penalizes missing time segments (>{:.1f}h threshold)\n".format(GAP_THRESHOLD/3600)
    md += "- **Outliers** (15%): `1 - min(outlier_count / 10, 1)` -- penalizes extreme wick spikes (>50% of close)\n"
    md += "- **Volume** (15%): `1 - zero_vol_bars / total_bars` -- penalizes zero-volume candles\n"
    md += "- **Spacing** (15%): stdev of candle intervals; perfect if <2h stdev, degrades beyond that\n\n"
    md += "Price integrity issues (zero/negative/NaN prices) apply an additional hard penalty.\n"

    with open(OUT_MD, "w") as f:
        f.write(md)
    print("Wrote {}".format(OUT_MD))

    elapsed = time.time() - t0
    print("")
    print("Done in {:.1f}s".format(elapsed))
    print("  Avg quality:    {:.1f}".format(avg_q))
    print("  Median quality: {:.1f}".format(med_q))
    print("  Below 50:       {} / {}".format(below_50, n))
    print("  Below 30:       {} / {}".format(below_30, n))
    print("  Kraken avg:     {}  |  MEXC avg: {}".format(kr_avg, mx_avg))


if __name__ == "__main__":
    main()

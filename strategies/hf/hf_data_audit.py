#!/usr/bin/env python3
"""
HF Data Audit — 4H variant research data integrity check.

Audits candle data for bar counts, gaps, duplicates, OHLCV integrity,
volume anomalies, and cross-symbol statistics.

Usage:
    python strategies/hf/hf_data_audit.py
    python strategies/hf/hf_data_audit.py --universe tradeable
    python strategies/hf/hf_data_audit.py --universe live

Outputs:
    reports/hf/data_audit_001.json  — full audit results (machine-readable)
    reports/hf/data_audit_001.md    — human-readable summary
"""

import sys
import json
import argparse
import statistics
from pathlib import Path
from datetime import datetime
from collections import Counter

# --- Path setup ---
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRADING_BOT = REPO_ROOT / "trading_bot"

# --- Constants ---
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"

DATA_FILES = {
    "tradeable": DATA_DIR / "candle_cache_tradeable.json",
    "live": DATA_DIR / "candle_cache_532.json",
}

# Thresholds
MIN_BARS_THRESHOLD = 700
ZERO_VOL_PCT_THRESHOLD = 50.0
VOL_SPIKE_MULT = 100.0
CONSECUTIVE_ZERO_VOL_ALERT = 10
EXPECTED_INTERVAL_4H = 4 * 3600  # 4 hours in seconds


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(universe: str) -> tuple:
    """Load candle data and return (data_dict, sorted_coins, path_str)."""
    path = DATA_FILES.get(universe)
    if path is None or not path.exists():
        path = TRADING_BOT / "candle_cache_532.json"
    if not path.exists():
        print(f"ERROR: No data file found for universe={universe}")
        print(f"  Tried: {DATA_FILES.get(universe, 'N/A')}")
        print(f"  Tried: {path}")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins, str(path)


# ---------------------------------------------------------------------------
# Per-symbol audit checks
# ---------------------------------------------------------------------------

def audit_bar_counts(candles_by_symbol: dict, coins: list) -> dict:
    """Check bar counts per symbol. Flag short or outlier series."""
    bar_counts = {sym: len(candles_by_symbol[sym]) for sym in coins}
    counts_list = list(bar_counts.values())
    if not counts_list:
        return {"bar_counts": {}, "median": 0, "min": 0, "max": 0, "flags": []}

    med = statistics.median(counts_list)
    mn = min(counts_list)
    mx = max(counts_list)

    flags = []
    for sym, cnt in bar_counts.items():
        if cnt < MIN_BARS_THRESHOLD:
            flags.append({
                "symbol": sym,
                "issue": "low_bar_count",
                "bars": cnt,
                "threshold": MIN_BARS_THRESHOLD,
            })
        # Flag if >10% deviation from median
        if med > 0 and abs(cnt - med) / med > 0.10:
            flags.append({
                "symbol": sym,
                "issue": "bar_count_deviation",
                "bars": cnt,
                "median": med,
                "deviation_pct": round(100 * abs(cnt - med) / med, 1),
            })

    return {
        "bar_counts": bar_counts,
        "median": med,
        "min": mn,
        "max": mx,
        "flags": flags,
    }


def _extract_timestamps(candles: list) -> list:
    """Extract numeric timestamps from candles. Returns empty if no ts field."""
    ts_list = []
    for c in candles:
        ts = c.get("timestamp") or c.get("ts") or c.get("time") or c.get("t")
        if ts is not None:
            try:
                ts_list.append(float(ts))
            except (ValueError, TypeError):
                pass
    return ts_list


def audit_gaps(candles: list, symbol: str) -> list:
    """Check for timestamp gaps (missing bars). Returns list of flag dicts."""
    ts_list = _extract_timestamps(candles)
    if len(ts_list) < 2:
        return []

    ts_sorted = sorted(ts_list)
    # Detect expected interval from the most common diff
    diffs = [ts_sorted[i + 1] - ts_sorted[i] for i in range(len(ts_sorted) - 1)]
    if not diffs:
        return []

    diff_counter = Counter(int(d) for d in diffs if d > 0)
    if not diff_counter:
        return []

    expected_interval = diff_counter.most_common(1)[0][0]
    # Use detected interval if reasonable, otherwise fall back to 4H
    if expected_interval <= 0:
        expected_interval = EXPECTED_INTERVAL_4H

    flags = []
    gap_count = 0
    for i in range(len(ts_sorted) - 1):
        diff = ts_sorted[i + 1] - ts_sorted[i]
        if diff > expected_interval * 1.5:
            gap_count += 1
            missing_bars = int(round(diff / expected_interval)) - 1
            if gap_count <= 5:  # Only store first 5 gap details
                flags.append({
                    "symbol": symbol,
                    "issue": "timestamp_gap",
                    "after_index": i,
                    "gap_seconds": int(diff),
                    "expected_seconds": expected_interval,
                    "missing_bars_approx": missing_bars,
                })

    if gap_count > 5:
        flags.append({
            "symbol": symbol,
            "issue": "timestamp_gap_summary",
            "total_gaps": gap_count,
            "note": f"First 5 shown, {gap_count - 5} more omitted",
        })

    return flags


def audit_duplicate_timestamps(candles: list, symbol: str) -> list:
    """Check for duplicate timestamps per symbol."""
    ts_list = _extract_timestamps(candles)
    if not ts_list:
        return []

    ts_counter = Counter(ts_list)
    dupes = {ts: cnt for ts, cnt in ts_counter.items() if cnt > 1}
    if not dupes:
        return []

    flags = [{
        "symbol": symbol,
        "issue": "duplicate_timestamps",
        "count": len(dupes),
        "total_duplicate_entries": sum(dupes.values()) - len(dupes),
        "examples": list(dupes.keys())[:5],
    }]
    return flags


def audit_ohlcv_integrity(candles: list, symbol: str) -> list:
    """Validate OHLCV data integrity per candle."""
    flags = []
    violation_counts = {
        "high_below_open_close": 0,
        "low_above_open_close": 0,
        "negative_volume": 0,
        "zero_close": 0,
        "negative_price": 0,
    }

    for i, c in enumerate(candles):
        o = c.get("open", 0)
        h = c.get("high", 0)
        l = c.get("low", 0)
        cl = c.get("close", 0)
        v = c.get("volume", 0)

        # high >= max(open, close)
        if h < max(o, cl):
            violation_counts["high_below_open_close"] += 1

        # low <= min(open, close)
        if l > min(o, cl):
            violation_counts["low_above_open_close"] += 1

        # volume >= 0
        if v < 0:
            violation_counts["negative_volume"] += 1

        # No zero-close (divide-by-zero risk)
        if cl == 0:
            violation_counts["zero_close"] += 1

        # No negative prices
        if any(p < 0 for p in [o, h, l, cl]):
            violation_counts["negative_price"] += 1

    total_violations = sum(violation_counts.values())
    if total_violations > 0:
        flags.append({
            "symbol": symbol,
            "issue": "ohlcv_violations",
            "total_violations": total_violations,
            "breakdown": {k: v for k, v in violation_counts.items() if v > 0},
            "candle_count": len(candles),
        })

    return flags


def audit_volume_anomalies(candles: list, symbol: str) -> list:
    """Check for volume anomalies: zero-volume bars, extended zero periods, spikes."""
    flags = []
    if not candles:
        return flags

    volumes = [c.get("volume", 0) for c in candles]
    n = len(volumes)

    # --- Zero-volume percentage ---
    zero_vol_count = sum(1 for v in volumes if v == 0)
    zero_vol_pct = 100.0 * zero_vol_count / n if n > 0 else 0.0

    if zero_vol_pct > ZERO_VOL_PCT_THRESHOLD:
        flags.append({
            "symbol": symbol,
            "issue": "high_zero_volume_pct",
            "zero_vol_bars": zero_vol_count,
            "total_bars": n,
            "zero_vol_pct": round(zero_vol_pct, 1),
            "threshold_pct": ZERO_VOL_PCT_THRESHOLD,
        })

    # --- Consecutive zero-volume runs (possible delisting) ---
    max_run = 0
    current_run = 0
    run_start_idx = 0
    worst_run_start = 0

    for i, v in enumerate(volumes):
        if v == 0:
            if current_run == 0:
                run_start_idx = i
            current_run += 1
        else:
            if current_run > max_run:
                max_run = current_run
                worst_run_start = run_start_idx
            current_run = 0

    # Check final run
    if current_run > max_run:
        max_run = current_run
        worst_run_start = run_start_idx

    if max_run >= CONSECUTIVE_ZERO_VOL_ALERT:
        flags.append({
            "symbol": symbol,
            "issue": "consecutive_zero_volume",
            "max_consecutive_bars": max_run,
            "starts_at_index": worst_run_start,
            "possible_delisting": max_run > n * 0.1,
        })

    # --- Extreme volume spikes (>100x median) ---
    nonzero_volumes = [v for v in volumes if v > 0]
    if len(nonzero_volumes) >= 10:
        vol_median = statistics.median(nonzero_volumes)
        if vol_median > 0:
            spike_count = 0
            spike_examples = []
            for i, v in enumerate(volumes):
                if v > vol_median * VOL_SPIKE_MULT:
                    spike_count += 1
                    if len(spike_examples) < 3:
                        spike_examples.append({
                            "index": i,
                            "volume": v,
                            "median": round(vol_median, 2),
                            "multiple": round(v / vol_median, 1),
                        })

            if spike_count > 0:
                flags.append({
                    "symbol": symbol,
                    "issue": "extreme_volume_spike",
                    "spike_count": spike_count,
                    "vol_median": round(vol_median, 2),
                    "threshold_mult": VOL_SPIKE_MULT,
                    "examples": spike_examples,
                })

    return flags


# ---------------------------------------------------------------------------
# Cross-symbol aggregate stats
# ---------------------------------------------------------------------------

def compute_cross_symbol_stats(
    candles_by_symbol: dict,
    coins: list,
    bar_audit: dict,
) -> dict:
    """Compute universe-wide aggregate statistics."""
    bar_counts = bar_audit["bar_counts"]
    counts_list = list(bar_counts.values())

    if not counts_list:
        return {
            "total_symbols": 0,
            "median_bars": 0,
            "min_bars": 0,
            "max_bars": 0,
            "full_coverage_pct": 0.0,
        }

    median_bars = bar_audit["median"]
    full_coverage = sum(1 for c in counts_list if c >= median_bars)
    full_pct = round(100.0 * full_coverage / len(counts_list), 1) if counts_list else 0.0

    # Universe-wide volume distribution
    all_volumes = []
    for sym in coins:
        for c in candles_by_symbol[sym]:
            v = c.get("volume", 0)
            if v > 0:
                all_volumes.append(v)

    vol_stats = {}
    if all_volumes:
        all_volumes_sorted = sorted(all_volumes)
        n = len(all_volumes_sorted)
        vol_stats = {
            "total_nonzero_candles": n,
            "volume_p10": round(all_volumes_sorted[int(n * 0.10)], 2),
            "volume_p25": round(all_volumes_sorted[int(n * 0.25)], 2),
            "volume_median": round(statistics.median(all_volumes_sorted), 2),
            "volume_p75": round(all_volumes_sorted[int(n * 0.75)], 2),
            "volume_p90": round(all_volumes_sorted[int(n * 0.90)], 2),
            "volume_p99": round(all_volumes_sorted[min(int(n * 0.99), n - 1)], 2),
            "volume_max": round(max(all_volumes_sorted), 2),
        }

    return {
        "total_symbols": len(coins),
        "median_bars": median_bars,
        "min_bars": bar_audit["min"],
        "max_bars": bar_audit["max"],
        "full_coverage_pct": full_pct,
        "bar_count_stdev": round(statistics.stdev(counts_list), 1) if len(counts_list) > 1 else 0.0,
        "volume_distribution": vol_stats,
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_json_report(
    data_path: str,
    universe: str,
    cross_stats: dict,
    all_flags: list,
    per_symbol_issues: dict,
    ohlcv_violation_total: int,
    zero_vol_symbol_count: int,
    vol_anomaly_symbol_count: int,
) -> dict:
    """Build the full JSON audit report."""
    return {
        "timestamp": datetime.now().isoformat(),
        "label": "4H variant research \u2014 data audit",
        "data_file": data_path,
        "universe": universe,
        "summary": {
            "total_symbols": cross_stats["total_symbols"],
            "median_bars": cross_stats["median_bars"],
            "min_bars": cross_stats["min_bars"],
            "max_bars": cross_stats["max_bars"],
            "full_coverage_pct": cross_stats["full_coverage_pct"],
            "ohlcv_violations": ohlcv_violation_total,
            "zero_volume_symbols": zero_vol_symbol_count,
            "volume_anomaly_symbols": vol_anomaly_symbol_count,
        },
        "cross_symbol_stats": cross_stats,
        "flags": all_flags,
        "per_symbol_issues": per_symbol_issues,
    }


def generate_markdown_report(report: dict) -> str:
    """Build a human-readable markdown summary from the JSON report."""
    s = report["summary"]
    lines = [
        "# HF Data Audit — 4H Variant Research",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Universe**: {report['universe']}",
        f"**Data file**: `{Path(report['data_file']).name}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total symbols | {s['total_symbols']} |",
        f"| Median bars | {s['median_bars']} |",
        f"| Min bars | {s['min_bars']} |",
        f"| Max bars | {s['max_bars']} |",
        f"| Full coverage % | {s['full_coverage_pct']}% |",
        f"| OHLCV violations | {s['ohlcv_violations']} |",
        f"| Zero-volume symbols (>{ZERO_VOL_PCT_THRESHOLD}%) | {s['zero_volume_symbols']} |",
        f"| Volume anomaly symbols | {s['volume_anomaly_symbols']} |",
        "",
    ]

    # Volume distribution
    vol_dist = report.get("cross_symbol_stats", {}).get("volume_distribution", {})
    if vol_dist:
        lines.extend([
            "## Volume Distribution (non-zero candles)",
            "",
            "| Percentile | Volume |",
            "|------------|--------|",
            f"| P10 | {vol_dist.get('volume_p10', 'N/A'):,.2f} |",
            f"| P25 | {vol_dist.get('volume_p25', 'N/A'):,.2f} |",
            f"| Median | {vol_dist.get('volume_median', 'N/A'):,.2f} |",
            f"| P75 | {vol_dist.get('volume_p75', 'N/A'):,.2f} |",
            f"| P90 | {vol_dist.get('volume_p90', 'N/A'):,.2f} |",
            f"| P99 | {vol_dist.get('volume_p99', 'N/A'):,.2f} |",
            f"| Max | {vol_dist.get('volume_max', 'N/A'):,.2f} |",
            "",
        ])

    # Flags section
    flags = report.get("flags", [])
    if flags:
        # Group flags by issue type
        issue_groups = {}
        for f in flags:
            issue_type = f.get("issue", "unknown")
            issue_groups.setdefault(issue_type, []).append(f)

        lines.extend([
            "## Flags",
            "",
            f"**Total flags**: {len(flags)}",
            "",
        ])

        for issue_type, items in sorted(issue_groups.items()):
            lines.append(f"### {issue_type.replace('_', ' ').title()} ({len(items)} flags)")
            lines.append("")

            if issue_type == "low_bar_count":
                lines.append("| Symbol | Bars | Threshold |")
                lines.append("|--------|------|-----------|")
                for item in sorted(items, key=lambda x: x.get("bars", 0)):
                    lines.append(
                        f"| {item['symbol']} | {item['bars']} | {item['threshold']} |"
                    )
                lines.append("")

            elif issue_type == "bar_count_deviation":
                lines.append("| Symbol | Bars | Median | Deviation% |")
                lines.append("|--------|------|--------|------------|")
                for item in sorted(items, key=lambda x: -x.get("deviation_pct", 0))[:20]:
                    lines.append(
                        f"| {item['symbol']} | {item['bars']} "
                        f"| {item['median']} | {item['deviation_pct']}% |"
                    )
                if len(items) > 20:
                    lines.append(f"| ... | ({len(items) - 20} more) | | |")
                lines.append("")

            elif issue_type == "ohlcv_violations":
                lines.append("| Symbol | Total Violations | Details |")
                lines.append("|--------|-----------------|---------|")
                for item in sorted(items, key=lambda x: -x.get("total_violations", 0))[:15]:
                    detail = ", ".join(
                        f"{k}={v}" for k, v in item.get("breakdown", {}).items()
                    )
                    lines.append(
                        f"| {item['symbol']} | {item['total_violations']} | {detail} |"
                    )
                if len(items) > 15:
                    lines.append(f"| ... | ({len(items) - 15} more) | |")
                lines.append("")

            elif issue_type == "high_zero_volume_pct":
                lines.append("| Symbol | Zero-Vol Bars | Total | Pct |")
                lines.append("|--------|--------------|-------|-----|")
                for item in sorted(items, key=lambda x: -x.get("zero_vol_pct", 0)):
                    lines.append(
                        f"| {item['symbol']} | {item['zero_vol_bars']} "
                        f"| {item['total_bars']} | {item['zero_vol_pct']}% |"
                    )
                lines.append("")

            elif issue_type == "consecutive_zero_volume":
                lines.append("| Symbol | Max Consecutive | Start Index | Delisting? |")
                lines.append("|--------|----------------|-------------|------------|")
                for item in sorted(items, key=lambda x: -x.get("max_consecutive_bars", 0)):
                    lines.append(
                        f"| {item['symbol']} | {item['max_consecutive_bars']} "
                        f"| {item['starts_at_index']} "
                        f"| {'YES' if item.get('possible_delisting') else 'no'} |"
                    )
                lines.append("")

            elif issue_type == "extreme_volume_spike":
                lines.append("| Symbol | Spikes | Median Vol | Example Multiple |")
                lines.append("|--------|--------|-----------|-----------------|")
                for item in sorted(items, key=lambda x: -x.get("spike_count", 0))[:15]:
                    ex = item.get("examples", [{}])[0]
                    mult = ex.get("multiple", "N/A")
                    lines.append(
                        f"| {item['symbol']} | {item['spike_count']} "
                        f"| {item['vol_median']:,.0f} | {mult}x |"
                    )
                if len(items) > 15:
                    lines.append(f"| ... | ({len(items) - 15} more) | | |")
                lines.append("")

            elif issue_type == "duplicate_timestamps":
                lines.append("| Symbol | Duplicate TS Count | Extra Entries |")
                lines.append("|--------|--------------------|---------------|")
                for item in sorted(items, key=lambda x: -x.get("count", 0)):
                    lines.append(
                        f"| {item['symbol']} | {item['count']} "
                        f"| {item['total_duplicate_entries']} |"
                    )
                lines.append("")

            elif issue_type in ("timestamp_gap", "timestamp_gap_summary"):
                lines.append("| Symbol | Gap (s) | Expected (s) | Missing Bars |")
                lines.append("|--------|---------|-------------|-------------|")
                for item in items[:15]:
                    if item["issue"] == "timestamp_gap":
                        lines.append(
                            f"| {item['symbol']} | {item['gap_seconds']:,} "
                            f"| {item['expected_seconds']:,} "
                            f"| ~{item['missing_bars_approx']} |"
                        )
                    else:
                        lines.append(
                            f"| {item['symbol']} | (summary) | | "
                            f"{item['total_gaps']} total gaps |"
                        )
                lines.append("")

            else:
                # Generic rendering
                for item in items[:10]:
                    lines.append(f"- `{item['symbol']}`: {item}")
                lines.append("")

    else:
        lines.extend([
            "## Flags",
            "",
            "No data integrity flags found. All checks passed.",
            "",
        ])

    # Top issues per symbol
    per_sym = report.get("per_symbol_issues", {})
    if per_sym:
        # Sort by number of issues descending
        sorted_syms = sorted(per_sym.items(), key=lambda x: -len(x[1]))
        top_n = 10

        lines.extend([
            "## Top Issue Symbols",
            "",
            f"Showing top {min(top_n, len(sorted_syms))} symbols by issue count.",
            "",
            "| Symbol | Issues | Types |",
            "|--------|--------|-------|",
        ])

        for sym, issues in sorted_syms[:top_n]:
            types = set(iss.get("issue", "?") for iss in issues)
            lines.append(f"| {sym} | {len(issues)} | {', '.join(sorted(types))} |")
        lines.append("")

    lines.extend([
        "---",
        f"*Generated by `hf_data_audit.py` at {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="HF Data Audit — 4H variant research data integrity check"
    )
    parser.add_argument(
        "--universe",
        choices=["tradeable", "live"],
        default="tradeable",
        help="Which candle cache to audit (default: tradeable)",
    )
    args = parser.parse_args()

    print(f"=== HF Data Audit (universe={args.universe}) ===")
    print(f"  Label: 4H variant research — data audit")

    # 1. Load data
    data, coins, data_path = load_data(args.universe)
    print(f"  Loaded {len(coins)} symbols from {Path(data_path).name}")

    candles_by_symbol = {sym: data[sym] for sym in coins}

    # 2. Bar count audit
    print("  [1/5] Checking bar counts...")
    bar_audit = audit_bar_counts(candles_by_symbol, coins)

    # 3-6. Per-symbol audits
    all_flags = list(bar_audit["flags"])
    per_symbol_issues = {}  # sym -> list of issues
    ohlcv_violation_total = 0
    zero_vol_symbols = set()
    vol_anomaly_symbols = set()

    total = len(coins)
    for idx, sym in enumerate(coins):
        if (idx + 1) % 100 == 0 or idx == 0:
            print(f"  [2-5/5] Auditing symbol {idx + 1}/{total}...")

        candles = candles_by_symbol[sym]
        sym_issues = []

        # Gap detection
        gap_flags = audit_gaps(candles, sym)
        sym_issues.extend(gap_flags)

        # Duplicate timestamps
        dupe_flags = audit_duplicate_timestamps(candles, sym)
        sym_issues.extend(dupe_flags)

        # OHLCV integrity
        ohlcv_flags = audit_ohlcv_integrity(candles, sym)
        for f in ohlcv_flags:
            ohlcv_violation_total += f.get("total_violations", 0)
        sym_issues.extend(ohlcv_flags)

        # Volume anomalies
        vol_flags = audit_volume_anomalies(candles, sym)
        for f in vol_flags:
            if f["issue"] == "high_zero_volume_pct":
                zero_vol_symbols.add(sym)
            if f["issue"] in ("extreme_volume_spike", "consecutive_zero_volume"):
                vol_anomaly_symbols.add(sym)
        sym_issues.extend(vol_flags)

        if sym_issues:
            per_symbol_issues[sym] = sym_issues
            all_flags.extend(sym_issues)

    print(f"  Audited {total} symbols, found {len(all_flags)} flags")

    # 7. Cross-symbol stats
    print("  Computing cross-symbol statistics...")
    cross_stats = compute_cross_symbol_stats(candles_by_symbol, coins, bar_audit)

    # 8. Generate reports
    report = generate_json_report(
        data_path=data_path,
        universe=args.universe,
        cross_stats=cross_stats,
        all_flags=all_flags,
        per_symbol_issues=per_symbol_issues,
        ohlcv_violation_total=ohlcv_violation_total,
        zero_vol_symbol_count=len(zero_vol_symbols),
        vol_anomaly_symbol_count=len(vol_anomaly_symbols),
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    json_path = REPORTS_DIR / "data_audit_001.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  Wrote {json_path}")

    md_path = REPORTS_DIR / "data_audit_001.md"
    md_content = generate_markdown_report(report)
    with open(md_path, "w") as f:
        f.write(md_content)
    print(f"  Wrote {md_path}")

    # 9. Console summary
    print()
    print("=== Audit Summary ===")
    print(f"  Symbols:          {cross_stats['total_symbols']}")
    print(f"  Bar counts:       median={cross_stats['median_bars']}, "
          f"min={cross_stats['min_bars']}, max={cross_stats['max_bars']}")
    print(f"  Full coverage:    {cross_stats['full_coverage_pct']}%")
    print(f"  OHLCV violations: {ohlcv_violation_total}")
    print(f"  Zero-vol symbols: {len(zero_vol_symbols)} (>{ZERO_VOL_PCT_THRESHOLD}% zero bars)")
    print(f"  Vol anomalies:    {len(vol_anomaly_symbols)} symbols")
    print(f"  Total flags:      {len(all_flags)}")

    if per_symbol_issues:
        worst = sorted(per_symbol_issues.items(), key=lambda x: -len(x[1]))[:5]
        print()
        print("  Top flagged symbols:")
        for sym, issues in worst:
            types = set(i.get("issue", "?") for i in issues)
            print(f"    {sym}: {len(issues)} issues ({', '.join(sorted(types))})")

    print()
    print("Done.")


if __name__ == "__main__":
    main()

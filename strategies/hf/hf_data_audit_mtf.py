#!/usr/bin/env python3
"""
HF Data Audit MTF — Multi-timeframe data integrity check for 1H/15m.

Reuses audit logic from hf_data_audit.py with timeframe-aware thresholds.

Usage:
    python strategies/hf/hf_data_audit_mtf.py --timeframe 1h
    python strategies/hf/hf_data_audit_mtf.py --timeframe 15m

Outputs:
    reports/hf/data_audit_1h_001.json  — full audit results
    reports/hf/data_audit_1h_001.md    — human-readable summary
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
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"

# Timeframe-aware thresholds
TF_THRESHOLDS = {
    "1h": {
        "cache_file": DATA_DIR / "candle_cache_1h.json",
        "expected_interval": 3600,     # 1 hour
        "min_bars": 500,               # ~21 days minimum
        "expected_bars": 2880,         # 120 days
        "zero_vol_pct_threshold": 50.0,
        "vol_spike_mult": 100.0,
        "consecutive_zero_vol_alert": 24,  # 1 day of zero vol
    },
    "15m": {
        "cache_file": DATA_DIR / "candle_cache_15m.json",
        "expected_interval": 900,      # 15 minutes
        "min_bars": 2000,              # ~21 days minimum
        "expected_bars": 11520,        # 120 days
        "zero_vol_pct_threshold": 50.0,
        "vol_spike_mult": 100.0,
        "consecutive_zero_vol_alert": 96,  # 1 day of zero vol
    },
    "4h": {
        "cache_file": DATA_DIR / "candle_cache_tradeable.json",
        "expected_interval": 14400,    # 4 hours
        "min_bars": 700,
        "expected_bars": 720,          # 120 days
        "zero_vol_pct_threshold": 50.0,
        "vol_spike_mult": 100.0,
        "consecutive_zero_vol_alert": 10,
    },
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(tf: str) -> tuple:
    """Load candle data for given timeframe."""
    cfg = TF_THRESHOLDS[tf]
    path = cfg["cache_file"]
    if not path.exists():
        print(f"ERROR: No data file found: {path}")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins, str(path)


# ---------------------------------------------------------------------------
# Audit checks (reused from hf_data_audit.py, parameterized)
# ---------------------------------------------------------------------------

def audit_bar_counts(candles_by_symbol: dict, coins: list, min_bars: int) -> dict:
    bar_counts = {sym: len(candles_by_symbol[sym]) for sym in coins}
    counts_list = list(bar_counts.values())
    if not counts_list:
        return {"bar_counts": {}, "median": 0, "min": 0, "max": 0, "flags": []}

    med = statistics.median(counts_list)
    mn = min(counts_list)
    mx = max(counts_list)

    flags = []
    for sym, cnt in bar_counts.items():
        if cnt < min_bars:
            flags.append({"symbol": sym, "issue": "low_bar_count", "bars": cnt, "threshold": min_bars})
        if med > 0 and abs(cnt - med) / med > 0.10:
            flags.append({
                "symbol": sym, "issue": "bar_count_deviation",
                "bars": cnt, "median": med,
                "deviation_pct": round(100 * abs(cnt - med) / med, 1),
            })

    return {"bar_counts": bar_counts, "median": med, "min": mn, "max": mx, "flags": flags}


def _extract_timestamps(candles: list) -> list:
    ts_list = []
    for c in candles:
        ts = c.get("timestamp") or c.get("ts") or c.get("time") or c.get("t")
        if ts is not None:
            try:
                ts_list.append(float(ts))
            except (ValueError, TypeError):
                pass
    return ts_list


def audit_gaps(candles: list, symbol: str, expected_interval: int) -> list:
    ts_list = _extract_timestamps(candles)
    if len(ts_list) < 2:
        return []
    ts_sorted = sorted(ts_list)
    flags = []
    gap_count = 0
    for i in range(len(ts_sorted) - 1):
        diff = ts_sorted[i + 1] - ts_sorted[i]
        if diff > expected_interval * 1.5:
            gap_count += 1
            missing_bars = int(round(diff / expected_interval)) - 1
            if gap_count <= 5:
                flags.append({
                    "symbol": symbol, "issue": "timestamp_gap",
                    "after_index": i, "gap_seconds": int(diff),
                    "expected_seconds": expected_interval,
                    "missing_bars_approx": missing_bars,
                })
    if gap_count > 5:
        flags.append({
            "symbol": symbol, "issue": "timestamp_gap_summary",
            "total_gaps": gap_count, "note": f"First 5 shown, {gap_count - 5} more omitted",
        })
    return flags


def audit_duplicate_timestamps(candles: list, symbol: str) -> list:
    ts_list = _extract_timestamps(candles)
    if not ts_list:
        return []
    ts_counter = Counter(ts_list)
    dupes = {ts: cnt for ts, cnt in ts_counter.items() if cnt > 1}
    if not dupes:
        return []
    return [{
        "symbol": symbol, "issue": "duplicate_timestamps",
        "count": len(dupes), "total_duplicate_entries": sum(dupes.values()) - len(dupes),
        "examples": list(dupes.keys())[:5],
    }]


def audit_ohlcv_integrity(candles: list, symbol: str) -> list:
    violation_counts = {
        "high_below_open_close": 0, "low_above_open_close": 0,
        "negative_volume": 0, "zero_close": 0, "negative_price": 0,
    }
    for c in candles:
        o, h, l, cl = c.get("open", 0), c.get("high", 0), c.get("low", 0), c.get("close", 0)
        v = c.get("volume", 0)
        if h < max(o, cl):
            violation_counts["high_below_open_close"] += 1
        if l > min(o, cl):
            violation_counts["low_above_open_close"] += 1
        if v < 0:
            violation_counts["negative_volume"] += 1
        if cl == 0:
            violation_counts["zero_close"] += 1
        if any(p < 0 for p in [o, h, l, cl]):
            violation_counts["negative_price"] += 1

    total = sum(violation_counts.values())
    if total > 0:
        return [{
            "symbol": symbol, "issue": "ohlcv_violations",
            "total_violations": total,
            "breakdown": {k: v for k, v in violation_counts.items() if v > 0},
            "candle_count": len(candles),
        }]
    return []


def audit_volume_anomalies(candles: list, symbol: str,
                            zero_vol_pct_threshold: float,
                            vol_spike_mult: float,
                            consecutive_zero_vol_alert: int) -> list:
    flags = []
    if not candles:
        return flags

    volumes = [c.get("volume", 0) for c in candles]
    n = len(volumes)

    # Zero-volume percentage
    zero_vol_count = sum(1 for v in volumes if v == 0)
    zero_vol_pct = 100.0 * zero_vol_count / n if n > 0 else 0.0
    if zero_vol_pct > zero_vol_pct_threshold:
        flags.append({
            "symbol": symbol, "issue": "high_zero_volume_pct",
            "zero_vol_bars": zero_vol_count, "total_bars": n,
            "zero_vol_pct": round(zero_vol_pct, 1),
        })

    # Consecutive zero-volume runs
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
    if current_run > max_run:
        max_run = current_run
        worst_run_start = run_start_idx
    if max_run >= consecutive_zero_vol_alert:
        flags.append({
            "symbol": symbol, "issue": "consecutive_zero_volume",
            "max_consecutive_bars": max_run, "starts_at_index": worst_run_start,
            "possible_delisting": max_run > n * 0.1,
        })

    # Extreme volume spikes
    nonzero_volumes = [v for v in volumes if v > 0]
    if len(nonzero_volumes) >= 10:
        vol_median = statistics.median(nonzero_volumes)
        if vol_median > 0:
            spike_count = 0
            spike_examples = []
            for i, v in enumerate(volumes):
                if v > vol_median * vol_spike_mult:
                    spike_count += 1
                    if len(spike_examples) < 3:
                        spike_examples.append({
                            "index": i, "volume": v,
                            "median": round(vol_median, 2),
                            "multiple": round(v / vol_median, 1),
                        })
            if spike_count > 0:
                flags.append({
                    "symbol": symbol, "issue": "extreme_volume_spike",
                    "spike_count": spike_count, "vol_median": round(vol_median, 2),
                    "threshold_mult": vol_spike_mult, "examples": spike_examples,
                })

    return flags


# ---------------------------------------------------------------------------
# Cross-symbol stats
# ---------------------------------------------------------------------------

def compute_cross_symbol_stats(candles_by_symbol: dict, coins: list, bar_audit: dict) -> dict:
    counts_list = list(bar_audit["bar_counts"].values())
    if not counts_list:
        return {"total_symbols": 0, "median_bars": 0, "min_bars": 0, "max_bars": 0, "full_coverage_pct": 0.0}

    median_bars = bar_audit["median"]
    full_coverage = sum(1 for c in counts_list if c >= median_bars)
    full_pct = round(100.0 * full_coverage / len(counts_list), 1)

    return {
        "total_symbols": len(coins),
        "median_bars": median_bars,
        "min_bars": bar_audit["min"],
        "max_bars": bar_audit["max"],
        "full_coverage_pct": full_pct,
        "bar_count_stdev": round(statistics.stdev(counts_list), 1) if len(counts_list) > 1 else 0.0,
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_markdown_report(report: dict, tf: str) -> str:
    s = report["summary"]
    lines = [
        f"# HF Data Audit — {tf.upper()} Candles",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Timeframe**: {tf}",
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
        f"| Zero-volume symbols | {s['zero_volume_symbols']} |",
        f"| Volume anomaly symbols | {s['volume_anomaly_symbols']} |",
        "",
    ]

    flags = report.get("flags", [])
    lines.append(f"## Flags ({len(flags)} total)")
    lines.append("")

    if not flags:
        lines.append("No data integrity flags found. All checks passed.")
        lines.append("")
    else:
        # Group by issue type
        issue_groups = {}
        for f in flags:
            issue_groups.setdefault(f.get("issue", "unknown"), []).append(f)
        for issue_type, items in sorted(issue_groups.items()):
            lines.append(f"### {issue_type.replace('_', ' ').title()} ({len(items)})")
            lines.append("")
            for item in items[:10]:
                lines.append(f"- `{item.get('symbol', '?')}`: {json.dumps({k: v for k, v in item.items() if k not in ('symbol', 'issue')})}")
            if len(items) > 10:
                lines.append(f"- ... and {len(items) - 10} more")
            lines.append("")

    lines.extend([
        "---",
        f"*Generated by `hf_data_audit_mtf.py` at {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HF Data Audit MTF")
    parser.add_argument("--timeframe", "-tf", choices=["1h", "15m", "4h"], required=True)
    args = parser.parse_args()

    tf = args.timeframe
    cfg = TF_THRESHOLDS[tf]

    print(f"=== HF Data Audit MTF (timeframe={tf}) ===")

    data, coins, data_path = load_data(tf)
    print(f"  Loaded {len(coins)} symbols from {Path(data_path).name}")

    candles_by_symbol = {sym: data[sym] for sym in coins}

    # Run audits
    print("  [1/5] Bar counts...")
    bar_audit = audit_bar_counts(candles_by_symbol, coins, cfg["min_bars"])

    all_flags = list(bar_audit["flags"])
    per_symbol_issues = {}
    ohlcv_violation_total = 0
    zero_vol_symbols = set()
    vol_anomaly_symbols = set()

    total = len(coins)
    for idx, sym in enumerate(coins):
        if (idx + 1) % 100 == 0 or idx == 0:
            print(f"  [2-5/5] Auditing symbol {idx + 1}/{total}...")

        candles = candles_by_symbol[sym]
        sym_issues = []

        sym_issues.extend(audit_gaps(candles, sym, cfg["expected_interval"]))
        sym_issues.extend(audit_duplicate_timestamps(candles, sym))

        ohlcv_flags = audit_ohlcv_integrity(candles, sym)
        for f in ohlcv_flags:
            ohlcv_violation_total += f.get("total_violations", 0)
        sym_issues.extend(ohlcv_flags)

        vol_flags = audit_volume_anomalies(
            candles, sym,
            cfg["zero_vol_pct_threshold"],
            cfg["vol_spike_mult"],
            cfg["consecutive_zero_vol_alert"],
        )
        for f in vol_flags:
            if f["issue"] == "high_zero_volume_pct":
                zero_vol_symbols.add(sym)
            if f["issue"] in ("extreme_volume_spike", "consecutive_zero_volume"):
                vol_anomaly_symbols.add(sym)
        sym_issues.extend(vol_flags)

        if sym_issues:
            per_symbol_issues[sym] = sym_issues
            all_flags.extend(sym_issues)

    cross_stats = compute_cross_symbol_stats(candles_by_symbol, coins, bar_audit)

    # Build report
    report = {
        "timestamp": datetime.now().isoformat(),
        "label": f"HF data audit — {tf}",
        "timeframe": tf,
        "data_file": data_path,
        "summary": {
            "total_symbols": cross_stats["total_symbols"],
            "median_bars": cross_stats["median_bars"],
            "min_bars": cross_stats["min_bars"],
            "max_bars": cross_stats["max_bars"],
            "full_coverage_pct": cross_stats["full_coverage_pct"],
            "ohlcv_violations": ohlcv_violation_total,
            "zero_volume_symbols": len(zero_vol_symbols),
            "volume_anomaly_symbols": len(vol_anomaly_symbols),
        },
        "cross_symbol_stats": cross_stats,
        "flags": all_flags,
        "per_symbol_issues": per_symbol_issues,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / f"data_audit_{tf}_001.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"  Wrote {json_path}")

    md_path = REPORTS_DIR / f"data_audit_{tf}_001.md"
    md_content = generate_markdown_report(report, tf)
    with open(md_path, "w") as f:
        f.write(md_content)
    print(f"  Wrote {md_path}")

    # Console summary
    print()
    print(f"=== Audit Summary ({tf}) ===")
    print(f"  Symbols:          {cross_stats['total_symbols']}")
    print(f"  Bar counts:       median={cross_stats['median_bars']}, "
          f"min={cross_stats['min_bars']}, max={cross_stats['max_bars']}")
    print(f"  Full coverage:    {cross_stats['full_coverage_pct']}%")
    print(f"  OHLCV violations: {ohlcv_violation_total}")
    print(f"  Zero-vol symbols: {len(zero_vol_symbols)}")
    print(f"  Vol anomalies:    {len(vol_anomaly_symbols)}")
    print(f"  Total flags:      {len(all_flags)}")
    print("Done.")


if __name__ == "__main__":
    main()

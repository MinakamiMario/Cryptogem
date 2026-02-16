"""
Orderbook snapshot analysis -- computes distributions and builds measured cost regimes.

Reads JSONL output from orderbook_collector.py and produces:
- Percentile distributions of spread, slippage, depth (per tier)
- Measured cost regimes compatible with COST_REGIMES in costs_mexc_v2.py
- Time-of-day spread analysis
- JSON + MD reports

Usage:
    python -m strategies.hf.screening.orderbook_analysis \\
        --input data/orderbook_snapshots/mexc_orderbook_001.jsonl

Output:
    reports/hf/mexc_orderbook_costs_001.json
    reports/hf/mexc_orderbook_costs_001.md
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_INPUT = _PROJECT_ROOT / "data" / "orderbook_snapshots" / "mexc_orderbook_001.jsonl"
_DEFAULT_REPORT_DIR = _PROJECT_ROOT / "reports" / "hf"

# Percentiles to compute
_PERCENTILES = [10, 25, 50, 75, 90, 95, 99]

# Metrics to compute distributions for
_SPREAD_KEY = "spread_bps"
_SLIPPAGE_KEYS = ["slippage_200_bps", "slippage_500_bps", "slippage_2000_bps"]
_DEPTH_KEYS = ["bid_depth_usd", "ask_depth_usd"]
_ALL_METRIC_KEYS = [_SPREAD_KEY] + _SLIPPAGE_KEYS + _DEPTH_KEYS


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_snapshots(path: str) -> List[dict]:
    """Read JSONL file, return list of snapshot dicts.

    Skips malformed lines gracefully.
    """
    snapshots = []
    errors = 0
    with open(path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                snapshots.append(json.loads(line))
            except json.JSONDecodeError:
                errors += 1
                if errors <= 5:
                    print(f"[analysis] Malformed JSON on line {line_num}, skipping")

    if errors > 5:
        print(f"[analysis] {errors} total malformed lines skipped")

    print(f"[analysis] Loaded {len(snapshots)} snapshots from {path}")
    return snapshots


# ---------------------------------------------------------------------------
# Percentile computation
# ---------------------------------------------------------------------------

def _percentile(values: List[float], pct: int) -> float:
    """Compute percentile from sorted values list."""
    if not values:
        return 0.0
    n = len(values)
    idx = min(int(n * pct / 100), n - 1)
    return values[idx]


def compute_distributions(
    snapshots: List[dict],
    by_tier: bool = True,
    by_size: bool = True,
) -> dict:
    """Compute P10/P25/P50/P75/P90/P95/P99 for spread, slippage, and depth.

    Args:
        snapshots: list of snapshot dicts from load_snapshots()
        by_tier: if True, compute per-tier distributions
        by_size: if True, compute slippage by notional size

    Returns:
        Nested dict: {tier: {metric: {percentile: value, "mean": value, "count": n}}}
        Tier keys: "all", "tier1", "tier2"
    """
    # Group by tier
    groups: Dict[str, List[dict]] = {"all": snapshots}
    if by_tier:
        groups["tier1"] = [s for s in snapshots if s.get("tier") == "tier1"]
        groups["tier2"] = [s for s in snapshots if s.get("tier") == "tier2"]

    result = {}
    for group_name, group_snaps in groups.items():
        if not group_snaps:
            result[group_name] = {"count": 0}
            continue

        group_result = {"count": len(group_snaps)}

        for metric in _ALL_METRIC_KEYS:
            # Filter out None values (slippage can be None for insufficient depth)
            values = [s[metric] for s in group_snaps if s.get(metric) is not None]
            if not values:
                group_result[metric] = {"count": 0}
                continue

            values.sort()
            pctiles = {}
            for p in _PERCENTILES:
                pctiles[f"p{p}"] = round(_percentile(values, p), 2)
            pctiles["mean"] = round(sum(values) / len(values), 2)
            pctiles["count"] = len(values)
            pctiles["min"] = round(values[0], 2)
            pctiles["max"] = round(values[-1], 2)
            group_result[metric] = pctiles

        result[group_name] = group_result

    return result


# ---------------------------------------------------------------------------
# Regime builder
# ---------------------------------------------------------------------------

def build_measured_regimes(distributions: dict) -> dict:
    """Build COST_REGIMES-compatible dicts from measured orderbook distributions.

    Produces regimes for both maker (limit) and taker (market) execution modes
    at P50, P90, and P95 percentiles.

    Maker regime logic:
    - exchange_fee_bps = 0 (MEXC maker promo)
    - spread_bps = 0 (you ARE the bid/ask)
    - slippage_bps = adverse selection proxy = spread_bps * 0.3
      (30% of spread as adverse selection when your limit order gets filled)
    - total = sum of above

    Taker regime logic:
    - exchange_fee_bps = 10 (MEXC taker)
    - spread_bps = half-spread (measured spread / 2, you cross half)
    - slippage_bps = measured slippage_200_bps (book walk impact)
    - total = sum of above

    Returns:
        dict of regime_name -> regime_dict, ready for register_regime()
    """
    regimes = {}

    for pct_label, pct_key in [("p50", "p50"), ("p90", "p90"), ("p95", "p95")]:
        # Build tier data for each execution mode
        for exec_mode, mode_label in [("maker_limit", "maker"), ("taker_market", "taker")]:
            tier_data = {}

            for tier_key in ("tier1", "tier2"):
                tier_dist = distributions.get(tier_key, {})
                spread_dist = tier_dist.get("spread_bps", {})
                slip_200_dist = tier_dist.get("slippage_200_bps", {})

                spread_pct = spread_dist.get(pct_key, 0.0)
                slip_200_pct = slip_200_dist.get(pct_key, 0.0)

                if exec_mode == "maker_limit":
                    # Maker: no fee, no spread (you're the liquidity),
                    # but adverse selection when filled
                    fee = 0.0
                    spread = 0.0
                    slippage = 0.0
                    adverse_selection = round(spread_pct * 0.3, 1)
                    total = round(fee + spread + slippage + adverse_selection, 1)

                    tier_data[tier_key] = {
                        "exchange_fee_bps": fee,
                        "spread_bps": spread,
                        "slippage_bps": slippage,
                        "adverse_selection_bps": adverse_selection,
                        "total_per_side_bps": total,
                    }
                else:
                    # Taker: cross the spread, pay fee, suffer book walk
                    fee = 10.0
                    spread = round(spread_pct / 2.0, 1)  # half-spread per side
                    slippage = round(slip_200_pct, 1)
                    total = round(fee + spread + slippage, 1)

                    tier_data[tier_key] = {
                        "exchange_fee_bps": fee,
                        "spread_bps": spread,
                        "slippage_bps": slippage,
                        "total_per_side_bps": total,
                    }

            regime_name = f"measured_ob_{mode_label}_{pct_label}"
            regimes[regime_name] = {
                "description": f"MEXC measured orderbook {mode_label} {pct_label.upper()}",
                "execution_mode": exec_mode,
                "percentile": pct_label,
                **tier_data,
            }

    return regimes


# ---------------------------------------------------------------------------
# Time-of-day analysis
# ---------------------------------------------------------------------------

def time_of_day_analysis(snapshots: List[dict]) -> dict:
    """Spread stats per hour-of-day (UTC). Identifies calm and volatile periods.

    Returns:
        Dict with keys 0-23, each containing spread stats per tier.
    """
    hourly: Dict[int, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))

    for s in snapshots:
        ts = s.get("ts", 0)
        if ts <= 0:
            continue
        hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
        tier = s.get("tier", "all")
        spread = s.get("spread_bps")
        if spread is not None:
            hourly[hour][tier].append(spread)
            hourly[hour]["all"].append(spread)

    result = {}
    for hour in range(24):
        hour_data = {}
        for tier in ("all", "tier1", "tier2"):
            values = sorted(hourly[hour].get(tier, []))
            if values:
                hour_data[tier] = {
                    "count": len(values),
                    "p50": round(_percentile(values, 50), 2),
                    "p90": round(_percentile(values, 90), 2),
                    "mean": round(sum(values) / len(values), 2),
                }
            else:
                hour_data[tier] = {"count": 0, "p50": None, "p90": None, "mean": None}
        result[hour] = hour_data

    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(
    distributions: dict,
    regimes: dict,
    output_dir: str,
    time_of_day: Optional[dict] = None,
    label: str = "001",
) -> Tuple[str, str]:
    """Generate JSON + MD reports.

    Returns:
        (json_path, md_path)
    """
    os.makedirs(output_dir, exist_ok=True)

    json_path = os.path.join(output_dir, f"mexc_orderbook_costs_{label}.json")
    md_path = os.path.join(output_dir, f"mexc_orderbook_costs_{label}.md")

    report = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "description": "MEXC orderbook cost analysis from live snapshots",
        },
        "distributions": distributions,
        "regimes": regimes,
    }
    if time_of_day is not None:
        report["time_of_day"] = time_of_day

    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[analysis] JSON report: {json_path}")

    # Generate markdown report
    md_lines = _generate_markdown(distributions, regimes, time_of_day)
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines))
    print(f"[analysis] MD report: {md_path}")

    return json_path, md_path


def _generate_markdown(
    distributions: dict,
    regimes: dict,
    time_of_day: Optional[dict],
) -> List[str]:
    """Build markdown lines for the report."""
    lines = [
        "# MEXC Orderbook Cost Analysis",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    # --- Distribution tables ---
    lines.append("## Spread & Slippage Distributions")
    lines.append("")

    for tier in ("tier1", "tier2", "all"):
        tier_dist = distributions.get(tier, {})
        count = tier_dist.get("count", 0)
        lines.append(f"### {tier.upper()} (n={count})")
        lines.append("")

        if count == 0:
            lines.append("*No data*")
            lines.append("")
            continue

        lines.append("| Metric | P10 | P25 | P50 | P75 | P90 | P95 | P99 | Mean |")
        lines.append("|--------|-----|-----|-----|-----|-----|-----|-----|------|")

        for metric in _ALL_METRIC_KEYS:
            m = tier_dist.get(metric, {})
            if not m or m.get("count", 0) == 0:
                continue
            row = f"| {metric:25s} "
            for p in _PERCENTILES:
                val = m.get(f"p{p}", "-")
                row += f"| {val:>7} "
            row += f"| {m.get('mean', '-'):>7} |"
            lines.append(row)

        lines.append("")

    # --- Regime comparison ---
    lines.append("## Measured Cost Regimes")
    lines.append("")
    lines.append("| Regime | Mode | Pct | T1 Fee | T1 Spread | T1 Slip | T1 AdvSel | T1 Total | T2 Fee | T2 Spread | T2 Slip | T2 AdvSel | T2 Total |")
    lines.append("|--------|------|-----|--------|-----------|---------|-----------|----------|--------|-----------|---------|-----------|----------|")

    for name, regime in sorted(regimes.items()):
        mode = regime.get("execution_mode", "?")
        pct = regime.get("percentile", "?")
        t1 = regime.get("tier1", {})
        t2 = regime.get("tier2", {})

        def _val(d, k):
            v = d.get(k, "-")
            return f"{v}" if v == "-" else f"{v:.1f}"

        lines.append(
            f"| {name:35s} | {mode:12s} | {pct:3s} "
            f"| {_val(t1, 'exchange_fee_bps'):>6s} "
            f"| {_val(t1, 'spread_bps'):>9s} "
            f"| {_val(t1, 'slippage_bps'):>7s} "
            f"| {_val(t1, 'adverse_selection_bps'):>9s} "
            f"| {_val(t1, 'total_per_side_bps'):>8s} "
            f"| {_val(t2, 'exchange_fee_bps'):>6s} "
            f"| {_val(t2, 'spread_bps'):>9s} "
            f"| {_val(t2, 'slippage_bps'):>7s} "
            f"| {_val(t2, 'adverse_selection_bps'):>9s} "
            f"| {_val(t2, 'total_per_side_bps'):>8s} |"
        )

    lines.append("")

    # --- Time of day ---
    if time_of_day:
        lines.append("## Time-of-Day Spread Analysis (UTC)")
        lines.append("")
        lines.append("| Hour | T1 P50 | T1 P90 | T2 P50 | T2 P90 | All P50 | All P90 | Count |")
        lines.append("|------|--------|--------|--------|--------|---------|---------|-------|")

        for hour in range(24):
            h = time_of_day.get(str(hour), time_of_day.get(hour, {}))
            t1 = h.get("tier1", {})
            t2 = h.get("tier2", {})
            a = h.get("all", {})

            def _v(d, k):
                v = d.get(k)
                return "-" if v is None else f"{v:.1f}"

            lines.append(
                f"| {hour:02d}:00 "
                f"| {_v(t1, 'p50'):>6s} | {_v(t1, 'p90'):>6s} "
                f"| {_v(t2, 'p50'):>6s} | {_v(t2, 'p90'):>6s} "
                f"| {_v(a, 'p50'):>7s} | {_v(a, 'p90'):>7s} "
                f"| {a.get('count', 0):>5d} |"
            )

        lines.append("")

    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze MEXC orderbook snapshots and build cost regimes"
    )
    parser.add_argument(
        "--input", type=str, default=str(_DEFAULT_INPUT),
        help=f"Input JSONL path (default: {_DEFAULT_INPUT})"
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(_DEFAULT_REPORT_DIR),
        help=f"Report output directory (default: {_DEFAULT_REPORT_DIR})"
    )
    parser.add_argument(
        "--label", type=str, default="001",
        help="Report label/suffix (default: 001)"
    )
    parser.add_argument(
        "--register", action="store_true",
        help="Register measured regimes into costs_mexc_v2.COST_REGIMES at runtime"
    )

    args = parser.parse_args()

    # Load
    snapshots = load_snapshots(args.input)
    if not snapshots:
        print("[analysis] No snapshots loaded, exiting.")
        return

    # Compute
    distributions = compute_distributions(snapshots)
    regimes = build_measured_regimes(distributions)
    tod = time_of_day_analysis(snapshots)

    # Report
    json_path, md_path = generate_report(
        distributions=distributions,
        regimes=regimes,
        output_dir=args.output_dir,
        time_of_day=tod,
        label=args.label,
    )

    # Optionally register into live COST_REGIMES
    if args.register:
        from strategies.hf.screening.costs_mexc_v2 import register_regime
        for name, regime in regimes.items():
            register_regime(name, regime)
            print(f"[analysis] Registered regime: {name}")

    # Summary
    print("\n--- Summary ---")
    for tier in ("tier1", "tier2"):
        d = distributions.get(tier, {})
        s = d.get("spread_bps", {})
        sl = d.get("slippage_200_bps", {})
        print(
            f"  {tier}: "
            f"spread P50={s.get('p50', '?')} P90={s.get('p90', '?')} bps | "
            f"slippage_200 P50={sl.get('p50', '?')} P90={sl.get('p90', '?')} bps | "
            f"n={d.get('count', 0)}"
        )

    print(f"\n  Regimes built: {len(regimes)}")
    for name in sorted(regimes):
        r = regimes[name]
        t1_total = r.get("tier1", {}).get("total_per_side_bps", "?")
        t2_total = r.get("tier2", {}).get("total_per_side_bps", "?")
        print(f"    {name}: T1={t1_total}bps T2={t2_total}bps")


if __name__ == "__main__":
    main()

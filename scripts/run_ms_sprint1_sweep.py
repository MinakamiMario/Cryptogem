#!/usr/bin/env python3
"""
MS Sprint 1 Sweep Runner — Market Structure Signal Screening on 4H Kraken.

Backtests 18 configs (5 families) with hybrid_notrl exits on 4H Kraken 526-coin dataset.

Uses Sprint 3 engine with exit_mode='dc' (DC TARGET + RSI RECOVERY + BB TARGET).
Uses MS indicators (swing, FVG, BoS, OB, liquidity zones) on top of Sprint 2 base.

Features:
  --dry-run    List configs only
  --pre-count  Count structural patterns per family (validate >=80 triggers feasible)
  --only N,N   Run specific configs by index
  --force      Overwrite existing results

Usage:
    python3 scripts/run_ms_sprint1_sweep.py --dry-run
    python3 scripts/run_ms_sprint1_sweep.py --pre-count
    python3 scripts/run_ms_sprint1_sweep.py
    python3 scripts/run_ms_sprint1_sweep.py --only 1,5,12
"""
from __future__ import annotations

import sys
import json
import time
import argparse
import importlib
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "trading_bot"))

_sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")
_ms_indicators = importlib.import_module("strategies.ms.indicators")
_ms_hypotheses = importlib.import_module("strategies.ms.hypotheses")
_ms_gates = importlib.import_module("strategies.ms.gates")

_data_resolver = importlib.import_module("strategies.4h.data_resolver")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPORT_DIR = REPO_ROOT / "reports" / "ms"
DATASET_ID = "4h_default"  # 4H Kraken 526 coins
MIN_BARS = 360  # ~2 months minimum
START_BAR = 50  # warmup for indicators


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data():
    """Load 4H Kraken dataset and build universe."""
    path = _data_resolver.resolve_dataset(DATASET_ID)
    print(f"  Dataset: {path}")
    with open(path, "r") as f:
        data = json.load(f)
    print(f"  Total coins in file: {len(data)}")

    # Filter to coins with enough bars (skip metadata keys starting with _)
    coins = [pair for pair in data if not pair.startswith("_")
             and isinstance(data[pair], list) and len(data[pair]) >= MIN_BARS]
    print(f"  Coins with >= {MIN_BARS} bars: {len(coins)}")

    return data, coins


# ---------------------------------------------------------------------------
# Pre-count: structural pattern frequency
# ---------------------------------------------------------------------------

def run_pre_count(data: dict, coins: list[str], indicators: dict):
    """Count structural patterns to validate >= 80 triggers are feasible."""
    print(f"\n{'='*72}")
    print("  MS SPRINT 1 — PRE-COUNT (structural pattern frequencies)")
    print(f"{'='*72}\n")

    totals = {
        "swing_lows": 0, "swing_highs": 0,
        "fvg_bullish": 0, "fvg_bearish": 0,
        "bos_bullish": 0, "bos_bearish": 0,
        "ob_bullish": 0, "ob_bearish": 0,
        "liq_below": 0, "liq_above": 0,
    }

    for pair in coins:
        ind = indicators.get(pair)
        if ind is None:
            continue
        n = ind["n"]

        for bar in range(START_BAR, n):
            if ind["swing_lows"][bar] is not None:
                totals["swing_lows"] += 1
            if ind["swing_highs"][bar] is not None:
                totals["swing_highs"] += 1

            # FVGs
            for fvg in ind["fvg_snapshots"][bar]:
                if fvg.bar_created == bar:
                    if fvg.direction == "bullish":
                        totals["fvg_bullish"] += 1
                    else:
                        totals["fvg_bearish"] += 1

            # BoS
            bos = ind["bos_events"][bar]
            if bos is not None:
                if bos.direction == "bullish":
                    totals["bos_bullish"] += 1
                else:
                    totals["bos_bearish"] += 1

            # OBs (count new ones only)
            for ob in ind["ob_snapshots"][bar]:
                # Check if newly created at this bar (approximate: ob appears and wasn't in prior bar)
                if ob.bar_created >= START_BAR:
                    pass  # We count unique OBs below

            # Liquidity zones
            for zone in ind["liq_zones"][bar]:
                if zone.direction == "below":
                    totals["liq_below"] += 1
                else:
                    totals["liq_above"] += 1

    # Count unique OBs across all coins
    unique_obs_bull = set()
    unique_obs_bear = set()
    for pair in coins:
        ind = indicators.get(pair)
        if ind is None:
            continue
        for bar in range(START_BAR, ind["n"]):
            for ob in ind["ob_snapshots"][bar]:
                key = (pair, ob.bar_created, ob.direction)
                if ob.direction == "bullish":
                    unique_obs_bull.add(key)
                else:
                    unique_obs_bear.add(key)
    totals["ob_bullish"] = len(unique_obs_bull)
    totals["ob_bearish"] = len(unique_obs_bear)

    total_bars = sum(max(0, indicators[pair]["n"] - START_BAR) for pair in coins if pair in indicators)

    print(f"  Universe: {len(coins)} coins, {total_bars:,} total bars\n")
    print(f"  {'Pattern':<20} {'Count':>10} {'Per 1000 bars':>15}")
    print(f"  {'─'*50}")
    for key, count in totals.items():
        rate = count / total_bars * 1000 if total_bars > 0 else 0
        print(f"  {key:<20} {count:>10,} {rate:>14.1f}")

    # Feasibility check
    print(f"\n  Feasibility for >= 80 trades:")
    families_ok = True
    # Rough estimates based on pattern counts
    estimates = {
        "A (liq_sweep)": totals["swing_lows"] // 10,  # ~10% of swings get swept
        "B (fvg_fill)": totals["fvg_bullish"] // 5,  # ~20% get filled entry
        "C (ob_touch)": totals["ob_bullish"] // 5,
        "D (sfp)": totals["swing_lows"] // 20,  # ~5% of swings are SFPs
        "E (shift_pb)": totals["bos_bullish"] // 10,
    }
    for fam, est in estimates.items():
        ok = "OK" if est >= 80 else "RISK"
        if est < 80:
            families_ok = False
        print(f"    {fam}: ~{est} estimated entries [{ok}]")

    if not families_ok:
        print(f"\n  ⚠️  Some families may not reach 80 trades. Proceed with awareness.")
    else:
        print(f"\n  ✅ All families likely feasible")

    return totals


# ---------------------------------------------------------------------------
# Backtest runner
# ---------------------------------------------------------------------------

def run_backtest_config(config: dict, data: dict, coins: list[str], indicators: dict) -> dict:
    """Run a single config through Sprint 3 engine with DC exits."""
    signal_fn = config["signal_fn"]
    params = config["params"]

    # Wrap signal_fn to track DC-geometry compliance
    dc_geometry_scores = []

    def wrapped_signal_fn(candles, bar, ind, par):
        result = signal_fn(candles, bar, ind, par)
        if result is not None:
            dc_geometry_scores.append(result.pop("dc_geometry", 0.0))
        return result

    bt = _sprint3_engine.run_backtest(
        data=data,
        coins=coins,
        signal_fn=wrapped_signal_fn,
        params=params,
        indicators=indicators,
        exit_mode="dc",
        start_bar=START_BAR,
    )

    # Build result dict
    result = {
        "id": config["id"],
        "idx": config["idx"],
        "label": config["label"],
        "family": config["family"],
        "hypothesis_id": config["hypothesis_id"],
        "hypothesis_name": config["hypothesis_name"],
        "trades": bt.trades,
        "pnl": round(bt.pnl, 2),
        "pf": round(bt.pf, 4) if bt.pf != float("inf") else 99.99,
        "wr": round(bt.wr, 4),
        "dd": round(bt.dd, 2),
        "trade_list": bt.trade_list,
        "exit_classes": bt.exit_classes,
        "dc_geometry_scores": dc_geometry_scores,
    }

    return result


# ---------------------------------------------------------------------------
# Exit attribution
# ---------------------------------------------------------------------------

def summarize_exit_classes(exit_classes: dict) -> str:
    """Format exit class distribution. Handles nested {A: {name: {count, pnl}}, B: {...}} format."""
    if not exit_classes:
        return "N/A"
    # Flatten nested structure
    flat = {}
    for _class_key, exits in exit_classes.items():
        if isinstance(exits, dict):
            for exit_name, info in exits.items():
                if isinstance(info, dict):
                    flat[exit_name] = flat.get(exit_name, 0) + info.get("count", 0)
                else:
                    flat[exit_name] = flat.get(exit_name, 0) + info
        else:
            flat[_class_key] = exits
    total = sum(flat.values())
    if total == 0:
        return "N/A"
    parts = []
    for cls, count in sorted(flat.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        parts.append(f"{cls}:{count}({pct:.0f}%)")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Scoreboard
# ---------------------------------------------------------------------------

def build_scoreboard(results: list[dict]) -> str:
    """Build markdown scoreboard."""
    lines = []
    lines.append("# MS Sprint 1 — Scoreboard\n")
    lines.append(f"**Date**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"**Configs**: {len(results)}")
    lines.append(f"**Dataset**: 4H Kraken ({DATASET_ID})\n")

    # Summary
    n_go = sum(1 for r in results if r.get("verdict") == "GO")
    n_pf_1 = sum(1 for r in results if r.get("pf", 0) >= 1.0)
    lines.append(f"**GO**: {n_go}/{len(results)}")
    lines.append(f"**PF >= 1.0**: {n_pf_1}/{len(results)}\n")

    # Table
    lines.append("| # | Config | Family | Trades | PF | P&L | DD% | Verdict | Exits |")
    lines.append("|---|--------|--------|--------|----|-----|-----|---------|-------|")

    sorted_results = sorted(results, key=lambda r: -r.get("pf", 0))
    for r in sorted_results:
        exits = summarize_exit_classes(r.get("exit_classes", {}))
        verdict = r.get("verdict", "?")
        lines.append(
            f"| {r['idx']} | {r['id']} | {r['family']} "
            f"| {r['trades']} | {r['pf']:.2f} | ${r['pnl']:,.0f} "
            f"| {r['dd']:.1f} | {verdict} | {exits} |"
        )

    # Family summary
    lines.append("\n## Family Summary\n")
    family_results: dict[str, list] = {}
    for r in results:
        family_results.setdefault(r["family"], []).append(r)

    for fam, frs in sorted(family_results.items()):
        pfs = [r["pf"] for r in frs]
        best_pf = max(pfs)
        avg_pf = sum(pfs) / len(pfs)
        n_go_fam = sum(1 for r in frs if r.get("verdict") == "GO")
        lines.append(f"- **{fam}** ({len(frs)} configs): best PF={best_pf:.2f}, avg PF={avg_pf:.2f}, {n_go_fam} GO")

    # DC-geometry compliance
    lines.append("\n## DC-Geometry Compliance\n")
    lines.append("| Config | Avg Score | Full Compliance % |")
    lines.append("|--------|-----------|-------------------|")
    for r in sorted_results:
        scores = r.get("dc_geometry_scores", [])
        if scores:
            avg = sum(scores) / len(scores)
            pct_full = sum(1 for s in scores if s >= 0.99) / len(scores) * 100
            lines.append(f"| {r['id']} | {avg:.2f} | {pct_full:.0f}% |")
        else:
            lines.append(f"| {r['id']} | N/A | N/A |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="MS Sprint 1 Sweep Runner")
    parser.add_argument("--dry-run", action="store_true", help="List configs only")
    parser.add_argument("--pre-count", action="store_true", help="Count structural patterns")
    parser.add_argument("--only", type=str, help="Comma-separated config indices to run")
    parser.add_argument("--force", action="store_true", help="Overwrite existing results")
    args = parser.parse_args()

    configs = _ms_hypotheses.build_sweep_configs()

    # --- DRY RUN ---
    if args.dry_run:
        print(f"\n{'='*72}")
        print("  MS SPRINT 1 — DRY RUN ({} configs)".format(len(configs)))
        print(f"{'='*72}\n")
        for c in configs:
            print(f"  [{c['idx']:2d}] {c['id']:<40s} {c['family']:<12s} {c['label']}")
        print(f"\n  Total: {len(configs)} configs across {len(set(c['family'] for c in configs))} families")
        return

    # --- Load data ---
    print(f"\n{'='*72}")
    print("  MS SPRINT 1 — Loading data")
    print(f"{'='*72}\n")
    data, coins = load_data()

    # --- Precompute indicators ---
    print(f"\n  Computing MS indicators for {len(coins)} coins...")
    t0 = time.time()
    indicators = _ms_indicators.precompute_ms_indicators(data, coins)
    t1 = time.time()
    print(f"  Indicators computed in {t1-t0:.1f}s")

    # --- PRE-COUNT ---
    if args.pre_count:
        run_pre_count(data, coins, indicators)
        return

    # --- Filter configs if --only ---
    if args.only:
        only_indices = set(int(x) for x in args.only.split(","))
        configs = [c for c in configs if c["idx"] in only_indices]
        print(f"\n  Running {len(configs)} configs: {[c['idx'] for c in configs]}")

    # --- Check existing results ---
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    scoreboard_json = REPORT_DIR / "sprint1_scoreboard.json"
    if scoreboard_json.exists() and not args.force:
        print(f"\n  ⚠️  Results already exist at {scoreboard_json}")
        print(f"  Use --force to overwrite")
        return

    # --- Run backtests ---
    print(f"\n{'='*72}")
    print(f"  MS SPRINT 1 — Running {len(configs)} backtests")
    print(f"{'='*72}\n")

    results = []
    for i, config in enumerate(configs):
        print(f"  [{i+1}/{len(configs)}] {config['id']}...", end=" ", flush=True)
        t0 = time.time()

        bt_result = run_backtest_config(config, data, coins, indicators)

        # Evaluate gates
        gate_report = _ms_gates.evaluate_ms_gates(bt_result)
        bt_result["verdict"] = gate_report.verdict
        bt_result["gate_summary"] = gate_report.summary_str
        bt_result["gates"] = _ms_gates.gates_to_dict(gate_report)

        t1 = time.time()
        print(f"trades={bt_result['trades']} PF={bt_result['pf']:.2f} P&L=${bt_result['pnl']:.0f} "
              f"DD={bt_result['dd']:.1f}% [{gate_report.verdict}] ({t1-t0:.1f}s)")

        results.append(bt_result)

    # --- Save results ---
    print(f"\n{'='*72}")
    print("  RESULTS SUMMARY")
    print(f"{'='*72}\n")

    n_go = sum(1 for r in results if r["verdict"] == "GO")
    n_pf_1 = sum(1 for r in results if r["pf"] >= 1.0)
    print(f"  Configs: {len(results)}")
    print(f"  GO (PF>=1.0 + trades>=80): {n_go}/{len(results)}")
    print(f"  PF >= 1.0: {n_pf_1}/{len(results)}")

    # Strip trade_list for JSON output (too large)
    json_results = []
    for r in results:
        r_copy = {k: v for k, v in r.items() if k != "trade_list"}
        json_results.append(r_copy)

    with open(scoreboard_json, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dataset": DATASET_ID,
            "n_coins": len(coins),
            "n_configs": len(results),
            "n_go": n_go,
            "n_pf_above_1": n_pf_1,
            "results": json_results,
        }, f, indent=2)
    print(f"\n  JSON: {scoreboard_json}")

    # Markdown scoreboard
    scoreboard_md = REPORT_DIR / "sprint1_scoreboard.md"
    with open(scoreboard_md, "w") as f:
        f.write(build_scoreboard(results))
    print(f"  MD:   {scoreboard_md}")

    # Print gate reports
    for r in sorted(results, key=lambda x: -x["pf"]):
        gate_report = _ms_gates.evaluate_ms_gates(r)
        _ms_gates.print_gate_report(gate_report, label=r["id"])


if __name__ == "__main__":
    main()

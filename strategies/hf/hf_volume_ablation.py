#!/usr/bin/env python3
"""
HF Volume Ablation — 4H variant research.

Answers: "Does the strategy edge lean on volume-anomaly symbols?"

Methodology:
  1. Load the full tradeable universe (425 coins)
  2. Load flagged symbols from data_audit_001.json
  3. Run baseline backtest on ALL coins
  4. Run backtest on CLEAN coins only (all minus flagged)
  5. Run backtest on FLAGGED coins only
  6. Compare metrics: P&L, PF, WR, DD, trades
  7. Verdict based on clean-vs-baseline P&L ratio

Verdict logic:
  - clean P&L >= 80% of baseline  -> "Edge does NOT lean on anomaly symbols"
  - clean P&L >= 50% of baseline  -> "Edge is modestly affected by anomaly symbols"
  - clean P&L <  50% of baseline  -> "WARNING: Edge may depend on volume anomalies"

Usage:
    python strategies/hf/hf_volume_ablation.py
    python strategies/hf/hf_volume_ablation.py --universe tradeable
    python strategies/hf/hf_volume_ablation.py --universe live

Outputs:
    reports/hf/volume_ablation_001.json  -- structured ablation results
    reports/hf/volume_ablation_001.md    -- human-readable summary
"""

import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Path setup (read-only import from trading_bot/)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRADING_BOT = REPO_ROOT / "trading_bot"
sys.path.insert(0, str(TRADING_BOT))

from agent_team_v3 import (  # noqa: E402
    precompute_all,
    run_backtest,
    normalize_cfg,
    KRAKEN_FEE,
    START_BAR,
    INITIAL_CAPITAL,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"

DATA_FILES = {
    "tradeable": DATA_DIR / "candle_cache_tradeable.json",
    "live": DATA_DIR / "candle_cache_532.json",
}

DATA_AUDIT_PATH = REPORTS_DIR / "data_audit_001.json"

# Configs under test (same as hf_validate.py)
CHAMPION_H2 = normalize_cfg({
    "exit_type": "tp_sl",
    "max_pos": 1,
    "rsi_max": 45,
    "sl_pct": 8,
    "time_max_bars": 15,
    "tp_pct": 12,
    "vol_confirm": True,
    "vol_spike_mult": 3.0,
})

GRID_BEST = normalize_cfg({
    "exit_type": "tp_sl",
    "max_pos": 1,
    "rsi_max": 45,
    "sl_pct": 10,
    "time_max_bars": 15,
    "tp_pct": 12,
    "vol_confirm": True,
    "vol_spike_mult": 2.5,
})

CONFIGS = {
    "Champion_H2": CHAMPION_H2,
    "GRID_BEST": GRID_BEST,
}

# Verdict thresholds
CLEAN_RATIO_SAFE = 0.80    # >= 80% of baseline -> edge does NOT lean on anomalies
CLEAN_RATIO_DANGER = 0.50  # <  50% of baseline -> WARNING


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_data(universe: str):
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


def load_flagged_symbols():
    """Load flagged symbol list from data_audit_001.json."""
    if not DATA_AUDIT_PATH.exists():
        print(f"ERROR: Data audit file not found: {DATA_AUDIT_PATH}")
        print("  Run: python strategies/hf/hf_data_audit.py first")
        sys.exit(1)
    with open(DATA_AUDIT_PATH) as f:
        audit = json.load(f)
    flags = audit.get("flags", [])
    # Extract unique symbols from flags
    flagged_symbols = sorted(set(f["symbol"] for f in flags))
    return flagged_symbols, flags


# ---------------------------------------------------------------------------
# Backtest runner with metric extraction
# ---------------------------------------------------------------------------
def run_ablation_backtest(data, coins, cfg, label=""):
    """
    Precompute indicators and run backtest on given coin subset.
    Returns dict with trades, pnl, pf, wr, dd.
    """
    if not coins:
        return {
            "trades": 0,
            "pnl": 0.0,
            "pf": 0.0,
            "wr": 0.0,
            "dd": 0.0,
            "final_equity": INITIAL_CAPITAL,
            "broke": False,
        }

    indicators = precompute_all(data, coins)
    result = run_backtest(indicators, coins, cfg)

    pf = result["pf"]
    if pf == float("inf"):
        pf = 99.0

    return {
        "trades": result["trades"],
        "pnl": round(result["pnl"], 2),
        "pf": round(min(pf, 99.0), 2),
        "wr": round(result["wr"], 1),
        "dd": round(result["dd"], 1),
        "final_equity": round(result["final_equity"], 2),
        "broke": result["broke"],
    }


# ---------------------------------------------------------------------------
# Ablation analysis for one config
# ---------------------------------------------------------------------------
def run_ablation(cfg_name, cfg, data, all_coins, clean_coins, flagged_coins):
    """Run ablation study: ALL vs CLEAN vs FLAGGED-only."""
    print(f"\n--- Ablation: {cfg_name} ---")
    print(f"  Config: {json.dumps(cfg, sort_keys=True)}")
    print(f"  ALL={len(all_coins)} | CLEAN={len(clean_coins)} | FLAGGED={len(flagged_coins)}")

    # 1. Baseline: ALL coins
    print(f"  [1/3] Running baseline (ALL {len(all_coins)} coins)...")
    t0 = time.time()
    baseline = run_ablation_backtest(data, all_coins, cfg, label="ALL")
    t_baseline = time.time() - t0
    print(f"         {baseline['trades']} trades, P&L=${baseline['pnl']:+,.2f}, "
          f"PF={baseline['pf']}, WR={baseline['wr']}%, DD={baseline['dd']}% "
          f"({t_baseline:.1f}s)")

    # 2. Clean: ALL minus flagged
    print(f"  [2/3] Running CLEAN ({len(clean_coins)} coins)...")
    t0 = time.time()
    clean = run_ablation_backtest(data, clean_coins, cfg, label="CLEAN")
    t_clean = time.time() - t0
    print(f"         {clean['trades']} trades, P&L=${clean['pnl']:+,.2f}, "
          f"PF={clean['pf']}, WR={clean['wr']}%, DD={clean['dd']}% "
          f"({t_clean:.1f}s)")

    # 3. Flagged-only
    print(f"  [3/3] Running FLAGGED-ONLY ({len(flagged_coins)} coins)...")
    t0 = time.time()
    flagged = run_ablation_backtest(data, flagged_coins, cfg, label="FLAGGED")
    t_flagged = time.time() - t0
    print(f"         {flagged['trades']} trades, P&L=${flagged['pnl']:+,.2f}, "
          f"PF={flagged['pf']}, WR={flagged['wr']}%, DD={flagged['dd']}% "
          f"({t_flagged:.1f}s)")

    # Compute deltas
    baseline_pnl = baseline["pnl"]
    clean_pnl = clean["pnl"]
    flagged_pnl = flagged["pnl"]

    # P&L ratio: clean vs baseline
    if baseline_pnl > 0:
        clean_ratio = clean_pnl / baseline_pnl
    elif baseline_pnl == 0:
        clean_ratio = 1.0 if clean_pnl >= 0 else 0.0
    else:
        # Baseline is negative; if clean is also negative but less so, ratio > 1
        clean_ratio = clean_pnl / baseline_pnl if baseline_pnl != 0 else 0.0

    pnl_delta = clean_pnl - baseline_pnl
    pnl_delta_pct = (pnl_delta / abs(baseline_pnl) * 100) if baseline_pnl != 0 else 0.0

    # Verdict
    if baseline_pnl <= 0:
        verdict = "BASELINE_NEGATIVE"
        verdict_detail = (
            "Baseline P&L is non-positive; ablation comparison is not meaningful. "
            "Strategy does not have positive edge on full universe."
        )
    elif clean_ratio >= CLEAN_RATIO_SAFE:
        verdict = "SAFE"
        verdict_detail = (
            f"Edge does NOT lean on anomaly symbols. "
            f"Clean P&L is {clean_ratio*100:.1f}% of baseline (>= {CLEAN_RATIO_SAFE*100:.0f}% threshold)."
        )
    elif clean_ratio >= CLEAN_RATIO_DANGER:
        verdict = "MODERATE"
        verdict_detail = (
            f"Edge is modestly affected by anomaly symbols. "
            f"Clean P&L is {clean_ratio*100:.1f}% of baseline "
            f"(between {CLEAN_RATIO_DANGER*100:.0f}% and {CLEAN_RATIO_SAFE*100:.0f}%)."
        )
    else:
        verdict = "WARNING"
        verdict_detail = (
            f"WARNING: Edge may depend on volume anomalies. "
            f"Clean P&L is only {clean_ratio*100:.1f}% of baseline (< {CLEAN_RATIO_DANGER*100:.0f}% threshold)."
        )

    print(f"\n  VERDICT: {verdict}")
    print(f"  {verdict_detail}")

    return {
        "config_name": cfg_name,
        "cfg": cfg,
        "coin_counts": {
            "all": len(all_coins),
            "clean": len(clean_coins),
            "flagged": len(flagged_coins),
        },
        "results": {
            "all": baseline,
            "clean": clean,
            "flagged_only": flagged,
        },
        "deltas": {
            "clean_vs_all_pnl_delta": round(pnl_delta, 2),
            "clean_vs_all_pnl_delta_pct": round(pnl_delta_pct, 1),
            "clean_pnl_ratio": round(clean_ratio, 4),
            "flagged_pnl_share": round(
                flagged_pnl / baseline_pnl * 100, 1
            ) if baseline_pnl != 0 else 0.0,
        },
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "timing_s": {
            "baseline": round(t_baseline, 1),
            "clean": round(t_clean, 1),
            "flagged": round(t_flagged, 1),
        },
    }


# ---------------------------------------------------------------------------
# Markdown report generator
# ---------------------------------------------------------------------------
def generate_markdown(all_results, meta):
    """Generate human-readable volume ablation report."""
    lines = [
        "# HF Volume Ablation Report -- 4H Variant Research",
        "",
        "> **Question**: Does the strategy edge lean on volume-anomaly symbols?",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Universe**: {meta['universe']}",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Total coins**: {meta['n_coins_all']}",
        f"**Clean coins**: {meta['n_coins_clean']}",
        f"**Flagged coins**: {meta['n_coins_flagged']}",
        f"**Flag categories**: {', '.join(meta['flag_categories'])}",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
    ]

    # Verdict summary table
    lines.extend([
        "## Verdict Summary",
        "",
        "| Config | Verdict | Clean P&L Ratio | Interpretation |",
        "|--------|---------|-----------------|----------------|",
    ])
    for r in all_results:
        ratio_pct = f"{r['deltas']['clean_pnl_ratio']*100:.1f}%"
        lines.append(
            f"| {r['config_name']} | **{r['verdict']}** "
            f"| {ratio_pct} | {r['verdict_detail'][:80]}{'...' if len(r['verdict_detail']) > 80 else ''} |"
        )
    lines.append("")

    # Detailed comparison per config
    for r in all_results:
        res = r["results"]
        deltas = r["deltas"]
        counts = r["coin_counts"]

        lines.extend([
            "---",
            "",
            f"## {r['config_name']}",
            "",
            f"**Config**: `{json.dumps(r['cfg'], sort_keys=True)}`",
            "",
            "### Performance Comparison",
            "",
            "| Subset | Coins | Trades | P&L | PF | WR% | DD% |",
            "|--------|-------|--------|-----|----|-----|-----|",
        ])

        for subset_name, subset_key in [("ALL", "all"), ("CLEAN", "clean"), ("FLAGGED-ONLY", "flagged_only")]:
            s = res[subset_key]
            coin_count = counts["all"] if subset_key == "all" else (
                counts["clean"] if subset_key == "clean" else counts["flagged"]
            )
            lines.append(
                f"| {subset_name} | {coin_count} "
                f"| {s['trades']} | ${s['pnl']:+,.2f} "
                f"| {s['pf']} | {s['wr']}% | {s['dd']}% |"
            )

        lines.extend([
            "",
            "### Delta Analysis",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Clean vs All P&L delta | ${deltas['clean_vs_all_pnl_delta']:+,.2f} ({deltas['clean_vs_all_pnl_delta_pct']:+.1f}%) |",
            f"| Clean P&L as % of baseline | {deltas['clean_pnl_ratio']*100:.1f}% |",
            f"| Flagged-only P&L share | {deltas['flagged_pnl_share']:.1f}% of baseline |",
            "",
            "### Verdict",
            "",
            f"**{r['verdict']}**: {r['verdict_detail']}",
            "",
        ])

    # Overall conclusion
    lines.extend([
        "---",
        "",
        "## Conclusion",
        "",
    ])

    all_safe = all(r["verdict"] == "SAFE" for r in all_results)
    any_warning = any(r["verdict"] == "WARNING" for r in all_results)

    if all_safe:
        lines.extend([
            "**Edge does NOT lean on anomaly symbols.**",
            "",
            "Both configs retain >= 80% of their baseline P&L when flagged symbols are removed.",
            "The strategy's profitability is robust to volume-anomaly filtering.",
        ])
    elif any_warning:
        lines.extend([
            "**WARNING: Edge may depend on volume anomalies.**",
            "",
            "At least one config loses > 50% of baseline P&L when flagged symbols are removed.",
            "Further investigation is needed before deploying with live capital.",
        ])
    else:
        lines.extend([
            "**Edge is modestly affected by anomaly symbols.**",
            "",
            "Removing flagged symbols reduces P&L but does not eliminate the edge entirely.",
            "Consider monitoring flagged symbols closely in production.",
        ])

    lines.extend([
        "",
        "## Thresholds",
        "",
        "| Threshold | Condition | Verdict |",
        "|-----------|-----------|---------|",
        f"| Safe | Clean P&L >= {CLEAN_RATIO_SAFE*100:.0f}% of baseline | Edge NOT dependent on anomalies |",
        f"| Moderate | Clean P&L between {CLEAN_RATIO_DANGER*100:.0f}%-{CLEAN_RATIO_SAFE*100:.0f}% | Modestly affected |",
        f"| Warning | Clean P&L < {CLEAN_RATIO_DANGER*100:.0f}% of baseline | May depend on anomalies |",
        "",
        "---",
        f"*Generated by hf_volume_ablation.py -- 4H variant research*",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="HF Volume Ablation -- 4H variant research"
    )
    parser.add_argument(
        "--universe",
        choices=["tradeable", "live"],
        default="tradeable",
        help="Which candle cache to use (default: tradeable)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  HF Volume Ablation -- 4H Variant Research")
    print("  Question: Does the strategy edge lean on volume-anomaly symbols?")
    print("=" * 70)
    print(f"  Universe: {args.universe}")

    # 1. Load candle data
    data, all_coins, data_path = load_data(args.universe)
    n_bars = len(data[all_coins[0]]) if all_coins else 0
    print(f"  Loaded {len(all_coins)} coins, {n_bars} bars from {Path(data_path).name}")

    # 2. Load flagged symbols
    flagged_symbols, raw_flags = load_flagged_symbols()
    print(f"  Flagged symbols: {len(flagged_symbols)} (from {DATA_AUDIT_PATH.name})")

    # Categorize flags
    flag_categories = sorted(set(f["issue"] for f in raw_flags))
    print(f"  Flag categories: {', '.join(flag_categories)}")

    # 3. Build coin subsets
    flagged_set = set(flagged_symbols)
    clean_coins = sorted([c for c in all_coins if c not in flagged_set])
    flagged_coins = sorted([c for c in all_coins if c in flagged_set])

    # Some flagged symbols might not be in the data (different universe)
    actual_flagged_in_data = len(flagged_coins)
    print(f"  Coin split: ALL={len(all_coins)} | "
          f"CLEAN={len(clean_coins)} | FLAGGED={actual_flagged_in_data}")

    if actual_flagged_in_data == 0:
        print("  WARNING: No flagged symbols found in current universe data!")
        print("  The ablation study may not be meaningful.")

    t_start = time.time()

    # 4. Run ablation for each config
    all_results = []
    for cfg_name, cfg in CONFIGS.items():
        result = run_ablation(cfg_name, cfg, data, all_coins, clean_coins, flagged_coins)
        all_results.append(result)

    total_time = time.time() - t_start

    # 5. Build meta
    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "universe": args.universe,
        "data_file": data_path,
        "data_audit_file": str(DATA_AUDIT_PATH),
        "n_coins_all": len(all_coins),
        "n_coins_clean": len(clean_coins),
        "n_coins_flagged": actual_flagged_in_data,
        "n_bars": n_bars,
        "flagged_symbols": flagged_symbols,
        "flag_categories": flag_categories,
        "total_time_s": round(total_time, 2),
        "label": "4H variant research",
        "configs_tested": list(CONFIGS.keys()),
        "thresholds": {
            "clean_ratio_safe": CLEAN_RATIO_SAFE,
            "clean_ratio_danger": CLEAN_RATIO_DANGER,
        },
    }

    # 6. Write JSON report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / "volume_ablation_001.json"

    json_output = {
        "meta": meta,
        "results": {r["config_name"]: r for r in all_results},
    }
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    print(f"\n  Wrote {json_path}")

    # 7. Write markdown report
    md_path = REPORTS_DIR / "volume_ablation_001.md"
    md = generate_markdown(all_results, meta)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # 8. Final summary
    print("\n" + "=" * 70)
    print("  VOLUME ABLATION SUMMARY (4H variant research)")
    print("=" * 70)
    print(f"\n  {'Config':<20} {'Verdict':<12} {'Clean Ratio':<14} {'Clean P&L':<14} {'All P&L'}")
    print("  " + "-" * 70)
    for r in all_results:
        ratio_str = f"{r['deltas']['clean_pnl_ratio']*100:.1f}%"
        clean_pnl = r["results"]["clean"]["pnl"]
        all_pnl = r["results"]["all"]["pnl"]
        print(f"  {r['config_name']:<20} {r['verdict']:<12} {ratio_str:<14} "
              f"${clean_pnl:>+10,.2f}   ${all_pnl:>+10,.2f}")

    print(f"\n  Total runtime: {total_time:.1f}s")
    print("  " + "=" * 65)


if __name__ == "__main__":
    main()

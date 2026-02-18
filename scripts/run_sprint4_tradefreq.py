#!/usr/bin/env python3
"""
Sprint 4 Trade Frequency Sensitivity Analysis
===============================================

Tests trade frequency sensitivity for Sprint 4 top-5 configs:
  1. Full pool (526 coins) vs universe (487 coins)
  2. RSI threshold sensitivity
  3. Volume threshold sensitivity
  4. Trade frequency calculation (trades/week, trades/day)

Quality gates:
  - stopout_ratio <= 30%
  - class_a_share >= 50% (positive profit attribution)
  - PF >= 1.0 (must not destroy edge)

Usage:
    python3 scripts/run_sprint4_tradefreq.py
    python3 scripts/run_sprint4_tradefreq.py --only 041,032
    python3 scripts/run_sprint4_tradefreq.py --test full_pool
    python3 scripts/run_sprint4_tradefreq.py --test rsi_sensitivity
    python3 scripts/run_sprint4_tradefreq.py --test vol_sensitivity
"""
from __future__ import annotations

import sys
import json
import time
import argparse
import importlib
import subprocess
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "trading_bot"))

# Import modules
_data_resolver = importlib.import_module("strategies.4h.data_resolver")
_sprint2_indicators = importlib.import_module("strategies.4h.sprint2.indicators")
_sprint2_ctx = importlib.import_module("strategies.4h.sprint2.market_context")
_sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")
_sprint4_hyp = importlib.import_module("strategies.4h.sprint4.hypotheses")

resolve_dataset = _data_resolver.resolve_dataset
precompute_all = _sprint2_indicators.precompute_all
precompute_sprint2_context = _sprint2_ctx.precompute_sprint2_context
run_backtest = _sprint3_engine.run_backtest
build_sweep_configs = _sprint4_hyp.build_sweep_configs

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_DATASET = "ohlcv_4h_kraken_spot_usd_526"
KRAKEN_FEE = 0.0026
OUTPUT_DIR = REPO_ROOT / "reports" / "4h"

# Dataset spans ~721 bars at 4H = ~120 days = ~17.1 weeks
DATASET_WEEKS = 17.1
DATASET_DAYS = 120.0

CLASS_A_REASONS = {"PROFIT TARGET", "RSI RECOVERY", "DC TARGET", "BB TARGET"}

# Quality gates
MAX_STOPOUT_RATIO = 0.30
MIN_CLASS_A_SHARE = 0.50
MIN_PF = 1.0

# Top-5 configs from Sprint 4 results
TOP5_CONFIG_IDS = [
    "sprint4_041_h4s4g05_vol3x_bblow_rsi40",
    "sprint4_032_h4s4f02_z2.5_dclow_rsi40",
    "sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35",
    "sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5",
    "sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol",
]

# RSI sensitivity grid per base rsi_max
RSI_GRID = {
    35: [35, 38, 40],
    40: [40, 42, 45],
    45: [45, 47, 50],
}

# Volume sensitivity grids
VOL_MULT_GRID = {
    3.0: [2.5, 3.0, 3.5],
    4.0: [3.5, 4.0, 4.5],
    5.0: [4.5, 5.0, 5.5],
}
VOL_SPIKE_MULT_GRID = {
    1.5: [1.0, 1.5, 2.0],
    2.0: [1.5, 2.0, 2.5],
    2.5: [2.0, 2.5, 3.0],
    3.0: [2.5, 3.0, 3.5],
}
VOL_FLOOR_MULT_GRID = {
    0.5: [0.3, 0.5, 0.7],
    0.8: [0.5, 0.8, 1.0],
    1.0: [0.7, 1.0, 1.3],
    1.5: [1.0, 1.5, 2.0],
}


def _git_hash() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Quality metrics
# ---------------------------------------------------------------------------

def compute_quality_metrics(trade_list: list[dict]) -> dict:
    """Compute stopout_ratio and class_a_share using positive profit attribution."""
    total = len(trade_list)
    if total == 0:
        return {"stopout_ratio": 0.0, "class_a_share": 0.0}

    stopouts = sum(1 for t in trade_list if t["reason"] == "FIXED STOP")
    stopout_ratio = stopouts / total

    # Positive profit attribution
    total_profit = sum(max(0, t["pnl"]) for t in trade_list)
    class_a_profit = sum(
        max(0, t["pnl"])
        for t in trade_list
        if t["reason"] in CLASS_A_REASONS
    )
    class_a_share = min(1.0, class_a_profit / total_profit) if total_profit > 0 else 0.0

    return {
        "stopout_ratio": round(stopout_ratio, 4),
        "class_a_share": round(class_a_share, 4),
    }


def check_quality_gates(
    pf: float,
    stopout_ratio: float,
    class_a_share: float,
) -> bool:
    """Check if result passes quality gates."""
    return (
        pf >= MIN_PF
        and stopout_ratio <= MAX_STOPOUT_RATIO
        and class_a_share >= MIN_CLASS_A_SHARE
    )


# ---------------------------------------------------------------------------
# Backtest runner
# ---------------------------------------------------------------------------

def run_single_test(
    config: dict,
    data: dict,
    coins: list[str],
    indicators: dict,
    market_ctx: dict,
    param_overrides: dict | None = None,
    test_name: str = "",
    universe_label: str = "",
) -> dict:
    """Run a single backtest with optional param overrides.

    Returns a result dict ready for the output JSON.
    """
    # Build params: copy original + apply overrides
    params = dict(config["params"])
    if param_overrides:
        params.update(param_overrides)

    # Inject market context
    enriched_params = {**params, "__market__": market_ctx}

    t0 = time.time()
    bt = run_backtest(
        data=data,
        coins=coins,
        signal_fn=config["signal_fn"],
        params=enriched_params,
        indicators=indicators,
        exit_mode="dc",
    )
    elapsed = time.time() - t0

    # Quality metrics
    qm = compute_quality_metrics(bt.trade_list)
    quality_pass = check_quality_gates(bt.pf, qm["stopout_ratio"], qm["class_a_share"])

    # Trade frequency
    trades_per_week = bt.trades / DATASET_WEEKS if DATASET_WEEKS > 0 else 0
    trades_per_day = bt.trades / DATASET_DAYS if DATASET_DAYS > 0 else 0

    # Clean overrides for serialization (remove None values)
    clean_overrides = {}
    if param_overrides:
        clean_overrides = {k: v for k, v in param_overrides.items() if v is not None}

    result = {
        "config_id": config["id"],
        "family": config["family"],
        "hypothesis_name": config.get("hypothesis_name", ""),
        "test": test_name,
        "universe": universe_label,
        "param_overrides": clean_overrides,
        "trades": bt.trades,
        "trades_per_week": round(trades_per_week, 2),
        "trades_per_day": round(trades_per_day, 2),
        "pf": round(min(bt.pf, 99.99), 4),
        "wr": round(bt.wr, 2),
        "pnl": round(bt.pnl, 2),
        "dd": round(bt.dd, 2),
        "stopout_ratio": qm["stopout_ratio"],
        "class_a_share": qm["class_a_share"],
        "quality_pass": quality_pass,
        "elapsed_s": round(elapsed, 2),
    }

    # Console output
    qp_mark = "PASS" if quality_pass else "FAIL"
    override_str = ""
    if clean_overrides:
        override_str = " | " + ", ".join(f"{k}={v}" for k, v in clean_overrides.items())
    print(
        f"  [{qp_mark:4s}] {config['id']:<50s} "
        f"| {universe_label:<15s} | {bt.trades:4d}tr "
        f"| PF {min(bt.pf, 99.99):5.2f} | ${bt.pnl:+8.2f} "
        f"| stop%={qm['stopout_ratio']:.2f} A%={qm['class_a_share']:.2f} "
        f"| {trades_per_day:.1f}/d{override_str}"
    )

    return result


# ---------------------------------------------------------------------------
# Test 1: Full Pool (526 vs 487 coins)
# ---------------------------------------------------------------------------

def test_full_pool(
    configs: list[dict],
    data: dict,
    all_coins: list[str],
    universe_coins: list[str],
    indicators_all: dict,
    indicators_uni: dict,
    market_ctx_all: dict,
    market_ctx_uni: dict,
) -> list[dict]:
    """Test each top-5 config on both 526-coin and 487-coin pools."""
    results = []
    print(f"\n{'=' * 90}")
    print(f"  TEST 1: Full Pool (526 coins vs 487 coins)")
    print(f"{'=' * 90}")

    for cfg in configs:
        # 487-coin universe (baseline)
        r_uni = run_single_test(
            cfg, data, universe_coins, indicators_uni, market_ctx_uni,
            test_name="full_pool",
            universe_label="universe_487",
        )
        results.append(r_uni)

        # 526-coin full pool
        r_all = run_single_test(
            cfg, data, all_coins, indicators_all, market_ctx_all,
            test_name="full_pool",
            universe_label="all_526",
        )
        results.append(r_all)

        # Delta summary
        delta_trades = r_all["trades"] - r_uni["trades"]
        delta_pf = r_all["pf"] - r_uni["pf"]
        print(
            f"    delta: {delta_trades:+d} trades, "
            f"PF {delta_pf:+.2f}, "
            f"frequency {r_all['trades_per_day']:.1f}/d vs {r_uni['trades_per_day']:.1f}/d"
        )
        print()

    return results


# ---------------------------------------------------------------------------
# Test 2: RSI Threshold Sensitivity
# ---------------------------------------------------------------------------

def test_rsi_sensitivity(
    configs: list[dict],
    data: dict,
    coins: list[str],
    indicators: dict,
    market_ctx: dict,
) -> list[dict]:
    """Test RSI threshold sensitivity for each top-5 config."""
    results = []
    print(f"\n{'=' * 90}")
    print(f"  TEST 2: RSI Threshold Sensitivity (on 487-coin universe)")
    print(f"{'=' * 90}")

    for cfg in configs:
        base_rsi = cfg["params"].get("rsi_max", 40)
        grid = RSI_GRID.get(base_rsi, [base_rsi])
        print(f"\n  Config: {cfg['id']} (base rsi_max={base_rsi})")

        for rsi_val in grid:
            overrides = {}
            if rsi_val != base_rsi:
                overrides = {"rsi_max": rsi_val}

            r = run_single_test(
                cfg, data, coins, indicators, market_ctx,
                param_overrides=overrides if overrides else None,
                test_name="rsi_sensitivity",
                universe_label="universe_487",
            )
            # Mark the override even if same as base (for clarity)
            r["param_overrides"] = {"rsi_max": rsi_val}
            results.append(r)

    return results


# ---------------------------------------------------------------------------
# Test 3: Volume Threshold Sensitivity
# ---------------------------------------------------------------------------

def _get_vol_param_and_grid(params: dict) -> list[tuple[str, float, list[float]]]:
    """Determine which volume param(s) the config uses and return grid(s).

    Returns list of (param_name, base_value, grid_values).
    """
    vol_params = []

    # vol_mult (Volume Capitulation family)
    if "vol_mult" in params:
        base = params["vol_mult"]
        grid = VOL_MULT_GRID.get(base, [base])
        vol_params.append(("vol_mult", base, grid))

    # vol_spike_mult (DC-Lite family)
    if "vol_spike_mult" in params:
        base = params["vol_spike_mult"]
        grid = VOL_SPIKE_MULT_GRID.get(base, [base])
        vol_params.append(("vol_spike_mult", base, grid))

    # vol_floor_mult (Z-Score Extreme, Wick Rejection, etc.)
    if "vol_floor_mult" in params:
        base = params["vol_floor_mult"]
        grid = VOL_FLOOR_MULT_GRID.get(base, [base])
        vol_params.append(("vol_floor_mult", base, grid))

    return vol_params


def test_vol_sensitivity(
    configs: list[dict],
    data: dict,
    coins: list[str],
    indicators: dict,
    market_ctx: dict,
) -> list[dict]:
    """Test volume threshold sensitivity for each top-5 config."""
    results = []
    print(f"\n{'=' * 90}")
    print(f"  TEST 3: Volume Threshold Sensitivity (on 487-coin universe)")
    print(f"{'=' * 90}")

    for cfg in configs:
        vol_params = _get_vol_param_and_grid(cfg["params"])

        if not vol_params:
            print(f"\n  Config: {cfg['id']} -- no volume params found, skipping")
            continue

        for param_name, base_val, grid in vol_params:
            print(f"\n  Config: {cfg['id']} ({param_name}={base_val})")

            for vol_val in grid:
                overrides = {}
                if vol_val != base_val:
                    overrides = {param_name: vol_val}

                r = run_single_test(
                    cfg, data, coins, indicators, market_ctx,
                    param_overrides=overrides if overrides else None,
                    test_name="vol_sensitivity",
                    universe_label="universe_487",
                )
                # Mark the override for clarity
                r["param_overrides"] = {param_name: vol_val}
                results.append(r)

    return results


# ---------------------------------------------------------------------------
# Output generation
# ---------------------------------------------------------------------------

def _build_summary(results: list[dict]) -> dict:
    """Build summary section from all results."""
    if not results:
        return {
            "best_frequency_config": "N/A",
            "best_frequency_trades_per_day": 0,
            "best_pf_config": "N/A",
            "recommendations": [],
        }

    # Filter to quality-passing results only for "best" selections
    passing = [r for r in results if r["quality_pass"]]

    if passing:
        best_freq = max(passing, key=lambda r: r["trades_per_day"])
        best_pf = max(passing, key=lambda r: r["pf"])
    else:
        best_freq = max(results, key=lambda r: r["trades_per_day"])
        best_pf = max(results, key=lambda r: r["pf"])

    # Build recommendations
    recs = []

    # Check if any config hits 1+ trade/day with quality gates
    daily_traders = [r for r in passing if r["trades_per_day"] >= 1.0]
    if daily_traders:
        recs.append(
            f"{len(daily_traders)} config(s) achieve >=1 trade/day "
            f"while passing quality gates."
        )
    else:
        recs.append(
            "No config achieves >=1 trade/day while passing quality gates. "
            "4H frequency is structurally low."
        )

    # Check full_pool delta
    full_pool_results = [r for r in results if r["test"] == "full_pool"]
    if full_pool_results:
        uni_results = [r for r in full_pool_results if r["universe"] == "universe_487"]
        all_results = [r for r in full_pool_results if r["universe"] == "all_526"]
        if uni_results and all_results:
            avg_delta_trades = (
                sum(r["trades"] for r in all_results) / len(all_results)
                - sum(r["trades"] for r in uni_results) / len(uni_results)
            )
            recs.append(
                f"Full pool (526 coins) adds avg {avg_delta_trades:+.0f} "
                f"trades vs 487-coin universe."
            )

    # RSI sensitivity findings
    rsi_results = [r for r in results if r["test"] == "rsi_sensitivity"]
    if rsi_results:
        rsi_passing = [r for r in rsi_results if r["quality_pass"]]
        recs.append(
            f"RSI sensitivity: {len(rsi_passing)}/{len(rsi_results)} "
            f"configs pass quality gates."
        )

    # Vol sensitivity findings
    vol_results = [r for r in results if r["test"] == "vol_sensitivity"]
    if vol_results:
        vol_passing = [r for r in vol_results if r["quality_pass"]]
        recs.append(
            f"Volume sensitivity: {len(vol_passing)}/{len(vol_results)} "
            f"configs pass quality gates."
        )

    best_freq_label = (
        f"{best_freq['config_id']}"
        + (f" ({best_freq['param_overrides']})" if best_freq["param_overrides"] else "")
    )
    best_pf_label = (
        f"{best_pf['config_id']}"
        + (f" ({best_pf['param_overrides']})" if best_pf["param_overrides"] else "")
    )

    return {
        "best_frequency_config": best_freq_label,
        "best_frequency_trades_per_day": best_freq["trades_per_day"],
        "best_pf_config": best_pf_label,
        "best_pf_value": best_pf["pf"],
        "total_tests": len(results),
        "quality_pass_count": len(passing),
        "recommendations": recs,
    }


def _write_json(results: list[dict], summary: dict, git_hash: str) -> Path:
    """Write results to JSON."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "sprint4_tradefreq.json"

    payload = {
        "experiment_id": "sprint4_tradefreq",
        "dataset_id": DEFAULT_DATASET,
        "fee_model": "kraken_spot_26bps",
        "git_hash": git_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "quality_gates": {
            "max_stopout_ratio": MAX_STOPOUT_RATIO,
            "min_class_a_share": MIN_CLASS_A_SHARE,
            "min_pf": MIN_PF,
        },
        "dataset_info": {
            "total_bars_approx": 721,
            "timeframe": "4H",
            "duration_days": DATASET_DAYS,
            "duration_weeks": DATASET_WEEKS,
        },
        "results": results,
        "summary": summary,
    }

    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)

    return out_path


def _write_markdown(results: list[dict], summary: dict, git_hash: str) -> Path:
    """Write human-readable markdown report."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "sprint4_tradefreq.md"

    lines = [
        "# Sprint 4 -- Trade Frequency Sensitivity Analysis",
        "",
        f"- **Dataset**: {DEFAULT_DATASET}",
        f"- **Fee model**: Kraken spot 26 bps/side",
        f"- **Git**: {git_hash}",
        f"- **Generated**: {datetime.now(timezone.utc).isoformat()}",
        f"- **Quality gates**: stopout <= {MAX_STOPOUT_RATIO:.0%}, "
        f"class_a >= {MIN_CLASS_A_SHARE:.0%}, PF >= {MIN_PF}",
        f"- **Dataset span**: ~{DATASET_DAYS:.0f} days (~{DATASET_WEEKS:.1f} weeks)",
        "",
    ]

    # Summary
    lines.extend([
        "## Summary",
        "",
        f"- **Total tests**: {summary['total_tests']}",
        f"- **Quality pass**: {summary['quality_pass_count']}",
        f"- **Best frequency**: {summary['best_frequency_config']} "
        f"({summary['best_frequency_trades_per_day']:.1f} trades/day)",
        f"- **Best PF**: {summary['best_pf_config']} (PF={summary.get('best_pf_value', 'N/A')})",
        "",
    ])
    if summary.get("recommendations"):
        lines.append("### Recommendations")
        for rec in summary["recommendations"]:
            lines.append(f"- {rec}")
        lines.append("")

    # Test 1: Full Pool
    full_pool = [r for r in results if r["test"] == "full_pool"]
    if full_pool:
        lines.extend([
            "## Test 1: Full Pool (526 coins vs 487 coins)",
            "",
            "| Config | Universe | Trades | Tr/wk | Tr/day | PF | WR | P&L | DD | Stop% | A% | Quality |",
            "|--------|----------|--------|-------|--------|------|------|------|------|-------|-----|---------|",
        ])
        for r in full_pool:
            qp = "PASS" if r["quality_pass"] else "FAIL"
            lines.append(
                f"| {r['config_id']} | {r['universe']} "
                f"| {r['trades']} | {r['trades_per_week']:.1f} | {r['trades_per_day']:.1f} "
                f"| {r['pf']:.2f} | {r['wr']:.1f}% | ${r['pnl']:+,.2f} | {r['dd']:.1f}% "
                f"| {r['stopout_ratio']:.2f} | {r['class_a_share']:.2f} | {qp} |"
            )
        lines.append("")

    # Test 2: RSI Sensitivity
    rsi_results = [r for r in results if r["test"] == "rsi_sensitivity"]
    if rsi_results:
        lines.extend([
            "## Test 2: RSI Threshold Sensitivity",
            "",
            "| Config | RSI | Trades | Tr/day | PF | WR | P&L | DD | Stop% | A% | Quality |",
            "|--------|-----|--------|--------|------|------|------|------|-------|-----|---------|",
        ])
        for r in rsi_results:
            qp = "PASS" if r["quality_pass"] else "FAIL"
            rsi_val = r["param_overrides"].get("rsi_max", "base")
            lines.append(
                f"| {r['config_id']} | {rsi_val} "
                f"| {r['trades']} | {r['trades_per_day']:.1f} "
                f"| {r['pf']:.2f} | {r['wr']:.1f}% | ${r['pnl']:+,.2f} | {r['dd']:.1f}% "
                f"| {r['stopout_ratio']:.2f} | {r['class_a_share']:.2f} | {qp} |"
            )
        lines.append("")

    # Test 3: Volume Sensitivity
    vol_results = [r for r in results if r["test"] == "vol_sensitivity"]
    if vol_results:
        lines.extend([
            "## Test 3: Volume Threshold Sensitivity",
            "",
            "| Config | Param | Value | Trades | Tr/day | PF | P&L | DD | Stop% | A% | Quality |",
            "|--------|-------|-------|--------|--------|------|------|------|-------|-----|---------|",
        ])
        for r in vol_results:
            qp = "PASS" if r["quality_pass"] else "FAIL"
            overrides = r["param_overrides"]
            if overrides:
                param_name = list(overrides.keys())[0]
                param_val = overrides[param_name]
            else:
                param_name = "base"
                param_val = "-"
            lines.append(
                f"| {r['config_id']} | {param_name} | {param_val} "
                f"| {r['trades']} | {r['trades_per_day']:.1f} "
                f"| {r['pf']:.2f} | ${r['pnl']:+,.2f} | {r['dd']:.1f}% "
                f"| {r['stopout_ratio']:.2f} | {r['class_a_share']:.2f} | {qp} |"
            )
        lines.append("")

    # Trade frequency overview (all results sorted by trades/day descending)
    lines.extend([
        "## Trade Frequency Overview (all tests, sorted by trades/day)",
        "",
        "| # | Config | Test | Overrides | Tr/day | Tr/wk | Trades | PF | Quality |",
        "|---|--------|------|-----------|--------|-------|--------|------|---------|",
    ])
    sorted_results = sorted(results, key=lambda r: -r["trades_per_day"])
    for i, r in enumerate(sorted_results[:30], 1):
        qp = "PASS" if r["quality_pass"] else "FAIL"
        overrides_str = json.dumps(r["param_overrides"]) if r["param_overrides"] else "-"
        lines.append(
            f"| {i} | {r['config_id']} | {r['test']} | {overrides_str} "
            f"| {r['trades_per_day']:.1f} | {r['trades_per_week']:.1f} "
            f"| {r['trades']} | {r['pf']:.2f} | {qp} |"
        )
    lines.append("")

    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sprint 4 Trade Frequency Sensitivity Analysis"
    )
    parser.add_argument(
        "--only", default=None,
        help="Comma-separated config ID fragments to filter (e.g., '041,032')"
    )
    parser.add_argument(
        "--test", default=None,
        choices=["full_pool", "rsi_sensitivity", "vol_sensitivity"],
        help="Run only a specific test (default: all)"
    )
    args = parser.parse_args()

    git_hash = _git_hash()
    run_tests = args.test  # None = all

    print(f"\n{'=' * 90}")
    print(f"  Sprint 4 Trade Frequency Sensitivity Analysis")
    print(f"{'=' * 90}")
    print(f"  Git hash: {git_hash}")
    print(f"  Fee model: Kraken spot {KRAKEN_FEE * 10000:.0f} bps/side")

    # -----------------------------------------------------------------------
    # Load all configs and filter to top-5
    # -----------------------------------------------------------------------
    all_configs = build_sweep_configs()
    top5_configs = []
    for tid in TOP5_CONFIG_IDS:
        found = [c for c in all_configs if c["id"] == tid]
        if found:
            top5_configs.append(found[0])
        else:
            print(f"  WARNING: config '{tid}' not found in hypotheses!")

    # Apply --only filter
    if args.only:
        fragments = [f.strip() for f in args.only.split(",")]
        filtered = []
        for cfg in top5_configs:
            if any(frag in cfg["id"] for frag in fragments):
                filtered.append(cfg)
        top5_configs = filtered
        print(f"  Filtered to: {len(top5_configs)} configs")

    print(f"  Top-5 configs loaded: {len(top5_configs)}")
    for cfg in top5_configs:
        print(f"    {cfg['id']} ({cfg['family']})")

    # -----------------------------------------------------------------------
    # Load dataset
    # -----------------------------------------------------------------------
    print(f"\n  Loading dataset...")
    t0 = time.time()
    dataset_path = resolve_dataset(DEFAULT_DATASET)
    with open(dataset_path) as f:
        data = json.load(f)
    all_coins = sorted([k for k in data.keys() if not k.startswith("_")])
    print(f"  All coins: {len(all_coins)}")
    print(f"  Data loaded: {time.time() - t0:.1f}s")

    # Load 487-coin universe
    universe_path = REPO_ROOT / "strategies" / "4h" / "universe_sprint1.json"
    with open(universe_path) as f:
        universe_data = json.load(f)
    universe_coins = universe_data["coins"]
    print(f"  Universe coins: {len(universe_coins)}")

    # -----------------------------------------------------------------------
    # Precompute indicators for BOTH coin sets
    # -----------------------------------------------------------------------
    # Universe indicators (487 coins)
    print(f"\n  Precomputing indicators (487-coin universe)...")
    t1 = time.time()
    indicators_uni = precompute_all(data, universe_coins)
    print(f"  Universe indicators: {time.time() - t1:.1f}s")

    # Market context for universe
    print(f"  Precomputing market context (universe)...")
    t2 = time.time()
    market_ctx_uni = precompute_sprint2_context(data, universe_coins, momentum_period=20)
    print(f"  Universe market context: {time.time() - t2:.1f}s")

    # Full pool indicators (526 coins) -- only if needed
    indicators_all = None
    market_ctx_all = None
    if run_tests is None or run_tests == "full_pool":
        print(f"\n  Precomputing indicators (526-coin full pool)...")
        t3 = time.time()
        indicators_all = precompute_all(data, all_coins)
        print(f"  Full pool indicators: {time.time() - t3:.1f}s")

        print(f"  Precomputing market context (full pool)...")
        t4 = time.time()
        market_ctx_all = precompute_sprint2_context(data, all_coins, momentum_period=20)
        print(f"  Full pool market context: {time.time() - t4:.1f}s")

    # -----------------------------------------------------------------------
    # Run tests
    # -----------------------------------------------------------------------
    all_results: list[dict] = []

    if run_tests is None or run_tests == "full_pool":
        assert indicators_all is not None
        assert market_ctx_all is not None
        results = test_full_pool(
            top5_configs, data,
            all_coins, universe_coins,
            indicators_all, indicators_uni,
            market_ctx_all, market_ctx_uni,
        )
        all_results.extend(results)

    if run_tests is None or run_tests == "rsi_sensitivity":
        results = test_rsi_sensitivity(
            top5_configs, data,
            universe_coins, indicators_uni, market_ctx_uni,
        )
        all_results.extend(results)

    if run_tests is None or run_tests == "vol_sensitivity":
        results = test_vol_sensitivity(
            top5_configs, data,
            universe_coins, indicators_uni, market_ctx_uni,
        )
        all_results.extend(results)

    # -----------------------------------------------------------------------
    # Build summary and write output
    # -----------------------------------------------------------------------
    summary = _build_summary(all_results)

    print(f"\n{'=' * 90}")
    print(f"  RESULTS SUMMARY")
    print(f"{'=' * 90}")
    print(f"  Total tests: {summary['total_tests']}")
    print(f"  Quality pass: {summary['quality_pass_count']}")
    print(f"  Best frequency: {summary['best_frequency_config']} "
          f"({summary['best_frequency_trades_per_day']:.1f} trades/day)")
    print(f"  Best PF: {summary['best_pf_config']} "
          f"(PF={summary.get('best_pf_value', 'N/A')})")
    for rec in summary.get("recommendations", []):
        print(f"  -> {rec}")

    json_path = _write_json(all_results, summary, git_hash)
    md_path = _write_markdown(all_results, summary, git_hash)

    print(f"\n  Output JSON: {json_path}")
    print(f"  Output MD:   {md_path}")
    print(f"{'=' * 90}\n")


if __name__ == "__main__":
    main()

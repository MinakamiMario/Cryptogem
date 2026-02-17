#!/usr/bin/env python3
"""
HF Latency Stress — 4H variant research.

Monte Carlo stress test for latency fragility. Instead of a fixed fee bump,
simulates random entry delays of 0, 1, or 2 candles per-trade by sampling
an effective fee from a delay-weighted distribution.

Fee mapping:
  - 0 candles delay:  0.0026  (KRAKEN_FEE baseline)
  - 1 candle  delay:  0.0102  (2*KRAKEN_FEE + 50bps slippage)
  - 2 candles delay:  0.0152  (2*KRAKEN_FEE + 100bps slippage)

Sampling weights: [0.50, 0.35, 0.15]  (50% on-time, 35% 1-candle, 15% 2-candle)

Also runs deterministic tests at each fixed delay level (0, 1, 2 candles)
to isolate which delay causes the most damage.

Usage:
    python strategies/hf/hf_latency_stress.py
    python strategies/hf/hf_latency_stress.py --universe tradeable
    python strategies/hf/hf_latency_stress.py --universe live
    python strategies/hf/hf_latency_stress.py --trials 100

Outputs:
    reports/hf/latency_stress_001.json  -- structured results
    reports/hf/latency_stress_001.md    -- human-readable report
"""

import sys
import json
import time
import random
import argparse
import statistics
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

# Fee mapping for delay levels
FEE_0_CANDLE = KRAKEN_FEE                        # 0.0026
FEE_1_CANDLE = KRAKEN_FEE * 2 + 0.005            # 0.0102
FEE_2_CANDLE = KRAKEN_FEE * 2 + 0.010            # 0.0152

DELAY_FEES = [FEE_0_CANDLE, FEE_1_CANDLE, FEE_2_CANDLE]
DELAY_WEIGHTS = [0.50, 0.35, 0.15]
DELAY_LABELS = ["0-candle (on-time)", "1-candle delay", "2-candle delay"]

# Verdict thresholds
SURVIVAL_FRAGILE = 0.70
SURVIVAL_MODERATE = 0.90

# Configs to test
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_pf(pf):
    """Cap infinite PF at 99.0."""
    if pf == float("inf"):
        return 99.0
    return round(pf, 2)


def percentile(data_list, p):
    """Compute percentile p (0-100) from sorted data."""
    if not data_list:
        return 0.0
    sorted_data = sorted(data_list)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])


# ---------------------------------------------------------------------------
# Deterministic delay tests
# ---------------------------------------------------------------------------
def run_deterministic_tests(indicators, coins, cfg, config_name):
    """Run backtest at each fixed delay level (0, 1, 2 candles)."""
    print(f"    Running deterministic delay tests...")
    results = []

    for i, (fee, label) in enumerate(zip(DELAY_FEES, DELAY_LABELS)):
        t0 = time.time()
        r = run_backtest(indicators, coins, cfg, fee_override=fee)
        elapsed = time.time() - t0

        pnl = round(r["pnl"], 2)
        pf = safe_pf(r["pf"])
        dd = round(r["dd"], 1)
        trades = r["trades"]
        wr = round(r["wr"], 1)

        result = {
            "delay_candles": i,
            "label": label,
            "fee": round(fee, 6),
            "fee_bps": round(fee * 10000, 1),
            "pnl": pnl,
            "pf": pf,
            "dd": dd,
            "trades": trades,
            "wr": wr,
            "profitable": pnl > 0,
            "elapsed_s": round(elapsed, 2),
        }
        results.append(result)
        print(f"      {label}: P&L=${pnl:+,.2f}  PF={pf}  DD={dd}%  "
              f"trades={trades}  ({elapsed:.1f}s)")

    # Compute damage from each delay relative to baseline
    baseline_pnl = results[0]["pnl"]
    for r in results:
        delta = r["pnl"] - baseline_pnl
        delta_pct = (delta / abs(baseline_pnl) * 100) if baseline_pnl != 0 else 0.0
        r["pnl_delta"] = round(delta, 2)
        r["pnl_delta_pct"] = round(delta_pct, 1)

    # Identify worst delay
    worst_idx = min(range(len(results)), key=lambda i: results[i]["pnl"])
    worst = results[worst_idx]

    return {
        "config": config_name,
        "levels": results,
        "baseline_pnl": baseline_pnl,
        "worst_delay": {
            "label": worst["label"],
            "delay_candles": worst["delay_candles"],
            "pnl": worst["pnl"],
            "pnl_delta": worst["pnl_delta"],
            "pnl_delta_pct": worst["pnl_delta_pct"],
        },
    }


# ---------------------------------------------------------------------------
# Monte Carlo trials
# ---------------------------------------------------------------------------
def run_monte_carlo(indicators, coins, cfg, config_name, n_trials):
    """Run N Monte Carlo trials, sampling fee from delay distribution."""
    print(f"    Running {n_trials} Monte Carlo trials...")
    t0 = time.time()

    trial_results = []
    for trial in range(n_trials):
        # Sample a random fee from the delay distribution
        fee = random.choices(DELAY_FEES, weights=DELAY_WEIGHTS, k=1)[0]

        r = run_backtest(indicators, coins, cfg, fee_override=fee)

        pf = safe_pf(r["pf"])
        trial_results.append({
            "trial": trial + 1,
            "fee_sampled": round(fee, 6),
            "pnl": round(r["pnl"], 2),
            "pf": pf,
            "dd": round(r["dd"], 1),
            "trades": r["trades"],
            "wr": round(r["wr"], 1),
            "profitable": r["pnl"] > 0,
        })

        # Progress indicator every 10 trials
        if (trial + 1) % 10 == 0:
            elapsed_so_far = time.time() - t0
            print(f"      Trial {trial + 1}/{n_trials} "
                  f"({elapsed_so_far:.1f}s elapsed)")

    elapsed = time.time() - t0

    # Compute distribution statistics
    pnl_values = [t["pnl"] for t in trial_results]
    pf_values = [t["pf"] for t in trial_results]
    dd_values = [t["dd"] for t in trial_results]

    n_profitable = sum(1 for t in trial_results if t["profitable"])
    survival_rate = n_profitable / n_trials if n_trials > 0 else 0.0

    # Verdict
    if survival_rate < SURVIVAL_FRAGILE:
        verdict = "FRAGILE"
    elif survival_rate < SURVIVAL_MODERATE:
        verdict = "MODERATE"
    else:
        verdict = "ROBUST"

    distribution = {
        "pnl": {
            "mean": round(statistics.mean(pnl_values), 2),
            "median": round(statistics.median(pnl_values), 2),
            "stdev": round(statistics.stdev(pnl_values), 2) if len(pnl_values) > 1 else 0.0,
            "p5": round(percentile(pnl_values, 5), 2),
            "p25": round(percentile(pnl_values, 25), 2),
            "p75": round(percentile(pnl_values, 75), 2),
            "p95": round(percentile(pnl_values, 95), 2),
            "min": round(min(pnl_values), 2),
            "max": round(max(pnl_values), 2),
        },
        "pf": {
            "mean": round(statistics.mean(pf_values), 2),
            "median": round(statistics.median(pf_values), 2),
            "min": round(min(pf_values), 2),
            "max": round(max(pf_values), 2),
        },
        "dd": {
            "mean": round(statistics.mean(dd_values), 1),
            "median": round(statistics.median(dd_values), 1),
            "max": round(max(dd_values), 1),
            "p95": round(percentile(dd_values, 95), 1),
        },
    }

    # Fee distribution actually sampled
    fee_counts = {}
    for t in trial_results:
        fee_str = f"{t['fee_sampled']:.4f}"
        fee_counts[fee_str] = fee_counts.get(fee_str, 0) + 1

    print(f"      Done: survival_rate={survival_rate*100:.1f}%, "
          f"mean_pnl=${distribution['pnl']['mean']:+,.2f}, "
          f"verdict={verdict} ({elapsed:.1f}s)")

    return {
        "config": config_name,
        "n_trials": n_trials,
        "seed": 42,
        "delay_fees": [round(f, 6) for f in DELAY_FEES],
        "delay_weights": DELAY_WEIGHTS,
        "elapsed_s": round(elapsed, 2),
        "trials": trial_results,
        "distribution": distribution,
        "survival_rate": round(survival_rate, 4),
        "survival_pct": round(survival_rate * 100, 1),
        "n_profitable": n_profitable,
        "n_unprofitable": n_trials - n_profitable,
        "fee_sample_counts": fee_counts,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Full analysis for one config
# ---------------------------------------------------------------------------
def analyze_config(name, cfg, indicators, coins, n_trials):
    """Run deterministic + Monte Carlo analysis for a single config."""
    print(f"\n  --- Latency Stress: {name} ---")
    print(f"  Config: {json.dumps(cfg, sort_keys=True)}")

    t0 = time.time()

    deterministic = run_deterministic_tests(indicators, coins, cfg, name)
    monte_carlo = run_monte_carlo(indicators, coins, cfg, name, n_trials)

    elapsed = time.time() - t0

    return {
        "name": name,
        "cfg": cfg,
        "deterministic": deterministic,
        "monte_carlo": monte_carlo,
        "elapsed_s": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------
def generate_markdown(all_results, meta):
    """Generate human-readable latency stress report."""
    lines = [
        "# HF Latency Stress Report -- 4H Variant Research",
        "",
        "> **Monte Carlo latency fragility test**: simulates random entry delays",
        "> of 0, 1, or 2 candles per trade via fee-based proxy.",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Universe**: {meta['universe']}",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Coins**: {meta['n_coins']}",
        f"**Trials per config**: {meta['n_trials']}",
        f"**Random seed**: {meta['seed']}",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
        "## Fee Model",
        "",
        "| Delay | Fee | Fee (bps) | Weight |",
        "|-------|-----|-----------|--------|",
    ]

    for i, (fee, label, weight) in enumerate(
        zip(DELAY_FEES, DELAY_LABELS, DELAY_WEIGHTS)
    ):
        lines.append(
            f"| {label} | {fee:.4f} | {fee*10000:.1f} | {weight*100:.0f}% |"
        )

    lines.extend([
        "",
        "## Verdict Thresholds",
        "",
        f"- **FRAGILE**: survival rate < {SURVIVAL_FRAGILE*100:.0f}%",
        f"- **MODERATE**: survival rate {SURVIVAL_FRAGILE*100:.0f}%--{SURVIVAL_MODERATE*100:.0f}%",
        f"- **ROBUST**: survival rate >= {SURVIVAL_MODERATE*100:.0f}%",
        "",
    ])

    # ---- Per-config sections ----
    for r in all_results:
        name = r["name"]
        det = r["deterministic"]
        mc = r["monte_carlo"]

        lines.extend([
            "---",
            "",
            f"## {name}",
            "",
            f"**Config**: `{json.dumps(r['cfg'], sort_keys=True)}`",
            "",
        ])

        # 1. Deterministic table
        lines.extend([
            "### 1. Deterministic Delay Tests",
            "",
            "| Delay | Fee (bps) | Trades | P&L | PF | DD% | WR% | Delta | Delta% |",
            "|-------|-----------|--------|-----|----|-----|-----|-------|--------|",
        ])
        for lev in det["levels"]:
            lines.append(
                f"| {lev['label']} | {lev['fee_bps']} "
                f"| {lev['trades']} | ${lev['pnl']:+,.2f} "
                f"| {lev['pf']} | {lev['dd']}% | {lev['wr']}% "
                f"| ${lev['pnl_delta']:+,.2f} | {lev['pnl_delta_pct']:+.1f}% |"
            )

        worst = det["worst_delay"]
        lines.extend([
            "",
            f"**Most damaging delay**: {worst['label']} "
            f"(P&L=${worst['pnl']:+,.2f}, delta={worst['pnl_delta_pct']:+.1f}%)",
            "",
        ])

        # 2. Monte Carlo distribution
        dist = mc["distribution"]
        lines.extend([
            "### 2. Monte Carlo Distribution",
            "",
            f"**Trials**: {mc['n_trials']} | "
            f"**Seed**: {mc['seed']}",
            "",
            "#### P&L Distribution",
            "",
            "| Statistic | Value |",
            "|-----------|-------|",
            f"| Mean | ${dist['pnl']['mean']:+,.2f} |",
            f"| Median | ${dist['pnl']['median']:+,.2f} |",
            f"| Std Dev | ${dist['pnl']['stdev']:,.2f} |",
            f"| P5 (worst 5%) | ${dist['pnl']['p5']:+,.2f} |",
            f"| P25 | ${dist['pnl']['p25']:+,.2f} |",
            f"| P75 | ${dist['pnl']['p75']:+,.2f} |",
            f"| P95 (best 5%) | ${dist['pnl']['p95']:+,.2f} |",
            f"| Min | ${dist['pnl']['min']:+,.2f} |",
            f"| Max | ${dist['pnl']['max']:+,.2f} |",
            "",
            "#### PF Distribution",
            "",
            "| Statistic | Value |",
            "|-----------|-------|",
            f"| Mean | {dist['pf']['mean']} |",
            f"| Median | {dist['pf']['median']} |",
            f"| Min | {dist['pf']['min']} |",
            f"| Max | {dist['pf']['max']} |",
            "",
            "#### Drawdown Distribution",
            "",
            "| Statistic | Value |",
            "|-----------|-------|",
            f"| Mean DD | {dist['dd']['mean']}% |",
            f"| Median DD | {dist['dd']['median']}% |",
            f"| P95 DD | {dist['dd']['p95']}% |",
            f"| Max DD | {dist['dd']['max']}% |",
            "",
        ])

        # Fee sample distribution
        lines.extend([
            "#### Fee Sample Counts",
            "",
            "| Fee | Count | Pct |",
            "|-----|-------|-----|",
        ])
        for fee_str, count in sorted(mc["fee_sample_counts"].items()):
            pct = count / mc["n_trials"] * 100
            lines.append(f"| {fee_str} | {count} | {pct:.1f}% |")
        lines.append("")

        # 3. Survival rate
        lines.extend([
            "### 3. Survival Rate",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Profitable trials | {mc['n_profitable']}/{mc['n_trials']} |",
            f"| Unprofitable trials | {mc['n_unprofitable']}/{mc['n_trials']} |",
            f"| **Survival rate** | **{mc['survival_pct']:.1f}%** |",
            "",
        ])

        # 4. Key finding
        # Determine which delay level causes the biggest absolute damage
        max_damage_level = max(
            det["levels"][1:],  # skip baseline
            key=lambda lev: abs(lev["pnl_delta"]),
        )

        lines.extend([
            "### 4. Key Finding",
            "",
            f"- The **{max_damage_level['label']}** causes the biggest absolute damage: "
            f"P&L delta of ${max_damage_level['pnl_delta']:+,.2f} "
            f"({max_damage_level['pnl_delta_pct']:+.1f}% vs baseline).",
        ])

        # Check if 2-candle is more damaging per-unit than 1-candle
        if len(det["levels"]) >= 3:
            d1 = det["levels"][1]
            d2 = det["levels"][2]
            if abs(d2["pnl_delta"]) > abs(d1["pnl_delta"]):
                marginal = d2["pnl_delta"] - d1["pnl_delta"]
                lines.append(
                    f"- Moving from 1-candle to 2-candle delay adds "
                    f"${marginal:+,.2f} additional damage."
                )
            else:
                lines.append(
                    "- The 1-candle delay already captures most of the "
                    "latency damage; 2-candle adds marginal impact."
                )

        # Live execution implication
        if mc["survival_pct"] >= 90:
            live_note = (
                "Strategy shows good resilience to random latency. "
                "Live execution with occasional 1-2 candle delays "
                "is unlikely to destroy profitability."
            )
        elif mc["survival_pct"] >= 70:
            live_note = (
                "Strategy shows moderate sensitivity to latency. "
                "Live execution should prioritize low-latency fills; "
                "sustained delays could erode edge significantly."
            )
        else:
            live_note = (
                "Strategy is highly fragile to latency variation. "
                "Even occasional entry delays can flip profitability negative. "
                "Do NOT deploy without guaranteed low-latency execution."
            )
        lines.extend([
            f"- **Live execution implication**: {live_note}",
            "",
        ])

        # 5. Verdict
        lines.extend([
            "### 5. Verdict",
            "",
            f"**{mc['verdict']}** (survival rate: {mc['survival_pct']:.1f}%)",
            "",
        ])

    # ---- Comparative summary (if two configs) ----
    if len(all_results) == 2:
        r0, r1 = all_results
        mc0, mc1 = r0["monte_carlo"], r1["monte_carlo"]
        d0, d1 = r0["deterministic"], r1["deterministic"]

        lines.extend([
            "---",
            "",
            "## Comparative Summary",
            "",
            f"| Metric | {r0['name']} | {r1['name']} |",
            f"|--------|{'---' * 8}|{'---' * 8}|",
            f"| Baseline P&L | ${d0['baseline_pnl']:+,.2f} "
            f"| ${d1['baseline_pnl']:+,.2f} |",
            f"| 1-candle P&L | ${d0['levels'][1]['pnl']:+,.2f} "
            f"| ${d1['levels'][1]['pnl']:+,.2f} |",
            f"| 2-candle P&L | ${d0['levels'][2]['pnl']:+,.2f} "
            f"| ${d1['levels'][2]['pnl']:+,.2f} |",
            f"| MC mean P&L | ${mc0['distribution']['pnl']['mean']:+,.2f} "
            f"| ${mc1['distribution']['pnl']['mean']:+,.2f} |",
            f"| MC P5 P&L | ${mc0['distribution']['pnl']['p5']:+,.2f} "
            f"| ${mc1['distribution']['pnl']['p5']:+,.2f} |",
            f"| Survival rate | {mc0['survival_pct']:.1f}% "
            f"| {mc1['survival_pct']:.1f}% |",
            f"| **Verdict** | **{mc0['verdict']}** "
            f"| **{mc1['verdict']}** |",
            "",
        ])

    lines.extend([
        "---",
        "",
        f"*Generated by hf_latency_stress.py -- 4H variant research*",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="HF Latency Stress -- 4H variant research"
    )
    parser.add_argument(
        "--universe",
        choices=["tradeable", "live"],
        default="tradeable",
        help="Which candle cache to use (default: tradeable)",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=50,
        help="Number of Monte Carlo trials per config (default: 50)",
    )
    args = parser.parse_args()

    # Reproducibility
    random.seed(42)

    print("=" * 70)
    print("  HF Latency Stress -- 4H Variant Research")
    print("  Monte Carlo latency fragility test")
    print("=" * 70)
    print(f"  Universe: {args.universe}")
    print(f"  Trials:   {args.trials}")
    print(f"  Seed:     42")

    # Load data
    data, coins, data_path = load_data(args.universe)
    n_bars = len(data[coins[0]]) if coins else 0
    print(f"  Loaded {len(coins)} coins, {n_bars} bars from {Path(data_path).name}")

    # Precompute indicators once
    print("  Precomputing indicators...")
    t_pre = time.time()
    indicators = precompute_all(data, coins)
    print(f"  Precompute: {time.time() - t_pre:.1f}s")

    t_start = time.time()

    # Run analysis for each config
    all_results = []
    for name, cfg in CONFIGS.items():
        result = analyze_config(name, cfg, indicators, coins, args.trials)
        all_results.append(result)

    total_time = time.time() - t_start

    # Meta info
    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "universe": args.universe,
        "data_file": data_path,
        "n_coins": len(coins),
        "n_bars": n_bars,
        "n_trials": args.trials,
        "seed": 42,
        "delay_fees": [round(f, 6) for f in DELAY_FEES],
        "delay_weights": DELAY_WEIGHTS,
        "delay_labels": DELAY_LABELS,
        "survival_thresholds": {
            "fragile_below": SURVIVAL_FRAGILE,
            "moderate_below": SURVIVAL_MODERATE,
        },
        "total_time_s": round(total_time, 2),
        "label": "4H variant research",
    }

    # Write JSON report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / "latency_stress_001.json"

    json_output = {
        "meta": meta,
        "results": {},
    }
    for r in all_results:
        # Omit per-trial detail from JSON to keep file manageable
        mc_summary = dict(r["monte_carlo"])
        mc_summary.pop("trials", None)

        json_output["results"][r["name"]] = {
            "name": r["name"],
            "cfg": r["cfg"],
            "deterministic": r["deterministic"],
            "monte_carlo": mc_summary,
            "elapsed_s": r["elapsed_s"],
        }

    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    print(f"\n  Wrote {json_path}")

    # Write Markdown report
    md_path = REPORTS_DIR / "latency_stress_001.md"
    md = generate_markdown(all_results, meta)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # Final summary
    print("\n" + "=" * 70)
    print("  LATENCY STRESS SUMMARY (4H variant research)")
    print("=" * 70)
    print(f"\n  {'Config':<20} {'Survival':<12} {'MC Mean P&L':<18} "
          f"{'MC P5 P&L':<18} {'Verdict'}")
    print("  " + "-" * 78)
    for r in all_results:
        mc = r["monte_carlo"]
        dist = mc["distribution"]
        print(f"  {r['name']:<20} {mc['survival_pct']:>5.1f}%      "
              f"${dist['pnl']['mean']:>+12,.2f}    "
              f"${dist['pnl']['p5']:>+12,.2f}    "
              f"{mc['verdict']}")

    print(f"\n  Total runtime: {total_time:.1f}s")
    print("  " + "=" * 65)


if __name__ == "__main__":
    main()

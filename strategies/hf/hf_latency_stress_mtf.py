#!/usr/bin/env python3
"""
HF Latency Stress MTF — Multi-timeframe latency stress test.

Monte Carlo stress test that simulates random execution delays (0-2 bars) on
entry signals.  At different timeframes, 1 bar of delay means different
wall-clock time (4h vs 1h vs 15m), so slippage impact varies.

Per-bar slippage estimates by timeframe:
  - 4h:  50 bps  (large bar-to-bar movement)
  - 1h:  25 bps  (moderate)
  - 15m: 12 bps  (small)

For each MC trial, a random extra fee = uniform(0, 2) * per_bar_slip is
added on top of the per-tier fee (T1=0.0031, T2=0.0056).

Tier-composite approach: run T1 and T2 separately with their own fee +
random latency penalty, then replay merged equity curve.

Survival gate: final_equity > 50% of INITIAL_CAPITAL in >= 95% of trials.

Usage:
    python strategies/hf/hf_latency_stress_mtf.py
    python strategies/hf/hf_latency_stress_mtf.py --timeframe 1h
    python strategies/hf/hf_latency_stress_mtf.py --timeframe 15m
    python strategies/hf/hf_latency_stress_mtf.py --timeframe 4h --trials 100

Outputs:
    reports/hf/latency_stress_{tf}_001.json  -- structured results
    reports/hf/latency_stress_{tf}_001.md    -- human-readable report
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
    check_entry_at_bar,
    KRAKEN_FEE,
    START_BAR,
    INITIAL_CAPITAL,
    COOLDOWN_BARS,
    COOLDOWN_AFTER_STOP,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"
TIERING_PATH = REPORTS_DIR / "universe_tiering_001.json"

# Per-timeframe data files and slippage estimates
TF_CONFIG = {
    "4h": {
        "cache_file": DATA_DIR / "candle_cache_tradeable.json",
        "per_bar_slip": 0.0050,   # 50 bps
        "bar_duration": "4 hours",
    },
    "1h": {
        "cache_file": DATA_DIR / "candle_cache_1h.json",
        "per_bar_slip": 0.0025,   # 25 bps
        "bar_duration": "1 hour",
    },
    "15m": {
        "cache_file": DATA_DIR / "candle_cache_15m.json",
        "per_bar_slip": 0.0012,   # 12 bps
        "bar_duration": "15 minutes",
    },
}

# Per-tier fees (same as friction_v2)
FEE_TIER1 = KRAKEN_FEE + 0.0005   # 0.0031
FEE_TIER2 = KRAKEN_FEE + 0.0030   # 0.0056

TIER_FEES = {1: FEE_TIER1, 2: FEE_TIER2}
TIER_LABELS = {1: "Tier 1 (Liquid)", 2: "Tier 2 (Mid)"}

# Configs under test (same as friction_v2)
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

CONFIGS = {
    "GRID_BEST": GRID_BEST,
    "Champion_H2": CHAMPION_H2,
}

# MC defaults
DEFAULT_TRIALS = 50
SURVIVAL_THRESHOLD = 0.50   # final_equity > 50% of INITIAL_CAPITAL
SURVIVAL_GATE_PCT = 0.95    # >= 95% of trials must survive


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_data(tf: str):
    """Load candle data for the given timeframe."""
    tf_cfg = TF_CONFIG[tf]
    path = tf_cfg["cache_file"]
    if not path.exists():
        # Fallback for 4h
        if tf == "4h":
            path = TRADING_BOT / "candle_cache_532.json"
        if not path.exists():
            print(f"ERROR: No data file found for timeframe={tf}")
            print(f"  Tried: {tf_cfg['cache_file']}")
            sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins, str(path)


def load_tier_assignments():
    """Load tier coin lists from universe_tiering_001.json (T1 + T2 only)."""
    if not TIERING_PATH.exists():
        print(f"ERROR: Tiering file not found: {TIERING_PATH}")
        print("  Run: python strategies/hf/hf_universe_tiering.py first")
        sys.exit(1)
    with open(TIERING_PATH) as f:
        tiering = json.load(f)
    tiers = {}
    tb = tiering.get("tier_breakdown", {})
    for tier_key in ("1", "2"):
        tiers[int(tier_key)] = tb.get(tier_key, {}).get("coins", [])
    return tiers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def safe_pf(pf):
    """Cap infinite PF at 99.0."""
    if pf == float("inf"):
        return 99.0
    return round(min(pf, 99.0), 2)


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


def replay_equity_curve(trade_list, initial_capital):
    """
    Replay equity curve from a merged trade_list sorted by entry_bar.

    Returns dict: {pnl, pf, dd, trades, wr, final_equity}
    """
    if not trade_list:
        return {
            "pnl": 0.0,
            "pf": 0.0,
            "dd": 0.0,
            "trades": 0,
            "wr": 0.0,
            "final_equity": float(initial_capital),
        }

    sorted_trades = sorted(
        trade_list, key=lambda t: (t["entry_bar"], t.get("exit_bar", 0))
    )

    equity = float(initial_capital)
    peak_eq = equity
    max_dd = 0.0

    total_win_pnl = 0.0
    total_loss_pnl = 0.0
    n_wins = 0

    for t in sorted_trades:
        pnl = t["pnl"]
        equity += pnl

        if pnl > 0:
            total_win_pnl += pnl
            n_wins += 1
        else:
            total_loss_pnl += pnl

        if equity > peak_eq:
            peak_eq = equity
        dd = (peak_eq - equity) / peak_eq * 100 if peak_eq > 0 else 0
        if dd > max_dd:
            max_dd = dd

    n_trades = len(sorted_trades)
    wr = (n_wins / n_trades * 100) if n_trades > 0 else 0.0
    abs_loss = abs(total_loss_pnl)
    pf = (total_win_pnl / abs_loss) if abs_loss > 0 else float("inf")

    return {
        "pnl": round(equity - initial_capital, 2),
        "pf": safe_pf(pf),
        "dd": round(max_dd, 1),
        "trades": n_trades,
        "wr": round(wr, 1),
        "final_equity": round(equity, 2),
    }


# ---------------------------------------------------------------------------
# Per-tier composite with random latency fee
# ---------------------------------------------------------------------------
def run_per_tier_composite_with_latency(
    data, tiers, cfg, tier_fees, per_bar_slip, rng,
):
    """
    Run backtest per tier with tier fee + random latency penalty.

    For each tier:
      - Sample delay ~ uniform(0, 2) for entire run (one delay per trial)
      - effective_fee = tier_fee + delay * per_bar_slip
      - run_backtest with fee_override=effective_fee
      - Collect trade_list

    Returns (composite_result, per_tier_results, delay_info)
    """
    all_trade_lists = []
    per_tier = {}
    delay_info = {}

    for tier_id in sorted(tiers.keys()):
        tier_coins = tiers[tier_id]
        base_fee = tier_fees[tier_id]

        if not tier_coins:
            per_tier[tier_id] = {
                "trades": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0, "dd": 0.0,
                "final_equity": INITIAL_CAPITAL, "fee": round(base_fee, 6),
                "fee_bps": round(base_fee * 10000, 1), "n_coins": 0,
                "delay": 0.0, "effective_fee": round(base_fee, 6),
            }
            continue

        # Sample random delay for this tier in this trial
        delay = rng.uniform(0, 2)
        latency_penalty = delay * per_bar_slip
        effective_fee = base_fee + latency_penalty

        indicators = precompute_all(data, tier_coins)
        result = run_backtest(indicators, tier_coins, cfg,
                              fee_override=effective_fee)

        trade_list = result.get("trade_list", [])
        for t in trade_list:
            t["_tier"] = tier_id

        all_trade_lists.extend(trade_list)

        per_tier[tier_id] = {
            "trades": result["trades"],
            "pnl": round(result["pnl"], 2),
            "pf": safe_pf(result["pf"]),
            "wr": round(result["wr"], 1),
            "dd": round(result["dd"], 1),
            "final_equity": round(result["final_equity"], 2),
            "fee": round(base_fee, 6),
            "fee_bps": round(base_fee * 10000, 1),
            "n_coins": len(tier_coins),
            "delay": round(delay, 4),
            "effective_fee": round(effective_fee, 6),
            "effective_fee_bps": round(effective_fee * 10000, 1),
        }

        delay_info[tier_id] = {
            "delay_bars": round(delay, 4),
            "latency_penalty": round(latency_penalty, 6),
            "latency_penalty_bps": round(latency_penalty * 10000, 1),
            "effective_fee": round(effective_fee, 6),
        }

    # Replay equity curve from merged trades
    composite = replay_equity_curve(all_trade_lists, INITIAL_CAPITAL)

    return composite, per_tier, delay_info


# ---------------------------------------------------------------------------
# Monte Carlo trials
# ---------------------------------------------------------------------------
def run_monte_carlo(data, tiers, cfg, config_name, per_bar_slip, n_trials):
    """Run N Monte Carlo trials with random latency per tier."""
    print(f"    Running {n_trials} Monte Carlo trials...")
    t0 = time.time()

    rng = random.Random(42)
    trial_results = []

    for trial in range(n_trials):
        composite, per_tier, delay_info = run_per_tier_composite_with_latency(
            data, tiers, cfg, TIER_FEES, per_bar_slip, rng,
        )

        survived = composite["final_equity"] > (INITIAL_CAPITAL * SURVIVAL_THRESHOLD)

        trial_results.append({
            "trial": trial + 1,
            "pnl": composite["pnl"],
            "pf": composite["pf"],
            "dd": composite["dd"],
            "trades": composite["trades"],
            "wr": composite["wr"],
            "final_equity": composite["final_equity"],
            "survived": survived,
            "delay_info": delay_info,
        })

        # Progress indicator every 10 trials
        if (trial + 1) % 10 == 0:
            elapsed_so_far = time.time() - t0
            print(f"      Trial {trial + 1}/{n_trials} "
                  f"({elapsed_so_far:.1f}s elapsed)")

    elapsed = time.time() - t0

    # Compute distribution statistics
    pnl_values = [t["pnl"] for t in trial_results]
    final_eq_values = [t["final_equity"] for t in trial_results]
    dd_values = [t["dd"] for t in trial_results]
    pf_values = [t["pf"] for t in trial_results]

    n_survived = sum(1 for t in trial_results if t["survived"])
    survival_rate = n_survived / n_trials if n_trials > 0 else 0.0

    # PASS/FAIL verdict
    verdict = "PASS" if survival_rate >= SURVIVAL_GATE_PCT else "FAIL"

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
        "final_equity": {
            "mean": round(statistics.mean(final_eq_values), 2),
            "median": round(statistics.median(final_eq_values), 2),
            "p5": round(percentile(final_eq_values, 5), 2),
            "p25": round(percentile(final_eq_values, 25), 2),
            "p75": round(percentile(final_eq_values, 75), 2),
            "p95": round(percentile(final_eq_values, 95), 2),
            "min": round(min(final_eq_values), 2),
            "max": round(max(final_eq_values), 2),
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

    print(f"      Done: survival_rate={survival_rate*100:.1f}%, "
          f"median_pnl=${distribution['pnl']['median']:+,.2f}, "
          f"verdict={verdict} ({elapsed:.1f}s)")

    return {
        "config": config_name,
        "n_trials": n_trials,
        "seed": 42,
        "per_bar_slip_bps": round(per_bar_slip * 10000, 1),
        "elapsed_s": round(elapsed, 2),
        "trials": trial_results,
        "distribution": distribution,
        "survival_rate": round(survival_rate, 4),
        "survival_pct": round(survival_rate * 100, 1),
        "n_survived": n_survived,
        "n_failed": n_trials - n_survived,
        "survival_threshold": SURVIVAL_THRESHOLD,
        "survival_gate_pct": SURVIVAL_GATE_PCT,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Full analysis for one config
# ---------------------------------------------------------------------------
def analyze_config(name, cfg, data, tiers, per_bar_slip, n_trials):
    """Run Monte Carlo latency stress analysis for a single config."""
    print(f"\n  --- Latency Stress MTF: {name} ---")
    print(f"  Config: {json.dumps(cfg, sort_keys=True)}")

    t0 = time.time()

    mc = run_monte_carlo(data, tiers, cfg, name, per_bar_slip, n_trials)

    elapsed = time.time() - t0

    return {
        "name": name,
        "cfg": cfg,
        "monte_carlo": mc,
        "elapsed_s": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------
def generate_markdown(all_results, meta, tf):
    """Generate human-readable multi-timeframe latency stress report."""
    tf_cfg = TF_CONFIG[tf]
    per_bar_slip_bps = round(tf_cfg["per_bar_slip"] * 10000, 1)

    lines = [
        f"# HF Latency Stress Report ({tf.upper()}) -- Multi-Timeframe",
        "",
        f"> **Monte Carlo latency stress test**: simulates random execution",
        f"> delays of 0-2 bars at {tf} resolution. 1 bar = {tf_cfg['bar_duration']}.",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Timeframe**: {tf}",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Coins (T1+T2)**: T1={meta['tier_counts']['1']}, T2={meta['tier_counts']['2']}",
        f"**Trials per config**: {meta['n_trials']}",
        f"**Random seed**: {meta['seed']}",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
        "## Latency Model",
        "",
        f"- **Per-bar slippage estimate ({tf})**: {per_bar_slip_bps} bps",
        f"- **Delay range**: uniform(0, 2) bars per trial",
        f"- **Max latency penalty**: {per_bar_slip_bps * 2:.1f} bps",
        f"- **Method**: For each MC trial, sample delay ~ U(0,2); "
        f"effective_fee = tier_fee + delay * {per_bar_slip_bps} bps",
        "",
        "| Tier | Base Fee (bps) | Max Effective Fee (bps) |",
        "|------|---------------|------------------------|",
        f"| Tier 1 (Liquid) | {FEE_TIER1*10000:.1f} | {(FEE_TIER1 + 2*tf_cfg['per_bar_slip'])*10000:.1f} |",
        f"| Tier 2 (Mid)    | {FEE_TIER2*10000:.1f} | {(FEE_TIER2 + 2*tf_cfg['per_bar_slip'])*10000:.1f} |",
        "",
        "## Survival Gate",
        "",
        f"- **Threshold**: final_equity > {SURVIVAL_THRESHOLD*100:.0f}% of "
        f"INITIAL_CAPITAL (${INITIAL_CAPITAL * SURVIVAL_THRESHOLD:,.0f})",
        f"- **Gate**: >= {SURVIVAL_GATE_PCT*100:.0f}% of trials must survive",
        f"- **Verdict**: PASS if survival >= {SURVIVAL_GATE_PCT*100:.0f}%, FAIL otherwise",
        "",
    ]

    # --- Per-config sections ---
    for r in all_results:
        name = r["name"]
        mc = r["monte_carlo"]
        dist = mc["distribution"]

        lines.extend([
            "---",
            "",
            f"## {name}",
            "",
            f"**Config**: `{json.dumps(r['cfg'], sort_keys=True)}`",
            "",
        ])

        # 1. Survival rate
        lines.extend([
            "### 1. Survival Rate",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Survived trials | {mc['n_survived']}/{mc['n_trials']} |",
            f"| Failed trials | {mc['n_failed']}/{mc['n_trials']} |",
            f"| **Survival rate** | **{mc['survival_pct']:.1f}%** |",
            f"| Gate ({SURVIVAL_GATE_PCT*100:.0f}%) | "
            f"**{mc['verdict']}** |",
            "",
        ])

        # 2. P&L distribution
        lines.extend([
            "### 2. P&L Distribution",
            "",
            "| Statistic | Value |",
            "|-----------|-------|",
            f"| P5 (worst 5%) | ${dist['pnl']['p5']:+,.2f} |",
            f"| P25 | ${dist['pnl']['p25']:+,.2f} |",
            f"| **Median** | **${dist['pnl']['median']:+,.2f}** |",
            f"| P75 | ${dist['pnl']['p75']:+,.2f} |",
            f"| P95 (best 5%) | ${dist['pnl']['p95']:+,.2f} |",
            f"| Mean | ${dist['pnl']['mean']:+,.2f} |",
            f"| Std Dev | ${dist['pnl']['stdev']:,.2f} |",
            f"| Min | ${dist['pnl']['min']:+,.2f} |",
            f"| Max | ${dist['pnl']['max']:+,.2f} |",
            "",
        ])

        # 3. Final equity distribution
        lines.extend([
            "### 3. Final Equity Distribution",
            "",
            "| Statistic | Value |",
            "|-----------|-------|",
            f"| P5 | ${dist['final_equity']['p5']:,.2f} |",
            f"| P25 | ${dist['final_equity']['p25']:,.2f} |",
            f"| Median | ${dist['final_equity']['median']:,.2f} |",
            f"| P75 | ${dist['final_equity']['p75']:,.2f} |",
            f"| P95 | ${dist['final_equity']['p95']:,.2f} |",
            f"| Min | ${dist['final_equity']['min']:,.2f} |",
            f"| Max | ${dist['final_equity']['max']:,.2f} |",
            "",
        ])

        # 4. Drawdown & PF
        lines.extend([
            "### 4. Drawdown & Profit Factor",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Mean DD | {dist['dd']['mean']}% |",
            f"| Median DD | {dist['dd']['median']}% |",
            f"| P95 DD | {dist['dd']['p95']}% |",
            f"| Max DD | {dist['dd']['max']}% |",
            f"| Mean PF | {dist['pf']['mean']} |",
            f"| Median PF | {dist['pf']['median']} |",
            f"| Min PF | {dist['pf']['min']} |",
            "",
        ])

        # 5. Verdict
        lines.extend([
            "### 5. Verdict",
            "",
            f"**{mc['verdict']}** -- survival rate {mc['survival_pct']:.1f}% "
            f"(gate: {SURVIVAL_GATE_PCT*100:.0f}%)",
            "",
        ])

    # --- Comparative summary (if two configs) ---
    if len(all_results) == 2:
        r0, r1 = all_results
        mc0, mc1 = r0["monte_carlo"], r1["monte_carlo"]
        d0, d1 = mc0["distribution"], mc1["distribution"]

        lines.extend([
            "---",
            "",
            "## Comparative Summary",
            "",
            f"| Metric | {r0['name']} | {r1['name']} |",
            f"|--------|{'---' * 8}|{'---' * 8}|",
            f"| Survival rate | {mc0['survival_pct']:.1f}% "
            f"| {mc1['survival_pct']:.1f}% |",
            f"| Median P&L | ${d0['pnl']['median']:+,.2f} "
            f"| ${d1['pnl']['median']:+,.2f} |",
            f"| P5 P&L | ${d0['pnl']['p5']:+,.2f} "
            f"| ${d1['pnl']['p5']:+,.2f} |",
            f"| P95 P&L | ${d0['pnl']['p95']:+,.2f} "
            f"| ${d1['pnl']['p95']:+,.2f} |",
            f"| Mean DD | {d0['dd']['mean']}% "
            f"| {d1['dd']['mean']}% |",
            f"| **Verdict** | **{mc0['verdict']}** "
            f"| **{mc1['verdict']}** |",
            "",
        ])

    # --- Overall timeframe assessment ---
    all_pass = all(r["monte_carlo"]["verdict"] == "PASS" for r in all_results)
    any_fail = any(r["monte_carlo"]["verdict"] == "FAIL" for r in all_results)

    lines.extend([
        "---",
        "",
        "## Overall Assessment",
        "",
    ])

    if all_pass:
        lines.extend([
            f"**All configs PASS the latency stress test at {tf} resolution.** ",
            f"Strategy survives random execution delays of 0-2 bars "
            f"({tf_cfg['bar_duration']} per bar) in >= {SURVIVAL_GATE_PCT*100:.0f}% "
            f"of Monte Carlo trials.",
        ])
    elif any_fail:
        lines.extend([
            f"**At least one config FAILS the latency stress test at {tf} resolution.** ",
            f"Random execution delays of 0-2 bars ({tf_cfg['bar_duration']} per bar) "
            f"cause equity to fall below {SURVIVAL_THRESHOLD*100:.0f}% of initial capital "
            f"in too many trials.",
        ])
    else:
        lines.extend([
            f"Mixed results at {tf} resolution. Review per-config verdicts above.",
        ])

    lines.extend([
        "",
        "---",
        f"*Generated by hf_latency_stress_mtf.py -- multi-timeframe research*",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="HF Latency Stress MTF -- Multi-timeframe research"
    )
    parser.add_argument(
        "--timeframe", "-tf",
        choices=["4h", "1h", "15m"],
        default="4h",
        help="Timeframe to test (default: 4h)",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=DEFAULT_TRIALS,
        help=f"Number of Monte Carlo trials per config (default: {DEFAULT_TRIALS})",
    )
    args = parser.parse_args()

    tf = args.timeframe
    tf_cfg = TF_CONFIG[tf]
    per_bar_slip = tf_cfg["per_bar_slip"]

    # Reproducibility
    random.seed(42)

    print("=" * 70)
    print(f"  HF Latency Stress MTF -- {tf.upper()} Resolution")
    print(f"  Monte Carlo latency stress test (0-2 bar delay)")
    print("=" * 70)
    print(f"  Timeframe:       {tf} ({tf_cfg['bar_duration']} per bar)")
    print(f"  Per-bar slip:    {per_bar_slip*10000:.1f} bps")
    print(f"  Trials:          {args.trials}")
    print(f"  Survival gate:   equity > {SURVIVAL_THRESHOLD*100:.0f}% of "
          f"${INITIAL_CAPITAL:,} in >= {SURVIVAL_GATE_PCT*100:.0f}% of trials")
    print(f"  Seed:            42")

    # Load data
    data, all_coins, data_path = load_data(tf)
    n_bars = len(data[all_coins[0]]) if all_coins else 0
    print(f"  Loaded {len(all_coins)} coins, {n_bars} bars from "
          f"{Path(data_path).name}")

    # Load tier assignments (T1 + T2 only)
    tiers = load_tier_assignments()

    # Filter tier coins to those present in data
    data_coins_set = set(all_coins)
    for tier_id in list(tiers.keys()):
        tiers[tier_id] = [c for c in tiers[tier_id] if c in data_coins_set]

    for tier_id in sorted(tiers.keys()):
        print(f"  {TIER_LABELS[tier_id]}: {len(tiers[tier_id])} coins")

    total_tiered = sum(len(v) for v in tiers.values())
    print(f"  Total tiered coins in data: {total_tiered}")

    # Print fee model
    print(f"\n  Fee model (per side):")
    for tier_id in sorted(TIER_FEES.keys()):
        base_bps = TIER_FEES[tier_id] * 10000
        max_bps = (TIER_FEES[tier_id] + 2 * per_bar_slip) * 10000
        print(f"    {TIER_LABELS[tier_id]}: {base_bps:.1f} bps base, "
              f"up to {max_bps:.1f} bps with 2-bar delay")

    t_start = time.time()

    # Run analysis for each config
    all_results = []
    for name, cfg in CONFIGS.items():
        result = analyze_config(name, cfg, data, tiers, per_bar_slip, args.trials)
        all_results.append(result)

    total_time = time.time() - t_start

    # Meta info
    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "timeframe": tf,
        "bar_duration": tf_cfg["bar_duration"],
        "per_bar_slip": per_bar_slip,
        "per_bar_slip_bps": round(per_bar_slip * 10000, 1),
        "data_file": data_path,
        "n_coins_total": len(all_coins),
        "n_bars": n_bars,
        "tier_counts": {str(k): len(v) for k, v in tiers.items()},
        "tier_fees": {str(k): round(v, 6) for k, v in TIER_FEES.items()},
        "n_trials": args.trials,
        "seed": 42,
        "survival_threshold": SURVIVAL_THRESHOLD,
        "survival_gate_pct": SURVIVAL_GATE_PCT,
        "initial_capital": INITIAL_CAPITAL,
        "total_time_s": round(total_time, 2),
        "label": f"multi-timeframe latency stress ({tf})",
        "configs_tested": list(CONFIGS.keys()),
    }

    # Write JSON report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / f"latency_stress_{tf}_001.json"

    json_output = {
        "meta": meta,
        "results": {},
    }
    for r in all_results:
        mc_summary = dict(r["monte_carlo"])
        # Omit per-trial detail from JSON to keep file manageable
        mc_summary.pop("trials", None)

        json_output["results"][r["name"]] = {
            "name": r["name"],
            "cfg": r["cfg"],
            "monte_carlo": mc_summary,
            "elapsed_s": r["elapsed_s"],
        }

    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    print(f"\n  Wrote {json_path}")

    # Write Markdown report
    md_path = REPORTS_DIR / f"latency_stress_{tf}_001.md"
    md = generate_markdown(all_results, meta, tf)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # Final summary
    print("\n" + "=" * 70)
    print(f"  LATENCY STRESS MTF SUMMARY ({tf.upper()})")
    print("=" * 70)
    print(f"\n  {'Config':<20} {'Survival':<12} {'Median P&L':<18} "
          f"{'P5 P&L':<18} {'Verdict'}")
    print("  " + "-" * 78)
    for r in all_results:
        mc = r["monte_carlo"]
        dist = mc["distribution"]
        print(f"  {r['name']:<20} {mc['survival_pct']:>5.1f}%      "
              f"${dist['pnl']['median']:>+12,.2f}    "
              f"${dist['pnl']['p5']:>+12,.2f}    "
              f"{mc['verdict']}")

    print(f"\n  Total runtime: {total_time:.1f}s")
    print("  " + "=" * 65)


if __name__ == "__main__":
    main()

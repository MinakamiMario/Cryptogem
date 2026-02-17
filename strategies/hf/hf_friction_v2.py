#!/usr/bin/env python3
"""
HF Per-Tier Friction Model (v2) -- 4H variant research.

Sprint 2.1: Replace the flat 20bps slippage model from Sprint 1 with a
per-tier slippage model that accounts for liquidity differences across
the universe.

Background data:
  - Tier 1 (Liquid, 100 coins):   median vol 1.29M, min vol 257K
  - Tier 2 (Mid, 216 coins):      median vol 44.8K, min vol 8.3K
  - Tier 3 (Illiquid, 109 coins): median vol 2.0K,  min vol 0.93

Per-tier fee model (per side):
  - Tier 1: KRAKEN_FEE + 5bps  = 0.0031  (liquid, tight spreads)
  - Tier 2: KRAKEN_FEE + 30bps = 0.0056  (mid-cap, wider spreads)
  - Tier 3: KRAKEN_FEE + 75bps = 0.0101  (illiquid, wide spreads, thin books)
  - Flat:   KRAKEN_FEE + 20bps = 0.0046  (Sprint 1 model for reference)

Methodology:
  1. Load tier assignments from universe_tiering_001.json
  2. Load candle data
  3. For each config (Champion_H2 and GRID_BEST):
     a. Flat baseline:  run_backtest on full universe with KRAKEN_FEE only
     b. Flat 20bps:     run_backtest with fee_override=0.0046
     c. Per-tier runs:  run backtest per tier with tier-specific fee,
                        then aggregate P&L / trades / DD / PF
     d. Stress 2x:      same as (c) but double the slippage component
  4. Compare flat vs per-tier results

Key constraint:
  run_backtest() applies ONE fee to ALL coins, so per-tier fees require:
  - Split coins into tiers
  - precompute_all() per tier
  - run_backtest() per tier with tier-specific fee_override
  - Aggregate: sum P&L and trades; replay equity curve for DD and PF

Usage:
    python strategies/hf/hf_friction_v2.py
    python strategies/hf/hf_friction_v2.py --universe tradeable
    python strategies/hf/hf_friction_v2.py --universe live

Outputs:
    reports/hf/friction_v2_001.json  -- structured results
    reports/hf/friction_v2_001.md    -- human-readable report
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

TIERING_PATH = REPORTS_DIR / "universe_tiering_001.json"

# --- Per-tier fee model (per side) ---
# Slippage components (added to KRAKEN_FEE)
SLIPPAGE_TIER1 = 0.0005    # 5 bps
SLIPPAGE_TIER2 = 0.0030    # 30 bps
SLIPPAGE_TIER3 = 0.0075    # 75 bps
SLIPPAGE_FLAT  = 0.0020    # 20 bps (Sprint 1 model)

FEE_TIER1 = KRAKEN_FEE + SLIPPAGE_TIER1   # 0.0031
FEE_TIER2 = KRAKEN_FEE + SLIPPAGE_TIER2   # 0.0056
FEE_TIER3 = KRAKEN_FEE + SLIPPAGE_TIER3   # 0.0101
FEE_FLAT  = KRAKEN_FEE + SLIPPAGE_FLAT    # 0.0046

# 2x stress: double the slippage component only
FEE_TIER1_2X = KRAKEN_FEE + SLIPPAGE_TIER1 * 2   # 0.0036
FEE_TIER2_2X = KRAKEN_FEE + SLIPPAGE_TIER2 * 2   # 0.0086
FEE_TIER3_2X = KRAKEN_FEE + SLIPPAGE_TIER3 * 2   # 0.0176

TIER_FEES = {1: FEE_TIER1, 2: FEE_TIER2, 3: FEE_TIER3}
TIER_FEES_2X = {1: FEE_TIER1_2X, 2: FEE_TIER2_2X, 3: FEE_TIER3_2X}
TIER_SLIPPAGE = {1: SLIPPAGE_TIER1, 2: SLIPPAGE_TIER2, 3: SLIPPAGE_TIER3}
TIER_LABELS = {1: "Tier 1 (Liquid)", 2: "Tier 2 (Mid)", 3: "Tier 3 (Illiquid)"}

# Configs under test
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


def load_tier_assignments():
    """Load tier coin lists from universe_tiering_001.json."""
    if not TIERING_PATH.exists():
        print(f"ERROR: Tiering file not found: {TIERING_PATH}")
        print("  Run: python strategies/hf/hf_universe_tiering.py first")
        sys.exit(1)
    with open(TIERING_PATH) as f:
        tiering = json.load(f)
    tiers = {}
    tb = tiering.get("tier_breakdown", {})
    for tier_key in ("1", "2", "3"):
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


def replay_equity_curve(trade_list, initial_capital):
    """
    Replay equity curve from a merged trade_list sorted by entry_bar.

    This correctly computes drawdown and profit factor from aggregated
    per-tier trades by replaying the equity curve chronologically.

    Returns dict: {pnl, pf, dd, trades, wr, final_equity, trade_count_by_tier}
    """
    if not trade_list:
        return {
            "pnl": 0.0,
            "pf": 0.0,
            "dd": 0.0,
            "trades": 0,
            "wr": 0.0,
            "final_equity": initial_capital,
        }

    # Sort by entry_bar for chronological replay
    sorted_trades = sorted(trade_list, key=lambda t: (t["entry_bar"], t.get("exit_bar", 0)))

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
            total_loss_pnl += pnl  # negative

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
# Single-fee backtest (flat models)
# ---------------------------------------------------------------------------
def run_flat_backtest(data, coins, cfg, fee_override=None, label=""):
    """Run backtest on full universe with a single fee."""
    if not coins:
        return {
            "trades": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0, "dd": 0.0,
            "final_equity": INITIAL_CAPITAL, "broke": False, "trade_list": [],
        }

    indicators = precompute_all(data, coins)
    kwargs = {"fee_override": fee_override} if fee_override is not None else {}
    result = run_backtest(indicators, coins, cfg, **kwargs)

    return {
        "trades": result["trades"],
        "pnl": round(result["pnl"], 2),
        "pf": safe_pf(result["pf"]),
        "wr": round(result["wr"], 1),
        "dd": round(result["dd"], 1),
        "final_equity": round(result["final_equity"], 2),
        "broke": result["broke"],
        "trade_list": result.get("trade_list", []),
    }


# ---------------------------------------------------------------------------
# Per-tier composite backtest
# ---------------------------------------------------------------------------
def run_per_tier_composite(data, tiers, cfg, tier_fees, label=""):
    """
    Run backtest per tier with tier-specific fees, then aggregate.

    For each tier:
      1. precompute_all(data, tier_coins)
      2. run_backtest(indicators, tier_coins, cfg, fee_override=tier_fee)
      3. Collect trade_list

    Aggregate:
      - Merge all trade_lists, sort by entry_bar
      - Replay equity curve from INITIAL_CAPITAL for correct DD
      - PF = sum(winning_pnl) / abs(sum(losing_pnl))

    Returns (composite_result, per_tier_results)
    """
    all_trade_lists = []
    per_tier = {}

    for tier_id in sorted(tiers.keys()):
        tier_coins = tiers[tier_id]
        fee = tier_fees[tier_id]
        tier_label = TIER_LABELS.get(tier_id, f"Tier {tier_id}")

        if not tier_coins:
            per_tier[tier_id] = {
                "trades": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0, "dd": 0.0,
                "final_equity": INITIAL_CAPITAL, "fee": round(fee, 6),
                "fee_bps": round(fee * 10000, 1), "n_coins": 0,
            }
            continue

        indicators = precompute_all(data, tier_coins)
        result = run_backtest(indicators, tier_coins, cfg, fee_override=fee)

        trade_list = result.get("trade_list", [])

        # Tag each trade with its tier for later analysis
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
            "fee": round(fee, 6),
            "fee_bps": round(fee * 10000, 1),
            "n_coins": len(tier_coins),
        }

        print(f"      {tier_label}: {result['trades']} trades, "
              f"P&L=${result['pnl']:+,.2f}, PF={safe_pf(result['pf'])}, "
              f"fee={fee*10000:.1f}bps")

    # Replay equity curve from merged trades
    composite = replay_equity_curve(all_trade_lists, INITIAL_CAPITAL)

    return composite, per_tier


# ---------------------------------------------------------------------------
# Full analysis for one config
# ---------------------------------------------------------------------------
def analyze_config(cfg_name, cfg, data, all_coins, tiers):
    """Run all friction models for a single config."""
    print(f"\n--- Friction v2: {cfg_name} ---")
    print(f"  Config: {json.dumps(cfg, sort_keys=True)}")

    t0_total = time.time()

    # (a) Flat baseline: KRAKEN_FEE only (Sprint 1 reference)
    print(f"  [a] Flat baseline (KRAKEN_FEE={KRAKEN_FEE*10000:.1f}bps)...")
    t0 = time.time()
    flat_baseline = run_flat_backtest(data, all_coins, cfg, fee_override=None,
                                     label="flat_baseline")
    t_a = time.time() - t0
    print(f"      {flat_baseline['trades']} trades, P&L=${flat_baseline['pnl']:+,.2f}, "
          f"PF={flat_baseline['pf']}, DD={flat_baseline['dd']}% ({t_a:.1f}s)")

    # (b) Flat 20bps: KRAKEN_FEE + 20bps slippage
    print(f"  [b] Flat 20bps (fee={FEE_FLAT*10000:.1f}bps)...")
    t0 = time.time()
    flat_20bps = run_flat_backtest(data, all_coins, cfg, fee_override=FEE_FLAT,
                                  label="flat_20bps")
    t_b = time.time() - t0
    print(f"      {flat_20bps['trades']} trades, P&L=${flat_20bps['pnl']:+,.2f}, "
          f"PF={flat_20bps['pf']}, DD={flat_20bps['dd']}% ({t_b:.1f}s)")

    # (c) Per-tier composite
    print(f"  [c] Per-tier composite...")
    t0 = time.time()
    composite, per_tier = run_per_tier_composite(data, tiers, cfg, TIER_FEES,
                                                 label="per_tier")
    t_c = time.time() - t0
    print(f"      COMPOSITE: {composite['trades']} trades, "
          f"P&L=${composite['pnl']:+,.2f}, PF={composite['pf']}, "
          f"DD={composite['dd']}% ({t_c:.1f}s)")

    # (d) Per-tier 2x stress
    print(f"  [d] Per-tier 2x stress...")
    t0 = time.time()
    composite_2x, per_tier_2x = run_per_tier_composite(data, tiers, cfg, TIER_FEES_2X,
                                                        label="per_tier_2x")
    t_d = time.time() - t0
    print(f"      COMPOSITE 2x: {composite_2x['trades']} trades, "
          f"P&L=${composite_2x['pnl']:+,.2f}, PF={composite_2x['pf']}, "
          f"DD={composite_2x['dd']}% ({t_d:.1f}s)")

    total_elapsed = time.time() - t0_total

    # --- Verdict logic ---
    baseline_pnl = flat_baseline["pnl"]
    composite_pnl = composite["pnl"]

    if baseline_pnl <= 0:
        verdict = "BASELINE_NEGATIVE"
        verdict_detail = (
            "Flat baseline P&L is non-positive; friction analysis not meaningful."
        )
    elif composite_pnl > 0 and composite_pnl >= baseline_pnl * 0.50:
        pct_retained = composite_pnl / baseline_pnl * 100
        verdict = "VIABLE"
        verdict_detail = (
            f"Per-tier composite P&L=${composite_pnl:+,.2f} retains "
            f"{pct_retained:.1f}% of flat baseline. Strategy is VIABLE "
            f"under realistic per-tier friction."
        )
    elif composite_pnl > 0:
        pct_retained = composite_pnl / baseline_pnl * 100
        verdict = "MARGINAL"
        verdict_detail = (
            f"Per-tier composite P&L=${composite_pnl:+,.2f} retains only "
            f"{pct_retained:.1f}% of flat baseline (< 50%). Strategy is "
            f"MARGINAL — friction substantially erodes edge."
        )
    else:
        verdict = "NOT_VIABLE"
        verdict_detail = (
            f"Per-tier composite P&L=${composite_pnl:+,.2f} is non-positive. "
            f"Strategy is NOT VIABLE under realistic per-tier friction."
        )

    # --- Tier 2 alpha survival check ---
    tier2_per_tier_pnl = per_tier.get(2, {}).get("pnl", 0.0)
    tier2_per_tier_trades = per_tier.get(2, {}).get("trades", 0)
    tier2_is_best_alpha = (
        tier2_per_tier_pnl > 0
        and tier2_per_tier_pnl >= per_tier.get(1, {}).get("pnl", 0.0)
        and tier2_per_tier_pnl >= per_tier.get(3, {}).get("pnl", 0.0)
    )

    print(f"\n  VERDICT: {verdict}")
    print(f"  {verdict_detail}")

    # Strip trade_list from serialized flat results
    flat_baseline_out = {k: v for k, v in flat_baseline.items() if k != "trade_list"}
    flat_20bps_out = {k: v for k, v in flat_20bps.items() if k != "trade_list"}

    return {
        "config_name": cfg_name,
        "cfg": cfg,
        "flat_baseline": flat_baseline_out,
        "flat_20bps": flat_20bps_out,
        "per_tier_composite": composite,
        "per_tier_breakdown": per_tier,
        "per_tier_2x_composite": composite_2x,
        "per_tier_2x_breakdown": per_tier_2x,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "tier2_alpha_survives": tier2_is_best_alpha,
        "tier2_pnl_after_friction": tier2_per_tier_pnl,
        "tier2_trades_after_friction": tier2_per_tier_trades,
        "timing_s": {
            "flat_baseline": round(t_a, 1),
            "flat_20bps": round(t_b, 1),
            "per_tier": round(t_c, 1),
            "per_tier_2x": round(t_d, 1),
            "total": round(total_elapsed, 1),
        },
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------
def generate_markdown(all_results, meta, tiers):
    """Generate human-readable per-tier friction report."""
    lines = [
        "# HF Per-Tier Friction Report (v2) -- 4H Variant Research",
        "",
        "> **Key question**: How much P&L evaporates under realistic per-tier friction?",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Universe**: {meta['universe']}",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Total coins**: {meta['n_coins']}",
        f"**Tier source**: `universe_tiering_001.json`",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
    ]

    # Section 1: Fee model table
    lines.extend([
        "## 1. Fee Model",
        "",
        "| Tier | Base Fee (bps) | Slippage (bps) | Total Per Side (bps) | Round Trip (bps) |",
        "|------|---------------|----------------|---------------------|-----------------|",
    ])
    for tier_id in (1, 2, 3):
        base_bps = KRAKEN_FEE * 10000
        slip_bps = TIER_SLIPPAGE[tier_id] * 10000
        total_bps = TIER_FEES[tier_id] * 10000
        rt_bps = total_bps * 2
        lines.append(
            f"| {TIER_LABELS[tier_id]} | {base_bps:.1f} | {slip_bps:.1f} "
            f"| {total_bps:.1f} | {rt_bps:.1f} |"
        )
    # Flat model rows
    flat_bps = FEE_FLAT * 10000
    lines.append(
        f"| Flat (Sprint 1) | {KRAKEN_FEE*10000:.1f} | {SLIPPAGE_FLAT*10000:.1f} "
        f"| {flat_bps:.1f} | {flat_bps*2:.1f} |"
    )
    base_bps = KRAKEN_FEE * 10000
    lines.append(
        f"| Flat baseline | {base_bps:.1f} | 0.0 "
        f"| {base_bps:.1f} | {base_bps*2:.1f} |"
    )
    lines.append("")

    # 2x stress table
    lines.extend([
        "### 2x Stress Fees (double slippage)",
        "",
        "| Tier | Slippage (bps) | Total Per Side (bps) | Round Trip (bps) |",
        "|------|----------------|---------------------|-----------------|",
    ])
    for tier_id in (1, 2, 3):
        slip_2x_bps = TIER_SLIPPAGE[tier_id] * 2 * 10000
        total_2x_bps = TIER_FEES_2X[tier_id] * 10000
        rt_2x_bps = total_2x_bps * 2
        lines.append(
            f"| {TIER_LABELS[tier_id]} | {slip_2x_bps:.1f} "
            f"| {total_2x_bps:.1f} | {rt_2x_bps:.1f} |"
        )
    lines.extend([
        "",
        f"**Tier coin counts**: "
        f"T1={len(tiers.get(1, []))}, "
        f"T2={len(tiers.get(2, []))}, "
        f"T3={len(tiers.get(3, []))}",
        "",
    ])

    # Section 2: Results per config
    for r in all_results:
        fb = r["flat_baseline"]
        f20 = r["flat_20bps"]
        comp = r["per_tier_composite"]
        comp2x = r["per_tier_2x_composite"]
        ptb = r["per_tier_breakdown"]
        ptb2x = r["per_tier_2x_breakdown"]

        lines.extend([
            "---",
            "",
            f"## 2. Results: {r['config_name']}",
            "",
            f"**Config**: `{json.dumps(r['cfg'], sort_keys=True)}`",
            "",
            "### Overall Comparison",
            "",
            "| Model | Trades | P&L | PF | WR% | DD% |",
            "|-------|--------|-----|----|-----|-----|",
        ])

        for label, res in [
            ("Flat baseline (KRAKEN_FEE)", fb),
            ("Flat 20bps (Sprint 1)", f20),
            ("Per-tier composite", comp),
            ("Per-tier 2x stress", comp2x),
        ]:
            lines.append(
                f"| {label} | {res['trades']} | ${res['pnl']:+,.2f} "
                f"| {res['pf']} | {res['wr']}% | {res['dd']}% |"
            )
        lines.append("")

        # P&L deltas relative to flat baseline
        baseline_pnl = fb["pnl"]
        lines.extend([
            "### P&L Delta vs Flat Baseline",
            "",
            "| Model | P&L | Delta | Delta % |",
            "|-------|-----|-------|---------|",
        ])
        for label, res in [
            ("Flat baseline", fb),
            ("Flat 20bps", f20),
            ("Per-tier composite", comp),
            ("Per-tier 2x stress", comp2x),
        ]:
            delta = res["pnl"] - baseline_pnl
            delta_pct = (delta / abs(baseline_pnl) * 100) if baseline_pnl != 0 else 0.0
            lines.append(
                f"| {label} | ${res['pnl']:+,.2f} | ${delta:+,.2f} | {delta_pct:+.1f}% |"
            )
        lines.append("")

        # Per-tier breakdown within composite
        lines.extend([
            "### Per-Tier Breakdown (composite model)",
            "",
            "| Tier | Coins | Fee (bps) | Trades | P&L | PF | WR% | DD% |",
            "|------|-------|-----------|--------|-----|----|-----|-----|",
        ])
        for tier_id in sorted(ptb.keys()):
            tr = ptb[tier_id]
            lines.append(
                f"| {TIER_LABELS.get(tier_id, f'Tier {tier_id}')} "
                f"| {tr['n_coins']} | {tr['fee_bps']:.1f} "
                f"| {tr['trades']} | ${tr['pnl']:+,.2f} "
                f"| {tr['pf']} | {tr['wr']}% | {tr['dd']}% |"
            )
        lines.append("")

        # Per-tier breakdown for 2x stress
        lines.extend([
            "### Per-Tier Breakdown (2x stress)",
            "",
            "| Tier | Coins | Fee (bps) | Trades | P&L | PF | WR% | DD% |",
            "|------|-------|-----------|--------|-----|----|-----|-----|",
        ])
        for tier_id in sorted(ptb2x.keys()):
            tr = ptb2x[tier_id]
            lines.append(
                f"| {TIER_LABELS.get(tier_id, f'Tier {tier_id}')} "
                f"| {tr['n_coins']} | {tr['fee_bps']:.1f} "
                f"| {tr['trades']} | ${tr['pnl']:+,.2f} "
                f"| {tr['pf']} | {tr['wr']}% | {tr['dd']}% |"
            )
        lines.append("")

    # Section 3: Tier 2 alpha survival
    lines.extend([
        "---",
        "",
        "## 3. Tier 2 Alpha Survival Under Friction",
        "",
        "> From Sprint 1.5 (universe tiering), Tier 2 (Mid) was identified as the",
        "> primary alpha source. Does this survive per-tier friction?",
        "",
        "| Config | T2 P&L (per-tier) | T2 Trades | T2 Best Alpha? | Survives? |",
        "|--------|-------------------|-----------|----------------|-----------|",
    ])
    for r in all_results:
        t2_pnl = r["tier2_pnl_after_friction"]
        t2_trades = r["tier2_trades_after_friction"]
        t2_best = r["tier2_alpha_survives"]
        survives = "YES" if t2_pnl > 0 else "NO"
        lines.append(
            f"| {r['config_name']} | ${t2_pnl:+,.2f} | {t2_trades} "
            f"| {'YES' if t2_best else 'NO'} | {survives} |"
        )
    lines.append("")

    # Section 4: Verdicts
    lines.extend([
        "---",
        "",
        "## 4. Verdicts",
        "",
        "### Verdict Logic",
        "",
        "- **VIABLE**: Per-tier composite P&L > $0 AND >= 50% of flat baseline",
        "- **MARGINAL**: Per-tier composite P&L > $0 but < 50% of flat baseline",
        "- **NOT_VIABLE**: Per-tier composite P&L <= $0",
        "",
        "### Per-Config Verdicts",
        "",
        "| Config | Verdict | Composite P&L | Baseline P&L | Retained % |",
        "|--------|---------|--------------|-------------|------------|",
    ])
    for r in all_results:
        comp_pnl = r["per_tier_composite"]["pnl"]
        base_pnl = r["flat_baseline"]["pnl"]
        retained = (comp_pnl / base_pnl * 100) if base_pnl != 0 else 0.0
        lines.append(
            f"| {r['config_name']} | **{r['verdict']}** "
            f"| ${comp_pnl:+,.2f} | ${base_pnl:+,.2f} | {retained:+.1f}% |"
        )
    lines.append("")

    for r in all_results:
        lines.extend([
            f"**{r['config_name']}**: {r['verdict_detail']}",
            "",
        ])

    # Section 5: Overall assessment
    lines.extend([
        "---",
        "",
        "## 5. Overall Assessment",
        "",
    ])

    all_viable = all(r["verdict"] == "VIABLE" for r in all_results)
    any_not_viable = any(r["verdict"] == "NOT_VIABLE" for r in all_results)
    all_t2_survive = all(r["tier2_pnl_after_friction"] > 0 for r in all_results)

    if all_viable:
        lines.extend([
            "**Strategy is VIABLE under realistic per-tier friction.** Both configs ",
            "retain meaningful profitability when accounting for tier-specific ",
            "slippage and spread costs.",
            "",
        ])
    elif any_not_viable:
        lines.extend([
            "**Strategy is NOT VIABLE under realistic per-tier friction.** At least ",
            "one config becomes unprofitable when per-tier friction is applied. ",
            "The flat fee model was overly optimistic.",
            "",
        ])
    else:
        lines.extend([
            "**Strategy viability is MARGINAL under per-tier friction.** Edge ",
            "survives but is substantially reduced. Consider restricting to ",
            "more liquid tiers or optimizing for lower turnover.",
            "",
        ])

    if all_t2_survive:
        lines.extend([
            "**Tier 2 alpha finding SURVIVES per-tier friction.** The Tier 2 (Mid) ",
            "universe remains profitable even with 30bps slippage.",
        ])
    else:
        lines.extend([
            "**Tier 2 alpha finding does NOT survive per-tier friction.** Higher ",
            "slippage costs for mid-cap coins erode the edge identified in Sprint 1.5.",
        ])

    lines.extend([
        "",
        "---",
        f"*Generated by hf_friction_v2.py -- 4H variant research*",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="HF Per-Tier Friction Model (v2) -- 4H variant research"
    )
    parser.add_argument(
        "--universe",
        choices=["tradeable", "live"],
        default="tradeable",
        help="Which candle cache to use (default: tradeable)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  HF Per-Tier Friction Model (v2) -- 4H Variant Research")
    print("  Key question: How much P&L evaporates under realistic friction?")
    print("=" * 70)
    print(f"  Universe: {args.universe}")

    # 1. Load tier assignments
    tiers = load_tier_assignments()
    for tier_id in sorted(tiers.keys()):
        print(f"  {TIER_LABELS[tier_id]}: {len(tiers[tier_id])} coins")

    # 2. Load candle data
    data, all_coins, data_path = load_data(args.universe)
    n_bars = len(data[all_coins[0]]) if all_coins else 0
    print(f"  Loaded {len(all_coins)} coins, {n_bars} bars from {Path(data_path).name}")

    # Filter tier coins to only those present in data
    for tier_id in list(tiers.keys()):
        data_coins_set = set(all_coins)
        tiers[tier_id] = [c for c in tiers[tier_id] if c in data_coins_set]

    total_tiered = sum(len(v) for v in tiers.values())
    print(f"  Tier coins in data: {total_tiered} / {len(all_coins)}")

    # Print fee model summary
    print("\n  Fee model (per side):")
    for tier_id in (1, 2, 3):
        print(f"    {TIER_LABELS[tier_id]}: {TIER_FEES[tier_id]*10000:.1f}bps "
              f"(2x stress: {TIER_FEES_2X[tier_id]*10000:.1f}bps)")
    print(f"    Flat (Sprint 1): {FEE_FLAT*10000:.1f}bps")
    print(f"    Flat baseline:   {KRAKEN_FEE*10000:.1f}bps")

    t_start = time.time()

    # 3. Run analysis for each config
    all_results = []
    for cfg_name, cfg in CONFIGS.items():
        result = analyze_config(cfg_name, cfg, data, all_coins, tiers)
        all_results.append(result)

    total_time = time.time() - t_start

    # 4. Build meta
    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "universe": args.universe,
        "data_file": data_path,
        "n_coins": len(all_coins),
        "n_bars": n_bars,
        "tier_source": str(TIERING_PATH),
        "tier_counts": {str(k): len(v) for k, v in tiers.items()},
        "fee_model": {
            "kraken_fee": KRAKEN_FEE,
            "tier1_fee": FEE_TIER1,
            "tier2_fee": FEE_TIER2,
            "tier3_fee": FEE_TIER3,
            "flat_fee": FEE_FLAT,
            "tier1_fee_2x": FEE_TIER1_2X,
            "tier2_fee_2x": FEE_TIER2_2X,
            "tier3_fee_2x": FEE_TIER3_2X,
        },
        "total_time_s": round(total_time, 2),
        "label": "4H variant research",
        "configs_tested": list(CONFIGS.keys()),
    }

    # 5. Write JSON report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / "friction_v2_001.json"

    json_output = {
        "meta": meta,
        "results": {r["config_name"]: r for r in all_results},
    }
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    print(f"\n  Wrote {json_path}")

    # 6. Write markdown report
    md_path = REPORTS_DIR / "friction_v2_001.md"
    md = generate_markdown(all_results, meta, tiers)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # 7. Final summary
    print("\n" + "=" * 70)
    print("  PER-TIER FRICTION SUMMARY (4H variant research)")
    print("=" * 70)

    print(f"\n  {'Model':<28} {'Trades':>7} {'P&L':>12} {'PF':>6} {'DD%':>6}")
    print("  " + "-" * 62)
    for r in all_results:
        print(f"\n  {r['config_name']}:")
        for label, res in [
            ("Flat baseline", r["flat_baseline"]),
            ("Flat 20bps", r["flat_20bps"]),
            ("Per-tier composite", r["per_tier_composite"]),
            ("Per-tier 2x stress", r["per_tier_2x_composite"]),
        ]:
            print(f"    {label:<26} {res['trades']:>7} "
                  f"${res['pnl']:>+10,.2f} {res['pf']:>6} {res['dd']:>5}%")

    print(f"\n  {'Config':<20} {'Verdict':<14} {'Retained%':>10} {'T2 Survives':>12}")
    print("  " + "-" * 60)
    for r in all_results:
        base_pnl = r["flat_baseline"]["pnl"]
        comp_pnl = r["per_tier_composite"]["pnl"]
        retained = (comp_pnl / base_pnl * 100) if base_pnl != 0 else 0.0
        t2_surv = "YES" if r["tier2_pnl_after_friction"] > 0 else "NO"
        print(f"  {r['config_name']:<20} {r['verdict']:<14} "
              f"{retained:>9.1f}% {t2_surv:>12}")

    print(f"\n  Total runtime: {total_time:.1f}s")
    print("  " + "=" * 65)


if __name__ == "__main__":
    main()

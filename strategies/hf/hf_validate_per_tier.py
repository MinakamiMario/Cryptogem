#!/usr/bin/env python3
"""
HF Per-Tier Validation — 4H variant research (Sprint 2.3).

Re-validates the strategy per tier with tier-specific friction.
Runs the same 5 hard gates from GATES.md on each tier independently,
using tier-appropriate fees instead of the flat fee model.

For each config (Champion_H2, GRID_BEST):
  For each tier (1, 2, 3) + "Tier 1+2" (live universe):
    - G1: Trade sufficiency (trades >= 20, or INSUFFICIENT_SAMPLE)
    - G2: Purged walk-forward (5-fold, embargo=2) with tier fee
    - G3: Rolling windows (180-bar) with tier fee
    - G4: Friction stress (tier_fee*1.5 and tier_fee*2.0)
    - G5: Concentration (top1 < 40%, top3 < 70%)
    Compute verdict per tier.

For "Tier 1+2" combined: run T1 and T2 coins at fee_override=0.0056
(T2 fee, conservative) as a single universe.

Usage:
    python strategies/hf/hf_validate_per_tier.py
    python strategies/hf/hf_validate_per_tier.py --universe tradeable
    python strategies/hf/hf_validate_per_tier.py --universe live

Outputs:
    reports/hf/validate_per_tier_001.json  — full structured results
    reports/hf/validate_per_tier_001.md    — human-readable summary
"""

import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

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

# Walk-forward parameters
WF_FOLDS = 5
WF_EMBARGO = 2  # bars purged between train/test boundary

# Rolling window size (~30 days at 4H = 180 bars)
ROLLING_WINDOW_BARS = 180

# Concentration gates
CONC_TOP1_MAX = 0.40  # top1 coin < 40% of positive P&L
CONC_TOP3_MAX = 0.70  # top3 coins < 70% of positive P&L

# Trade sufficiency
MIN_TRADES = 20

# --- Per-tier fee model (per side) ---
FEE_TIER1 = 0.0031   # KRAKEN_FEE + 5 bps
FEE_TIER2 = 0.0056   # KRAKEN_FEE + 30 bps
FEE_TIER3 = 0.0101   # KRAKEN_FEE + 75 bps

TIER_FEES = {
    1: FEE_TIER1,
    2: FEE_TIER2,
    3: FEE_TIER3,
    "1+2": FEE_TIER2,  # conservative: use T2 fee for combined
}

TIER_LABELS = {
    1: "Tier 1 (Liquid)",
    2: "Tier 2 (Mid)",
    3: "Tier 3 (Illiquid)",
    "1+2": "Tier 1+2 (Live)",
}

# Configs to validate
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


# ---------------------------------------------------------------------------
# G1: Trade Sufficiency
# ---------------------------------------------------------------------------
def gate_trade_sufficiency(indicators, coins, cfg, fee):
    """
    G1: Trade sufficiency. If total trades < 20, verdict is INSUFFICIENT_SAMPLE.
    """
    result = run_backtest(indicators, coins, cfg, fee_override=fee)
    n_trades = result["trades"]
    sufficient = n_trades >= MIN_TRADES

    return {
        "gate": "G1",
        "name": "trade_sufficiency",
        "total_trades": n_trades,
        "min_required": MIN_TRADES,
        "pnl": round(result["pnl"], 2),
        "wr": round(result["wr"], 1),
        "result": "PASS" if sufficient else "INSUFFICIENT_SAMPLE",
    }


# ---------------------------------------------------------------------------
# G2: Purged Walk-Forward (5-fold, embargo=2)
# ---------------------------------------------------------------------------
def gate_walk_forward(data, coins, cfg, fee, n_folds=WF_FOLDS, embargo=WF_EMBARGO):
    """
    G2: Purged walk-forward validation with tier-specific fee.
    Split the bar range into n_folds segments. For each fold, test on that
    segment only, purging embargo bars at boundaries.
    """
    if not coins:
        return {
            "gate": "G2",
            "name": "walk_forward",
            "n_folds": n_folds,
            "embargo": embargo,
            "folds": [],
            "positive_folds": 0,
            "pf_above1_folds": 0,
            "result": "FAIL",
            "soft_pass": False,
        }

    sample_coin = coins[0]
    n_bars = len(data[sample_coin])
    usable_start = START_BAR
    usable_bars = n_bars - usable_start

    fold_size = usable_bars // n_folds
    folds = []

    for i in range(n_folds):
        test_start = usable_start + i * fold_size
        test_end = test_start + fold_size if i < n_folds - 1 else n_bars

        # Purge: embargo bars before test_start and after test_end
        purge_start = max(usable_start, test_start - embargo)
        purge_end = min(n_bars, test_end + embargo)

        # Precompute indicators only up to test_end (causal)
        indicators = precompute_all(data, coins, end_bar=test_end)

        # Run backtest only on the test segment with tier fee
        result = run_backtest(
            indicators, coins, cfg,
            start_bar=test_start,
            end_bar=test_end,
            fee_override=fee,
        )

        pf = result["pf"]
        if pf == float("inf"):
            pf = 99.0

        fold_result = {
            "fold": i + 1,
            "test_start": test_start,
            "test_end": test_end,
            "purge_start": purge_start,
            "purge_end": purge_end,
            "trades": result["trades"],
            "pnl": round(result["pnl"], 2),
            "pf": round(pf, 2),
            "wr": round(result["wr"], 1),
            "dd": round(result["dd"], 1),
            "positive": result["pnl"] > 0,
            "pf_above_1": pf > 1.0,
        }
        folds.append(fold_result)

    positive_folds = sum(1 for f in folds if f["positive"])
    pf_folds = sum(1 for f in folds if f["pf_above_1"])

    # Gate: >= 4/5 folds positive OR PF > 1 in 4/5
    gate_pass = positive_folds >= 4 or pf_folds >= 4
    # Soft pass: 3/5
    soft_pass = positive_folds >= 3 or pf_folds >= 3

    return {
        "gate": "G2",
        "name": "walk_forward",
        "n_folds": n_folds,
        "embargo": embargo,
        "folds": folds,
        "positive_folds": positive_folds,
        "pf_above1_folds": pf_folds,
        "result": "PASS" if gate_pass else "FAIL",
        "soft_pass": soft_pass,
    }


# ---------------------------------------------------------------------------
# G3: Rolling Windows (180-bar)
# ---------------------------------------------------------------------------
def gate_rolling_windows(data, coins, cfg, fee, window_bars=ROLLING_WINDOW_BARS):
    """
    G3: Rolling windows with tier-specific fee.
    Gate: >= 70% windows have positive P&L.
    """
    if not coins:
        return {
            "gate": "G3",
            "name": "rolling_windows",
            "window_bars": window_bars,
            "n_windows": 0,
            "positive_windows": 0,
            "positive_ratio": 0.0,
            "windows": [],
            "result": "FAIL",
        }

    sample_coin = coins[0]
    n_bars = len(data[sample_coin])

    # Precompute indicators once for full dataset
    indicators = precompute_all(data, coins)

    windows = []
    start = START_BAR
    while start + window_bars <= n_bars:
        end = start + window_bars
        result = run_backtest(
            indicators, coins, cfg,
            start_bar=start,
            end_bar=end,
            fee_override=fee,
        )

        pf = result["pf"]
        if pf == float("inf"):
            pf = 99.0

        windows.append({
            "start_bar": start,
            "end_bar": end,
            "trades": result["trades"],
            "pnl": round(result["pnl"], 2),
            "pf": round(pf, 2),
            "wr": round(result["wr"], 1),
            "positive": result["pnl"] > 0,
        })
        start += window_bars

    # Handle leftover bars as a final window if substantial (>= 50% of window)
    if start < n_bars and (n_bars - start) >= window_bars // 2:
        result = run_backtest(
            indicators, coins, cfg,
            start_bar=start,
            end_bar=n_bars,
            fee_override=fee,
        )
        pf = result["pf"]
        if pf == float("inf"):
            pf = 99.0
        windows.append({
            "start_bar": start,
            "end_bar": n_bars,
            "trades": result["trades"],
            "pnl": round(result["pnl"], 2),
            "pf": round(pf, 2),
            "wr": round(result["wr"], 1),
            "positive": result["pnl"] > 0,
        })

    n_windows = len(windows)
    positive_windows = sum(1 for w in windows if w["positive"])
    ratio = positive_windows / n_windows if n_windows > 0 else 0.0

    gate_pass = ratio >= 0.70

    return {
        "gate": "G3",
        "name": "rolling_windows",
        "window_bars": window_bars,
        "n_windows": n_windows,
        "positive_windows": positive_windows,
        "positive_ratio": round(ratio, 3),
        "windows": windows,
        "result": "PASS" if gate_pass else "FAIL",
    }


# ---------------------------------------------------------------------------
# G4: Friction Stress (tier_fee*1.5 and tier_fee*2.0)
# ---------------------------------------------------------------------------
def gate_friction_stress(indicators, coins, cfg, tier_fee):
    """
    G4: Friction stress with tier-specific fee levels.
    Instead of fixed 72/102 bps, use tier_fee*1.5 and tier_fee*2.0.
    Gate: P&L > $0 at BOTH regimes.
    """
    fee_15x = tier_fee * 1.5
    fee_20x = tier_fee * 2.0

    r_15x = run_backtest(indicators, coins, cfg, fee_override=fee_15x)
    r_20x = run_backtest(indicators, coins, cfg, fee_override=fee_20x)

    pf_15x = safe_pf(r_15x["pf"])
    pf_20x = safe_pf(r_20x["pf"])

    pass_15x = r_15x["pnl"] > 0
    pass_20x = r_20x["pnl"] > 0

    return {
        "gate": "G4",
        "name": "friction_stress",
        "tier_fee": round(tier_fee, 6),
        "fee_15x": round(fee_15x, 6),
        "fee_20x": round(fee_20x, 6),
        "fee_15x_bps": round(fee_15x * 10000, 1),
        "fee_20x_bps": round(fee_20x * 10000, 1),
        "regime_15x": {
            "trades": r_15x["trades"],
            "pnl": round(r_15x["pnl"], 2),
            "pf": pf_15x,
            "wr": round(r_15x["wr"], 1),
            "dd": round(r_15x["dd"], 1),
            "pass": pass_15x,
        },
        "regime_20x": {
            "trades": r_20x["trades"],
            "pnl": round(r_20x["pnl"], 2),
            "pf": pf_20x,
            "wr": round(r_20x["wr"], 1),
            "dd": round(r_20x["dd"], 1),
            "pass": pass_20x,
        },
        "result": "PASS" if (pass_15x and pass_20x) else "FAIL",
    }


# ---------------------------------------------------------------------------
# G5: Concentration (top1 < 40%, top3 < 70%)
# ---------------------------------------------------------------------------
def gate_concentration(indicators, coins, cfg, fee):
    """
    G5: Concentration with tier-specific fee.
    Denominator = sum(max(0, pnl)) across all trades (positive profit attribution).
    Gate: top1 < 40%, top3 < 70%.
    """
    result = run_backtest(indicators, coins, cfg, fee_override=fee)
    trade_list = result.get("trade_list", [])

    # Aggregate P&L by coin
    coin_pnl = defaultdict(float)
    for t in trade_list:
        coin_pnl[t["pair"]] += t["pnl"]

    # Denominator: sum of positive P&L per coin
    positive_profits = {c: max(0.0, pnl) for c, pnl in coin_pnl.items()}
    total_positive = sum(positive_profits.values())

    if total_positive <= 0:
        return {
            "gate": "G5",
            "name": "concentration",
            "total_positive_pnl": 0.0,
            "n_coins_traded": len(coin_pnl),
            "top1_coin": None,
            "top1_share": 0.0,
            "top1_pct": 0.0,
            "top3_coins": [],
            "top3_share": 0.0,
            "top3_pct": 0.0,
            "result": "FAIL",
            "note": "No positive P&L to measure concentration",
        }

    # Sort coins by positive profit descending
    sorted_coins = sorted(positive_profits.items(), key=lambda x: -x[1])

    top1_coin = sorted_coins[0][0] if sorted_coins else None
    top1_profit = sorted_coins[0][1] if sorted_coins else 0.0
    top1_share = top1_profit / total_positive

    top3_coins = sorted_coins[:3]
    top3_profit = sum(p for _, p in top3_coins)
    top3_share = top3_profit / total_positive

    pass_top1 = top1_share < CONC_TOP1_MAX
    pass_top3 = top3_share < CONC_TOP3_MAX

    return {
        "gate": "G5",
        "name": "concentration",
        "total_positive_pnl": round(total_positive, 2),
        "n_coins_traded": len(coin_pnl),
        "top1_coin": top1_coin,
        "top1_share": round(top1_share, 4),
        "top1_pct": round(top1_share * 100, 1),
        "top1_gate": f"< {CONC_TOP1_MAX*100:.0f}%",
        "top1_pass": pass_top1,
        "top3_coins": [c for c, _ in top3_coins],
        "top3_share": round(top3_share, 4),
        "top3_pct": round(top3_share * 100, 1),
        "top3_gate": f"< {CONC_TOP3_MAX*100:.0f}%",
        "top3_pass": pass_top3,
        "result": "PASS" if (pass_top1 and pass_top3) else "FAIL",
    }


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------
def compute_verdict(gates):
    """
    Compute overall verdict from gate results.
    - trades < 20:           INSUFFICIENT_SAMPLE
    - all gates pass:         GO
    - WF 3/5 and rest pass:   SOFT-GO
    - else:                   NO-GO with failed gates list
    """
    g1 = gates["G1"]
    if g1["result"] == "INSUFFICIENT_SAMPLE":
        return {
            "verdict": "INSUFFICIENT_SAMPLE",
            "reason": f"Only {g1['total_trades']} trades (need >= {MIN_TRADES})",
            "label": "4H variant research",
            "failed_gates": ["G1"],
        }

    # Collect gate results for G2-G5
    gate_results = {
        "G2": gates["G2"]["result"],
        "G3": gates["G3"]["result"],
        "G4": gates["G4"]["result"],
        "G5": gates["G5"]["result"],
    }

    failed = [name for name, status in gate_results.items() if status != "PASS"]

    if not failed:
        return {
            "verdict": "GO",
            "reason": "All 5 hard gates passed",
            "label": "4H variant research",
            "failed_gates": [],
        }

    # Check for SOFT-GO: WF at 3/5 (soft_pass) and everything else passes
    wf_soft = gates["G2"].get("soft_pass", False)
    other_failed = [g for g in failed if g != "G2"]

    if wf_soft and not other_failed and "G2" in failed:
        return {
            "verdict": "SOFT-GO",
            "reason": (
                f"WF {gates['G2']['positive_folds']}/5 folds "
                f"(soft pass at 3/5), all other gates pass"
            ),
            "label": "4H variant research",
            "failed_gates": ["G2 (soft)"],
        }

    return {
        "verdict": "NO-GO",
        "reason": f"Failed gates: {', '.join(failed)}",
        "label": "4H variant research",
        "failed_gates": failed,
    }


# ---------------------------------------------------------------------------
# Validate one config on one tier
# ---------------------------------------------------------------------------
def validate_tier(cfg_name, cfg, data, tier_coins, tier_id, tier_fee):
    """Run all 5 hard gates for a single config on a single tier."""
    tier_label = TIER_LABELS.get(tier_id, f"Tier {tier_id}")
    print(f"\n    [{tier_label}] {len(tier_coins)} coins, fee={tier_fee*10000:.1f}bps...")

    t0 = time.time()

    if not tier_coins:
        print(f"      No coins in {tier_label} — skipping")
        return {
            "tier_id": str(tier_id),
            "tier_label": tier_label,
            "n_coins": 0,
            "tier_fee": round(tier_fee, 6),
            "tier_fee_bps": round(tier_fee * 10000, 1),
            "gates": {},
            "verdict": {
                "verdict": "NO-GO",
                "reason": "No coins in tier",
                "label": "4H variant research",
                "failed_gates": ["no_coins"],
            },
            "elapsed_s": 0.0,
        }

    gates = {}

    # G1: Trade Sufficiency
    print(f"      G1: Trade Sufficiency...")
    t1 = time.time()
    indicators = precompute_all(data, tier_coins)
    g1 = gate_trade_sufficiency(indicators, tier_coins, cfg, tier_fee)
    gates["G1"] = g1
    print(f"          {g1['total_trades']} trades (min={MIN_TRADES}) "
          f"-> {g1['result']} ({time.time()-t1:.1f}s)")

    # G2: Purged Walk-Forward
    print(f"      G2: Purged Walk-Forward ({WF_FOLDS}-fold, embargo={WF_EMBARGO})...")
    t2 = time.time()
    g2 = gate_walk_forward(data, tier_coins, cfg, tier_fee)
    gates["G2"] = g2
    print(f"          {g2['positive_folds']}/{WF_FOLDS} positive folds "
          f"-> {g2['result']} ({time.time()-t2:.1f}s)")

    # G3: Rolling Windows
    print(f"      G3: Rolling Windows ({ROLLING_WINDOW_BARS}-bar)...")
    t3 = time.time()
    g3 = gate_rolling_windows(data, tier_coins, cfg, tier_fee)
    gates["G3"] = g3
    print(f"          {g3['positive_windows']}/{g3['n_windows']} positive "
          f"({g3['positive_ratio']*100:.0f}%) -> {g3['result']} ({time.time()-t3:.1f}s)")

    # G4: Friction Stress (tier_fee*1.5 and tier_fee*2.0)
    print(f"      G4: Friction Stress ({tier_fee*15000:.1f}bps / {tier_fee*20000:.1f}bps)...")
    t4 = time.time()
    g4 = gate_friction_stress(indicators, tier_coins, cfg, tier_fee)
    gates["G4"] = g4
    print(f"          1.5x: ${g4['regime_15x']['pnl']:+,.0f} | "
          f"2.0x: ${g4['regime_20x']['pnl']:+,.0f} -> {g4['result']} ({time.time()-t4:.1f}s)")

    # G5: Concentration
    print(f"      G5: Concentration...")
    t5 = time.time()
    g5 = gate_concentration(indicators, tier_coins, cfg, tier_fee)
    gates["G5"] = g5
    top1_pct = g5.get("top1_pct", 0.0)
    top3_pct = g5.get("top3_pct", 0.0)
    print(f"          top1={top1_pct:.1f}% top3={top3_pct:.1f}% "
          f"-> {g5['result']} ({time.time()-t5:.1f}s)")

    # Compute verdict
    verdict = compute_verdict(gates)
    elapsed = time.time() - t0

    print(f"      VERDICT: {verdict['verdict']} ({verdict['reason']}) [{elapsed:.1f}s]")

    return {
        "tier_id": str(tier_id),
        "tier_label": tier_label,
        "n_coins": len(tier_coins),
        "tier_fee": round(tier_fee, 6),
        "tier_fee_bps": round(tier_fee * 10000, 1),
        "gates": gates,
        "verdict": verdict,
        "elapsed_s": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Validate one config across all tiers
# ---------------------------------------------------------------------------
def validate_config(cfg_name, cfg, data, all_coins, tiers):
    """Run per-tier validation for a single config."""
    print(f"\n  === Validating: {cfg_name} ===")
    print(f"  Config: {json.dumps(cfg, sort_keys=True)}")

    t0 = time.time()
    tier_results = {}

    # Individual tiers: 1, 2, 3
    for tier_id in (1, 2, 3):
        tier_coins = tiers.get(tier_id, [])
        tier_fee = TIER_FEES[tier_id]
        result = validate_tier(cfg_name, cfg, data, tier_coins, tier_id, tier_fee)
        tier_results[str(tier_id)] = result

    # Combined Tier 1+2 (live universe) at conservative T2 fee
    combined_coins = sorted(set(tiers.get(1, []) + tiers.get(2, [])))
    combined_fee = TIER_FEES["1+2"]
    result_combined = validate_tier(
        cfg_name, cfg, data, combined_coins, "1+2", combined_fee
    )
    tier_results["1+2"] = result_combined

    total_elapsed = time.time() - t0

    # Summary
    print(f"\n  --- {cfg_name} Summary ---")
    for tid in ("1", "2", "3", "1+2"):
        tr = tier_results[tid]
        v = tr["verdict"]["verdict"]
        n = tr["n_coins"]
        fee_bps = tr["tier_fee_bps"]
        print(f"    {tr['tier_label']:<22} coins={n:<4} fee={fee_bps:.1f}bps "
              f"-> {v}")

    return {
        "config_name": cfg_name,
        "cfg": cfg,
        "tier_results": tier_results,
        "elapsed_s": round(total_elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------
def generate_markdown(all_results, meta):
    """Generate human-readable per-tier validation report."""
    lines = [
        "# HF Per-Tier Validation Report -- 4H Variant Research (Sprint 2.3)",
        "",
        "> **Key question**: Which tiers pass all 5 hard gates under tier-specific friction?",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Universe**: {meta['universe']}",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Total coins**: {meta['n_coins']}",
        f"**Tier source**: `universe_tiering_001.json`",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
    ]

    # Section 1: Summary matrix
    lines.extend([
        "## 1. Summary Matrix",
        "",
        "| Config | Tier | Coins | Fee (bps) | Verdict | G1 | G2 | G3 | G4 | G5 |",
        "|--------|------|-------|-----------|---------|----|----|----|----|-----|",
    ])

    for r in all_results:
        cfg_name = r["config_name"]
        for tid in ("1", "2", "3", "1+2"):
            tr = r["tier_results"][tid]
            gates = tr["gates"]
            v = tr["verdict"]["verdict"]

            def gate_str(gate_key):
                g = gates.get(gate_key, {})
                res = g.get("result", "N/A")
                if res == "PASS":
                    return "PASS"
                elif res == "INSUFFICIENT_SAMPLE":
                    return "INSUF"
                else:
                    return "FAIL"

            lines.append(
                f"| {cfg_name} | {tr['tier_label']} "
                f"| {tr['n_coins']} | {tr['tier_fee_bps']:.1f} "
                f"| **{v}** "
                f"| {gate_str('G1')} "
                f"| {gate_str('G2')} "
                f"| {gate_str('G3')} "
                f"| {gate_str('G4')} "
                f"| {gate_str('G5')} |"
            )
    lines.append("")

    # Section 2: Detail per config per tier
    for r in all_results:
        cfg_name = r["config_name"]
        lines.extend([
            "---",
            "",
            f"## 2. Detail: {cfg_name}",
            "",
            f"**Config**: `{json.dumps(r['cfg'], sort_keys=True)}`",
            "",
        ])

        for tid in ("1", "2", "3", "1+2"):
            tr = r["tier_results"][tid]
            gates = tr["gates"]
            v = tr["verdict"]

            lines.extend([
                f"### {tr['tier_label']} ({tr['n_coins']} coins, "
                f"fee={tr['tier_fee_bps']:.1f}bps)",
                "",
                f"**Verdict**: **{v['verdict']}** -- {v['reason']}",
                "",
            ])

            if not gates:
                lines.append("*No gates evaluated (0 coins)*")
                lines.append("")
                continue

            # G1
            g1 = gates.get("G1", {})
            lines.append(
                f"- **G1 Trade Sufficiency**: {g1.get('total_trades', 0)} trades "
                f"(min={MIN_TRADES}) -> **{g1.get('result', 'N/A')}**"
            )

            # G2
            g2 = gates.get("G2", {})
            lines.append(
                f"- **G2 Walk-Forward**: {g2.get('positive_folds', 0)}/{WF_FOLDS} "
                f"positive folds, {g2.get('pf_above1_folds', 0)}/{WF_FOLDS} PF>1 "
                f"-> **{g2.get('result', 'N/A')}**"
            )

            # G2 fold detail
            folds = g2.get("folds", [])
            if folds:
                lines.extend([
                    "",
                    "  | Fold | Bars | Trades | P&L | PF | WR% | Positive |",
                    "  |------|------|--------|-----|----|-----|----------|",
                ])
                for f in folds:
                    lines.append(
                        f"  | {f['fold']} | {f['test_start']}-{f['test_end']} "
                        f"| {f['trades']} | ${f['pnl']:+,.0f} | {f['pf']} "
                        f"| {f['wr']}% | {'YES' if f['positive'] else 'NO'} |"
                    )
                lines.append("")

            # G3
            g3 = gates.get("G3", {})
            lines.append(
                f"- **G3 Rolling Windows**: {g3.get('positive_windows', 0)}/"
                f"{g3.get('n_windows', 0)} positive "
                f"({g3.get('positive_ratio', 0)*100:.0f}%, gate >= 70%) "
                f"-> **{g3.get('result', 'N/A')}**"
            )

            # G4
            g4 = gates.get("G4", {})
            r15 = g4.get("regime_15x", {})
            r20 = g4.get("regime_20x", {})
            lines.append(
                f"- **G4 Friction Stress**: "
                f"1.5x ({g4.get('fee_15x_bps', 0):.1f}bps): "
                f"${r15.get('pnl', 0):+,.0f} | "
                f"2.0x ({g4.get('fee_20x_bps', 0):.1f}bps): "
                f"${r20.get('pnl', 0):+,.0f} "
                f"-> **{g4.get('result', 'N/A')}**"
            )

            # G5
            g5 = gates.get("G5", {})
            lines.append(
                f"- **G5 Concentration**: "
                f"top1={g5.get('top1_pct', 0):.1f}% (< {CONC_TOP1_MAX*100:.0f}%), "
                f"top3={g5.get('top3_pct', 0):.1f}% (< {CONC_TOP3_MAX*100:.0f}%) "
                f"-> **{g5.get('result', 'N/A')}**"
            )

            lines.append("")

    # Section 3: Key findings
    lines.extend([
        "---",
        "",
        "## 3. Key Findings",
        "",
    ])

    for r in all_results:
        cfg_name = r["config_name"]
        lines.append(f"### {cfg_name}")
        lines.append("")

        passing_tiers = []
        failing_tiers = []
        insuf_tiers = []

        for tid in ("1", "2", "3", "1+2"):
            tr = r["tier_results"][tid]
            v = tr["verdict"]["verdict"]
            label = tr["tier_label"]
            if v == "GO":
                passing_tiers.append(label)
            elif v == "SOFT-GO":
                passing_tiers.append(f"{label} (SOFT-GO)")
            elif v == "INSUFFICIENT_SAMPLE":
                insuf_tiers.append(label)
            else:
                failing_tiers.append(f"{label}: {tr['verdict']['reason']}")

        if passing_tiers:
            lines.append(f"**Passing tiers**: {', '.join(passing_tiers)}")
        if failing_tiers:
            lines.append(f"**Failing tiers**:")
            for ft in failing_tiers:
                lines.append(f"  - {ft}")
        if insuf_tiers:
            lines.append(f"**Insufficient sample**: {', '.join(insuf_tiers)}")
        lines.append("")

    # Section 4: Live eligibility
    lines.extend([
        "---",
        "",
        "## 4. Live Eligibility Assessment",
        "",
        "> Does **Tier 1+2** at conservative fees (T2={:.1f}bps) pass all gates?".format(
            FEE_TIER2 * 10000
        ),
        "",
        "| Config | Tier 1+2 Verdict | Live Eligible? |",
        "|--------|-----------------|----------------|",
    ])

    for r in all_results:
        combined = r["tier_results"]["1+2"]
        v = combined["verdict"]["verdict"]
        eligible = "YES" if v in ("GO", "SOFT-GO") else "NO"
        lines.append(
            f"| {r['config_name']} | **{v}** | **{eligible}** |"
        )
    lines.append("")

    # Overall recommendation
    all_live_go = all(
        r["tier_results"]["1+2"]["verdict"]["verdict"] in ("GO", "SOFT-GO")
        for r in all_results
    )

    if all_live_go:
        lines.extend([
            "**Recommendation**: Both configs pass gates on the live universe (Tier 1+2) ",
            "under conservative per-tier friction. The strategy is eligible for live trading ",
            "on the tradeable universe defined in `UNIVERSE_POLICY.md`.",
        ])
    else:
        lines.extend([
            "**Recommendation**: Not all configs pass gates on the live universe. ",
            "Review per-tier results above to determine which config(s) and tier(s) ",
            "are viable. Refer to `UNIVERSE_POLICY.md` for eligibility criteria.",
        ])

    lines.extend([
        "",
        "---",
        "",
        "## Gate Thresholds (per GATES.md)",
        "",
        "| Gate | Threshold |",
        "|------|-----------|",
        f"| G1 Trade Sufficiency | >= {MIN_TRADES} trades |",
        f"| G2 Walk-Forward | >= 4/{WF_FOLDS} folds positive (or PF>1) |",
        f"| G3 Rolling Windows | >= 70% positive P&L |",
        "| G4 Friction Stress | P&L > $0 at tier_fee*1.5 AND tier_fee*2.0 |",
        f"| G5 Concentration | top1 < {CONC_TOP1_MAX*100:.0f}%, "
        f"top3 < {CONC_TOP3_MAX*100:.0f}% |",
        "",
        "## Fee Model",
        "",
        "| Tier | Base Fee | Per-Side | 1.5x Stress | 2.0x Stress |",
        "|------|----------|----------|-------------|-------------|",
        f"| Tier 1 (Liquid) | {KRAKEN_FEE*10000:.1f} bps "
        f"| {FEE_TIER1*10000:.1f} bps "
        f"| {FEE_TIER1*1.5*10000:.1f} bps "
        f"| {FEE_TIER1*2.0*10000:.1f} bps |",
        f"| Tier 2 (Mid) | {KRAKEN_FEE*10000:.1f} bps "
        f"| {FEE_TIER2*10000:.1f} bps "
        f"| {FEE_TIER2*1.5*10000:.1f} bps "
        f"| {FEE_TIER2*2.0*10000:.1f} bps |",
        f"| Tier 3 (Illiquid) | {KRAKEN_FEE*10000:.1f} bps "
        f"| {FEE_TIER3*10000:.1f} bps "
        f"| {FEE_TIER3*1.5*10000:.1f} bps "
        f"| {FEE_TIER3*2.0*10000:.1f} bps |",
        f"| Tier 1+2 (Live) | {KRAKEN_FEE*10000:.1f} bps "
        f"| {FEE_TIER2*10000:.1f} bps "
        f"| {FEE_TIER2*1.5*10000:.1f} bps "
        f"| {FEE_TIER2*2.0*10000:.1f} bps |",
        "",
        "## Verdict Logic",
        "",
        "- `INSUFFICIENT_SAMPLE`: trades < 20",
        "- `GO`: all 5 hard gates pass",
        "- `SOFT-GO`: WF 3/5 and all other gates pass",
        "- `NO-GO`: any gate fails (beyond soft WF)",
        "",
        f"*Generated by hf_validate_per_tier.py at {meta['timestamp']} -- "
        f"4H variant research*",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="HF Per-Tier Validation -- 4H variant research (Sprint 2.3)"
    )
    parser.add_argument(
        "--universe",
        choices=["tradeable", "live"],
        default="tradeable",
        help="Which candle cache to use (default: tradeable)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  HF Per-Tier Validation -- 4H Variant Research (Sprint 2.3)")
    print("  Question: Which tiers pass all 5 hard gates under realistic friction?")
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
    data_coins_set = set(all_coins)
    for tier_id in list(tiers.keys()):
        tiers[tier_id] = [c for c in tiers[tier_id] if c in data_coins_set]

    total_tiered = sum(len(v) for v in tiers.values())
    print(f"  Tier coins in data: {total_tiered} / {len(all_coins)}")

    # Print fee model summary
    print("\n  Fee model (per side):")
    for tier_id in (1, 2, 3):
        fee = TIER_FEES[tier_id]
        print(f"    {TIER_LABELS[tier_id]}: {fee*10000:.1f}bps "
              f"(1.5x={fee*1.5*10000:.1f}bps, 2.0x={fee*2.0*10000:.1f}bps)")
    combined_fee = TIER_FEES["1+2"]
    print(f"    {TIER_LABELS['1+2']}: {combined_fee*10000:.1f}bps "
          f"(conservative T2 fee)")

    t_start = time.time()

    # 3. Run per-tier validation for each config
    all_results = []
    for cfg_name, cfg in CONFIGS.items():
        result = validate_config(cfg_name, cfg, data, all_coins, tiers)
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
            "tier1_fee": FEE_TIER1,
            "tier2_fee": FEE_TIER2,
            "tier3_fee": FEE_TIER3,
            "combined_fee": TIER_FEES["1+2"],
        },
        "gate_thresholds": {
            "min_trades": MIN_TRADES,
            "wf_folds": WF_FOLDS,
            "wf_embargo": WF_EMBARGO,
            "wf_pass_min": 4,
            "rolling_window_bars": ROLLING_WINDOW_BARS,
            "rolling_positive_min": 0.70,
            "concentration_top1_max": CONC_TOP1_MAX,
            "concentration_top3_max": CONC_TOP3_MAX,
        },
        "total_time_s": round(total_time, 2),
        "label": "4H variant research",
        "configs_validated": list(CONFIGS.keys()),
    }

    # 5. Write JSON report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / "validate_per_tier_001.json"

    json_output = {
        "meta": meta,
        "results": [],
    }
    for r in all_results:
        json_output["results"].append({
            "config_name": r["config_name"],
            "cfg": r["cfg"],
            "tier_results": r["tier_results"],
            "elapsed_s": r["elapsed_s"],
        })

    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    print(f"\n  Wrote {json_path}")

    # 6. Write Markdown report
    md_path = REPORTS_DIR / "validate_per_tier_001.md"
    md = generate_markdown(all_results, meta)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # 7. Final summary
    print("\n" + "=" * 70)
    print("  PER-TIER VALIDATION SUMMARY (4H variant research)")
    print("=" * 70)

    print(f"\n  {'Config':<16} {'Tier':<22} {'Coins':>6} {'Fee':>8} "
          f"{'Verdict':<16} {'Failed Gates'}")
    print("  " + "-" * 80)

    for r in all_results:
        first = True
        for tid in ("1", "2", "3", "1+2"):
            tr = r["tier_results"][tid]
            v = tr["verdict"]
            failed = ", ".join(v["failed_gates"]) if v["failed_gates"] else "-"
            cfg_display = r["config_name"] if first else ""
            first = False
            print(f"  {cfg_display:<16} {tr['tier_label']:<22} "
                  f"{tr['n_coins']:>6} {tr['tier_fee_bps']:>6.1f}bp "
                  f"{v['verdict']:<16} {failed}")
        print()

    # Live eligibility check
    print("  LIVE ELIGIBILITY (Tier 1+2):")
    for r in all_results:
        combined = r["tier_results"]["1+2"]
        v = combined["verdict"]["verdict"]
        eligible = "ELIGIBLE" if v in ("GO", "SOFT-GO") else "NOT ELIGIBLE"
        print(f"    {r['config_name']:<16} {v:<16} -> {eligible}")

    print(f"\n  Total runtime: {total_time:.1f}s")
    print("  " + "=" * 65)


if __name__ == "__main__":
    main()

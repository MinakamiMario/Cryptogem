#!/usr/bin/env python3
"""
HF Validate MTF — Multi-Timeframe validation with A/B config comparison.

Phase 3: Run the full gate suite on 1H/15m data, comparing two config
variants side-by-side to determine if the DualConfirm edge survives
at higher frequencies.

A/B Config comparison:
  Config A ("as-is"):         GRID_BEST unchanged (time_max_bars=15)
  Config B ("wall-clock"):    time_max_bars scaled to preserve 60h hold time
                              1H: time_max_bars=60, 15m: time_max_bars=240

Gates (from GATES.md):
  Gate 1: MIN_TRADES >= 20
  Gate 2: Walk-Forward >= 3/5 folds profitable (with embargo)
  Gate 3: Max DD < 50%
  Gate 4: Outlier dependency < 80% (top trade < 80% of total P&L)
  Gate 5: Friction stress survival (per-tier 2x fees, P&L > 0)
  Gate 6: Coin concentration < 80% (informational)

Per-tier composite:
  Run T1 and T2 separately with tier fees (T1=0.0031, T2=0.0056),
  merge trade_lists, replay equity curve.

Usage:
    python strategies/hf/hf_validate_mtf.py --timeframe 1h
    python strategies/hf/hf_validate_mtf.py --timeframe 15m

Outputs:
    reports/hf/validate_{tf}_001.json  — full structured results
    reports/hf/validate_{tf}_001.md    — human-readable summary
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
TIERING_PATH = REPORTS_DIR / "universe_tiering_001.json"

# --- Timeframe-scaled parameters ---
TF_PARAMS = {
    "4h": {
        "cache_file": DATA_DIR / "candle_cache_tradeable.json",
        "rolling_window_bars": 180,
        "wf_embargo": 2,
        "start_bar": 50,
        "min_trades": 20,
        "time_max_bars_scaled": 15,   # baseline (60h / 4h = 15)
    },
    "1h": {
        "cache_file": DATA_DIR / "candle_cache_1h.json",
        "rolling_window_bars": 720,
        "wf_embargo": 2,
        "start_bar": 50,
        "min_trades": 20,
        "time_max_bars_scaled": 60,   # 60h / 1h = 60
    },
    "15m": {
        "cache_file": DATA_DIR / "candle_cache_15m.json",
        "rolling_window_bars": 2880,
        "wf_embargo": 8,
        "start_bar": 200,
        "min_trades": 20,
        "time_max_bars_scaled": 240,  # 60h / 0.25h = 240
    },
}

# Walk-forward parameters (shared)
WF_FOLDS = 5

# Gate thresholds
MAX_DD_PCT = 50.0               # Gate 3: max drawdown
OUTLIER_DEP_MAX = 0.80          # Gate 4: top trade < 80% of total P&L
CONC_MAX = 0.80                 # Gate 6: coin concentration < 80%

# --- Per-tier fee model (per side) ---
FEE_TIER1 = 0.0031   # KRAKEN_FEE + 5 bps
FEE_TIER2 = 0.0056   # KRAKEN_FEE + 30 bps
TIER_FEES = {1: FEE_TIER1, 2: FEE_TIER2}
TIER_FEES_2X = {1: KRAKEN_FEE + 0.0005 * 2, 2: KRAKEN_FEE + 0.0030 * 2}
TIER_LABELS = {1: "Tier 1 (Liquid)", 2: "Tier 2 (Mid)"}

# --- Configs under test ---
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


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_data(tf: str):
    """Load candle data for given timeframe."""
    params = TF_PARAMS[tf]
    path = params["cache_file"]
    if not path.exists():
        print(f"ERROR: No data file found: {path}")
        print(f"  Expected: data/candle_cache_{tf}.json")
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


def replay_equity_curve(trade_list, initial_capital):
    """
    Replay equity curve from a merged trade_list sorted by entry_bar.

    Correctly computes drawdown and profit factor from aggregated
    per-tier trades by replaying the equity curve chronologically.

    Returns dict: {pnl, pf, dd, trades, wr, final_equity}
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
    sorted_trades = sorted(
        trade_list,
        key=lambda t: (t["entry_bar"], t.get("exit_bar", 0)),
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
# Per-tier composite backtest
# ---------------------------------------------------------------------------
def run_per_tier_composite(data, tiers, cfg, tier_fees, start_bar, label=""):
    """
    Run backtest per tier with tier-specific fees, then aggregate.

    For each tier:
      1. precompute_all(data, tier_coins)
      2. run_backtest(indicators, tier_coins, cfg, fee_override=tier_fee)
      3. Collect trade_list

    Aggregate:
      - Merge all trade_lists, sort by entry_bar
      - Replay equity curve from INITIAL_CAPITAL for correct DD

    Returns (composite_result, per_tier_results, merged_trade_list)
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
        result = run_backtest(
            indicators, tier_coins, cfg,
            start_bar=start_bar,
            fee_override=fee,
        )

        trade_list = result.get("trade_list", [])

        # Tag each trade with its tier
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

    return composite, per_tier, all_trade_lists


# ---------------------------------------------------------------------------
# Gate 1: MIN_TRADES >= 20
# ---------------------------------------------------------------------------
def gate_min_trades(trade_count, min_trades):
    """Gate 1: Check minimum trade count."""
    passed = trade_count >= min_trades
    return {
        "gate": "G1",
        "name": "min_trades",
        "trade_count": trade_count,
        "threshold": min_trades,
        "result": "PASS" if passed else "FAIL",
    }


# ---------------------------------------------------------------------------
# Gate 2: Walk-Forward >= 3/5 folds profitable (with embargo)
# ---------------------------------------------------------------------------
def gate_walk_forward(data, tiers, cfg, tier_fees, tf_params):
    """
    Gate 2: Purged walk-forward with per-tier composite on each fold.
    Split bars into 5 folds, run per-tier composite per fold.
    Pass: >= 3/5 folds profitable.
    """
    # Determine total bar range from first available coin
    all_coins = []
    for tier_coins in tiers.values():
        all_coins.extend(tier_coins)
    if not all_coins:
        return {
            "gate": "G2", "name": "walk_forward",
            "n_folds": WF_FOLDS, "embargo": tf_params["wf_embargo"],
            "folds": [], "positive_folds": 0, "result": "FAIL",
        }

    sample_coin = all_coins[0]
    n_bars = len(data[sample_coin])
    start_bar = tf_params["start_bar"]
    embargo = tf_params["wf_embargo"]
    usable_bars = n_bars - start_bar
    fold_size = usable_bars // WF_FOLDS

    folds = []
    for i in range(WF_FOLDS):
        test_start = start_bar + i * fold_size
        test_end = test_start + fold_size if i < WF_FOLDS - 1 else n_bars

        # Purge embargo bars
        actual_start = test_start + embargo if i > 0 else test_start

        # Build per-tier data limited to fold range
        fold_trade_list = []
        for tier_id in sorted(tiers.keys()):
            tier_coins = tiers[tier_id]
            fee = tier_fees[tier_id]
            if not tier_coins:
                continue

            indicators = precompute_all(data, tier_coins, end_bar=test_end)
            result = run_backtest(
                indicators, tier_coins, cfg,
                start_bar=actual_start,
                end_bar=test_end,
                fee_override=fee,
            )
            tl = result.get("trade_list", [])
            for t in tl:
                t["_tier"] = tier_id
            fold_trade_list.extend(tl)

        fold_composite = replay_equity_curve(fold_trade_list, INITIAL_CAPITAL)

        fold_result = {
            "fold": i + 1,
            "test_start": actual_start,
            "test_end": test_end,
            "trades": fold_composite["trades"],
            "pnl": fold_composite["pnl"],
            "pf": fold_composite["pf"],
            "wr": fold_composite["wr"],
            "dd": fold_composite["dd"],
            "positive": fold_composite["pnl"] > 0,
        }
        folds.append(fold_result)

    positive_folds = sum(1 for f in folds if f["positive"])
    passed = positive_folds >= 3

    return {
        "gate": "G2",
        "name": "walk_forward",
        "n_folds": WF_FOLDS,
        "embargo": embargo,
        "folds": folds,
        "positive_folds": positive_folds,
        "result": "PASS" if passed else "FAIL",
    }


# ---------------------------------------------------------------------------
# Gate 3: Max DD < 50%
# ---------------------------------------------------------------------------
def gate_max_dd(composite_result):
    """Gate 3: Check max drawdown from composite result."""
    dd = composite_result["dd"]
    passed = dd < MAX_DD_PCT
    return {
        "gate": "G3",
        "name": "max_dd",
        "dd_pct": dd,
        "threshold": MAX_DD_PCT,
        "result": "PASS" if passed else "FAIL",
    }


# ---------------------------------------------------------------------------
# Gate 4: Outlier dependency < 80%
# ---------------------------------------------------------------------------
def gate_outlier_dependency(trade_list):
    """
    Gate 4: Top single trade < 80% of total P&L.
    If total P&L <= 0, gate fails (no positive P&L to measure).
    """
    if not trade_list:
        return {
            "gate": "G4", "name": "outlier_dependency",
            "top_trade_pnl": 0.0, "total_pnl": 0.0,
            "top_trade_share": 0.0, "threshold": OUTLIER_DEP_MAX,
            "result": "FAIL", "note": "No trades",
        }

    total_pnl = sum(t["pnl"] for t in trade_list)
    if total_pnl <= 0:
        return {
            "gate": "G4", "name": "outlier_dependency",
            "top_trade_pnl": 0.0, "total_pnl": round(total_pnl, 2),
            "top_trade_share": 0.0, "threshold": OUTLIER_DEP_MAX,
            "result": "FAIL", "note": "Total P&L not positive",
        }

    top_trade_pnl = max(t["pnl"] for t in trade_list)
    top_trade_share = top_trade_pnl / total_pnl if total_pnl > 0 else 0.0
    passed = top_trade_share < OUTLIER_DEP_MAX

    return {
        "gate": "G4",
        "name": "outlier_dependency",
        "top_trade_pnl": round(top_trade_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "top_trade_share": round(top_trade_share, 4),
        "top_trade_pct": round(top_trade_share * 100, 1),
        "threshold": OUTLIER_DEP_MAX,
        "result": "PASS" if passed else "FAIL",
    }


# ---------------------------------------------------------------------------
# Gate 5: Friction stress (per-tier 2x fees, P&L > 0)
# ---------------------------------------------------------------------------
def gate_friction_stress(data, tiers, cfg, start_bar):
    """
    Gate 5: Per-tier 2x fees composite must have P&L > 0.
    """
    print("      Running friction stress (2x fees)...")
    composite_2x, per_tier_2x, _ = run_per_tier_composite(
        data, tiers, cfg, TIER_FEES_2X, start_bar, label="friction_2x",
    )
    passed = composite_2x["pnl"] > 0

    return {
        "gate": "G5",
        "name": "friction_stress",
        "composite_pnl": composite_2x["pnl"],
        "composite_pf": composite_2x["pf"],
        "composite_dd": composite_2x["dd"],
        "composite_trades": composite_2x["trades"],
        "per_tier": per_tier_2x,
        "result": "PASS" if passed else "FAIL",
    }


# ---------------------------------------------------------------------------
# Gate 6: Coin concentration < 80% (informational)
# ---------------------------------------------------------------------------
def gate_coin_concentration(trade_list):
    """
    Gate 6 (informational): No single coin > 80% of total positive P&L.
    """
    if not trade_list:
        return {
            "gate": "G6", "name": "coin_concentration",
            "top_coin": None, "top_coin_share": 0.0,
            "result": "INFO", "note": "No trades",
        }

    coin_pnl = defaultdict(float)
    for t in trade_list:
        coin_pnl[t["pair"]] += t["pnl"]

    positive_profits = {c: max(0.0, pnl) for c, pnl in coin_pnl.items()}
    total_positive = sum(positive_profits.values())

    if total_positive <= 0:
        return {
            "gate": "G6", "name": "coin_concentration",
            "top_coin": None, "top_coin_share": 0.0,
            "result": "INFO", "note": "No positive P&L",
        }

    sorted_coins = sorted(positive_profits.items(), key=lambda x: -x[1])
    top_coin = sorted_coins[0][0]
    top_coin_profit = sorted_coins[0][1]
    top_coin_share = top_coin_profit / total_positive

    passed = top_coin_share < CONC_MAX

    return {
        "gate": "G6",
        "name": "coin_concentration",
        "top_coin": top_coin,
        "top_coin_profit": round(top_coin_profit, 2),
        "total_positive_pnl": round(total_positive, 2),
        "top_coin_share": round(top_coin_share, 4),
        "top_coin_pct": round(top_coin_share * 100, 1),
        "threshold": CONC_MAX,
        "n_coins_traded": len(coin_pnl),
        "result": "PASS" if passed else "FAIL",
        "informational": True,
    }


# ---------------------------------------------------------------------------
# Build A/B configs
# ---------------------------------------------------------------------------
def build_ab_configs(tf: str):
    """
    Build Config A (as-is) and Config B (wall-clock scaled) for the
    given timeframe.
    """
    params = TF_PARAMS[tf]
    scaled_tmb = params["time_max_bars_scaled"]

    # Config A: GRID_BEST unchanged (time_max_bars=15)
    config_a = normalize_cfg(dict(GRID_BEST))

    # Config B: time_max_bars scaled to preserve 60h hold time
    config_b_dict = dict(GRID_BEST)
    config_b_dict["time_max_bars"] = scaled_tmb
    config_b = normalize_cfg(config_b_dict)

    return {
        "Config_A (as-is)": {
            "cfg": config_a,
            "description": f"GRID_BEST unchanged (time_max_bars=15)",
        },
        "Config_B (scaled)": {
            "cfg": config_b,
            "description": f"Wall-clock scaled (time_max_bars={scaled_tmb}, preserves 60h hold)",
        },
    }


# ---------------------------------------------------------------------------
# Run all gates for one config
# ---------------------------------------------------------------------------
def run_all_gates(config_name, cfg, data, tiers, tf_params):
    """Run all 6 gates for a single config. Returns gate results + composite."""
    print(f"\n  --- {config_name} ---")
    print(f"  Config: {json.dumps(cfg, sort_keys=True)}")

    t0 = time.time()
    start_bar = tf_params["start_bar"]
    min_trades = tf_params["min_trades"]

    # Run per-tier composite baseline
    print("    Running per-tier composite (baseline fees)...")
    composite, per_tier, trade_list = run_per_tier_composite(
        data, tiers, cfg, TIER_FEES, start_bar, label="baseline",
    )
    print(f"    Composite: {composite['trades']} trades, "
          f"P&L=${composite['pnl']:+,.2f}, PF={composite['pf']}, "
          f"DD={composite['dd']}%")

    gates = {}

    # Gate 1: MIN_TRADES
    print("    G1: Min trades...")
    g1 = gate_min_trades(composite["trades"], min_trades)
    gates["G1"] = g1
    print(f"        {g1['trade_count']} trades (min={min_trades}) -> {g1['result']}")

    # Gate 2: Walk-Forward
    print("    G2: Walk-Forward (5-fold)...")
    t2 = time.time()
    g2 = gate_walk_forward(data, tiers, cfg, TIER_FEES, tf_params)
    gates["G2"] = g2
    print(f"        {g2['positive_folds']}/{WF_FOLDS} positive folds "
          f"-> {g2['result']} ({time.time()-t2:.1f}s)")

    # Gate 3: Max DD
    print("    G3: Max DD...")
    g3 = gate_max_dd(composite)
    gates["G3"] = g3
    print(f"        DD={g3['dd_pct']}% (max={MAX_DD_PCT}%) -> {g3['result']}")

    # Gate 4: Outlier dependency
    print("    G4: Outlier dependency...")
    g4 = gate_outlier_dependency(trade_list)
    gates["G4"] = g4
    print(f"        Top trade share={g4.get('top_trade_pct', 0):.1f}% "
          f"(max={OUTLIER_DEP_MAX*100:.0f}%) -> {g4['result']}")

    # Gate 5: Friction stress (2x fees)
    print("    G5: Friction stress (2x fees)...")
    t5 = time.time()
    g5 = gate_friction_stress(data, tiers, cfg, start_bar)
    gates["G5"] = g5
    print(f"        P&L=${g5['composite_pnl']:+,.2f} "
          f"-> {g5['result']} ({time.time()-t5:.1f}s)")

    # Gate 6: Coin concentration (informational)
    print("    G6: Coin concentration (informational)...")
    g6 = gate_coin_concentration(trade_list)
    gates["G6"] = g6
    top_coin_pct = g6.get("top_coin_pct", 0.0)
    print(f"        Top coin={g6.get('top_coin', 'N/A')} "
          f"share={top_coin_pct:.1f}% -> {g6['result']}")

    # Compute verdict
    hard_gates = ["G1", "G2", "G3", "G4", "G5"]
    failed = [g for g in hard_gates if gates[g]["result"] != "PASS"]

    if not failed:
        verdict = "PASS"
        verdict_reason = "All 5 hard gates passed"
    else:
        verdict = "FAIL"
        verdict_reason = f"Failed gates: {', '.join(failed)}"

    elapsed = time.time() - t0
    print(f"\n    VERDICT: {verdict} ({verdict_reason}) [{elapsed:.1f}s]")

    return {
        "config_name": config_name,
        "cfg": cfg,
        "composite": composite,
        "per_tier": per_tier,
        "gates": gates,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "failed_gates": failed,
        "elapsed_s": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Overall MTF verdict
# ---------------------------------------------------------------------------
def compute_mtf_verdict(result_a, result_b, tf):
    """
    Determine overall MTF verdict from A/B comparison.
    - If A passes -> "{TF} viable with as-is config"
    - If A fails but B passes -> "{TF} viable with TF-scaled params, grid-search needed"
    - If both fail -> "{TF} has no edge for DualConfirm"
    """
    a_pass = result_a["verdict"] == "PASS"
    b_pass = result_b["verdict"] == "PASS"
    tf_upper = tf.upper()

    if a_pass:
        return {
            "overall_verdict": "VIABLE_AS_IS",
            "summary": f"{tf_upper} viable with as-is config",
            "detail": (
                f"Config A (time_max_bars=15) passes all 5 hard gates on {tf_upper} data. "
                f"The DualConfirm edge survives at {tf_upper} frequency without parameter changes."
            ),
            "config_a_pass": True,
            "config_b_pass": b_pass,
        }
    elif b_pass:
        return {
            "overall_verdict": "VIABLE_SCALED",
            "summary": f"{tf_upper} viable with TF-scaled params, grid-search needed",
            "detail": (
                f"Config A fails on {tf_upper}, but Config B (wall-clock scaled time_max_bars) "
                f"passes all gates. A dedicated {tf_upper} grid-search is recommended."
            ),
            "config_a_pass": False,
            "config_b_pass": True,
        }
    else:
        return {
            "overall_verdict": "NO_EDGE",
            "summary": f"{tf_upper} has no edge for DualConfirm",
            "detail": (
                f"Both Config A and Config B fail on {tf_upper} data. "
                f"The DualConfirm strategy does not transfer to {tf_upper} frequency."
            ),
            "config_a_pass": False,
            "config_b_pass": False,
        }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------
def generate_markdown(result_a, result_b, mtf_verdict, meta, tf, tiers):
    """Generate human-readable validation report with A vs B comparison."""
    tf_upper = tf.upper()
    params = TF_PARAMS[tf]

    lines = [
        f"# HF Multi-Timeframe Validation Report -- {tf_upper}",
        "",
        f"> **Key question**: Does the DualConfirm edge survive at {tf_upper} frequency?",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Timeframe**: {tf_upper}",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Total coins**: {meta['n_coins']}",
        f"**Tier source**: `universe_tiering_001.json`",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
    ]

    # Section 1: TF-scaled parameters
    lines.extend([
        "## 1. Timeframe-Scaled Parameters",
        "",
        "| Param | 4H | 1H | 15m |",
        "|-------|----|----|-----|",
    ])
    param_rows = [
        ("ROLLING_WINDOW_BARS", "180", "720", "2880"),
        ("WF_EMBARGO", "2", "2", "8"),
        ("start_bar", "50", "50", "200"),
        ("MIN_TRADES", "20", "20", "20"),
        ("time_max_bars (scaled)", "15", "60", "240"),
    ]
    for row in param_rows:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} |")
    lines.extend([
        "",
        f"**Active timeframe**: {tf_upper}",
        f"**Rolling window**: {params['rolling_window_bars']} bars",
        f"**WF embargo**: {params['wf_embargo']} bars",
        f"**Start bar**: {params['start_bar']}",
        "",
    ])

    # Section 2: A/B Config definition
    lines.extend([
        "## 2. A/B Config Definition",
        "",
        "| Config | time_max_bars | Description |",
        "|--------|---------------|-------------|",
        f"| Config A (as-is) | 15 | GRID_BEST unchanged |",
        f"| Config B (scaled) | {params['time_max_bars_scaled']} "
        f"| Wall-clock scaled to preserve 60h hold time |",
        "",
        f"**Config A**: `{json.dumps(result_a['cfg'], sort_keys=True)}`",
        f"**Config B**: `{json.dumps(result_b['cfg'], sort_keys=True)}`",
        "",
    ])

    # Section 3: Gate-by-gate comparison
    lines.extend([
        "## 3. Gate-by-Gate Comparison (A vs B)",
        "",
        "| Gate | Threshold | Config A | Config B |",
        "|------|-----------|----------|----------|",
    ])

    gate_thresholds = {
        "G1": f"Trades >= {params['min_trades']}",
        "G2": f"WF >= 3/{WF_FOLDS} folds profitable",
        "G3": f"Max DD < {MAX_DD_PCT:.0f}%",
        "G4": f"Top trade < {OUTLIER_DEP_MAX*100:.0f}% of P&L",
        "G5": "Per-tier 2x fees P&L > $0",
        "G6": f"Coin conc < {CONC_MAX*100:.0f}% (info)",
    }

    for gate_key in ("G1", "G2", "G3", "G4", "G5", "G6"):
        ga = result_a["gates"].get(gate_key, {})
        gb = result_b["gates"].get(gate_key, {})
        a_res = ga.get("result", "N/A")
        b_res = gb.get("result", "N/A")

        # Add detail to result
        a_detail = _gate_detail(gate_key, ga)
        b_detail = _gate_detail(gate_key, gb)

        lines.append(
            f"| {gate_key} {gate_thresholds.get(gate_key, '')} "
            f"| {a_res} {a_detail} | {b_res} {b_detail} |"
        )

    lines.extend([
        "",
        f"**Config A verdict**: **{result_a['verdict']}** -- {result_a['verdict_reason']}",
        f"**Config B verdict**: **{result_b['verdict']}** -- {result_b['verdict_reason']}",
        "",
    ])

    # Section 4: Composite results side-by-side
    lines.extend([
        "## 4. Composite Results (A vs B)",
        "",
        "| Metric | Config A | Config B |",
        "|--------|----------|----------|",
    ])
    ca = result_a["composite"]
    cb = result_b["composite"]
    for label, key, fmt in [
        ("Trades", "trades", "{}"),
        ("P&L", "pnl", "${:+,.2f}"),
        ("PF", "pf", "{}"),
        ("WR%", "wr", "{}%"),
        ("DD%", "dd", "{}%"),
    ]:
        va = fmt.format(ca[key])
        vb = fmt.format(cb[key])
        lines.append(f"| {label} | {va} | {vb} |")
    lines.append("")

    # Section 5: Per-tier breakdown
    lines.extend([
        "## 5. Per-Tier Breakdown",
        "",
        "### Config A",
        "",
        "| Tier | Coins | Fee (bps) | Trades | P&L | PF | DD% |",
        "|------|-------|-----------|--------|-----|----|-----|",
    ])
    for tier_id in sorted(result_a["per_tier"].keys()):
        tr = result_a["per_tier"][tier_id]
        lines.append(
            f"| {TIER_LABELS.get(tier_id, f'Tier {tier_id}')} "
            f"| {tr['n_coins']} | {tr['fee_bps']:.1f} "
            f"| {tr['trades']} | ${tr['pnl']:+,.2f} "
            f"| {tr['pf']} | {tr['dd']}% |"
        )

    lines.extend([
        "",
        "### Config B",
        "",
        "| Tier | Coins | Fee (bps) | Trades | P&L | PF | DD% |",
        "|------|-------|-----------|--------|-----|----|-----|",
    ])
    for tier_id in sorted(result_b["per_tier"].keys()):
        tr = result_b["per_tier"][tier_id]
        lines.append(
            f"| {TIER_LABELS.get(tier_id, f'Tier {tier_id}')} "
            f"| {tr['n_coins']} | {tr['fee_bps']:.1f} "
            f"| {tr['trades']} | ${tr['pnl']:+,.2f} "
            f"| {tr['pf']} | {tr['dd']}% |"
        )
    lines.append("")

    # Section 6: Walk-Forward detail
    lines.extend([
        "## 6. Walk-Forward Detail",
        "",
    ])
    for config_label, result in [("Config A", result_a), ("Config B", result_b)]:
        g2 = result["gates"].get("G2", {})
        folds = g2.get("folds", [])
        lines.extend([
            f"### {config_label} ({g2.get('positive_folds', 0)}/{WF_FOLDS} positive)",
            "",
            "| Fold | Bars | Trades | P&L | PF | WR% | DD% | Positive |",
            "|------|------|--------|-----|----|-----|-----|----------|",
        ])
        for f in folds:
            lines.append(
                f"| {f['fold']} | {f['test_start']}-{f['test_end']} "
                f"| {f['trades']} | ${f['pnl']:+,.2f} | {f['pf']} "
                f"| {f['wr']}% | {f['dd']}% | {'YES' if f['positive'] else 'NO'} |"
            )
        lines.append("")

    # Section 7: Overall verdict
    lines.extend([
        "---",
        "",
        "## 7. Overall MTF Verdict",
        "",
        f"### **{mtf_verdict['overall_verdict']}**: {mtf_verdict['summary']}",
        "",
        f"{mtf_verdict['detail']}",
        "",
    ])

    # Verdict interpretation table
    lines.extend([
        "### Verdict Interpretation",
        "",
        "| Condition | Result |",
        "|-----------|--------|",
        f"| Config A passes | {'YES' if mtf_verdict['config_a_pass'] else 'NO'} |",
        f"| Config B passes | {'YES' if mtf_verdict['config_b_pass'] else 'NO'} |",
        "",
        "**Verdict logic**:",
        f"- If A passes: \"{tf_upper} viable with as-is config\"",
        f"- If A fails but B passes: \"{tf_upper} viable with TF-scaled params, "
        f"grid-search needed\"",
        f"- If both fail: \"{tf_upper} has no edge for DualConfirm\"",
        "",
    ])

    # Section 8: Gate thresholds
    lines.extend([
        "---",
        "",
        "## 8. Gate Thresholds (from GATES.md)",
        "",
        "| Gate | Threshold | Type |",
        "|------|-----------|------|",
        f"| G1 Min Trades | >= {params['min_trades']} | Hard |",
        f"| G2 Walk-Forward | >= 3/{WF_FOLDS} folds profitable | Hard |",
        f"| G3 Max DD | < {MAX_DD_PCT:.0f}% | Hard |",
        f"| G4 Outlier Dependency | < {OUTLIER_DEP_MAX*100:.0f}% of total P&L | Hard |",
        f"| G5 Friction Stress | Per-tier 2x fees P&L > $0 | Hard |",
        f"| G6 Coin Concentration | < {CONC_MAX*100:.0f}% | Informational |",
        "",
    ])

    # Fee model
    lines.extend([
        "## Fee Model",
        "",
        "| Tier | Per-Side Fee | 2x Stress Fee |",
        "|------|-------------|---------------|",
        f"| Tier 1 (Liquid) | {FEE_TIER1*10000:.1f} bps "
        f"| {TIER_FEES_2X[1]*10000:.1f} bps |",
        f"| Tier 2 (Mid) | {FEE_TIER2*10000:.1f} bps "
        f"| {TIER_FEES_2X[2]*10000:.1f} bps |",
        "",
        "---",
        f"*Generated by hf_validate_mtf.py at {meta['timestamp']} -- "
        f"{tf_upper} multi-timeframe validation*",
    ])

    return "\n".join(lines)


def _gate_detail(gate_key, gate_result):
    """Return a short detail string for each gate result in the table."""
    if not gate_result:
        return ""
    if gate_key == "G1":
        return f"({gate_result.get('trade_count', 0)} trades)"
    if gate_key == "G2":
        return f"({gate_result.get('positive_folds', 0)}/{WF_FOLDS})"
    if gate_key == "G3":
        return f"({gate_result.get('dd_pct', 0)}%)"
    if gate_key == "G4":
        return f"({gate_result.get('top_trade_pct', 0):.1f}%)"
    if gate_key == "G5":
        return f"(${gate_result.get('composite_pnl', 0):+,.0f})"
    if gate_key == "G6":
        return f"({gate_result.get('top_coin_pct', 0):.1f}%)"
    return ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="HF Multi-Timeframe Validation with A/B Config Comparison"
    )
    parser.add_argument(
        "--timeframe", "-tf",
        choices=["1h", "15m"],
        required=True,
        help="Timeframe to validate (1h or 15m)",
    )
    args = parser.parse_args()

    tf = args.timeframe
    tf_upper = tf.upper()
    params = TF_PARAMS[tf]

    print("=" * 70)
    print(f"  HF Multi-Timeframe Validation -- {tf_upper}")
    print(f"  Key question: Does DualConfirm edge survive at {tf_upper}?")
    print("=" * 70)

    # 1. Load tier assignments
    tiers = load_tier_assignments()
    for tier_id in sorted(tiers.keys()):
        print(f"  {TIER_LABELS[tier_id]}: {len(tiers[tier_id])} coins")

    # 2. Load candle data
    data, all_coins, data_path = load_data(tf)
    n_bars = len(data[all_coins[0]]) if all_coins else 0
    print(f"  Loaded {len(all_coins)} coins, {n_bars} bars from {Path(data_path).name}")

    # Filter tier coins to only those present in data
    data_coins_set = set(all_coins)
    for tier_id in list(tiers.keys()):
        tiers[tier_id] = [c for c in tiers[tier_id] if c in data_coins_set]

    total_tiered = sum(len(v) for v in tiers.values())
    print(f"  Tier coins in data: {total_tiered} / {len(all_coins)}")

    # Print TF parameters
    print(f"\n  TF Parameters ({tf_upper}):")
    print(f"    rolling_window_bars: {params['rolling_window_bars']}")
    print(f"    wf_embargo: {params['wf_embargo']}")
    print(f"    start_bar: {params['start_bar']}")
    print(f"    min_trades: {params['min_trades']}")
    print(f"    time_max_bars (scaled): {params['time_max_bars_scaled']}")

    # Print fee model
    print("\n  Fee model (per side):")
    for tier_id in (1, 2):
        print(f"    {TIER_LABELS[tier_id]}: {TIER_FEES[tier_id]*10000:.1f}bps "
              f"(2x: {TIER_FEES_2X[tier_id]*10000:.1f}bps)")

    # 3. Build A/B configs
    ab_configs = build_ab_configs(tf)
    print("\n  A/B Configs:")
    for name, info in ab_configs.items():
        print(f"    {name}: {info['description']}")
        print(f"      {json.dumps(info['cfg'], sort_keys=True)}")

    t_start = time.time()

    # 4. Run all gates for Config A and Config B
    config_a_name = "Config_A (as-is)"
    config_b_name = "Config_B (scaled)"

    result_a = run_all_gates(
        config_a_name,
        ab_configs[config_a_name]["cfg"],
        data, tiers, params,
    )

    result_b = run_all_gates(
        config_b_name,
        ab_configs[config_b_name]["cfg"],
        data, tiers, params,
    )

    total_time = time.time() - t_start

    # 5. Compute overall MTF verdict
    mtf_verdict = compute_mtf_verdict(result_a, result_b, tf)

    # 6. Build meta
    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "timeframe": tf,
        "data_file": data_path,
        "n_coins": len(all_coins),
        "n_bars": n_bars,
        "tier_source": str(TIERING_PATH),
        "tier_counts": {str(k): len(v) for k, v in tiers.items()},
        "tf_params": {
            "rolling_window_bars": params["rolling_window_bars"],
            "wf_embargo": params["wf_embargo"],
            "start_bar": params["start_bar"],
            "min_trades": params["min_trades"],
            "time_max_bars_scaled": params["time_max_bars_scaled"],
        },
        "fee_model": {
            "tier1_fee": FEE_TIER1,
            "tier2_fee": FEE_TIER2,
            "tier1_fee_2x": TIER_FEES_2X[1],
            "tier2_fee_2x": TIER_FEES_2X[2],
        },
        "gate_thresholds": {
            "min_trades": params["min_trades"],
            "wf_folds": WF_FOLDS,
            "wf_min_positive": 3,
            "max_dd_pct": MAX_DD_PCT,
            "outlier_dep_max": OUTLIER_DEP_MAX,
            "conc_max": CONC_MAX,
        },
        "total_time_s": round(total_time, 2),
        "label": f"{tf_upper} multi-timeframe validation",
    }

    # 7. Write JSON report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / f"validate_{tf}_001.json"

    json_output = {
        "meta": meta,
        "config_a": {
            "config_name": result_a["config_name"],
            "cfg": result_a["cfg"],
            "composite": result_a["composite"],
            "per_tier": result_a["per_tier"],
            "gates": result_a["gates"],
            "verdict": result_a["verdict"],
            "verdict_reason": result_a["verdict_reason"],
            "failed_gates": result_a["failed_gates"],
            "elapsed_s": result_a["elapsed_s"],
        },
        "config_b": {
            "config_name": result_b["config_name"],
            "cfg": result_b["cfg"],
            "composite": result_b["composite"],
            "per_tier": result_b["per_tier"],
            "gates": result_b["gates"],
            "verdict": result_b["verdict"],
            "verdict_reason": result_b["verdict_reason"],
            "failed_gates": result_b["failed_gates"],
            "elapsed_s": result_b["elapsed_s"],
        },
        "mtf_verdict": mtf_verdict,
    }
    with open(json_path, "w") as f:
        json.dump(json_output, f, indent=2, default=str)
    print(f"\n  Wrote {json_path}")

    # 8. Write markdown report
    md_path = REPORTS_DIR / f"validate_{tf}_001.md"
    md = generate_markdown(result_a, result_b, mtf_verdict, meta, tf, tiers)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # 9. Final summary
    print("\n" + "=" * 70)
    print(f"  MTF VALIDATION SUMMARY -- {tf_upper}")
    print("=" * 70)

    print(f"\n  {'Config':<24} {'Verdict':<10} {'Trades':>7} {'P&L':>12} "
          f"{'PF':>6} {'DD%':>6} {'Failed Gates'}")
    print("  " + "-" * 80)
    for label, r in [("Config A (as-is)", result_a), ("Config B (scaled)", result_b)]:
        c = r["composite"]
        failed = ", ".join(r["failed_gates"]) if r["failed_gates"] else "-"
        print(f"  {label:<24} {r['verdict']:<10} {c['trades']:>7} "
              f"${c['pnl']:>+10,.2f} {c['pf']:>6} {c['dd']:>5}% {failed}")

    print(f"\n  OVERALL: {mtf_verdict['overall_verdict']}")
    print(f"  {mtf_verdict['summary']}")
    print(f"  {mtf_verdict['detail']}")

    print(f"\n  Total runtime: {total_time:.1f}s")
    print("  " + "=" * 65)


if __name__ == "__main__":
    main()

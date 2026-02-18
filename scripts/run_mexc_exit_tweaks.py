#!/usr/bin/env python3
"""
AGENT 2: Stopout Anatomy + Exit Tweaks Sweep — MEXC Top-200.

Analyzes FIXED STOP anatomy of the MEXC top-200 baseline, then tests exit
parameter modifications that reduce losses while preserving Class A quality.

Baseline: Sprint4_041 (Vol Capitulation, H4S4-G05) with vol_mult=3.5, rsi_max=35
Dataset: MEXC v2 4H candles, top 200 coins by median volume, >=2160 bars
Fee: MEXC 10bps (0.0010/side)
Exit mode: dc (hybrid_notrl)
Full range: ~2853 bars, ~467 days
Fixed-notional: $2000/trade (no compounding)

Sweeps:
  A. max_stop_pct = [5, 7, 10, 12, 15(baseline)]
  B. time_max_bars = [10, 15(baseline), 20, 25, 30]
  C. rsi_rec_target = [35, 40, 42, 45(baseline), 48, 50]
  D. rsi_rec_min_bars = [1, 2(baseline), 3, 4, 5]
  E. Combined best + manual combos

Usage:
    PYTHONUNBUFFERED=1 python3 -B scripts/run_mexc_exit_tweaks.py
"""
from __future__ import annotations

import sys
import json
import time
import copy
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from statistics import median
from collections import defaultdict

import numpy as np

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "trading_bot"))

DATA_ROOT = Path.home() / "CryptogemData"
V2_DATA_FILE = DATA_ROOT / "derived" / "candle_cache" / "mexc" / "4h" / "candle_cache_4h_mexc_v2.json"
REPORT_DIR = REPO_ROOT / "reports" / "4h"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONFIG_041_HYP_ID = "H4S4-G05"
MEXC_FEE = 0.0010
START_BAR = 50
INITIAL_CAPITAL = 2000
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8

MIN_BARS_TOP200 = 2160
TOP_N = 200
MAX_RETURN_RATIO = 1.0

# Baseline exit params
BASELINE_EXIT = {
    "max_stop_pct": 15.0,
    "time_max_bars": 15,
    "rsi_recovery": True,
    "rsi_rec_target": 45.0,
    "rsi_rec_min_bars": 2,
}


def _git_hash() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT))
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ===========================================================================
# Data loading (same as truthpass)
# ===========================================================================

def load_top200():
    """Load MEXC v2, filter to top-200 by median volume with >=2160 bars."""
    print("\n  Loading top-200 universe...")
    with open(V2_DATA_FILE) as f:
        raw_data = json.load(f)

    coins_all = [k for k in raw_data if not k.startswith("_")]
    eligible = []
    for pair in coins_all:
        candles = raw_data[pair]
        n = len(candles)
        if n < MIN_BARS_TOP200:
            continue
        vols = [c.get("volume", 0) or 0 for c in candles[-720:]]
        eligible.append((pair, n, median(vols)))

    eligible.sort(key=lambda x: x[2], reverse=True)
    top200 = eligible[:TOP_N]
    coins = sorted([t[0] for t in top200])
    data = {c: raw_data[c] for c in coins}
    bars_counts = [len(data[c]) for c in coins]

    print(f"  Coins: {len(coins)}, Bars: {min(bars_counts)}-{max(bars_counts)}, "
          f"median: {int(median(bars_counts))}")
    return data, coins, bars_counts


# ===========================================================================
# Fixed-notional wrapper
# ===========================================================================

def to_fixed_notional(trade_list, notional=INITIAL_CAPITAL):
    """Convert equity-proportional trades to fixed-notional."""
    fixed = []
    n_capped = 0
    for t in trade_list:
        size = t.get("size", t.get("size_usd", notional))
        if size <= 0:
            size = notional
        ret = t["pnl"] / size
        if abs(ret) > MAX_RETURN_RATIO:
            ret = MAX_RETURN_RATIO if ret > 0 else -MAX_RETURN_RATIO
            n_capped += 1
        ft = dict(t)
        ft["pnl"] = round(ret * notional, 2)
        ft["size"] = notional
        ft["_orig_pnl"] = round(t["pnl"], 2)
        ft["_orig_size"] = round(size, 2)
        fixed.append(ft)
    return fixed, n_capped


def compute_metrics(trades, initial=INITIAL_CAPITAL):
    """PF, DD, P&L, WR from fixed-notional trades."""
    if not trades:
        return {"trades": 0, "pf": 0, "pnl": 0, "dd": 0, "wr": 0}
    equity = initial
    peak = initial
    max_dd = 0
    wins = losses = 0
    gp = gl = 0
    for t in trades:
        equity += t["pnl"]
        if t["pnl"] > 0:
            wins += 1
            gp += t["pnl"]
        else:
            losses += 1
            gl += abs(t["pnl"])
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    pf = gp / gl if gl > 0 else 99.99
    return {
        "trades": len(trades),
        "pf": round(min(pf, 99.99), 4),
        "pnl": round(equity - initial, 2),
        "dd": round(max_dd, 2),
        "wr": round(wins / len(trades) * 100, 2) if trades else 0,
    }


def exit_attribution(trades):
    """Exit reason breakdown."""
    CLASS_A = {"RSI RECOVERY", "DC TARGET", "BB TARGET", "PROFIT TARGET"}
    by_reason = {}
    for t in trades:
        reason = t.get("reason", "UNKNOWN")
        if reason not in by_reason:
            by_reason[reason] = {"class": "A" if reason in CLASS_A else "B",
                                 "count": 0, "pnl": 0.0, "wins": 0}
        by_reason[reason]["count"] += 1
        by_reason[reason]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            by_reason[reason]["wins"] += 1
    for r in by_reason.values():
        r["wr"] = round(100 * r["wins"] / r["count"], 1) if r["count"] > 0 else 0
        r["pnl"] = round(r["pnl"], 2)
    return by_reason


# ===========================================================================
# Run engine with specific exit params
# ===========================================================================

def run_with_exit_params(data, coins, signal_fn, base_params, indicators,
                         exit_overrides, market_context):
    """Run engine with overridden exit params, return fixed-notional results."""
    import importlib
    _engine = importlib.import_module("strategies.4h.sprint3.engine")

    params = dict(base_params)
    params.update(exit_overrides)
    params["__market__"] = market_context
    for c in coins:
        indicators[c]["__coin__"] = c

    r = _engine.run_backtest(
        data, coins, signal_fn, params, indicators,
        fee=MEXC_FEE, exit_mode="dc",
        start_bar=START_BAR, initial_capital=INITIAL_CAPITAL,
        cooldown_bars=COOLDOWN_BARS, cooldown_after_stop=COOLDOWN_AFTER_STOP,
    )

    fixed_trades, n_capped = to_fixed_notional(r.trade_list)
    metrics = compute_metrics(fixed_trades)
    ea = exit_attribution(fixed_trades)

    return {
        "metrics": metrics,
        "exit_attribution": ea,
        "n_capped": n_capped,
        "trade_list": fixed_trades,
        "raw_trade_list": r.trade_list,
    }


# ===========================================================================
# Step 1: Stopout Anatomy Analysis
# ===========================================================================

def analyze_stopout_anatomy(data, indicators, raw_trade_list, fixed_trade_list):
    """Deep analysis of FIXED STOP trades: MFE, MAE, bars to stop, saveable stops."""
    print("\n" + "=" * 70)
    print("  STEP 1: Stopout Anatomy Analysis")
    print("=" * 70)

    # Separate by exit reason
    stop_trades = [t for t in fixed_trade_list if t.get("reason") == "FIXED STOP"]
    tm_trades = [t for t in fixed_trade_list if t.get("reason") == "TIME MAX"]
    rsi_trades = [t for t in fixed_trade_list if t.get("reason") == "RSI RECOVERY"]
    dc_trades = [t for t in fixed_trade_list if t.get("reason") == "DC TARGET"]
    bb_trades = [t for t in fixed_trade_list if t.get("reason") == "BB TARGET"]
    end_trades = [t for t in fixed_trade_list if t.get("reason") == "END"]

    # For FIXED STOP trades, compute MFE and MAE using raw trade data + candle data
    stop_details = []
    for ft in stop_trades:
        pair = ft["pair"]
        entry_bar = ft["entry_bar"]
        exit_bar = ft["exit_bar"]
        entry_price = ft["entry"]

        ind = indicators.get(pair)
        if ind is None:
            continue

        highs = ind["highs"]
        lows = ind["lows"]
        closes = ind["closes"]
        rsi_arr = ind["rsi"]
        n = ind["n"]

        # Walk bar-by-bar from entry to exit
        max_favorable = 0.0  # max price reached above entry
        max_adverse = 0.0    # max price drop below entry
        for b in range(entry_bar + 1, min(exit_bar + 1, n)):
            high_pct = (highs[b] - entry_price) / entry_price * 100
            low_pct = (entry_price - lows[b]) / entry_price * 100
            if high_pct > max_favorable:
                max_favorable = high_pct
            if low_pct > max_adverse:
                max_adverse = low_pct

        # RSI at exit
        rsi_at_exit = rsi_arr[exit_bar] if exit_bar < n and rsi_arr[exit_bar] is not None else None
        bars_held = exit_bar - entry_bar

        stop_details.append({
            "pair": pair,
            "entry_bar": entry_bar,
            "exit_bar": exit_bar,
            "bars_held": bars_held,
            "pnl": ft["pnl"],
            "mfe_pct": round(max_favorable, 2),  # max favorable excursion (%)
            "mae_pct": round(max_adverse, 2),     # max adverse excursion (%)
            "rsi_at_exit": round(rsi_at_exit, 1) if rsi_at_exit is not None else None,
            "went_profitable": max_favorable > 0.5,  # went >0.5% above entry
        })

    # Aggregate stats
    n_stops = len(stop_details)
    if n_stops > 0:
        avg_stop_loss = np.mean([s["pnl"] for s in stop_details])
        median_bars = np.median([s["bars_held"] for s in stop_details])
        avg_mfe = np.mean([s["mfe_pct"] for s in stop_details])
        avg_mae = np.mean([s["mae_pct"] for s in stop_details])
        saveable = sum(1 for s in stop_details if s["went_profitable"])
        saveable_pct = saveable / n_stops * 100

        # MFE distribution
        mfe_vals = [s["mfe_pct"] for s in stop_details]
        mfe_p25 = np.percentile(mfe_vals, 25)
        mfe_p50 = np.percentile(mfe_vals, 50)
        mfe_p75 = np.percentile(mfe_vals, 75)

        # Bars to stop distribution
        bars_vals = [s["bars_held"] for s in stop_details]
        bars_p25 = np.percentile(bars_vals, 25)
        bars_p50 = np.percentile(bars_vals, 50)
        bars_p75 = np.percentile(bars_vals, 75)

        # RSI at exit distribution
        rsi_exits = [s["rsi_at_exit"] for s in stop_details if s["rsi_at_exit"] is not None]
        avg_rsi_exit = np.mean(rsi_exits) if rsi_exits else None
    else:
        avg_stop_loss = median_bars = avg_mfe = avg_mae = 0
        saveable = saveable_pct = 0
        mfe_p25 = mfe_p50 = mfe_p75 = 0
        bars_p25 = bars_p50 = bars_p75 = 0
        avg_rsi_exit = None

    # P&L attribution
    total_pnl = sum(t["pnl"] for t in fixed_trade_list)
    stop_pnl = sum(t["pnl"] for t in stop_trades)
    tm_pnl = sum(t["pnl"] for t in tm_trades)
    rsi_pnl = sum(t["pnl"] for t in rsi_trades)
    dc_pnl = sum(t["pnl"] for t in dc_trades)
    bb_pnl = sum(t["pnl"] for t in bb_trades)
    end_pnl = sum(t["pnl"] for t in end_trades)

    anatomy = {
        "total_trades": len(fixed_trade_list),
        "total_pnl": round(total_pnl, 2),
        "fixed_stop": {
            "count": n_stops,
            "pnl": round(stop_pnl, 2),
            "avg_loss": round(avg_stop_loss, 2) if n_stops else 0,
            "median_bars": round(float(median_bars), 1) if n_stops else 0,
            "avg_mfe_pct": round(float(avg_mfe), 2),
            "avg_mae_pct": round(float(avg_mae), 2),
            "mfe_quartiles": {"p25": round(float(mfe_p25), 2),
                              "p50": round(float(mfe_p50), 2),
                              "p75": round(float(mfe_p75), 2)},
            "bars_quartiles": {"p25": round(float(bars_p25), 1),
                               "p50": round(float(bars_p50), 1),
                               "p75": round(float(bars_p75), 1)},
            "avg_rsi_at_exit": round(float(avg_rsi_exit), 1) if avg_rsi_exit is not None else None,
            "saveable_count": saveable,
            "saveable_pct": round(saveable_pct, 1),
            "saveable_lost_pnl": round(sum(s["pnl"] for s in stop_details if s["went_profitable"]), 2),
        },
        "time_max": {
            "count": len(tm_trades),
            "pnl": round(tm_pnl, 2),
            "avg_loss": round(np.mean([t["pnl"] for t in tm_trades]), 2) if tm_trades else 0,
        },
        "rsi_recovery": {
            "count": len(rsi_trades),
            "pnl": round(rsi_pnl, 2),
            "wr": round(100 * sum(1 for t in rsi_trades if t["pnl"] > 0) / len(rsi_trades), 1) if rsi_trades else 0,
        },
        "dc_target": {
            "count": len(dc_trades),
            "pnl": round(dc_pnl, 2),
            "wr": round(100 * sum(1 for t in dc_trades if t["pnl"] > 0) / len(dc_trades), 1) if dc_trades else 0,
        },
        "bb_target": {
            "count": len(bb_trades),
            "pnl": round(bb_pnl, 2),
            "wr": round(100 * sum(1 for t in bb_trades if t["pnl"] > 0) / len(bb_trades), 1) if bb_trades else 0,
        },
        "end": {
            "count": len(end_trades),
            "pnl": round(end_pnl, 2),
        },
        "stop_details": stop_details,  # for later analysis
    }

    # Print summary
    print(f"\n  Total trades: {anatomy['total_trades']}, Total P&L: ${total_pnl:+,.2f}")
    print(f"\n  FIXED STOP:")
    print(f"    Count: {n_stops} ({n_stops / len(fixed_trade_list) * 100:.1f}% of trades)")
    print(f"    Total loss: ${stop_pnl:+,.2f}")
    print(f"    Avg loss: ${avg_stop_loss:+,.2f}")
    print(f"    Median bars to stop: {median_bars:.1f}")
    print(f"    Avg MFE (went up before crashing): {avg_mfe:.2f}%")
    print(f"    MFE quartiles: P25={mfe_p25:.2f}%, P50={mfe_p50:.2f}%, P75={mfe_p75:.2f}%")
    print(f"    Saveable (MFE > 0.5%): {saveable}/{n_stops} ({saveable_pct:.1f}%)")
    print(f"    Saveable lost P&L: ${anatomy['fixed_stop']['saveable_lost_pnl']:+,.2f}")
    if avg_rsi_exit is not None:
        print(f"    Avg RSI at exit: {avg_rsi_exit:.1f}")

    print(f"\n  TIME MAX:")
    print(f"    Count: {len(tm_trades)}, P&L: ${tm_pnl:+,.2f}")

    print(f"\n  RSI RECOVERY:")
    print(f"    Count: {len(rsi_trades)}, P&L: ${rsi_pnl:+,.2f}, "
          f"WR: {anatomy['rsi_recovery']['wr']:.1f}%")

    print(f"\n  DC TARGET:")
    print(f"    Count: {len(dc_trades)}, P&L: ${dc_pnl:+,.2f}, "
          f"WR: {anatomy['dc_target']['wr']:.1f}%")

    print(f"\n  BB TARGET:")
    print(f"    Count: {len(bb_trades)}, P&L: ${bb_pnl:+,.2f}, "
          f"WR: {anatomy['bb_target']['wr']:.1f}%")

    # Top coin concentration in stops
    coin_stops = defaultdict(lambda: {"count": 0, "pnl": 0})
    for s in stop_details:
        coin_stops[s["pair"]]["count"] += 1
        coin_stops[s["pair"]]["pnl"] += s["pnl"]
    top_stop_coins = sorted(coin_stops.items(), key=lambda x: x[1]["count"], reverse=True)[:10]
    print(f"\n  Top-10 coins by FIXED STOP count:")
    for pair, stats in top_stop_coins:
        print(f"    {pair}: {stats['count']}x, ${stats['pnl']:+,.0f}")

    return anatomy


# ===========================================================================
# Step 2: Exit Tweaks Sweep
# ===========================================================================

def run_exit_sweep(data, coins, signal_fn, base_params, indicators, market_context):
    """Run all exit parameter tweaks and collect results."""
    print("\n" + "=" * 70)
    print("  STEP 2: Exit Tweaks Sweep")
    print("=" * 70)

    results = {}

    # --- A. max_stop_pct sweep ---
    print("\n  === A. max_stop_pct sweep ===")
    for msp in [5, 7, 10, 12]:  # 15 = baseline
        label = f"A_maxstop_{msp}"
        overrides = dict(BASELINE_EXIT)
        overrides["max_stop_pct"] = msp
        print(f"  Running {label}...", end=" ", flush=True)
        t0 = time.time()
        r = run_with_exit_params(data, coins, signal_fn, base_params, indicators,
                                 overrides, market_context)
        m = r["metrics"]
        print(f"PF={m['pf']:.4f}, Tr={m['trades']}, P&L=${m['pnl']:+,.0f}, "
              f"DD={m['dd']:.1f}%, WR={m['wr']:.1f}% ({time.time()-t0:.1f}s)")
        results[label] = {
            "category": "A_max_stop_pct",
            "params": {"max_stop_pct": msp},
            "desc": f"max_stop_pct={msp}",
            **r,
        }

    # --- B. time_max_bars sweep ---
    print("\n  === B. time_max_bars sweep ===")
    for tmb in [10, 20, 25, 30]:  # 15 = baseline
        label = f"B_timemax_{tmb}"
        overrides = dict(BASELINE_EXIT)
        overrides["time_max_bars"] = tmb
        print(f"  Running {label}...", end=" ", flush=True)
        t0 = time.time()
        r = run_with_exit_params(data, coins, signal_fn, base_params, indicators,
                                 overrides, market_context)
        m = r["metrics"]
        print(f"PF={m['pf']:.4f}, Tr={m['trades']}, P&L=${m['pnl']:+,.0f}, "
              f"DD={m['dd']:.1f}%, WR={m['wr']:.1f}% ({time.time()-t0:.1f}s)")
        results[label] = {
            "category": "B_time_max_bars",
            "params": {"time_max_bars": tmb},
            "desc": f"time_max_bars={tmb}",
            **r,
        }

    # --- C. rsi_rec_target sweep ---
    print("\n  === C. rsi_rec_target sweep ===")
    for rrt in [35, 40, 42, 48, 50]:  # 45 = baseline
        label = f"C_rsitarget_{rrt}"
        overrides = dict(BASELINE_EXIT)
        overrides["rsi_rec_target"] = rrt
        print(f"  Running {label}...", end=" ", flush=True)
        t0 = time.time()
        r = run_with_exit_params(data, coins, signal_fn, base_params, indicators,
                                 overrides, market_context)
        m = r["metrics"]
        print(f"PF={m['pf']:.4f}, Tr={m['trades']}, P&L=${m['pnl']:+,.0f}, "
              f"DD={m['dd']:.1f}%, WR={m['wr']:.1f}% ({time.time()-t0:.1f}s)")
        results[label] = {
            "category": "C_rsi_rec_target",
            "params": {"rsi_rec_target": rrt},
            "desc": f"rsi_rec_target={rrt}",
            **r,
        }

    # --- D. rsi_rec_min_bars sweep ---
    print("\n  === D. rsi_rec_min_bars sweep ===")
    for rmb in [1, 3, 4, 5]:  # 2 = baseline
        label = f"D_rsimin_{rmb}"
        overrides = dict(BASELINE_EXIT)
        overrides["rsi_rec_min_bars"] = rmb
        print(f"  Running {label}...", end=" ", flush=True)
        t0 = time.time()
        r = run_with_exit_params(data, coins, signal_fn, base_params, indicators,
                                 overrides, market_context)
        m = r["metrics"]
        print(f"PF={m['pf']:.4f}, Tr={m['trades']}, P&L=${m['pnl']:+,.0f}, "
              f"DD={m['dd']:.1f}%, WR={m['wr']:.1f}% ({time.time()-t0:.1f}s)")
        results[label] = {
            "category": "D_rsi_rec_min_bars",
            "params": {"rsi_rec_min_bars": rmb},
            "desc": f"rsi_rec_min_bars={rmb}",
            **r,
        }

    return results


def find_best_per_category(results):
    """Find the best individual tweak per category by PF."""
    best = {}
    categories = set(r["category"] for r in results.values())
    for cat in categories:
        cat_results = {k: v for k, v in results.items() if v["category"] == cat}
        if not cat_results:
            continue
        best_key = max(cat_results, key=lambda k: cat_results[k]["metrics"]["pf"])
        best[cat] = {
            "label": best_key,
            **cat_results[best_key],
        }
    return best


def run_combined_tweaks(data, coins, signal_fn, base_params, indicators,
                        market_context, best_per_cat, individual_results):
    """Run combined exit parameter tweaks."""
    print("\n" + "=" * 70)
    print("  STEP 3: Combined Exit Tweaks")
    print("=" * 70)

    combined_results = {}

    # Find best individual values per dimension
    best_msp = 15.0  # baseline
    best_tmb = 15    # baseline
    best_rrt = 45.0  # baseline
    best_rmb = 2     # baseline

    for cat, entry in best_per_cat.items():
        p = entry["params"]
        if "max_stop_pct" in p and entry["metrics"]["pf"] > 1.15:
            best_msp = p["max_stop_pct"]
        if "time_max_bars" in p and entry["metrics"]["pf"] > 1.15:
            best_tmb = p["time_max_bars"]
        if "rsi_rec_target" in p and entry["metrics"]["pf"] > 1.15:
            best_rrt = p["rsi_rec_target"]
        if "rsi_rec_min_bars" in p and entry["metrics"]["pf"] > 1.15:
            best_rmb = p["rsi_rec_min_bars"]

    # Also check if any individual beat baseline — use those values
    for k, v in individual_results.items():
        p = v["params"]
        m = v["metrics"]
        if m["pf"] > 1.36:  # baseline PF
            if "max_stop_pct" in p:
                best_msp = p["max_stop_pct"]
            if "time_max_bars" in p:
                best_tmb = p["time_max_bars"]
            if "rsi_rec_target" in p:
                best_rrt = p["rsi_rec_target"]
            if "rsi_rec_min_bars" in p:
                best_rmb = p["rsi_rec_min_bars"]

    print(f"  Best individual values: msp={best_msp}, tmb={best_tmb}, "
          f"rrt={best_rrt}, rmb={best_rmb}")

    # E1: Combined best
    label = "E1_combined_best"
    overrides = dict(BASELINE_EXIT)
    overrides["max_stop_pct"] = best_msp
    overrides["time_max_bars"] = best_tmb
    overrides["rsi_rec_target"] = best_rrt
    overrides["rsi_rec_min_bars"] = best_rmb
    print(f"\n  Running {label} (msp={best_msp}, tmb={best_tmb}, rrt={best_rrt}, rmb={best_rmb})...",
          end=" ", flush=True)
    t0 = time.time()
    r = run_with_exit_params(data, coins, signal_fn, base_params, indicators,
                             overrides, market_context)
    m = r["metrics"]
    print(f"PF={m['pf']:.4f}, Tr={m['trades']}, P&L=${m['pnl']:+,.0f}, "
          f"DD={m['dd']:.1f}%, WR={m['wr']:.1f}% ({time.time()-t0:.1f}s)")
    combined_results[label] = {
        "category": "E_combined",
        "params": {"max_stop_pct": best_msp, "time_max_bars": best_tmb,
                   "rsi_rec_target": best_rrt, "rsi_rec_min_bars": best_rmb},
        "desc": f"Combined best: msp={best_msp}, tmb={best_tmb}, rrt={best_rrt}, rmb={best_rmb}",
        **r,
    }

    # E2: Tighter stop + wider TM
    label = "E2_tight_stop_wide_tm"
    overrides = dict(BASELINE_EXIT)
    overrides["max_stop_pct"] = 10
    overrides["time_max_bars"] = 25
    print(f"  Running {label} (msp=10, tmb=25)...", end=" ", flush=True)
    t0 = time.time()
    r = run_with_exit_params(data, coins, signal_fn, base_params, indicators,
                             overrides, market_context)
    m = r["metrics"]
    print(f"PF={m['pf']:.4f}, Tr={m['trades']}, P&L=${m['pnl']:+,.0f}, "
          f"DD={m['dd']:.1f}%, WR={m['wr']:.1f}% ({time.time()-t0:.1f}s)")
    combined_results[label] = {
        "category": "E_combined",
        "params": {"max_stop_pct": 10, "time_max_bars": 25},
        "desc": "Tighter stop (10%) + wider TM (25 bars)",
        **r,
    }

    # E3: Tighter stop + lower RSI target
    label = "E3_tight_stop_low_rsi"
    overrides = dict(BASELINE_EXIT)
    overrides["max_stop_pct"] = 10
    overrides["rsi_rec_target"] = 40
    print(f"  Running {label} (msp=10, rrt=40)...", end=" ", flush=True)
    t0 = time.time()
    r = run_with_exit_params(data, coins, signal_fn, base_params, indicators,
                             overrides, market_context)
    m = r["metrics"]
    print(f"PF={m['pf']:.4f}, Tr={m['trades']}, P&L=${m['pnl']:+,.0f}, "
          f"DD={m['dd']:.1f}%, WR={m['wr']:.1f}% ({time.time()-t0:.1f}s)")
    combined_results[label] = {
        "category": "E_combined",
        "params": {"max_stop_pct": 10, "rsi_rec_target": 40},
        "desc": "Tighter stop (10%) + lower RSI target (40)",
        **r,
    }

    # E4: All three changed
    label = "E4_all_three"
    overrides = dict(BASELINE_EXIT)
    overrides["max_stop_pct"] = 10
    overrides["time_max_bars"] = 25
    overrides["rsi_rec_target"] = 40
    print(f"  Running {label} (msp=10, tmb=25, rrt=40)...", end=" ", flush=True)
    t0 = time.time()
    r = run_with_exit_params(data, coins, signal_fn, base_params, indicators,
                             overrides, market_context)
    m = r["metrics"]
    print(f"PF={m['pf']:.4f}, Tr={m['trades']}, P&L=${m['pnl']:+,.0f}, "
          f"DD={m['dd']:.1f}%, WR={m['wr']:.1f}% ({time.time()-t0:.1f}s)")
    combined_results[label] = {
        "category": "E_combined",
        "params": {"max_stop_pct": 10, "time_max_bars": 25, "rsi_rec_target": 40},
        "desc": "All three: msp=10, tmb=25, rrt=40",
        **r,
    }

    # E5: Tight stop 7 + wider TM 20
    label = "E5_stop7_tm20"
    overrides = dict(BASELINE_EXIT)
    overrides["max_stop_pct"] = 7
    overrides["time_max_bars"] = 20
    print(f"  Running {label} (msp=7, tmb=20)...", end=" ", flush=True)
    t0 = time.time()
    r = run_with_exit_params(data, coins, signal_fn, base_params, indicators,
                             overrides, market_context)
    m = r["metrics"]
    print(f"PF={m['pf']:.4f}, Tr={m['trades']}, P&L=${m['pnl']:+,.0f}, "
          f"DD={m['dd']:.1f}%, WR={m['wr']:.1f}% ({time.time()-t0:.1f}s)")
    combined_results[label] = {
        "category": "E_combined",
        "params": {"max_stop_pct": 7, "time_max_bars": 20},
        "desc": "Tight stop (7%) + wider TM (20 bars)",
        **r,
    }

    # E6: Tight stop 7 + wider TM 25 + lower RSI 40
    label = "E6_stop7_tm25_rsi40"
    overrides = dict(BASELINE_EXIT)
    overrides["max_stop_pct"] = 7
    overrides["time_max_bars"] = 25
    overrides["rsi_rec_target"] = 40
    print(f"  Running {label} (msp=7, tmb=25, rrt=40)...", end=" ", flush=True)
    t0 = time.time()
    r = run_with_exit_params(data, coins, signal_fn, base_params, indicators,
                             overrides, market_context)
    m = r["metrics"]
    print(f"PF={m['pf']:.4f}, Tr={m['trades']}, P&L=${m['pnl']:+,.0f}, "
          f"DD={m['dd']:.1f}%, WR={m['wr']:.1f}% ({time.time()-t0:.1f}s)")
    combined_results[label] = {
        "category": "E_combined",
        "params": {"max_stop_pct": 7, "time_max_bars": 25, "rsi_rec_target": 40},
        "desc": "Tight stop (7%) + wider TM (25) + RSI target (40)",
        **r,
    }

    return combined_results


# ===========================================================================
# Step 4: Reporting
# ===========================================================================

def build_leaderboard(baseline_result, individual_results, combined_results):
    """Build a top-3 leaderboard + full comparison sorted by PF."""
    all_configs = {}

    # Add baseline
    all_configs["BASELINE"] = {
        "category": "baseline",
        "params": BASELINE_EXIT,
        "desc": "Baseline (msp=15, tmb=15, rrt=45, rmb=2)",
        **baseline_result,
    }

    # Merge individual + combined
    all_configs.update(individual_results)
    all_configs.update(combined_results)

    # Sort by PF descending
    sorted_configs = sorted(all_configs.items(), key=lambda x: x[1]["metrics"]["pf"],
                           reverse=True)

    # Top-3 with PF >= 1.15
    top3 = [(k, v) for k, v in sorted_configs if v["metrics"]["pf"] >= 1.15][:3]

    return sorted_configs, top3


def write_reports(anatomy, baseline_result, individual_results, combined_results,
                  sorted_configs, top3, n_coins, bars_counts):
    """Write JSON + MD reports."""
    print("\n" + "=" * 70)
    print("  STEP 4: Reports")
    print("=" * 70)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    git = _git_hash()
    max_bar = max(bars_counts)
    n_days = (max_bar - START_BAR) * 4 / 24

    # Prepare anatomy for JSON (strip stop_details)
    anatomy_json = {k: v for k, v in anatomy.items() if k != "stop_details"}

    # Prepare configs for JSON (strip trade_list and raw_trade_list)
    def _clean_result(r):
        return {k: v for k, v in r.items()
                if k not in ("trade_list", "raw_trade_list")}

    json_report = {
        "experiment": "mexc_exit_tweaks",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_hash": git,
        "dataset_id": "ohlcv_4h_mexc_spot_usdt_v2",
        "universe": {
            "filter": f"top {TOP_N} by median volume, >= {MIN_BARS_TOP200} bars",
            "n_coins": n_coins,
            "bars_min": min(bars_counts),
            "bars_max": max(bars_counts),
            "bars_median": int(median(bars_counts)),
            "full_range_days": round(n_days, 1),
        },
        "fee": MEXC_FEE,
        "sizing": "fixed_notional_2000",
        "baseline_entry": {"vol_mult": 3.5, "rsi_max": 35, "hypothesis": CONFIG_041_HYP_ID},
        "baseline_exit": BASELINE_EXIT,
        "stopout_anatomy": anatomy_json,
        "leaderboard": [],
        "individual_sweeps": {},
        "combined_tweaks": {},
        "top3": [],
    }

    # Add leaderboard
    for rank, (label, entry) in enumerate(sorted_configs, 1):
        m = entry["metrics"]
        json_report["leaderboard"].append({
            "rank": rank,
            "label": label,
            "desc": entry["desc"],
            "params": entry.get("params", {}),
            "pf": m["pf"], "pnl": m["pnl"], "trades": m["trades"],
            "dd": m["dd"], "wr": m["wr"],
        })

    # Add individual results
    for label, entry in individual_results.items():
        json_report["individual_sweeps"][label] = _clean_result(entry)

    for label, entry in combined_results.items():
        json_report["combined_tweaks"][label] = _clean_result(entry)

    # Add top-3
    for rank, (label, entry) in enumerate(top3, 1):
        m = entry["metrics"]
        json_report["top3"].append({
            "rank": rank,
            "label": label,
            "desc": entry["desc"],
            "params": entry.get("params", {}),
            "pf": m["pf"], "pnl": m["pnl"], "trades": m["trades"],
            "dd": m["dd"], "wr": m["wr"],
            "exit_attribution": entry.get("exit_attribution", {}),
        })

    json_path = REPORT_DIR / "mexc_exit_tweaks_007.json"
    with open(json_path, "w") as f:
        json.dump(json_report, f, indent=2)
    print(f"  JSON: {json_path}")

    # --- MD Report ---
    md = _build_md(json_report, anatomy, sorted_configs, top3,
                   baseline_result, individual_results, combined_results,
                   n_coins, bars_counts, git, n_days)
    md_path = REPORT_DIR / "mexc_exit_tweaks_007.md"
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  MD: {md_path}")

    return json_path


def _build_md(report, anatomy, sorted_configs, top3, baseline_result,
              individual_results, combined_results, n_coins, bars_counts,
              git, n_days):
    max_bar = max(bars_counts)
    bm = baseline_result["metrics"]

    lines = [
        "# MEXC Exit Tweaks Sweep -- Config 041 (Vol Cap 3.5x RSI35)",
        "",
        f"**Date**: {report['timestamp'][:10]}",
        f"**Git**: `{git}`",
        f"**Universe**: Top {TOP_N} by volume, >= {MIN_BARS_TOP200} bars ({n_coins} coins)",
        f"**Full range**: ~{n_days:.0f} days, {max_bar} bars",
        f"**Fee**: MEXC 10bps",
        f"**Sizing**: Fixed $2,000/trade (no compounding)",
        f"**Baseline**: PF={bm['pf']:.2f}, P&L=${bm['pnl']:+,.0f}, "
        f"{bm['trades']} trades, DD={bm['dd']:.1f}%, WR={bm['wr']:.1f}%",
        "",
        "---",
        "",
        "## Stopout Anatomy",
        "",
    ]

    # Anatomy section
    fs = anatomy["fixed_stop"]
    tm = anatomy["time_max"]
    rsi = anatomy["rsi_recovery"]
    dc = anatomy["dc_target"]
    bb = anatomy["bb_target"]

    lines.append("### P&L Attribution by Exit Reason")
    lines.append("")
    lines.append("| Exit Reason | Class | Count | P&L | WR | Avg P&L |")
    lines.append("|-------------|-------|------:|----:|---:|--------:|")

    # Build rows sorted by P&L
    reasons = [
        ("RSI RECOVERY", "A", rsi["count"], rsi["pnl"], rsi["wr"]),
        ("DC TARGET", "A", dc["count"], dc["pnl"], dc["wr"]),
        ("BB TARGET", "A", bb["count"], bb["pnl"], bb["wr"]),
        ("FIXED STOP", "B", fs["count"], fs["pnl"], 0),
        ("TIME MAX", "B", tm["count"], tm["pnl"], 0),
        ("END", "B", anatomy["end"]["count"], anatomy["end"]["pnl"], 0),
    ]
    reasons.sort(key=lambda x: x[3], reverse=True)
    for name, cls, cnt, pnl, wr in reasons:
        avg = pnl / cnt if cnt > 0 else 0
        wr_s = f"{wr:.0f}%" if wr > 0 else "--"
        lines.append(f"| {name} | {cls} | {cnt} | ${pnl:+,.0f} | {wr_s} | ${avg:+,.0f} |")
    lines.append("")

    lines.append("### FIXED STOP Deep Dive")
    lines.append("")
    lines.append(f"- **Count**: {fs['count']} ({fs['count'] / anatomy['total_trades'] * 100:.1f}% of trades)")
    lines.append(f"- **Total loss**: ${fs['pnl']:+,.0f}")
    lines.append(f"- **Avg loss**: ${fs['avg_loss']:+,.0f}")
    lines.append(f"- **Median bars to stop**: {fs['median_bars']:.1f}")
    lines.append(f"- **Avg MFE (went up before crashing)**: {fs['avg_mfe_pct']:.2f}%")
    lines.append(f"- **MFE quartiles**: P25={fs['mfe_quartiles']['p25']:.2f}%, "
                 f"P50={fs['mfe_quartiles']['p50']:.2f}%, "
                 f"P75={fs['mfe_quartiles']['p75']:.2f}%")
    lines.append(f"- **Bars to stop quartiles**: P25={fs['bars_quartiles']['p25']:.0f}, "
                 f"P50={fs['bars_quartiles']['p50']:.0f}, "
                 f"P75={fs['bars_quartiles']['p75']:.0f}")
    if fs['avg_rsi_at_exit'] is not None:
        lines.append(f"- **Avg RSI at exit**: {fs['avg_rsi_at_exit']:.1f}")
    lines.append(f"- **Saveable (MFE > 0.5%)**: {fs['saveable_count']}/{fs['count']} ({fs['saveable_pct']:.1f}%)")
    lines.append(f"- **Saveable lost P&L**: ${fs['saveable_lost_pnl']:+,.0f}")
    lines.append("")

    # Full leaderboard
    lines.append("---")
    lines.append("")
    lines.append("## Full Leaderboard (sorted by PF)")
    lines.append("")
    lines.append("| # | Label | Description | PF | P&L | Trades | DD | WR |")
    lines.append("|--:|-------|-------------|---:|----:|-------:|---:|---:|")
    for rank, (label, entry) in enumerate(sorted_configs, 1):
        m = entry["metrics"]
        is_baseline = label == "BASELINE"
        marker = " **[B]**" if is_baseline else ""
        lines.append(f"| {rank} | {label}{marker} | {entry['desc'][:50]} "
                     f"| {m['pf']:.2f} | ${m['pnl']:+,.0f} | {m['trades']} "
                     f"| {m['dd']:.1f}% | {m['wr']:.1f}% |")
    lines.append("")

    # Individual sweep results by category
    for cat_name, cat_label in [("A. max_stop_pct", "A_max_stop_pct"),
                                 ("B. time_max_bars", "B_time_max_bars"),
                                 ("C. rsi_rec_target", "C_rsi_rec_target"),
                                 ("D. rsi_rec_min_bars", "D_rsi_rec_min_bars")]:
        cat_results = {k: v for k, v in individual_results.items()
                       if v["category"] == cat_label}
        if not cat_results:
            continue
        lines.append(f"### {cat_name} Sweep")
        lines.append("")
        lines.append("| Value | PF | P&L | Trades | DD | WR |")
        lines.append("|------:|---:|----:|-------:|---:|---:|")
        # Add baseline row
        lines.append(f"| **baseline** | {bm['pf']:.2f} | ${bm['pnl']:+,.0f} | "
                     f"{bm['trades']} | {bm['dd']:.1f}% | {bm['wr']:.1f}% |")
        for label, entry in sorted(cat_results.items(),
                                   key=lambda x: list(x[1]["params"].values())[0]):
            m = entry["metrics"]
            val = list(entry["params"].values())[0]
            lines.append(f"| {val} | {m['pf']:.2f} | ${m['pnl']:+,.0f} | "
                         f"{m['trades']} | {m['dd']:.1f}% | {m['wr']:.1f}% |")
        lines.append("")

    # Combined
    lines.append("### Combined Tweaks")
    lines.append("")
    lines.append("| Label | Description | PF | P&L | Trades | DD | WR |")
    lines.append("|-------|-------------|---:|----:|-------:|---:|---:|")
    lines.append(f"| BASELINE | baseline | {bm['pf']:.2f} | ${bm['pnl']:+,.0f} | "
                 f"{bm['trades']} | {bm['dd']:.1f}% | {bm['wr']:.1f}% |")
    for label, entry in combined_results.items():
        m = entry["metrics"]
        lines.append(f"| {label} | {entry['desc'][:50]} | {m['pf']:.2f} | "
                     f"${m['pnl']:+,.0f} | {m['trades']} | {m['dd']:.1f}% | {m['wr']:.1f}% |")
    lines.append("")

    # Top-3
    lines.append("---")
    lines.append("")
    lines.append("## Top-3 Exit Tweaks (PF >= 1.15)")
    lines.append("")
    if top3:
        lines.append("| # | Label | Description | PF | P&L | Trades | DD | WR |")
        lines.append("|--:|-------|-------------|---:|----:|-------:|---:|---:|")
        for rank, (label, entry) in enumerate(top3, 1):
            m = entry["metrics"]
            lines.append(f"| {rank} | {label} | {entry['desc'][:50]} | {m['pf']:.2f} | "
                         f"${m['pnl']:+,.0f} | {m['trades']} | {m['dd']:.1f}% | {m['wr']:.1f}% |")
        lines.append("")

        # Exit attribution comparison: baseline vs top-1
        lines.append("### Exit Attribution: Baseline vs Top-1")
        lines.append("")
        t1_label, t1_entry = top3[0]
        t1_ea = t1_entry.get("exit_attribution", {})
        base_ea = baseline_result.get("exit_attribution", {})
        lines.append("| Exit Reason | Baseline Count | Baseline P&L | Top-1 Count | Top-1 P&L |")
        lines.append("|-------------|---------------:|---------:|------------:|------:|")
        all_reasons = set(list(base_ea.keys()) + list(t1_ea.keys()))
        for reason in sorted(all_reasons):
            b = base_ea.get(reason, {"count": 0, "pnl": 0})
            t = t1_ea.get(reason, {"count": 0, "pnl": 0})
            lines.append(f"| {reason} | {b['count']} | ${b['pnl']:+,.0f} "
                         f"| {t['count']} | ${t['pnl']:+,.0f} |")
        lines.append("")
    else:
        lines.append("No configs passed the PF >= 1.15 gate.")
        lines.append("")

    # Deploy recommendation
    lines.append("## Deploy Recommendation")
    lines.append("")
    if top3:
        t1_label, t1_entry = top3[0]
        t1m = t1_entry["metrics"]
        beats_pf = t1m["pf"] > bm["pf"]
        beats_dd = t1m["dd"] < bm["dd"]
        if beats_pf and beats_dd:
            lines.append(f"**DEPLOY CANDIDATE**: `{t1_label}` beats baseline on BOTH PF ({t1m['pf']:.2f} vs {bm['pf']:.2f}) "
                         f"AND DD ({t1m['dd']:.1f}% vs {bm['dd']:.1f}%).")
        elif beats_pf:
            lines.append(f"**INVESTIGATE**: `{t1_label}` beats baseline on PF ({t1m['pf']:.2f} vs {bm['pf']:.2f}) "
                         f"but DD is worse ({t1m['dd']:.1f}% vs {bm['dd']:.1f}%).")
        else:
            lines.append(f"**NO IMPROVEMENT**: No config beats baseline PF ({bm['pf']:.2f}).")
    else:
        lines.append("**NO IMPROVEMENT**: No config passed PF >= 1.15 gate.")
    lines.append("")

    return "\n".join(lines)


# ===========================================================================
# Main
# ===========================================================================

def main():
    t_total = time.time()
    print("\n" + "=" * 70)
    print("  MEXC EXIT TWEAKS SWEEP — Config 041 (Vol Cap 3.5x RSI35)")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # --- Load data ---
    data, coins, bars_counts = load_top200()
    n_coins = len(coins)
    max_bar = max(bars_counts)
    n_days = (max_bar - START_BAR) * 4 / 24
    print(f"  Max bars: {max_bar}, Days: ~{n_days:.0f}")

    # --- Precompute ---
    import importlib
    _s2_ind = importlib.import_module("strategies.4h.sprint2.indicators")
    _s2_ctx = importlib.import_module("strategies.4h.sprint2.market_context")
    _hyp = importlib.import_module("strategies.4h.sprint4.hypotheses")

    print("  Precomputing indicators...")
    t0 = time.time()
    indicators = _s2_ind.precompute_all(data, coins)
    market_context = _s2_ctx.precompute_sprint2_context(data, coins)
    print(f"  Done in {time.time()-t0:.1f}s")

    # --- Resolve config 041 ---
    all_cfgs = _hyp.build_sweep_configs()
    cfg041 = next(c for c in all_cfgs if c["hypothesis_id"] == CONFIG_041_HYP_ID)
    signal_fn = cfg041["signal_fn"]
    base_params = dict(cfg041["params"])
    # Apply entry overrides for this baseline
    base_params["vol_mult"] = 3.5
    base_params["rsi_max"] = 35

    # --- Run baseline ---
    print("\n  Running BASELINE...")
    t0 = time.time()
    baseline_result = run_with_exit_params(
        data, coins, signal_fn, base_params, indicators,
        BASELINE_EXIT, market_context)
    bm = baseline_result["metrics"]
    print(f"  BASELINE: PF={bm['pf']:.4f}, Tr={bm['trades']}, "
          f"P&L=${bm['pnl']:+,.0f}, DD={bm['dd']:.1f}%, "
          f"WR={bm['wr']:.1f}% ({time.time()-t0:.1f}s)")

    # --- Step 1: Stopout Anatomy ---
    anatomy = analyze_stopout_anatomy(
        data, indicators,
        baseline_result["raw_trade_list"],
        baseline_result["trade_list"])

    # --- Step 2: Exit Sweeps ---
    individual_results = run_exit_sweep(
        data, coins, signal_fn, base_params, indicators, market_context)

    # --- Step 3: Combined Tweaks ---
    best_per_cat = find_best_per_category(individual_results)
    combined_results = run_combined_tweaks(
        data, coins, signal_fn, base_params, indicators,
        market_context, best_per_cat, individual_results)

    # --- Step 4: Leaderboard + Reports ---
    sorted_configs, top3 = build_leaderboard(
        baseline_result, individual_results, combined_results)

    json_path = write_reports(
        anatomy, baseline_result, individual_results, combined_results,
        sorted_configs, top3, n_coins, bars_counts)

    # --- Summary ---
    elapsed = time.time() - t_total
    print("\n" + "=" * 70)
    print("  COMPLETE")
    print("=" * 70)
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Universe: top-{TOP_N} ({n_coins} coins)")
    print(f"  Individual configs: {len(individual_results)}")
    print(f"  Combined configs: {len(combined_results)}")
    print(f"  Total configs: {len(sorted_configs)}")
    print(f"  Baseline: PF={bm['pf']:.4f}, Tr={bm['trades']}, P&L=${bm['pnl']:+,.0f}")
    print(f"\n  Top-3 (PF >= 1.15):")
    if top3:
        for rank, (label, entry) in enumerate(top3, 1):
            m = entry["metrics"]
            print(f"    #{rank} {label}: PF={m['pf']:.4f}, P&L=${m['pnl']:+,.0f}, "
                  f"DD={m['dd']:.1f}%, WR={m['wr']:.1f}%")
    else:
        print("    No configs passed PF >= 1.15 gate")
    print(f"\n  Reports: {json_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
HF Tail Risk Analysis — 4H variant research.

Computes drawdown-per-window, worst-coin contribution, friction ladder,
latency sensitivity, consecutive-loss analysis, and trade sufficiency
for Champion H2 and GRID_BEST configs.

Usage:
    python strategies/hf/hf_tail_risk.py
    python strategies/hf/hf_tail_risk.py --universe tradeable
    python strategies/hf/hf_tail_risk.py --universe live

Outputs:
    reports/hf/risk_001.json   — structured risk metrics (both configs)
    reports/hf/risk_001.md     — human-readable tail risk report
"""

import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# --- Path setup (read-only import from trading_bot/) ---
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

# --- Constants ---
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports" / "hf"

DATA_FILES = {
    "tradeable": DATA_DIR / "candle_cache_tradeable.json",
    "live": DATA_DIR / "candle_cache_532.json",
}

WINDOW_SIZE = 180  # ~30 days at 4H bars
DD_FLAG_THRESHOLD = 30.0  # flag windows with DD > 30%
TRADE_SUFFICIENCY_MIN = 20

# --- Configs under test ---
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

# --- Friction ladder levels ---
FRICTION_LADDER = [
    ("baseline",       KRAKEN_FEE),
    ("1.5x_fees",      round(KRAKEN_FEE * 1.5, 4)),
    ("2x_fees",        round(KRAKEN_FEE * 2.0, 4)),
    ("2x+10bps",       round(KRAKEN_FEE * 2.0 + 0.0010, 4)),
    ("2x+20bps",       round(KRAKEN_FEE * 2.0 + 0.0020, 4)),
    ("2x+35bps",       round(KRAKEN_FEE * 2.0 + 0.0035, 4)),
    ("1_candle_later",  round(KRAKEN_FEE * 2.0 + 0.0050, 4)),
]


# ============================================================
# DATA LOADING
# ============================================================
def load_data(universe: str):
    """Load candle data and return (data_dict, sorted_coins, path_str)."""
    path = DATA_FILES.get(universe)
    if path is None or not path.exists():
        path = TRADING_BOT / "candle_cache_532.json"
    if not path.exists():
        print(f"ERROR: No data file found for universe={universe}")
        sys.exit(1)
    with open(path) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith("_")])
    return data, coins, str(path)


# ============================================================
# 1. DRAWDOWN PER WINDOW
# ============================================================
def compute_drawdown_per_window(trade_list, total_bars):
    """Split bars into ~180-bar windows and compute per-window metrics."""
    windows = []
    n_windows = max(1, total_bars // WINDOW_SIZE)

    for w in range(n_windows):
        w_start = START_BAR + w * WINDOW_SIZE
        w_end = w_start + WINDOW_SIZE
        if w == n_windows - 1:
            w_end = START_BAR + total_bars  # last window gets remainder

        # Trades in this window (by entry_bar)
        w_trades = [
            t for t in trade_list
            if w_start <= t["entry_bar"] < w_end
        ]

        w_pnl = sum(t["pnl"] for t in w_trades)
        w_count = len(w_trades)

        # Compute max drawdown within window using equity_after sequence
        w_max_dd_pct = 0.0
        if w_trades:
            # Reconstruct equity curve for this window
            # Start from equity before first trade in window
            eq_start = w_trades[0]["equity_after"] - w_trades[0]["pnl"]
            peak = eq_start
            for t in w_trades:
                eq = t["equity_after"]
                if eq > peak:
                    peak = eq
                dd = (peak - eq) / peak * 100 if peak > 0 else 0
                if dd > w_max_dd_pct:
                    w_max_dd_pct = dd

        flagged = w_max_dd_pct > DD_FLAG_THRESHOLD

        windows.append({
            "window": w + 1,
            "bar_start": w_start,
            "bar_end": w_end,
            "trades": w_count,
            "pnl": round(w_pnl, 2),
            "max_dd_pct": round(w_max_dd_pct, 1),
            "flagged_dd_gt_30": flagged,
        })

    return windows


# ============================================================
# 2. WORST-COIN CONTRIBUTION
# ============================================================
def compute_worst_coin_contribution(trade_list, total_pnl):
    """Per-coin P&L contribution. What if worst 1/3 coins removed?"""
    coin_pnl = defaultdict(float)
    coin_count = defaultdict(int)

    for t in trade_list:
        coin_pnl[t["pair"]] += t["pnl"]
        coin_count[t["pair"]] += 1

    # Sort by P&L ascending (worst first)
    sorted_coins = sorted(coin_pnl.items(), key=lambda x: x[1])

    coin_details = []
    for pair, pnl in sorted_coins:
        coin_details.append({
            "pair": pair,
            "pnl": round(pnl, 2),
            "trades": coin_count[pair],
            "pnl_pct_of_total": round(pnl / total_pnl * 100, 1) if total_pnl != 0 else 0.0,
        })

    # Impact of removing worst 1 coin
    if sorted_coins:
        worst_1_pair, worst_1_pnl = sorted_coins[0]
        pnl_without_worst_1 = total_pnl - worst_1_pnl
    else:
        worst_1_pair = None
        worst_1_pnl = 0
        pnl_without_worst_1 = total_pnl

    # Impact of removing worst 3 coins
    worst_3_pairs = [p for p, _ in sorted_coins[:3]]
    worst_3_pnl = sum(pnl for _, pnl in sorted_coins[:3])
    pnl_without_worst_3 = total_pnl - worst_3_pnl

    return {
        "coins_traded": len(coin_pnl),
        "coin_details": coin_details,
        "worst_1": {
            "pair": worst_1_pair,
            "pnl": round(worst_1_pnl, 2),
            "pnl_without": round(pnl_without_worst_1, 2),
            "delta": round(pnl_without_worst_1 - total_pnl, 2),
        },
        "worst_3": {
            "pairs": worst_3_pairs,
            "combined_pnl": round(worst_3_pnl, 2),
            "pnl_without": round(pnl_without_worst_3, 2),
            "delta": round(pnl_without_worst_3 - total_pnl, 2),
        },
    }


# ============================================================
# 3. FRICTION LADDER
# ============================================================
def compute_friction_ladder(cfg, indicators, coins):
    """Run backtest at each friction level. Find breakeven friction."""
    ladder = []
    breakeven_fee = None
    prev_pnl = None

    for label, fee in FRICTION_LADDER:
        result = run_backtest(indicators, coins, cfg, fee_override=fee)
        pnl = result["pnl"]
        trades = result["trades"]
        dd = result["dd"]

        # Detect breakeven crossing
        if prev_pnl is not None and prev_pnl > 0 and pnl <= 0 and breakeven_fee is None:
            # Linear interpolation for breakeven fee
            prev_fee = FRICTION_LADDER[len(ladder) - 1][1]
            if prev_pnl != pnl:
                breakeven_fee = round(
                    prev_fee + (fee - prev_fee) * prev_pnl / (prev_pnl - pnl), 6
                )
            else:
                breakeven_fee = round(fee, 6)

        ladder.append({
            "label": label,
            "fee": fee,
            "fee_bps": round(fee * 10000, 1),
            "pnl": round(pnl, 2),
            "trades": trades,
            "dd": round(dd, 1),
            "profitable": pnl > 0,
        })
        prev_pnl = pnl

    # If never crossed zero, check if always profitable or always negative
    if breakeven_fee is None:
        if all(r["pnl"] > 0 for r in ladder):
            breakeven_note = "Still profitable at max tested friction"
        elif all(r["pnl"] <= 0 for r in ladder):
            breakeven_note = "Already negative at baseline fees"
            breakeven_fee = FRICTION_LADDER[0][1]
        else:
            breakeven_note = "Could not interpolate breakeven"
    else:
        breakeven_note = None

    return {
        "ladder": ladder,
        "breakeven_fee": breakeven_fee,
        "breakeven_fee_bps": round(breakeven_fee * 10000, 1) if breakeven_fee else None,
        "breakeven_note": breakeven_note,
    }


# ============================================================
# 4. LATENCY SENSITIVITY (1-candle-later)
# ============================================================
def compute_latency_sensitivity(friction_result, baseline_pnl):
    """Extract latency impact from friction ladder (1-candle-later entry)."""
    one_candle = None
    for r in friction_result["ladder"]:
        if r["label"] == "1_candle_later":
            one_candle = r
            break

    if one_candle is None:
        return {"error": "1_candle_later not found in friction ladder"}

    pnl_delta = one_candle["pnl"] - baseline_pnl
    pnl_delta_pct = (pnl_delta / abs(baseline_pnl) * 100) if baseline_pnl != 0 else 0.0

    return {
        "baseline_pnl": round(baseline_pnl, 2),
        "one_candle_later_pnl": round(one_candle["pnl"], 2),
        "pnl_delta": round(pnl_delta, 2),
        "pnl_delta_pct": round(pnl_delta_pct, 1),
        "still_profitable": one_candle["pnl"] > 0,
        "fee_used_bps": one_candle["fee_bps"],
    }


# ============================================================
# 5. CONSECUTIVE LOSS ANALYSIS
# ============================================================
def compute_consecutive_loss_analysis(trade_list):
    """Find max consecutive losing streak and its equity impact."""
    if not trade_list:
        return {
            "max_consecutive_losses": 0,
            "worst_streak_pnl": 0,
            "worst_streak_pnl_pct": 0,
            "worst_streak_start_idx": None,
            "worst_streak_end_idx": None,
            "all_streaks": [],
        }

    # Build list of losing streaks
    streaks = []
    current_streak = 0
    current_streak_pnl = 0.0
    current_streak_start = 0

    for i, t in enumerate(trade_list):
        if t["pnl"] <= 0:
            if current_streak == 0:
                current_streak_start = i
            current_streak += 1
            current_streak_pnl += t["pnl"]
        else:
            if current_streak > 0:
                streaks.append({
                    "length": current_streak,
                    "pnl": round(current_streak_pnl, 2),
                    "start_idx": current_streak_start,
                    "end_idx": i - 1,
                })
            current_streak = 0
            current_streak_pnl = 0.0

    # Don't forget the last streak
    if current_streak > 0:
        streaks.append({
            "length": current_streak,
            "pnl": round(current_streak_pnl, 2),
            "start_idx": current_streak_start,
            "end_idx": len(trade_list) - 1,
        })

    if not streaks:
        return {
            "max_consecutive_losses": 0,
            "worst_streak_pnl": 0,
            "worst_streak_pnl_pct": 0,
            "worst_streak_start_idx": None,
            "worst_streak_end_idx": None,
            "all_streaks": [],
        }

    # Find worst by length
    worst_by_length = max(streaks, key=lambda s: s["length"])
    # Find worst by P&L impact
    worst_by_pnl = min(streaks, key=lambda s: s["pnl"])

    # Equity impact of worst streak (by P&L)
    # Find equity at start of worst streak
    if worst_by_pnl["start_idx"] > 0:
        eq_before = trade_list[worst_by_pnl["start_idx"] - 1]["equity_after"]
    else:
        eq_before = INITIAL_CAPITAL

    eq_after = trade_list[worst_by_pnl["end_idx"]]["equity_after"]
    equity_impact_pct = (eq_before - eq_after) / eq_before * 100 if eq_before > 0 else 0

    return {
        "max_consecutive_losses": worst_by_length["length"],
        "worst_streak_by_length": worst_by_length,
        "worst_streak_by_pnl": worst_by_pnl,
        "equity_impact_pct": round(equity_impact_pct, 1),
        "equity_before_worst": round(eq_before, 2),
        "equity_after_worst": round(eq_after, 2),
        "total_losing_streaks": len(streaks),
        "streak_length_distribution": _streak_distribution(streaks),
    }


def _streak_distribution(streaks):
    """Count streaks by length bucket."""
    dist = defaultdict(int)
    for s in streaks:
        dist[s["length"]] += 1
    return {str(k): v for k, v in sorted(dist.items())}


# ============================================================
# 6. TRADE SUFFICIENCY
# ============================================================
def check_trade_sufficiency(total_trades):
    """Return warning if trade count is below threshold."""
    if total_trades < TRADE_SUFFICIENCY_MIN:
        return {
            "warning": "INSUFFICIENT_SAMPLE",
            "trades": total_trades,
            "minimum_required": TRADE_SUFFICIENCY_MIN,
            "message": (
                f"Only {total_trades} trades — below {TRADE_SUFFICIENCY_MIN} minimum. "
                "All risk metrics should be interpreted with extreme caution."
            ),
        }
    return {
        "warning": None,
        "trades": total_trades,
        "minimum_required": TRADE_SUFFICIENCY_MIN,
    }


# ============================================================
# FULL RISK ANALYSIS FOR ONE CONFIG
# ============================================================
def run_risk_analysis(label, cfg, indicators, coins, total_bars):
    """Run all risk modules for a single config."""
    print(f"\n--- Risk Analysis: {label} ---")
    print(f"  Config: {json.dumps(cfg, sort_keys=True)}")

    # Baseline backtest
    print(f"  Running baseline backtest...")
    t0 = time.time()
    baseline = run_backtest(indicators, coins, cfg)
    t_baseline = time.time() - t0
    print(f"    Baseline: {baseline['trades']} trades, "
          f"P&L=${baseline['pnl']:+,.2f}, DD={baseline['dd']:.1f}%, "
          f"PF={baseline['pf']:.2f} ({t_baseline:.1f}s)")

    trade_list = baseline.get("trade_list", [])
    total_pnl = baseline["pnl"]

    # 6. Trade sufficiency (check first, applies to all metrics)
    sufficiency = check_trade_sufficiency(baseline["trades"])
    if sufficiency["warning"]:
        print(f"  WARNING: {sufficiency['message']}")

    # 1. Drawdown per window
    print(f"  Computing drawdown per window...")
    windows = compute_drawdown_per_window(trade_list, total_bars)
    flagged_count = sum(1 for w in windows if w["flagged_dd_gt_30"])
    print(f"    {len(windows)} windows, {flagged_count} flagged (DD>30%)")

    # 2. Worst-coin contribution
    print(f"  Computing worst-coin contribution...")
    worst_coin = compute_worst_coin_contribution(trade_list, total_pnl)
    print(f"    {worst_coin['coins_traded']} coins traded")
    if worst_coin["worst_1"]["pair"]:
        print(f"    Worst coin: {worst_coin['worst_1']['pair']} "
              f"P&L=${worst_coin['worst_1']['pnl']:+,.2f}")
        print(f"    P&L without worst 1: ${worst_coin['worst_1']['pnl_without']:+,.2f}")
        print(f"    P&L without worst 3: ${worst_coin['worst_3']['pnl_without']:+,.2f}")

    # 3. Friction ladder
    print(f"  Running friction ladder ({len(FRICTION_LADDER)} levels)...")
    t0 = time.time()
    friction = compute_friction_ladder(cfg, indicators, coins)
    t_friction = time.time() - t0
    if friction["breakeven_fee_bps"]:
        print(f"    Breakeven friction: {friction['breakeven_fee_bps']} bps")
    elif friction["breakeven_note"]:
        print(f"    Breakeven: {friction['breakeven_note']}")
    print(f"    Friction ladder: {t_friction:.1f}s")

    # 4. Latency sensitivity
    print(f"  Computing latency sensitivity...")
    latency = compute_latency_sensitivity(friction, total_pnl)
    print(f"    1-candle-later P&L: ${latency.get('one_candle_later_pnl', 0):+,.2f} "
          f"(delta: {latency.get('pnl_delta_pct', 0):+.1f}%)")

    # 5. Consecutive loss analysis
    print(f"  Computing consecutive loss analysis...")
    consec = compute_consecutive_loss_analysis(trade_list)
    print(f"    Max consecutive losses: {consec['max_consecutive_losses']}")
    print(f"    Equity impact of worst streak: {consec['equity_impact_pct']:.1f}%")

    return {
        "label": label,
        "cfg": cfg,
        "baseline": {
            "trades": baseline["trades"],
            "wr": round(baseline["wr"], 1),
            "pnl": round(baseline["pnl"], 2),
            "final_equity": round(baseline["final_equity"], 2),
            "pf": round(baseline["pf"], 2) if baseline["pf"] != float("inf") else 99.0,
            "dd": round(baseline["dd"], 1),
            "broke": baseline["broke"],
        },
        "trade_sufficiency": sufficiency,
        "drawdown_windows": windows,
        "worst_coin": worst_coin,
        "friction_ladder": friction,
        "latency_sensitivity": latency,
        "consecutive_losses": consec,
    }


# ============================================================
# MARKDOWN REPORT
# ============================================================
def generate_markdown(results, meta):
    """Generate human-readable risk report."""
    lines = [
        "# HF Tail Risk Report — 4H Variant Research",
        "",
        f"**Date**: {meta['timestamp']}",
        f"**Universe**: {meta['universe']}",
        f"**Data**: `{Path(meta['data_file']).name}`",
        f"**Coins**: {meta['n_coins']}",
        f"**Bars**: {meta['total_bars']}",
        f"**Window size**: {WINDOW_SIZE} bars (~30 days)",
        f"**Runtime**: {meta['total_time_s']:.1f}s",
        "",
    ]

    for r in results:
        label = r["label"]
        bl = r["baseline"]
        lines.extend([
            f"---",
            f"",
            f"## {label}",
            f"",
            f"**Config**: `{json.dumps(r['cfg'], sort_keys=True)}`",
            f"",
        ])

        # Trade sufficiency warning
        suf = r["trade_sufficiency"]
        if suf["warning"]:
            lines.extend([
                f"> **WARNING: {suf['warning']}** — {suf['message']}",
                f"",
            ])

        # Baseline
        lines.extend([
            f"### Baseline Performance",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Trades | {bl['trades']} |",
            f"| Win Rate | {bl['wr']}% |",
            f"| P&L | ${bl['pnl']:+,.2f} |",
            f"| Final Equity | ${bl['final_equity']:,.2f} |",
            f"| Profit Factor | {bl['pf']} |",
            f"| Max Drawdown | {bl['dd']}% |",
            f"| Broke | {bl['broke']} |",
            f"",
        ])

        # 1. Drawdown windows
        windows = r["drawdown_windows"]
        flagged = [w for w in windows if w["flagged_dd_gt_30"]]
        lines.extend([
            f"### 1. Drawdown Per Window",
            f"",
            f"| Window | Bars | Trades | P&L | Max DD% | Flagged |",
            f"|--------|------|--------|-----|---------|---------|",
        ])
        for w in windows:
            flag_str = "YES" if w["flagged_dd_gt_30"] else ""
            lines.append(
                f"| {w['window']} | {w['bar_start']}-{w['bar_end']} "
                f"| {w['trades']} | ${w['pnl']:+,.2f} "
                f"| {w['max_dd_pct']}% | {flag_str} |"
            )
        lines.extend([
            f"",
            f"**Flagged windows (DD>30%)**: {len(flagged)}/{len(windows)}",
            f"",
        ])

        # 2. Worst-coin contribution
        wc = r["worst_coin"]
        lines.extend([
            f"### 2. Worst-Coin Contribution",
            f"",
            f"**Coins traded**: {wc['coins_traded']}",
            f"",
        ])

        # Show top-5 worst and top-5 best
        n_show = min(5, len(wc["coin_details"]))
        if n_show > 0:
            lines.extend([
                f"**Worst 5 coins**:",
                f"",
                f"| Coin | P&L | Trades | % of Total |",
                f"|------|-----|--------|------------|",
            ])
            for cd in wc["coin_details"][:n_show]:
                lines.append(
                    f"| {cd['pair']} | ${cd['pnl']:+,.2f} "
                    f"| {cd['trades']} | {cd['pnl_pct_of_total']}% |"
                )
            lines.append("")

            lines.extend([
                f"**Best 5 coins**:",
                f"",
                f"| Coin | P&L | Trades | % of Total |",
                f"|------|-----|--------|------------|",
            ])
            for cd in wc["coin_details"][-n_show:][::-1]:
                lines.append(
                    f"| {cd['pair']} | ${cd['pnl']:+,.2f} "
                    f"| {cd['trades']} | {cd['pnl_pct_of_total']}% |"
                )
            lines.append("")

        lines.extend([
            f"**Removal impact**:",
            f"",
            f"| Scenario | P&L | Delta |",
            f"|----------|-----|-------|",
            f"| Baseline | ${bl['pnl']:+,.2f} | — |",
            f"| Remove worst 1 ({wc['worst_1']['pair']}) "
            f"| ${wc['worst_1']['pnl_without']:+,.2f} "
            f"| ${wc['worst_1']['delta']:+,.2f} |",
            f"| Remove worst 3 ({', '.join(wc['worst_3']['pairs'])}) "
            f"| ${wc['worst_3']['pnl_without']:+,.2f} "
            f"| ${wc['worst_3']['delta']:+,.2f} |",
            f"",
        ])

        # 3. Friction ladder
        fl = r["friction_ladder"]
        lines.extend([
            f"### 3. Friction Ladder",
            f"",
            f"| Level | Fee (bps) | P&L | Trades | DD% | Profitable |",
            f"|-------|-----------|-----|--------|-----|------------|",
        ])
        for lev in fl["ladder"]:
            prof_str = "YES" if lev["profitable"] else "NO"
            lines.append(
                f"| {lev['label']} | {lev['fee_bps']} "
                f"| ${lev['pnl']:+,.2f} | {lev['trades']} "
                f"| {lev['dd']}% | {prof_str} |"
            )

        lines.append("")
        if fl["breakeven_fee_bps"]:
            lines.append(
                f"**Breakeven friction**: ~{fl['breakeven_fee_bps']} bps "
                f"(fee={fl['breakeven_fee']})"
            )
        elif fl["breakeven_note"]:
            lines.append(f"**Breakeven**: {fl['breakeven_note']}")
        lines.append("")

        # 4. Latency sensitivity
        lat = r["latency_sensitivity"]
        lines.extend([
            f"### 4. Latency Sensitivity (1-Candle-Later Entry)",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Baseline P&L | ${lat.get('baseline_pnl', 0):+,.2f} |",
            f"| 1-candle-later P&L | ${lat.get('one_candle_later_pnl', 0):+,.2f} |",
            f"| Delta | ${lat.get('pnl_delta', 0):+,.2f} ({lat.get('pnl_delta_pct', 0):+.1f}%) |",
            f"| Still profitable | {lat.get('still_profitable', 'N/A')} |",
            f"| Fee modeled | {lat.get('fee_used_bps', 'N/A')} bps |",
            f"",
        ])

        # 5. Consecutive loss analysis
        cl = r["consecutive_losses"]
        lines.extend([
            f"### 5. Consecutive Loss Analysis",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Max consecutive losses | {cl['max_consecutive_losses']} |",
            f"| Total losing streaks | {cl.get('total_losing_streaks', 0)} |",
            f"| Equity impact of worst streak | {cl['equity_impact_pct']}% |",
        ])

        if "equity_before_worst" in cl:
            lines.extend([
                f"| Equity before worst streak | ${cl['equity_before_worst']:,.2f} |",
                f"| Equity after worst streak | ${cl['equity_after_worst']:,.2f} |",
            ])

        if "worst_streak_by_length" in cl and cl["worst_streak_by_length"]:
            ws = cl["worst_streak_by_length"]
            lines.append(
                f"| Worst streak (by length) | {ws['length']} trades, "
                f"${ws['pnl']:+,.2f} |"
            )
        if "worst_streak_by_pnl" in cl and cl["worst_streak_by_pnl"]:
            ws = cl["worst_streak_by_pnl"]
            lines.append(
                f"| Worst streak (by P&L) | {ws['length']} trades, "
                f"${ws['pnl']:+,.2f} |"
            )

        lines.append("")

        # Streak distribution
        if "streak_length_distribution" in cl and cl["streak_length_distribution"]:
            lines.extend([
                f"**Losing streak distribution**:",
                f"",
                f"| Streak Length | Count |",
                f"|--------------|-------|",
            ])
            for length, count in sorted(cl["streak_length_distribution"].items(),
                                         key=lambda x: int(x[0])):
                lines.append(f"| {length} | {count} |")
            lines.append("")

    # Summary comparison
    if len(results) == 2:
        r0, r1 = results
        lines.extend([
            f"---",
            f"",
            f"## Comparative Summary",
            f"",
            f"| Metric | {r0['label']} | {r1['label']} |",
            f"|--------|{'---' * 5}|{'---' * 5}|",
            f"| Trades | {r0['baseline']['trades']} | {r1['baseline']['trades']} |",
            f"| P&L | ${r0['baseline']['pnl']:+,.2f} | ${r1['baseline']['pnl']:+,.2f} |",
            f"| Max DD | {r0['baseline']['dd']}% | {r1['baseline']['dd']}% |",
            f"| PF | {r0['baseline']['pf']} | {r1['baseline']['pf']} |",
        ])

        # Breakeven friction comparison
        be0 = r0["friction_ladder"].get("breakeven_fee_bps")
        be1 = r1["friction_ladder"].get("breakeven_fee_bps")
        be0_str = f"{be0} bps" if be0 else (r0["friction_ladder"].get("breakeven_note", "N/A"))
        be1_str = f"{be1} bps" if be1 else (r1["friction_ladder"].get("breakeven_note", "N/A"))
        lines.append(f"| Breakeven friction | {be0_str} | {be1_str} |")

        # Latency impact
        lat0 = r0["latency_sensitivity"]
        lat1 = r1["latency_sensitivity"]
        lines.append(
            f"| 1-candle P&L delta | "
            f"${lat0.get('pnl_delta', 0):+,.2f} | "
            f"${lat1.get('pnl_delta', 0):+,.2f} |"
        )

        # Max consecutive losses
        lines.append(
            f"| Max consec. losses | "
            f"{r0['consecutive_losses']['max_consecutive_losses']} | "
            f"{r1['consecutive_losses']['max_consecutive_losses']} |"
        )

        lines.append("")

    lines.extend([
        "",
        "---",
        f"*Generated by hf_tail_risk.py — 4H variant research*",
    ])

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="HF Tail Risk Analysis — 4H variant research"
    )
    parser.add_argument(
        "--universe",
        choices=["tradeable", "live"],
        default="tradeable",
        help="Which candle cache to use (default: tradeable)",
    )
    args = parser.parse_args()

    print(f"=== HF Tail Risk Analysis — 4H variant research (universe={args.universe}) ===")

    # 1. Load data
    data, coins, data_path = load_data(args.universe)
    print(f"  Loaded {len(coins)} coins from {Path(data_path).name}")

    # Determine total bars
    bar_counts = [len(data[c]) for c in coins if c in data]
    total_bars = max(bar_counts) if bar_counts else 0
    print(f"  Total bars: {total_bars}")

    # 2. Precompute indicators
    print("  Precomputing indicators...")
    t0 = time.time()
    indicators = precompute_all(data, coins)
    t_precompute = time.time() - t0
    print(f"  Precompute: {t_precompute:.1f}s")

    # 3. Run risk analysis for both configs
    configs = [
        ("Champion_H2", CHAMPION_H2),
        ("GRID_BEST", GRID_BEST),
    ]

    all_results = []
    for label, cfg in configs:
        result = run_risk_analysis(label, cfg, indicators, coins, total_bars)
        all_results.append(result)

    total_time = time.time() - t0

    # 4. Write JSON report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    meta = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "universe": args.universe,
        "data_file": data_path,
        "n_coins": len(coins),
        "total_bars": total_bars,
        "window_size": WINDOW_SIZE,
        "friction_levels": len(FRICTION_LADDER),
        "total_time_s": round(total_time, 2),
        "variant": "4H variant research",
    }

    json_path = REPORTS_DIR / "risk_001.json"
    with open(json_path, "w") as f:
        json.dump(
            {
                "meta": meta,
                "configs": {r["label"]: r for r in all_results},
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\n  Wrote {json_path}")

    # 5. Write markdown report
    md_path = REPORTS_DIR / "risk_001.md"
    md = generate_markdown(all_results, meta)
    with open(md_path, "w") as f:
        f.write(md)
    print(f"  Wrote {md_path}")

    # 6. Summary
    print(f"\n=== Summary ===")
    for r in all_results:
        bl = r["baseline"]
        fl = r["friction_ladder"]
        cl = r["consecutive_losses"]
        suf = r["trade_sufficiency"]

        print(f"\n  {r['label']}:")
        print(f"    Trades={bl['trades']} P&L=${bl['pnl']:+,.2f} DD={bl['dd']}%")

        if suf["warning"]:
            print(f"    *** {suf['warning']}: {suf['trades']} trades < {suf['minimum_required']} ***")

        if fl["breakeven_fee_bps"]:
            print(f"    Breakeven friction: {fl['breakeven_fee_bps']} bps")
        elif fl["breakeven_note"]:
            print(f"    Breakeven: {fl['breakeven_note']}")

        print(f"    Max consec. losses: {cl['max_consecutive_losses']} "
              f"(equity impact: {cl['equity_impact_pct']}%)")

        # Worst coin
        wc = r["worst_coin"]
        if wc["worst_1"]["pair"]:
            print(f"    Worst coin: {wc['worst_1']['pair']} "
                  f"(${wc['worst_1']['pnl']:+,.2f})")

    print(f"\nDone in {total_time:.1f}s")


if __name__ == "__main__":
    main()

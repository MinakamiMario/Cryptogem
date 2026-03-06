#!/usr/bin/env python3
"""
Halal Universe Analysis — ms_018 per-coin profitability on FULL universe.

Purpose:
  1. Run ms_018 backtest on ALL 487+ coins, track per-coin results
  2. Rank ALL coins by P&L (top 50 most profitable)
  3. Output: symbol, trade_count, PF, P&L, win_rate for each
  4. Identify which current 45 halal coins are UNPROFITABLE (PF < 1.0)

Goal: Give user a list of profitable coins to review for halal compatibility
(utility tokens, infrastructure, etc.) vs clearly haram (lending, gambling, meme).

Config: ms_018 (shift_pb shallow)
  - max_bos_age=15, pullback_pct=0.382, max_pullback_bars=6
  - DC exits: max_stop_pct=15, time_max_bars=15, rsi_recovery=True
  - Fee: 10bps (MEXC) per side
  - max_pos=1 per coin (isolated per-coin analysis)
  - $5K initial capital per coin
"""
from __future__ import annotations

import sys
import json
import time
from pathlib import Path
from collections import defaultdict

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "trading_bot"))

import importlib
import importlib.util


def _register_pkg(name: str, init_path: str, search_path: str):
    """Register a package with numeric-prefixed name in sys.modules."""
    spec = importlib.util.spec_from_file_location(
        name, init_path, submodule_search_locations=[search_path])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Bootstrap strategies.4h.* (Python 3.13 rejects '4h' as identifier)
_strat_base = str(REPO_ROOT / "strategies")
_register_pkg("strategies", f"{_strat_base}/__init__.py", _strat_base)
_register_pkg("strategies.4h", f"{_strat_base}/4h/__init__.py", f"{_strat_base}/4h")
for _sub in ("sprint1", "sprint2", "sprint3", "sweep_v1"):
    _sub_init = Path(f"{_strat_base}/4h/{_sub}/__init__.py")
    if _sub_init.exists():
        _register_pkg(f"strategies.4h.{_sub}", str(_sub_init), f"{_strat_base}/4h/{_sub}")

_sprint3_engine = importlib.import_module("strategies.4h.sprint3.engine")
_ms_indicators = importlib.import_module("strategies.ms.indicators")
_ms_hypotheses = importlib.import_module("strategies.ms.hypotheses")
_data_resolver = importlib.import_module("strategies.4h.data_resolver")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HALAL_FILE = REPO_ROOT / "trading_bot" / "halal_coins.txt"
DATASET_ID = "4h_default"
MIN_BARS = 360
START_BAR = 50
MEXC_FEE = 0.0010  # 10bps per side
TOP_N = 50  # Show top N coins by P&L

# ms_018 params (frozen from ADR-MS-002 / paper_ms_4h.py)
MS018_PARAMS = {
    "max_bos_age": 15,
    "pullback_pct": 0.382,
    "max_pullback_bars": 6,
    "max_stop_pct": 15.0,
    "time_max_bars": 15,
    "rsi_recovery": True,
    "rsi_rec_target": 45.0,
    "rsi_rec_min_bars": 2,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_halal_coins() -> list[str]:
    """Load halal coins from file, return as /USD pairs (cache format)."""
    coins = []
    with open(HALAL_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pair = line.replace("/USDT", "/USD")
            coins.append(pair)
    return coins


def run_single_coin_backtest(
    data: dict,
    coin: str,
    indicators: dict,
    signal_fn,
    params: dict,
) -> dict:
    """Run ms_018 backtest on a single coin, returning per-coin stats."""
    bt = _sprint3_engine.run_backtest(
        data=data,
        coins=[coin],
        signal_fn=signal_fn,
        params=params,
        indicators=indicators,
        exit_mode="dc",
        start_bar=START_BAR,
        fee=MEXC_FEE,
        initial_capital=5000.0,
        max_pos=1,
    )
    return {
        "pair": coin,
        "trades": bt.trades,
        "pnl": round(bt.pnl, 2),
        "pf": round(bt.pf, 4) if bt.pf != float("inf") else 99.99,
        "wr": round(bt.wr, 2),
        "dd": round(bt.dd, 2),
        "trade_list": bt.trade_list,
        "exit_classes": bt.exit_classes,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"\n{'='*80}")
    print("  MS_018 (shift_pb shallow) — FULL UNIVERSE PER-COIN PROFITABILITY ANALYSIS")
    print(f"{'='*80}\n")

    # 1. Load halal coins for cross-reference
    halal_coins = load_halal_coins()
    halal_set = set(halal_coins)
    print(f"  Halal whitelist: {len(halal_coins)} coins")

    # 2. Load candle cache
    path = _data_resolver.resolve_dataset(DATASET_ID)
    print(f"  Dataset: {path}")
    t0 = time.time()
    with open(path, "r") as f:
        data = json.load(f)
    t_load = time.time() - t0
    print(f"  Loaded in {t_load:.1f}s")

    all_coins = [k for k in data if not k.startswith("_")]
    print(f"  Total coins in cache: {len(all_coins)}")

    # 3. Filter to coins with enough bars
    eligible_coins = [
        c for c in all_coins
        if isinstance(data[c], list) and len(data[c]) >= MIN_BARS
    ]
    print(f"  Coins with >= {MIN_BARS} bars: {len(eligible_coins)}")

    # 4. Precompute indicators for ALL eligible coins
    print(f"\n  Computing MS indicators for {len(eligible_coins)} coins...")
    t0 = time.time()
    indicators = _ms_indicators.precompute_ms_indicators(data, eligible_coins)
    t_ind = time.time() - t0
    print(f"  Indicators computed in {t_ind:.1f}s\n")

    # 5. Get signal_fn for ms_018
    signal_fn = _ms_hypotheses.signal_structure_shift_pullback

    # 6. Per-coin backtest — ALL coins
    print(f"  Running per-coin backtests (max_pos=1, $5K, fee=10bps)...")
    t0 = time.time()
    coin_results = []
    for i, coin in enumerate(sorted(eligible_coins)):
        result = run_single_coin_backtest(data, coin, indicators, signal_fn, MS018_PARAMS)
        coin_results.append(result)
        if (i + 1) % 100 == 0:
            print(f"    ... {i+1}/{len(eligible_coins)} coins done")
    t_bt = time.time() - t0
    print(f"  Backtests completed in {t_bt:.1f}s\n")

    # 7. Stats
    active_coins = [r for r in coin_results if r["trades"] > 0]
    zero_coins = [r for r in coin_results if r["trades"] == 0]
    profitable = [r for r in active_coins if r["pf"] >= 1.0]
    unprofitable = [r for r in active_coins if r["pf"] < 1.0]

    print(f"  --- UNIVERSE SUMMARY ---")
    print(f"  Total eligible coins: {len(eligible_coins)}")
    print(f"  Coins with >= 1 trade: {len(active_coins)}")
    print(f"  Coins with 0 trades:   {len(zero_coins)}")
    print(f"  Profitable (PF >= 1.0): {len(profitable)}")
    print(f"  Unprofitable (PF < 1.0): {len(unprofitable)}")

    total_pnl = sum(r["pnl"] for r in active_coins)
    total_trades = sum(r["trades"] for r in active_coins)
    print(f"  Total trades: {total_trades}")
    print(f"  Total P&L (sum all coins): ${total_pnl:+,.2f}")
    if profitable:
        prof_pnl = sum(r["pnl"] for r in profitable)
        print(f"  Profitable coins total P&L: ${prof_pnl:+,.2f}")
    if unprofitable:
        unprof_pnl = sum(r["pnl"] for r in unprofitable)
        print(f"  Unprofitable coins total P&L: ${unprof_pnl:+,.2f}")

    # =====================================================================
    # SECTION A: TOP 50 MOST PROFITABLE COINS BY P&L
    # =====================================================================
    print(f"\n{'='*80}")
    print(f"  TOP {TOP_N} MOST PROFITABLE COINS BY P&L")
    print(f"  (Review for halal compatibility: utility/infra = potentially OK,")
    print(f"   lending/interest/meme/gambling = haram)")
    print(f"{'='*80}\n")

    # Sort by P&L descending
    sorted_by_pnl = sorted(active_coins, key=lambda r: -r["pnl"])
    top_n = sorted_by_pnl[:TOP_N]

    print(f"  {'#':>3s}  {'Coin':<14s} {'Trades':>6s} {'PF':>6s} {'WR%':>6s} "
          f"{'P&L':>10s} {'DD%':>6s} {'Halal?':>6s}")
    print(f"  {'─'*66}")

    for i, r in enumerate(top_n, 1):
        is_halal = "YES" if r["pair"] in halal_set else "  -"
        print(f"  {i:>3d}  {r['pair']:<14s} {r['trades']:>6d} {r['pf']:>6.2f} "
              f"{r['wr']:>5.1f}% ${r['pnl']:>+9.2f} {r['dd']:>5.1f}% {is_halal:>6s}")

    # Count halal in top N
    halal_in_top = sum(1 for r in top_n if r["pair"] in halal_set)
    print(f"\n  Halal coins in top {TOP_N}: {halal_in_top}/{TOP_N}")

    # =====================================================================
    # SECTION B: TOP 50 BY PROFIT FACTOR (min 3 trades)
    # =====================================================================
    print(f"\n{'='*80}")
    print(f"  TOP {TOP_N} COINS BY PROFIT FACTOR (min 3 trades)")
    print(f"{'='*80}\n")

    min_trades = 3
    filtered_by_pf = [r for r in active_coins if r["trades"] >= min_trades]
    sorted_by_pf = sorted(filtered_by_pf, key=lambda r: -r["pf"])
    top_pf = sorted_by_pf[:TOP_N]

    print(f"  {'#':>3s}  {'Coin':<14s} {'Trades':>6s} {'PF':>6s} {'WR%':>6s} "
          f"{'P&L':>10s} {'DD%':>6s} {'Halal?':>6s}")
    print(f"  {'─'*66}")

    for i, r in enumerate(top_pf, 1):
        is_halal = "YES" if r["pair"] in halal_set else "  -"
        print(f"  {i:>3d}  {r['pair']:<14s} {r['trades']:>6d} {r['pf']:>6.2f} "
              f"{r['wr']:>5.1f}% ${r['pnl']:>+9.2f} {r['dd']:>5.1f}% {is_halal:>6s}")

    # =====================================================================
    # SECTION C: HALAL WHITELIST — UNPROFITABLE COINS (candidates for removal)
    # =====================================================================
    print(f"\n{'='*80}")
    print(f"  HALAL WHITELIST — UNPROFITABLE COINS (candidates for removal)")
    print(f"  These cost money and add no value to the ms_018 strategy.")
    print(f"{'='*80}\n")

    halal_results = [r for r in coin_results if r["pair"] in halal_set]
    halal_active = [r for r in halal_results if r["trades"] > 0]
    halal_zero = [r for r in halal_results if r["trades"] == 0]
    halal_unprofitable = [r for r in halal_active if r["pf"] < 1.0]
    halal_profitable = [r for r in halal_active if r["pf"] >= 1.0]

    # Missing from cache
    halal_missing = [c for c in halal_coins if c not in data]
    halal_short_bars = [
        c for c in halal_coins
        if c in data and isinstance(data[c], list) and len(data[c]) < MIN_BARS
    ]

    print(f"  Halal coins total: {len(halal_coins)}")
    print(f"  In cache with >= {MIN_BARS} bars: {len(halal_results)}")
    if halal_missing:
        print(f"  Missing from cache: {halal_missing}")
    if halal_short_bars:
        print(f"  Too few bars: {halal_short_bars}")
    print(f"  With >= 1 trade: {len(halal_active)}")
    print(f"  With 0 trades: {len(halal_zero)}")
    print(f"  Profitable (PF >= 1.0): {len(halal_profitable)}")
    print(f"  Unprofitable (PF < 1.0): {len(halal_unprofitable)}")
    print()

    # Table: unprofitable halal coins
    if halal_unprofitable:
        halal_unprofitable.sort(key=lambda r: r["pnl"])  # worst first
        print(f"  UNPROFITABLE halal coins (worst first):")
        print(f"  {'Coin':<14s} {'Trades':>6s} {'PF':>6s} {'WR%':>6s} {'P&L':>10s} {'DD%':>6s}")
        print(f"  {'─'*50}")
        for r in halal_unprofitable:
            print(f"  {r['pair']:<14s} {r['trades']:>6d} {r['pf']:>6.2f} {r['wr']:>5.1f}% "
                  f"${r['pnl']:>+9.2f} {r['dd']:>5.1f}%")
        total_halal_loss = sum(r["pnl"] for r in halal_unprofitable)
        print(f"\n  Total P&L drag from unprofitable halal coins: ${total_halal_loss:+,.2f}")
    else:
        print(f"  No unprofitable halal coins (all profitable or zero trades).")

    # Table: zero-trade halal coins
    if halal_zero:
        print(f"\n  Halal coins with 0 trades (no signal generated):")
        for r in sorted(halal_zero, key=lambda r: r["pair"]):
            print(f"    {r['pair']}")
        print(f"  ({len(halal_zero)} coins generate NO ms_018 signals)")

    # Table: profitable halal coins
    if halal_profitable:
        halal_profitable.sort(key=lambda r: -r["pnl"])
        print(f"\n  PROFITABLE halal coins:")
        print(f"  {'Coin':<14s} {'Trades':>6s} {'PF':>6s} {'WR%':>6s} {'P&L':>10s} {'DD%':>6s}")
        print(f"  {'─'*50}")
        for r in halal_profitable:
            print(f"  {r['pair']:<14s} {r['trades']:>6d} {r['pf']:>6.2f} {r['wr']:>5.1f}% "
                  f"${r['pnl']:>+9.2f} {r['dd']:>5.1f}%")
        total_halal_prof = sum(r["pnl"] for r in halal_profitable)
        print(f"\n  Total P&L from profitable halal coins: ${total_halal_prof:+,.2f}")

    # =====================================================================
    # SECTION D: NON-HALAL PROFITABLE COINS — REVIEW CANDIDATES
    # =====================================================================
    print(f"\n{'='*80}")
    print(f"  NON-HALAL PROFITABLE COINS — POTENTIAL HALAL REVIEW CANDIDATES")
    print(f"  Coins NOT on halal list but profitable with ms_018.")
    print(f"  Review: utility/infra/L1/L2 = potentially halal")
    print(f"{'='*80}\n")

    non_halal_profitable = [
        r for r in active_coins
        if r["pf"] >= 1.0 and r["pair"] not in halal_set
    ]
    non_halal_profitable.sort(key=lambda r: -r["pnl"])

    print(f"  Total non-halal profitable coins: {len(non_halal_profitable)}")
    print(f"\n  {'#':>3s}  {'Coin':<14s} {'Trades':>6s} {'PF':>6s} {'WR%':>6s} {'P&L':>10s} {'DD%':>6s}")
    print(f"  {'─'*60}")

    for i, r in enumerate(non_halal_profitable, 1):
        print(f"  {i:>3d}  {r['pair']:<14s} {r['trades']:>6d} {r['pf']:>6.2f} "
              f"{r['wr']:>5.1f}% ${r['pnl']:>+9.2f} {r['dd']:>5.1f}%")

    # =====================================================================
    # SECTION E: VERDICT & RECOMMENDATIONS
    # =====================================================================
    print(f"\n{'='*80}")
    print(f"  VERDICT & RECOMMENDATIONS")
    print(f"{'='*80}\n")

    print(f"  1. HALAL WHITELIST CLEANUP:")
    if halal_unprofitable:
        print(f"     - {len(halal_unprofitable)} coins are UNPROFITABLE (remove to reduce P&L drag)")
        for r in halal_unprofitable[:5]:
            print(f"       {r['pair']}: PF={r['pf']:.2f}, ${r['pnl']:+.2f}")
        if len(halal_unprofitable) > 5:
            print(f"       ... and {len(halal_unprofitable) - 5} more")
    if halal_zero:
        print(f"     - {len(halal_zero)} coins generate ZERO trades (no impact, but cluttering)")

    print(f"\n  2. EXPANSION CANDIDATES:")
    print(f"     - {len(non_halal_profitable)} non-halal coins are profitable")
    print(f"     - Top 10 by P&L should be reviewed for halal compatibility")
    top10_expand = non_halal_profitable[:10]
    for r in top10_expand:
        print(f"       {r['pair']}: PF={r['pf']:.2f}, {r['trades']} trades, ${r['pnl']:+.2f}")

    print(f"\n  3. STRATEGY CONCENTRATION:")
    if active_coins:
        top20_pnl = sum(r["pnl"] for r in sorted_by_pnl[:20])
        print(f"     - Top 20 coins contribute ${top20_pnl:+,.2f} of ${total_pnl:+,.2f} total")
        if total_pnl > 0:
            print(f"     - That's {top20_pnl/total_pnl*100:.1f}% of total P&L")

    print()


if __name__ == "__main__":
    main()

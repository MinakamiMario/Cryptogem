#!/usr/bin/env python3
"""
Halal Coins ms_018 Backtest — Targeted analysis on 45 halal coins.

Questions answered:
  1. How many halal coins generate ANY ms_018 signals?
  2. Per-coin trade count and P&L
  3. Is the strategy profitable on this subset?
  4. Do paper trader coins overlap with halal list?

Config: ms_018 (shift_pb shallow)
  - max_bos_age=15, pullback_pct=0.382, max_pullback_bars=6
  - DC exits: max_stop_pct=15, time_max_bars=15, rsi_recovery=True
  - Fee: 10bps (MEXC) per side
  - max_pos=2, $5K/trade, $10K initial capital
"""
from __future__ import annotations

import sys
import json
import time
from pathlib import Path
from collections import defaultdict

# ---------------------------------------------------------------------------
# Path setup — bootstrap strategies.4h.* packages (Python 3.13 compat)
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
PAPER_STATE = REPO_ROOT / "trading_bot" / "paper_state_ms_4h_paper.json"
DATASET_ID = "4h_default"
MIN_BARS = 360
START_BAR = 50
MEXC_FEE = 0.0010  # 10bps per side

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
            # Convert SYMBOL/USDT -> SYMBOL/USD (candle cache format)
            pair = line.replace("/USDT", "/USD")
            coins.append(pair)
    return coins


def load_paper_trades() -> list[dict]:
    """Load paper trader trade log."""
    if not PAPER_STATE.exists():
        return []
    with open(PAPER_STATE, "r") as f:
        state = json.load(f)
    return state.get("trade_log", [])


def run_single_coin_backtest(
    data: dict,
    coin: str,
    indicators: dict,
    signal_fn,
    params: dict,
) -> dict:
    """Run ms_018 backtest on a single coin, returning per-coin stats."""
    # We run with max_pos=1 for single-coin analysis to see per-coin signal quality
    bt = _sprint3_engine.run_backtest(
        data=data,
        coins=[coin],
        signal_fn=signal_fn,
        params=params,
        indicators=indicators,
        exit_mode="dc",
        start_bar=START_BAR,
        fee=MEXC_FEE,
        initial_capital=5000.0,  # single coin, $5K
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


def run_portfolio_backtest(
    data: dict,
    coins: list[str],
    indicators: dict,
    signal_fn,
    params: dict,
) -> dict:
    """Run ms_018 as a portfolio on all halal coins (max_pos=2)."""
    bt = _sprint3_engine.run_backtest(
        data=data,
        coins=coins,
        signal_fn=signal_fn,
        params=params,
        indicators=indicators,
        exit_mode="dc",
        start_bar=START_BAR,
        fee=MEXC_FEE,
        initial_capital=10000.0,
        max_pos=2,
    )
    return {
        "trades": bt.trades,
        "pnl": round(bt.pnl, 2),
        "pf": round(bt.pf, 4) if bt.pf != float("inf") else 99.99,
        "wr": round(bt.wr, 2),
        "dd": round(bt.dd, 2),
        "final_equity": round(bt.final_equity, 2),
        "trade_list": bt.trade_list,
        "exit_classes": bt.exit_classes,
    }


def format_exit_classes(ec: dict) -> str:
    """Format exit class breakdown."""
    parts = []
    for cls in ("A", "B"):
        for reason, info in ec.get(cls, {}).items():
            count = info.get("count", 0) if isinstance(info, dict) else info
            pnl = info.get("pnl", 0) if isinstance(info, dict) else 0
            parts.append(f"{reason}:{count}(${pnl:+.0f})")
    return " ".join(parts) if parts else "N/A"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"\n{'='*76}")
    print("  MS_018 (shift_pb shallow) — HALAL COINS BACKTEST")
    print(f"{'='*76}\n")

    # 1. Load halal coins
    halal_coins = load_halal_coins()
    print(f"  Halal coins in file: {len(halal_coins)}")
    print(f"  Sample: {halal_coins[:5]} ... {halal_coins[-3:]}\n")

    # 2. Load candle cache
    path = _data_resolver.resolve_dataset(DATASET_ID)
    print(f"  Dataset: {path}")
    with open(path, "r") as f:
        data = json.load(f)

    all_coins = [k for k in data if not k.startswith("_")]
    print(f"  Total coins in cache: {len(all_coins)}")

    # 3. Match halal coins to cache
    halal_in_cache = [c for c in halal_coins if c in data]
    halal_missing = [c for c in halal_coins if c not in data]
    halal_enough_bars = [c for c in halal_in_cache
                         if isinstance(data[c], list) and len(data[c]) >= MIN_BARS]

    print(f"  Halal coins found in cache: {len(halal_in_cache)}/{len(halal_coins)}")
    if halal_missing:
        print(f"  Missing from cache: {halal_missing}")
    print(f"  Halal coins with >= {MIN_BARS} bars: {len(halal_enough_bars)}")
    print()

    # 4. Check paper trader overlap
    print(f"  --- Paper Trader Overlap ---")
    paper_trades = load_paper_trades()
    paper_coins = set()
    if PAPER_STATE.exists():
        with open(PAPER_STATE) as f:
            paper_state = json.load(f)
        # Current positions
        for pair in paper_state.get("positions", {}):
            paper_coins.add(pair)
        # Closed trades
        for t in paper_state.get("trade_log", []):
            paper_coins.add(t.get("pair", ""))

    # Convert paper coins (SYMBOL/USDT) to USD for comparison
    paper_coins_usd = {p.replace("/USDT", "/USD") for p in paper_coins}
    halal_set = set(halal_coins)
    halal_set_usdt = {c.replace("/USD", "/USDT") for c in halal_coins}

    overlap = paper_coins & halal_set_usdt
    print(f"  Paper trader coins traded so far: {sorted(paper_coins)}")
    print(f"  Overlap with halal list: {sorted(overlap) if overlap else 'NONE'}")
    print()

    # 5. Precompute indicators for halal coins only
    print(f"  Computing MS indicators for {len(halal_enough_bars)} halal coins...")
    t0 = time.time()
    indicators = _ms_indicators.precompute_ms_indicators(data, halal_enough_bars)
    t1 = time.time()
    print(f"  Indicators computed in {t1-t0:.1f}s\n")

    # 6. Get signal_fn for ms_018
    signal_fn = _ms_hypotheses.signal_structure_shift_pullback

    # 7. Per-coin backtest
    print(f"  --- Per-Coin Backtest (max_pos=1, $5K, fee=10bps) ---\n")
    coin_results = []
    for coin in sorted(halal_enough_bars):
        result = run_single_coin_backtest(data, coin, indicators, signal_fn, MS018_PARAMS)
        coin_results.append(result)

    # Sort by trades descending
    coin_results.sort(key=lambda r: (-r["trades"], -r["pnl"]))

    # Print table
    print(f"  {'Coin':<14s} {'Trades':>6s} {'PF':>6s} {'WR%':>6s} {'P&L':>10s} {'DD%':>6s} {'Exits'}")
    print(f"  {'─'*80}")

    active_coins = 0
    total_coin_trades = 0
    for r in coin_results:
        if r["trades"] > 0:
            active_coins += 1
            total_coin_trades += r["trades"]
            exits = format_exit_classes(r["exit_classes"])
            print(f"  {r['pair']:<14s} {r['trades']:>6d} {r['pf']:>6.2f} {r['wr']:>5.1f}% "
                  f"${r['pnl']:>+9.2f} {r['dd']:>5.1f}% {exits}")

    # Print coins with 0 trades
    zero_coins = [r for r in coin_results if r["trades"] == 0]
    if zero_coins:
        print(f"\n  Coins with 0 trades ({len(zero_coins)}):")
        for r in zero_coins:
            print(f"    {r['pair']}")

    print(f"\n  --- Per-Coin Summary ---")
    print(f"  Coins with >= 1 trade: {active_coins}/{len(halal_enough_bars)}")
    print(f"  Total trades (single-coin): {total_coin_trades}")

    profitable_coins = [r for r in coin_results if r["trades"] > 0 and r["pf"] >= 1.0]
    unprofitable_coins = [r for r in coin_results if r["trades"] > 0 and r["pf"] < 1.0]
    print(f"  Profitable coins (PF >= 1.0): {len(profitable_coins)}")
    print(f"  Unprofitable coins (PF < 1.0): {len(unprofitable_coins)}")

    if profitable_coins:
        avg_pf = sum(r["pf"] for r in profitable_coins) / len(profitable_coins)
        total_pnl_prof = sum(r["pnl"] for r in profitable_coins)
        print(f"  Profitable avg PF: {avg_pf:.2f}, total P&L: ${total_pnl_prof:+,.2f}")
    if unprofitable_coins:
        avg_pf_loss = sum(r["pf"] for r in unprofitable_coins) / len(unprofitable_coins)
        total_pnl_loss = sum(r["pnl"] for r in unprofitable_coins)
        print(f"  Unprofitable avg PF: {avg_pf_loss:.2f}, total P&L: ${total_pnl_loss:+,.2f}")

    # 8. Portfolio backtest
    print(f"\n  --- Portfolio Backtest (max_pos=2, $10K, fee=10bps) ---\n")

    portfolio = run_portfolio_backtest(data, halal_enough_bars, indicators, signal_fn, MS018_PARAMS)

    print(f"  Trades:      {portfolio['trades']}")
    print(f"  PF:          {portfolio['pf']:.2f}")
    print(f"  WR:          {portfolio['wr']:.1f}%")
    print(f"  P&L:         ${portfolio['pnl']:+,.2f}")
    print(f"  DD:          {portfolio['dd']:.1f}%")
    print(f"  Final Equity: ${portfolio['final_equity']:,.2f}")
    print(f"  Exits:       {format_exit_classes(portfolio['exit_classes'])}")

    # Per-coin distribution in portfolio
    if portfolio["trade_list"]:
        coin_dist = defaultdict(lambda: {"count": 0, "pnl": 0.0})
        for t in portfolio["trade_list"]:
            pair = t.get("pair", "UNKNOWN")
            coin_dist[pair]["count"] += 1
            coin_dist[pair]["pnl"] += t["pnl"]

        print(f"\n  Portfolio Trade Distribution:")
        print(f"  {'Coin':<14s} {'Trades':>6s} {'P&L':>10s}")
        print(f"  {'─'*35}")
        for pair, info in sorted(coin_dist.items(), key=lambda x: -x[1]["count"]):
            print(f"  {pair:<14s} {info['count']:>6d} ${info['pnl']:>+9.2f}")

        n_coins_traded = len(coin_dist)
        print(f"\n  Coins traded in portfolio: {n_coins_traded}/{len(halal_enough_bars)}")

    # 9. Comparison with full universe
    print(f"\n  --- Comparison with Full Universe (from scoreboard) ---")
    print(f"  Full universe: 487 coins, PF=2.08, 697 trades, $46,017 P&L (Kraken 26bps)")
    print(f"  Halal subset:  {len(halal_enough_bars)} coins, PF={portfolio['pf']:.2f}, "
          f"{portfolio['trades']} trades, ${portfolio['pnl']:+,.2f} P&L (MEXC 10bps)")

    # Trade frequency
    n_bars = 0
    for coin in halal_enough_bars:
        ind = indicators.get(coin)
        if ind:
            n_bars = max(n_bars, ind["n"] - START_BAR)

    if n_bars > 0 and portfolio["trades"] > 0:
        trades_per_bar = portfolio["trades"] / n_bars
        trades_per_day = trades_per_bar * 6  # 4H bars, 6 bars/day
        print(f"  Trade frequency: {trades_per_day:.2f} trades/day ({trades_per_bar:.3f}/bar)")
        print(f"  Bar count: {n_bars} bars")

    # 10. Final verdict
    print(f"\n  {'='*76}")
    print(f"  VERDICT")
    print(f"  {'='*76}")
    if portfolio["trades"] < 10:
        print(f"  INSUFFICIENT DATA — only {portfolio['trades']} trades in backtest period.")
        print(f"  ms_018 generates too few signals on halal coins for standalone use.")
    elif portfolio["pf"] >= 1.0:
        print(f"  PROFITABLE — PF={portfolio['pf']:.2f} on {portfolio['trades']} trades.")
        if portfolio["trades"] < 80:
            print(f"  WARNING: Low trade count ({portfolio['trades']}). "
                  f"Statistical significance questionable.")
        if portfolio["pf"] >= 1.5:
            print(f"  STRONG — PF >= 1.5 on halal subset.")
    else:
        print(f"  UNPROFITABLE — PF={portfolio['pf']:.2f} < 1.0 on halal subset.")
        print(f"  ms_018 does NOT generate edge on halal-only universe.")
    print()


if __name__ == "__main__":
    main()

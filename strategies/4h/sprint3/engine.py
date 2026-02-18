"""
Sprint 3 Screening Engine — Stage 0 prefilter with DualConfirm exits.

Extends Sprint 1 engine with exit_mode='dc' (hybrid_notrl from agent_team_v3.py).
Reuses Sprint 1 constants, sizing, fee model for parity.

exit_mode='fixed': Sprint 1/2 behavior (TP/SL/TM)
exit_mode='dc':    DualConfirm hybrid_notrl (FIXED STOP, TIME MAX, RSI RECOVERY, DC TARGET, BB TARGET)

Every Stage 0 winner MUST be re-verified through agent_team_v3.py (truth-pass).
"""
from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "trading_bot") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "trading_bot"))

# Parity constants — must match agent_team_v3.py
KRAKEN_FEE = 0.0026  # per-side
START_BAR = 50
INITIAL_CAPITAL = 2000
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8

# Exit class mapping (parity with agent_team_v3)
CLASS_A_REASONS = {"PROFIT TARGET", "RSI RECOVERY", "DC TARGET", "BB TARGET"}

# Lazy-loaded exits module reference (populated on first dc-mode call)
_exits_mod = None


def _get_exits_module():
    """Lazy import of strategies.4h.sprint3.exits via importlib."""
    global _exits_mod
    if _exits_mod is None:
        _exits_mod = importlib.import_module("strategies.4h.sprint3.exits")
    return _exits_mod


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class _Pos:
    """Open position tracker.

    Extended from Sprint 1 with max_stop_pct for DC exit mode.
    """
    pair: str
    entry_price: float
    entry_bar: int
    size_usd: float
    stop_price: float
    target_price: float
    time_limit: int
    max_stop_pct: float = 15.0


@dataclass
class BacktestResult:
    """Backtest output — compatible with gates evaluation."""
    trades: int = 0
    pnl: float = 0.0
    pf: float = 0.0
    wr: float = 0.0
    dd: float = 0.0
    final_equity: float = 0.0
    broke: bool = False
    early_stopped: bool = False
    trade_list: list = field(default_factory=list)
    exit_classes: dict = field(default_factory=lambda: {"A": {}, "B": {}})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def precompute_dc_indicators(indicators: dict) -> None:
    """Ensure dc_mid and bb_mid exist in every coin's indicator dict.

    Sprint 1 indicators.py already computes these. This helper is a
    safety net: if indicators were built by a pipeline that omits
    dc_mid / bb_mid, we add empty arrays so exit evaluation does not
    KeyError.  Modifies indicators dict in place.
    """
    for pair, ind in indicators.items():
        n = ind.get("n", 0)
        if "dc_mid" not in ind:
            ind["dc_mid"] = [None] * n
        if "bb_mid" not in ind:
            ind["bb_mid"] = [None] * n


# ---------------------------------------------------------------------------
# Core backtest engine
# ---------------------------------------------------------------------------

def run_backtest(
    data: dict,
    coins: list[str],
    signal_fn: Callable,
    params: dict,
    indicators: dict,
    *,
    exit_mode: str = "fixed",
    fee: float = KRAKEN_FEE,
    initial_capital: float = INITIAL_CAPITAL,
    start_bar: int = START_BAR,
    end_bar: Optional[int] = None,
    cooldown_bars: int = COOLDOWN_BARS,
    cooldown_after_stop: int = COOLDOWN_AFTER_STOP,
    max_pos: int = 3,
) -> BacktestResult:
    """Run a backtest using a signal_fn with selectable exit mode.

    Parameters
    ----------
    data : dict
        Candle cache: {pair: [candle_dicts]}.
    coins : list[str]
        Coins to trade (filtered universe).
    signal_fn : callable
        (candles, bar, indicators, params) -> dict|None
        Return dict: {stop_price, target_price, time_limit, strength}
    params : dict
        Hypothesis parameter dict.
    indicators : dict
        Precomputed indicators: {pair: {rsi, atr, dc_mid, bb_mid, ..., closes, highs, lows, volumes, n}}.
    exit_mode : str
        'fixed' = Sprint 1/2 TP/SL/TM exits.
        'dc'    = DualConfirm hybrid_notrl exits.
    """
    assert exit_mode in ("fixed", "dc"), f"Unknown exit_mode: {exit_mode!r}"

    # Override max_pos from params if present
    max_pos = params.get("max_pos", max_pos)

    # Pre-resolve exits module and dc params for dc mode
    if exit_mode == "dc":
        exits = _get_exits_module()
        evaluate_exit = exits.evaluate_exit_hybrid_notrl
        precompute_dc_indicators(indicators)
        dc_max_stop_pct = params.get("max_stop_pct", 15.0)
        dc_time_max_bars = params.get("time_max_bars", 15)
        dc_rsi_recovery = params.get("rsi_recovery", True)
        dc_rsi_rec_target = params.get("rsi_rec_target", 45.0)
        dc_rsi_rec_min_bars = params.get("rsi_rec_min_bars", 2)
    else:
        exits = None
        evaluate_exit = None

    # Determine bar range
    max_bars = end_bar
    if max_bars is None:
        max_bars = max(ind["n"] for ind in indicators.values()) if indicators else 0

    equity = float(initial_capital)
    peak_equity = equity
    max_dd = 0.0

    positions: list[_Pos] = []
    trades: list[dict] = []
    last_exit_bar: dict[str, int] = {}
    last_exit_was_stop: dict[str, bool] = {}
    exit_classes: dict[str, dict] = {"A": {}, "B": {}}

    for bar in range(start_bar, max_bars):
        # --- Phase 1: Process exits ---
        closed_this_bar = []
        for pos in positions:
            ind = indicators.get(pos.pair)
            if ind is None or bar >= ind["n"]:
                closed_this_bar.append(pos)
                continue

            low = ind["lows"][bar]
            high = ind["highs"][bar]
            close = ind["closes"][bar]
            bars_in = bar - pos.entry_bar

            exit_price = None
            reason = None

            if exit_mode == "fixed":
                # Sprint 1/2 behavior: TP/SL/TM — EXACT copy from Sprint 1 engine
                # Priority 1: Stop loss
                if low <= pos.stop_price:
                    exit_price = pos.stop_price
                    reason = "FIXED STOP"

                # Priority 2: Take profit
                elif high >= pos.target_price:
                    exit_price = pos.target_price
                    reason = "PROFIT TARGET"

                # Priority 3: Time max
                elif bars_in >= pos.time_limit:
                    exit_price = close
                    reason = "TIME MAX"

            else:
                # DC mode: hybrid_notrl exits via exits module
                rsi_val = ind["rsi"][bar] if ind["rsi"][bar] is not None else None
                dc_mid_val = ind["dc_mid"][bar]
                bb_mid_val = ind["bb_mid"][bar]

                sig = evaluate_exit(
                    entry_price=pos.entry_price,
                    entry_bar=pos.entry_bar,
                    bar=bar,
                    low=low,
                    high=high,
                    close=close,
                    rsi=rsi_val,
                    dc_mid=dc_mid_val,
                    bb_mid=bb_mid_val,
                    max_stop_pct=pos.max_stop_pct,
                    time_max_bars=dc_time_max_bars,
                    rsi_recovery=dc_rsi_recovery,
                    rsi_rec_target=dc_rsi_rec_target,
                    rsi_rec_min_bars=dc_rsi_rec_min_bars,
                )
                if sig is not None:
                    exit_price = sig.price
                    reason = sig.reason

            if exit_price is not None:
                gross = pos.size_usd * (exit_price / pos.entry_price - 1.0)
                fees = pos.size_usd * fee + (pos.size_usd + gross) * fee
                net_pnl = gross - fees
                equity += pos.size_usd + net_pnl

                trade = {
                    "pair": pos.pair,
                    "entry": pos.entry_price,
                    "exit": exit_price,
                    "pnl": net_pnl,
                    "pnl_pct": net_pnl / pos.size_usd * 100 if pos.size_usd > 0 else 0.0,
                    "reason": reason,
                    "bars": bars_in,
                    "entry_bar": pos.entry_bar,
                    "exit_bar": bar,
                    "size": pos.size_usd,
                    "equity_after": equity,
                }
                trades.append(trade)

                # Track exit classes
                cls = "A" if reason in CLASS_A_REASONS else "B"
                if reason not in exit_classes[cls]:
                    exit_classes[cls][reason] = {"count": 0, "pnl": 0.0, "wins": 0}
                exit_classes[cls][reason]["count"] += 1
                exit_classes[cls][reason]["pnl"] += net_pnl
                if net_pnl > 0:
                    exit_classes[cls][reason]["wins"] += 1

                last_exit_bar[pos.pair] = bar
                last_exit_was_stop[pos.pair] = reason in ("FIXED STOP", "HARD STOP")

                closed_this_bar.append(pos)

        for pos in closed_this_bar:
            if pos in positions:
                positions.remove(pos)

        # --- Phase 2: Process entries ---
        if len(positions) < max_pos and equity > 0:
            buys = []
            held_pairs = {p.pair for p in positions}

            for pair in coins:
                if pair in held_pairs:
                    continue
                ind = indicators.get(pair)
                if ind is None or bar >= ind["n"]:
                    continue

                # Cooldown
                cd = cooldown_after_stop if last_exit_was_stop.get(pair, False) else cooldown_bars
                if (bar - last_exit_bar.get(pair, -999)) < cd:
                    continue

                # Signal check
                candles = data.get(pair, [])
                sig = signal_fn(candles, bar, ind, params)
                if sig is not None:
                    buys.append((pair, sig.get("strength", 0.0), sig))

            # Rank by strength, fill available slots
            buys.sort(key=lambda x: x[1], reverse=True)
            open_slots = max_pos - len(positions)

            for pair, strength, sig in buys[:open_slots]:
                size_per_pos = equity / open_slots if open_slots > 0 else 0
                if size_per_pos <= 0:
                    break

                ind = indicators[pair]
                entry_price = ind["closes"][bar]
                if entry_price <= 0:
                    continue

                if exit_mode == "fixed":
                    # Sprint 1/2: use signal_fn's stop/target/time_limit directly
                    pos_stop_price = sig["stop_price"]
                    pos_target_price = sig["target_price"]
                    pos_time_limit = sig.get("time_limit", 20)
                    pos_max_stop_pct = 15.0  # unused in fixed mode
                else:
                    # DC mode: stop from max_stop_pct, target disabled, time from params
                    pos_max_stop_pct = dc_max_stop_pct
                    pos_stop_price = entry_price * (1 - pos_max_stop_pct / 100)
                    pos_target_price = float("inf")  # never triggers fixed TP
                    pos_time_limit = dc_time_max_bars

                positions.append(_Pos(
                    pair=pair,
                    entry_price=entry_price,
                    entry_bar=bar,
                    size_usd=size_per_pos,
                    stop_price=pos_stop_price,
                    target_price=pos_target_price,
                    time_limit=pos_time_limit,
                    max_stop_pct=pos_max_stop_pct,
                ))
                equity -= size_per_pos
                open_slots -= 1

        # --- Phase 3: Mark-to-market DD ---
        total_value = equity
        for pos in positions:
            ind = indicators.get(pos.pair)
            if ind and bar < ind["n"]:
                cur_price = ind["closes"][bar]
                unrealized = pos.size_usd * (cur_price / pos.entry_price - 1.0)
                total_value += pos.size_usd + unrealized

        if total_value > peak_equity:
            peak_equity = total_value
        if peak_equity > 0:
            dd_pct = (peak_equity - total_value) / peak_equity * 100
            if dd_pct > max_dd:
                max_dd = dd_pct

        if equity < 0:
            break

    # --- Close remaining positions at end ---
    for pos in positions:
        ind = indicators.get(pos.pair)
        if ind is None:
            continue
        last_bar = min(max_bars - 1, ind["n"] - 1)
        if last_bar < 0:
            continue
        close = ind["closes"][last_bar]
        bars_in = last_bar - pos.entry_bar

        gross = pos.size_usd * (close / pos.entry_price - 1.0)
        fees = pos.size_usd * fee + (pos.size_usd + gross) * fee
        net_pnl = gross - fees
        equity += pos.size_usd + net_pnl

        trade = {
            "pair": pos.pair,
            "entry": pos.entry_price,
            "exit": close,
            "pnl": net_pnl,
            "pnl_pct": net_pnl / pos.size_usd * 100 if pos.size_usd > 0 else 0.0,
            "reason": "END",
            "bars": bars_in,
            "entry_bar": pos.entry_bar,
            "exit_bar": last_bar,
            "size": pos.size_usd,
            "equity_after": equity,
        }
        trades.append(trade)

        cls = "B"
        reason = "END"
        if reason not in exit_classes[cls]:
            exit_classes[cls][reason] = {"count": 0, "pnl": 0.0, "wins": 0}
        exit_classes[cls][reason]["count"] += 1
        exit_classes[cls][reason]["pnl"] += net_pnl
        if net_pnl > 0:
            exit_classes[cls][reason]["wins"] += 1

    # --- Build result ---
    n_trades = len(trades)
    total_pnl = equity - initial_capital
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    sum_wins = sum(wins)
    sum_losses = abs(sum(losses))
    pf = sum_wins / sum_losses if sum_losses > 0 else (float("inf") if sum_wins > 0 else 0.0)
    wr = len(wins) / n_trades * 100 if n_trades > 0 else 0.0

    return BacktestResult(
        trades=n_trades,
        pnl=round(total_pnl, 2),
        pf=round(pf, 4),
        wr=round(wr, 2),
        dd=round(max_dd, 2),
        final_equity=round(equity, 2),
        broke=equity < 0,
        early_stopped=False,
        trade_list=trades,
        exit_classes=exit_classes,
    )

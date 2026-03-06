"""
Scalp Backtest Harness — Single-coin, zero-fee, spread-as-cost backtest engine.
================================================================================

Designed for 1-minute XRP/USDT scalping on MEXC (0% maker/taker fees).
Cost model: spread only (configurable bps per side).

Follows same patterns as strategies/hf/screening/harness.py but:
  - Single coin (no coin_list loop)
  - fee=0.0 (zero exchange fees)
  - Spread deducted from fill price on entry and exit
  - ATR-based TP/SL (not fixed %)

signal_fn protocol (identical to existing framework):
    signal_fn(candles, bar, indicators, params) → dict | None
    Return: {'stop_price', 'target_price', 'time_limit', 'strength'} or None

Usage:
    from strategies.scalp.harness import run_backtest, walk_forward
    result = run_backtest(candles, signal_fn, params, indicators, spread_bps=1.5)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class BacktestResult:
    """Backtest output — compatible with HF harness pattern."""
    pf: float = 0.0             # Profit Factor (gross wins / gross losses)
    trades: int = 0             # Total trades
    wr: float = 0.0             # Win rate %
    dd: float = 0.0             # Max drawdown %
    pnl: float = 0.0            # Net P&L in USD
    avg_hold: float = 0.0       # Average hold time in bars
    trades_per_day: float = 0.0 # Trades per calendar day
    trade_list: list = field(default_factory=list)  # [{pnl, bars_held, exit_type, ...}]


def run_backtest(
    candles: list[dict],
    signal_fn: Callable,
    params: dict,
    indicators: dict,
    spread_bps: float = 1.5,
    initial_capital: float = 2000.0,
    capital_per_trade: float = 200.0,
    max_positions: int = 1,
    start_bar: int = 50,
    end_bar: int | None = None,
    cooldown_bars: int = 2,
    cooldown_after_stop: int = 5,
    daily_loss_limit: float = -0.02,
) -> BacktestResult:
    """
    Run backtest on single-coin 1m candles with spread cost model.

    Args:
        candles: list of {time, open, high, low, close, volume} dicts
        signal_fn: (candles, bar, indicators, params) → dict|None
        params: entry parameters for signal_fn
        indicators: precomputed indicators dict (from precompute_fn)
        spread_bps: half-spread in basis points (applied on entry AND exit)
        initial_capital: starting equity
        capital_per_trade: USD per position
        max_positions: max simultaneous positions (typically 1)
        start_bar: first bar to evaluate signals
        end_bar: last bar (exclusive), None = len(candles)
        cooldown_bars: bars to wait after a trade
        cooldown_after_stop: bars to wait after a stop-loss
        daily_loss_limit: -0.02 = halt after -2% daily loss (0 = disabled)

    Returns:
        BacktestResult with metrics and trade list
    """
    n = len(candles)
    if end_bar is None:
        end_bar = n

    equity = initial_capital
    peak_equity = initial_capital
    max_dd = 0.0
    trade_list = []
    positions = []  # [{entry_price, entry_bar, stop_price, target_price, time_limit, size_usd}]
    cooldown_until = 0  # bar when cooldown expires

    # Daily loss tracking
    current_day = None
    daily_start_equity = equity

    spread_fraction = spread_bps / 10000.0  # e.g., 1.5 bps = 0.00015

    for bar in range(start_bar, end_bar):
        close = candles[bar]['close']
        high = candles[bar]['high']
        low = candles[bar]['low']

        if close <= 0:
            continue

        # Daily loss limit check
        bar_day = candles[bar]['time'] // 86400
        if bar_day != current_day:
            current_day = bar_day
            daily_start_equity = equity

        if daily_loss_limit < 0 and daily_start_equity > 0:
            daily_return = (equity - daily_start_equity) / daily_start_equity
            if daily_return <= daily_loss_limit:
                continue  # Skip this bar (daily loss limit hit)

        # ──── UPDATE TRAILING STOPS (before exit checks) ────
        for pos in positions:
            pos['highest_since_entry'] = max(pos.get('highest_since_entry', pos['entry_fill']), high)

            be_atr = pos.get('breakeven_atr')
            trail_atr = pos.get('trail_atr')
            if be_atr is None and trail_atr is None:
                continue  # No trailing stop configured

            # Get current ATR for this bar
            cur_atr = indicators.get('atr14', indicators.get('atr', [None] * (bar + 1)))[bar] if indicators else None
            if cur_atr is None or cur_atr <= 0:
                continue

            # Breakeven: move stop to entry after X ATR profit
            if be_atr and not pos.get('breakeven_hit', False):
                profit = pos['highest_since_entry'] - pos['entry_fill']
                if profit >= be_atr * cur_atr:
                    pos['stop_price'] = pos['entry_fill']
                    pos['breakeven_hit'] = True

            # Trail: after breakeven, trail stop at Y ATR below highest
            if pos.get('breakeven_hit', False) and trail_atr:
                trail_stop = pos['highest_since_entry'] - trail_atr * cur_atr
                if trail_stop > pos['stop_price']:
                    pos['stop_price'] = trail_stop

        # ──── EXIT LOGIC ────
        closed_positions = []
        for i, pos in enumerate(positions):
            exit_price = None
            exit_type = None
            bars_held = bar - pos['entry_bar']

            # Check stop loss (intra-bar: low touches stop)
            if pos['stop_price'] and low <= pos['stop_price']:
                exit_price = pos['stop_price']
                exit_type = 'TRAIL' if pos.get('breakeven_hit', False) else 'STOP'

            # Check target (intra-bar: high touches target)
            elif pos['target_price'] and high >= pos['target_price']:
                exit_price = pos['target_price']
                exit_type = 'TARGET'

            # Check time limit
            elif pos.get('time_limit') and bars_held >= pos['time_limit']:
                exit_price = close
                exit_type = 'TIME'

            if exit_price is not None:
                # Apply spread cost on exit
                fill_price = exit_price * (1 - spread_fraction)
                pnl = (fill_price - pos['entry_fill']) * pos['qty']

                equity += pnl
                peak_equity = max(peak_equity, equity)
                dd_pct = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
                max_dd = max(max_dd, dd_pct)

                trade_list.append({
                    'pnl': round(pnl, 4),
                    'bars_held': bars_held,
                    'exit_type': exit_type,
                    'entry_price': pos['entry_price'],
                    'exit_price': exit_price,
                    'entry_bar': pos['entry_bar'],
                    'exit_bar': bar,
                })

                closed_positions.append(i)

                # Set cooldown
                if exit_type == 'STOP':
                    cooldown_until = bar + cooldown_after_stop
                else:
                    cooldown_until = bar + cooldown_bars

        # Remove closed positions (reverse order to preserve indices)
        for i in sorted(closed_positions, reverse=True):
            positions.pop(i)

        # ──── ENTRY LOGIC ────
        if len(positions) >= max_positions:
            continue
        if bar < cooldown_until:
            continue
        if bar >= end_bar - 2:  # Don't enter in last 2 bars
            continue

        signal = signal_fn(candles, bar, indicators, params)
        if signal is None:
            continue

        # Entry fill: apply spread cost
        entry_price = close
        entry_fill = entry_price * (1 + spread_fraction)  # Buy at ask (higher)
        qty = capital_per_trade / entry_fill

        positions.append({
            'entry_price': entry_price,
            'entry_fill': entry_fill,
            'entry_bar': bar,
            'stop_price': signal.get('stop_price'),
            'target_price': signal.get('target_price'),
            'time_limit': signal.get('time_limit'),
            'qty': qty,
            'size_usd': capital_per_trade,
            # Trailing stop (opt-in: None = disabled, backward compatible)
            'breakeven_atr': signal.get('breakeven_atr'),
            'trail_atr': signal.get('trail_atr'),
            'highest_since_entry': entry_fill,
            'breakeven_hit': False,
        })

    # Force-close remaining positions at last bar
    if positions and end_bar <= n:
        last_close = candles[end_bar - 1]['close']
        for pos in positions:
            fill_price = last_close * (1 - spread_fraction)
            pnl = (fill_price - pos['entry_fill']) * pos['qty']
            equity += pnl
            bars_held = (end_bar - 1) - pos['entry_bar']
            trade_list.append({
                'pnl': round(pnl, 4),
                'bars_held': bars_held,
                'exit_type': 'FORCE_CLOSE',
                'entry_price': pos['entry_price'],
                'exit_price': last_close,
                'entry_bar': pos['entry_bar'],
                'exit_bar': end_bar - 1,
            })

    # ──── COMPUTE METRICS ────
    total_trades = len(trade_list)
    if total_trades == 0:
        return BacktestResult()

    wins = sum(1 for t in trade_list if t['pnl'] > 0)
    gross_wins = sum(t['pnl'] for t in trade_list if t['pnl'] > 0)
    gross_losses = abs(sum(t['pnl'] for t in trade_list if t['pnl'] <= 0))
    pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')
    wr = wins / total_trades * 100
    net_pnl = sum(t['pnl'] for t in trade_list)
    avg_hold = sum(t['bars_held'] for t in trade_list) / total_trades

    # Trades per day
    if total_trades > 0 and end_bar > start_bar:
        span_days = (candles[min(end_bar - 1, n - 1)]['time'] - candles[start_bar]['time']) / 86400
        trades_per_day = total_trades / span_days if span_days > 0 else 0
    else:
        trades_per_day = 0

    return BacktestResult(
        pf=round(pf, 3),
        trades=total_trades,
        wr=round(wr, 1),
        dd=round(max_dd, 1),
        pnl=round(net_pnl, 2),
        avg_hold=round(avg_hold, 1),
        trades_per_day=round(trades_per_day, 1),
        trade_list=trade_list,
    )


def walk_forward(
    candles: list[dict],
    signal_fn: Callable,
    params: dict,
    indicators: dict,
    n_folds: int = 5,
    embargo: int = 2,
    spread_bps: float = 1.5,
    initial_capital: float = 2000.0,
    capital_per_trade: float = 200.0,
    start_bar: int = 50,
    cooldown_bars: int = 2,
    cooldown_after_stop: int = 5,
    max_positions: int = 1,
    daily_loss_limit: float = -0.02,
) -> list[BacktestResult]:
    """
    Walk-forward validation: split data into n_folds, train on first k, test on k+1.
    Returns list of BacktestResult (one per out-of-sample fold).
    """
    n = len(candles)
    usable = n - start_bar
    fold_size = usable // n_folds

    results = []
    for fold in range(n_folds):
        oos_start = start_bar + fold * fold_size
        oos_end = oos_start + fold_size if fold < n_folds - 1 else n

        # Add embargo gap
        oos_start_actual = oos_start + embargo

        if oos_start_actual >= oos_end:
            continue

        r = run_backtest(
            candles=candles,
            signal_fn=signal_fn,
            params=params,
            indicators=indicators,
            spread_bps=spread_bps,
            initial_capital=initial_capital,
            capital_per_trade=capital_per_trade,
            max_positions=max_positions,
            start_bar=oos_start_actual,
            end_bar=oos_end,
            cooldown_bars=cooldown_bars,
            cooldown_after_stop=cooldown_after_stop,
            daily_loss_limit=daily_loss_limit,
        )
        results.append(r)

    return results

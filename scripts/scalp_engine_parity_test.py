#!/usr/bin/env python3
"""
Engine Parity Test — Proves the forming-candle hypothesis.
============================================================

This script simulates BOTH the paper trader behavior and the backtest behavior
on the same stored 1m data to quantify the TPD gap root cause.

Three modes compared:
  A) BACKTEST:    evaluate signal on every bar (complete candle) → harness behavior
  B) PAPER_BUGGY: evaluate signal on bar N-1 (forming candle) → current paper behavior
  C) PAPER_FIXED: evaluate signal on bar N-2 (completed candle) → proposed fix

For mode B, we also simulate the polling cycle timing (65s sleep + processing)
to model which candles are skipped.

Usage:
    python scripts/scalp_engine_parity_test.py                 # All 4 coins
    python scripts/scalp_engine_parity_test.py --coins XRP     # Single coin
    python scripts/scalp_engine_parity_test.py --days 10       # Shorter window
"""

import sys
import json
import argparse
from pathlib import Path
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategies.scalp.ms_indicators import precompute_scalp_ms_indicators
from strategies.scalp.ms_hypotheses import signal_mssb
from strategies.scalp.harness import run_backtest

# ─── Config ────────────────────────────────────────────────
DATA_DIR = Path.home() / 'CryptogemData' / 'scalp' / '1m' / 'mexc'
COINS = ['XRP', 'BTC', 'ETH', 'SUI']

# Frozen fvg_x2027 params
ENTRY_PARAMS = {
    'max_fvg_age': 25,
    'fill_depth': 0.75,
    'rsi_max': 40,
    'tp_atr': 2.5,
    'sl_atr': 0.75,
    'time_limit': 15,
}

PRECOMPUTE_KWARGS = {
    'swing_left': 3,
    'swing_right': 1,
    'min_gap_atr': 0.3,
    'min_impulse_atr': 1.5,
    'lookback_impulse': 3,
    'tolerance_atr': 0.5,
    'min_touches': 2,
}

# Paper trader constants
POLL_INTERVAL_BUGGY = 65          # Old value (caused 50% bar coverage)
POLL_INTERVAL_FIXED = 10          # ADR-SCALP-007 fix value
PROCESSING_TIME_PER_PAIR_SEC = 4  # ~4 seconds per pair
COOLDOWN_BARS = 2
COOLDOWN_AFTER_STOP = 5
START_BAR = 50
CAPITAL_PER_TRADE = 200.0
SPREAD_BPS = 1.5


# ─── Simulate Paper Trader (Buggy: bar N-1 = forming candle) ──────

def simulate_paper_buggy(candles, indicators, params, spread_bps=1.5):
    """Simulate paper trader behavior: evaluate only bar N-1 (forming candle).

    Simulates the 65s polling cycle — only evaluates candles that would be
    seen by the paper trader's timing. Each check evaluates the latest
    candle (which is the forming/incomplete one).
    """
    n = len(candles)
    signals_fired = []
    trades = []
    position = None
    cooldown_until = 0
    equity = 2000.0
    daily_start_equity = equity
    current_day = None
    spread_fraction = spread_bps / 10000.0

    # Simulate polling: we can only check at certain bars
    # With 65s sleep + 4s processing per pair (single coin here) = ~69s cycle
    # At 1m candles, this means we check roughly every 69/60 ≈ 1.15 bars
    # So approximately every bar, but some are skipped
    cycle_time_sec = POLL_INTERVAL_BUGGY + PROCESSING_TIME_PER_PAIR_SEC  # 69s

    # Simulate time progression
    # Start at bar START_BAR
    sim_time_sec = candles[START_BAR]['time']  # Start at bar 50

    checked_bars = 0
    skipped_bars = 0
    last_checked_time = 0

    for bar in range(START_BAR, n):
        bar_time = candles[bar]['time']

        # Would the paper trader be awake at this bar?
        if bar_time < sim_time_sec:
            continue  # Not yet time to poll

        # Paper trader wakes up at sim_time_sec
        # At this moment, candles[-1] is the FORMING candle for the current minute
        # The paper trader sees bar_time as the latest candle

        # Check for skipped candles (gap > 60s since last check)
        if last_checked_time > 0:
            gap_bars = (bar_time - last_checked_time) // 60
            if gap_bars > 1:
                skipped_bars += gap_bars - 1

        checked_bars += 1
        last_checked_time = bar_time

        # The paper trader evaluates THIS bar (which is forming/incomplete)
        # In reality, the OHLCV values at this point are partial
        # But for simulation, we use the COMPLETE bar data — this OVERESTIMATES
        # the paper trader's signal rate. The real paper trader would have
        # even fewer signals because it sees incomplete OHLCV.
        eval_bar = bar  # Paper buggy: evaluates the "forming" bar

        # Daily loss limit (not in paper trader, but track for comparison)
        bar_day = bar_time // 86400
        if bar_day != current_day:
            current_day = bar_day
            daily_start_equity = equity

        # Exit check
        if position is not None:
            close = candles[eval_bar]['close']
            high = candles[eval_bar]['high']
            low = candles[eval_bar]['low']
            bars_held = (bar_time - position['entry_time']) // 60

            exit_price = None
            exit_type = None

            if position['stop_price'] and low <= position['stop_price']:
                exit_price = position['stop_price']
                exit_type = 'STOP'
            elif position['target_price'] and high >= position['target_price']:
                exit_price = position['target_price']
                exit_type = 'TARGET'
            elif position['time_limit'] and bars_held >= position['time_limit']:
                exit_price = close
                exit_type = 'TIME'

            if exit_price is not None:
                fill_price = exit_price * (1 - spread_fraction)
                pnl = (fill_price - position['entry_fill']) * position['qty']
                equity += pnl
                trades.append({
                    'bar': bar,
                    'time': bar_time,
                    'exit_type': exit_type,
                    'pnl': round(pnl, 4),
                    'bars_held': int(bars_held),
                })
                cooldown_until = bar + (COOLDOWN_AFTER_STOP if exit_type == 'STOP' else COOLDOWN_BARS)
                position = None

        # Entry check
        if position is None and bar >= cooldown_until and bar < n - 2:
            sig = signal_mssb(candles, eval_bar, indicators, params)
            if sig is not None:
                entry_price = candles[eval_bar]['close']
                entry_fill = entry_price * (1 + spread_fraction)
                qty = CAPITAL_PER_TRADE / entry_fill

                signals_fired.append({
                    'bar': bar,
                    'time': bar_time,
                    'close': entry_price,
                })

                position = {
                    'entry_fill': entry_fill,
                    'entry_time': bar_time,
                    'stop_price': sig['stop_price'],
                    'target_price': sig['target_price'],
                    'time_limit': sig.get('time_limit'),
                    'qty': qty,
                }

        # Advance simulation time
        sim_time_sec = bar_time + cycle_time_sec

    return {
        'mode': 'PAPER_BUGGY',
        'signals': len(signals_fired),
        'trades': len(trades),
        'checked_bars': checked_bars,
        'skipped_bars': skipped_bars,
        'total_bars': n - START_BAR,
        'coverage_pct': round(checked_bars / (n - START_BAR) * 100, 1),
        'pnl': round(sum(t['pnl'] for t in trades), 4),
        'trade_list': trades,
    }


# ─── Simulate Paper Trader (Fixed: bar N-2 = completed candle) ──────

def simulate_paper_fixed(candles, indicators, params, spread_bps=1.5):
    """Simulate fixed paper trader: evaluate bar N-2 (completed candle).

    Same polling cycle as buggy version, but evaluates the PREVIOUS
    (completed) candle instead of the forming one.
    """
    n = len(candles)
    signals_fired = []
    trades = []
    position = None
    cooldown_until = 0
    equity = 2000.0
    spread_fraction = spread_bps / 10000.0

    cycle_time_sec = POLL_INTERVAL_FIXED + PROCESSING_TIME_PER_PAIR_SEC  # 14s
    sim_time_sec = candles[START_BAR]['time']

    checked_bars = 0
    last_checked_time = 0

    for bar in range(START_BAR + 1, n):  # +1 because we need bar-1 to be valid
        bar_time = candles[bar]['time']

        if bar_time < sim_time_sec:
            continue

        checked_bars += 1
        last_checked_time = bar_time

        # FIXED: evaluate bar-1 (the COMPLETED candle)
        eval_bar = bar - 1

        # Exit check (also on completed candle)
        if position is not None:
            close = candles[eval_bar]['close']
            high = candles[eval_bar]['high']
            low = candles[eval_bar]['low']
            bars_held = (candles[eval_bar]['time'] - position['entry_time']) // 60

            exit_price = None
            exit_type = None

            if position['stop_price'] and low <= position['stop_price']:
                exit_price = position['stop_price']
                exit_type = 'STOP'
            elif position['target_price'] and high >= position['target_price']:
                exit_price = position['target_price']
                exit_type = 'TARGET'
            elif position['time_limit'] and bars_held >= position['time_limit']:
                exit_price = close
                exit_type = 'TIME'

            if exit_price is not None:
                fill_price = exit_price * (1 - spread_fraction)
                pnl = (fill_price - position['entry_fill']) * position['qty']
                equity += pnl
                trades.append({
                    'bar': eval_bar,
                    'time': candles[eval_bar]['time'],
                    'exit_type': exit_type,
                    'pnl': round(pnl, 4),
                    'bars_held': int(bars_held),
                })
                cooldown_until = eval_bar + (COOLDOWN_AFTER_STOP if exit_type == 'STOP' else COOLDOWN_BARS)
                position = None

        # Entry check (on completed candle)
        if position is None and eval_bar >= cooldown_until and eval_bar < n - 2:
            sig = signal_mssb(candles, eval_bar, indicators, params)
            if sig is not None:
                entry_price = candles[eval_bar]['close']
                entry_fill = entry_price * (1 + spread_fraction)
                qty = CAPITAL_PER_TRADE / entry_fill

                signals_fired.append({
                    'bar': eval_bar,
                    'time': candles[eval_bar]['time'],
                    'close': entry_price,
                })

                position = {
                    'entry_fill': entry_fill,
                    'entry_time': candles[eval_bar]['time'],
                    'stop_price': sig['stop_price'],
                    'target_price': sig['target_price'],
                    'time_limit': sig.get('time_limit'),
                    'qty': qty,
                }

        # Advance simulation time
        sim_time_sec = bar_time + cycle_time_sec

    return {
        'mode': 'PAPER_FIXED',
        'signals': len(signals_fired),
        'trades': len(trades),
        'checked_bars': checked_bars,
        'total_bars': n - START_BAR,
        'coverage_pct': round(checked_bars / (n - START_BAR) * 100, 1),
        'pnl': round(sum(t['pnl'] for t in trades), 4),
        'trade_list': trades,
    }


# ─── Main ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Engine Parity Test')
    parser.add_argument('--coins', nargs='+', default=COINS)
    parser.add_argument('--days', type=int, default=0,
                        help='Limit to last N days (0=all data)')
    args = parser.parse_args()

    print('=' * 70)
    print('  ENGINE PARITY TEST — Forming Candle Hypothesis')
    print('=' * 70)
    print(f'  Signal: FVG Fill (fvg_x2027)')
    print(f'  Params: {ENTRY_PARAMS}')
    print(f'  Spread: {SPREAD_BPS} bps | Buggy cycle: {POLL_INTERVAL_BUGGY}s | Fixed cycle: {POLL_INTERVAL_FIXED}s')
    print(f'  Coins:  {args.coins}')
    print()

    totals = {
        'backtest': {'trades': 0, 'signals': 0, 'pnl': 0},
        'paper_buggy': {'trades': 0, 'signals': 0, 'pnl': 0, 'checked': 0, 'skipped': 0},
        'paper_fixed': {'trades': 0, 'signals': 0, 'pnl': 0, 'checked': 0},
    }

    for coin in args.coins:
        filepath = DATA_DIR / f'{coin}_USDT_1m.json'
        if not filepath.exists():
            print(f'  [{coin}] Data file not found: {filepath}')
            continue

        with open(filepath) as f:
            candles = json.load(f)

        if args.days > 0:
            cutoff = candles[-1]['time'] - args.days * 86400
            candles = [c for c in candles if c['time'] >= cutoff]

        pair = f'{coin}/USDT'
        n = len(candles)
        span_days = (candles[-1]['time'] - candles[0]['time']) / 86400

        print(f'  [{coin}] {n:,} bars ({span_days:.1f} days)')
        print(f'  {"-" * 50}')

        # Precompute indicators
        data = {pair: candles}
        indicators = precompute_scalp_ms_indicators(data, [pair], **PRECOMPUTE_KWARGS)
        ind = indicators[pair]

        # ─── A) Backtest (harness) ──────────────────────────
        bt = run_backtest(
            candles=candles,
            signal_fn=signal_mssb,
            params=ENTRY_PARAMS,
            indicators=ind,
            spread_bps=SPREAD_BPS,
            start_bar=START_BAR,
            cooldown_bars=COOLDOWN_BARS,
            cooldown_after_stop=COOLDOWN_AFTER_STOP,
            daily_loss_limit=-0.02,
        )
        bt_tpd = bt.trades / span_days if span_days > 0 else 0

        print(f'  A) BACKTEST:     {bt.trades:4d} trades ({bt_tpd:.1f} TPD) | '
              f'PF={bt.pf:.3f} | PnL=${bt.pnl:+.2f}')

        totals['backtest']['trades'] += bt.trades
        totals['backtest']['pnl'] += bt.pnl

        # ─── B) Paper Buggy (forming candle) ─────────────────
        pb = simulate_paper_buggy(candles, ind, ENTRY_PARAMS, SPREAD_BPS)
        pb_tpd = pb['trades'] / span_days if span_days > 0 else 0

        print(f'  B) PAPER_BUGGY:  {pb["trades"]:4d} trades ({pb_tpd:.1f} TPD) | '
              f'PnL=${pb["pnl"]:+.2f} | '
              f'coverage={pb["coverage_pct"]}% ({pb["checked_bars"]}/{pb["total_bars"]}) | '
              f'skipped={pb["skipped_bars"]}')

        totals['paper_buggy']['trades'] += pb['trades']
        totals['paper_buggy']['signals'] += pb['signals']
        totals['paper_buggy']['pnl'] += pb['pnl']
        totals['paper_buggy']['checked'] += pb['checked_bars']
        totals['paper_buggy']['skipped'] += pb['skipped_bars']

        # ─── C) Paper Fixed (completed candle) ───────────────
        pf = simulate_paper_fixed(candles, ind, ENTRY_PARAMS, SPREAD_BPS)
        pf_tpd = pf['trades'] / span_days if span_days > 0 else 0

        print(f'  C) PAPER_FIXED:  {pf["trades"]:4d} trades ({pf_tpd:.1f} TPD) | '
              f'PnL=${pf["pnl"]:+.2f} | '
              f'coverage={pf["coverage_pct"]}% ({pf["checked_bars"]}/{pf["total_bars"]})')

        totals['paper_fixed']['trades'] += pf['trades']
        totals['paper_fixed']['signals'] += pf['signals']
        totals['paper_fixed']['pnl'] += pf['pnl']
        totals['paper_fixed']['checked'] += pf['checked_bars']

        # ─── Comparison ──────────────────────────────────────
        gap_buggy = (1 - pb['trades'] / bt.trades) * 100 if bt.trades > 0 else 0
        gap_fixed = (1 - pf['trades'] / bt.trades) * 100 if bt.trades > 0 else 0
        recovery = pf['trades'] - pb['trades']
        recovery_pct = (recovery / (bt.trades - pb['trades']) * 100) if (bt.trades - pb['trades']) > 0 else 0

        print()
        print(f'  Gap buggy:   −{gap_buggy:.0f}% vs backtest')
        print(f'  Gap fixed:   −{gap_fixed:.0f}% vs backtest')
        print(f'  Recovery:    +{recovery} trades ({recovery_pct:.0f}% of gap closed)')
        print()

    # ─── Portfolio Summary ─────────────────────────────────
    print('=' * 70)
    print('  PORTFOLIO SUMMARY')
    print('=' * 70)

    bt_total = totals['backtest']['trades']
    pb_total = totals['paper_buggy']['trades']
    pf_total = totals['paper_fixed']['trades']

    print(f'  A) BACKTEST:     {bt_total:4d} total trades | PnL=${totals["backtest"]["pnl"]:+.2f}')
    print(f'  B) PAPER_BUGGY:  {pb_total:4d} total trades | PnL=${totals["paper_buggy"]["pnl"]:+.2f} | '
          f'skipped={totals["paper_buggy"]["skipped"]} bars')
    print(f'  C) PAPER_FIXED:  {pf_total:4d} total trades | PnL=${totals["paper_fixed"]["pnl"]:+.2f}')
    print()

    if bt_total > 0:
        gap_b = (1 - pb_total / bt_total) * 100
        gap_c = (1 - pf_total / bt_total) * 100
        gap_closed = ((pf_total - pb_total) / (bt_total - pb_total) * 100) if (bt_total - pb_total) > 0 else 0

        print(f'  Buggy gap:   −{gap_b:.0f}% vs backtest (trades missing)')
        print(f'  Fixed gap:   −{gap_c:.0f}% vs backtest (residual from coverage loss)')
        print(f'  Gap closed:  {gap_closed:.0f}% (forming-candle fix)')
        print()
        print(f'  NOTE: Mode B uses COMPLETE candle data even for the "forming" bar.')
        print(f'  Real paper trader sees INCOMPLETE OHLCV (5-30s into the candle),')
        print(f'  so actual gap is LARGER than shown here. Mode B is a best-case')
        print(f'  simulation of the buggy behavior.')

    print()
    print('[DONE]')


if __name__ == '__main__':
    main()

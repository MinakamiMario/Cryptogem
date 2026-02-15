#!/usr/bin/env python3
"""
DEBUG SCRIPT: Why does overnight_optimizer get 1 trade for V5+VolSpk3
while mega_vergelijk gets 39?

ROOT CAUSE FOUND:
=================
overnight_optimizer.py line ~153: `if equity <= 0: broke = True; break`

When a trade is entered, equity -= size_per_pos makes equity = $0.00.
On the NEXT bar, `0.0 <= 0` is True, so the loop BREAKS immediately.
The position is never evaluated for exit conditions.

FIX: Change `if equity <= 0` to `if equity < 0` (or better: track
free cash separately from invested capital).
"""
import sys
import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from backtest_mega_vergelijk import (
    precompute_all, run_backtest, CONFIGS, CACHE_FILE, START_BAR
)

INITIAL_CAPITAL = 2000
KRAKEN_FEE = 0.0026
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8


def main():
    print("=" * 100)
    print("DEBUG: Mega_vergelijk (39 trades) vs Overnight_optimizer (1 trade)")
    print("=" * 100)

    # Load data
    print("\nLaden candle_cache_532.json...")
    with open(CACHE_FILE) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith('_')])
    print(f"Geladen: {len(coins)} coins")

    # Precompute indicators
    indicators = precompute_all(data, coins)

    # ================================================================
    # STAP 1: Mega_vergelijk's trades (fixed $2000)
    # ================================================================
    print("\n" + "=" * 100)
    print("STAP 1: Mega_vergelijk run_backtest (fixed $2000 per trade)")
    print("=" * 100)

    result = run_backtest(indicators, coins, 'v5_volspk3')
    trades = sorted(result['trade_list'], key=lambda t: t['entry_bar'])

    print(f"\nTotaal trades: {len(trades)}")
    print(f"P&L: ${result['pnl']:+.2f}")
    print(f"\n{'#':>3} {'Pair':<15} {'Entry':>6} {'Exit':>6} {'Bars':>5} {'Reason':<15} {'PnL':>10}")
    print("-" * 70)
    for i, t in enumerate(trades):
        print(f"{i+1:>3} {t['pair']:<15} {t['entry_bar']:>6} {t['exit_bar']:>6} "
              f"{t['bars']:>5} {t['reason']:<15} ${t['pnl']:>+9.2f}")

    # ================================================================
    # STAP 2: Overnight_optimizer's realistic backtest
    # ================================================================
    print("\n" + "=" * 100)
    print("STAP 2: Overnight_optimizer run_backtest_realistic")
    print("=" * 100)

    from overnight_optimizer import run_backtest_realistic

    v5_cfg = {
        'exit_type': 'trail', 'rsi_max': 40, 'atr_mult': 2.0,
        'vol_spike_mult': 3.0, 'vol_confirm': True,
        'breakeven': True, 'be_trigger': 3.0,
        'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
        'max_stop_pct': 15.0, 'max_pos': 1,
    }

    result_r = run_backtest_realistic(indicators, coins, v5_cfg)
    trades_r = result_r['trade_list']

    print(f"\nTrades: {result_r['trades']}")
    print(f"P&L: ${result_r['pnl']:+.2f}")
    print(f"Final equity: ${result_r['final_equity']:.2f}")
    print(f"Broke: {result_r['broke']}")
    if trades_r:
        for t in trades_r:
            print(f"  {t['pair']}: entry={t['entry_bar']}, exit={t['exit_bar']}, "
                  f"bars={t['bars']}, reason={t['reason']}, pnl=${t['pnl']:+.2f}")

    # ================================================================
    # STAP 3: ROOT CAUSE DEMONSTRATION
    # ================================================================
    print("\n" + "=" * 100)
    print("STAP 3: ROOT CAUSE DEMONSTRATION")
    print("=" * 100)

    print(f"""
    overnight_optimizer.py has this logic:

        for bar in range(start_bar, max_bars):
            if equity <= 0:       # <--- THE BUG
                broke = True
                break

    When you enter a trade:
        equity -= size_per_pos    # equity becomes $0.00

    Next bar:
        if equity <= 0:           # 0.0 <= 0 is TRUE!
            broke = True
            break                 # LOOP EXITS IMMEDIATELY

    The position is NEVER evaluated for exit conditions.
    It gets force-closed by the "close remaining" logic at max_bars.
    """)

    # Demonstrate
    print("Python proof:")
    equity = 2000.0
    print(f"  Start: equity = ${equity:.2f}")
    equity -= 2000.0
    print(f"  After entry (equity -= 2000): equity = ${equity:.2f}")
    print(f"  equity <= 0: {equity <= 0}  <-- THIS IS THE BUG!")
    print(f"  equity < 0:  {equity < 0}   <-- This would be correct")

    # ================================================================
    # STAP 4: VERIFY FIX — run with `equity < 0` instead
    # ================================================================
    print("\n" + "=" * 100)
    print("STAP 4: VERIFY FIX — run with `equity < 0` (strictly less than)")
    print("=" * 100)

    from overnight_optimizer import Pos as OPos
    from overnight_optimizer import check_entry_at_bar

    exit_type = v5_cfg['exit_type']
    max_pos = v5_cfg.get('max_pos', 1)
    coin_list = [c for c in coins if c in indicators]
    max_bars = max(indicators[p]['n'] for p in coin_list)

    positions = {}
    trades_fixed = []
    equity = float(INITIAL_CAPITAL)
    peak_eq = equity
    max_dd = 0
    last_exit_bar = {p: -999 for p in coin_list}
    last_exit_was_stop = {p: False for p in coin_list}

    for bar in range(START_BAR, max_bars):
        if equity < 0:  # FIX: strictly less than
            break

        sells = []

        # EXIT CHECK (exact copy from overnight_optimizer)
        for pair in list(positions.keys()):
            pos = positions[pair]
            ind = indicators[pair]
            if bar >= ind['n'] or ind['rsi'][bar] is None:
                continue

            entry_price = pos.entry_price
            bars_in = bar - pos.entry_bar
            close = ind['closes'][bar]
            low = ind['lows'][bar]
            high = ind['highs'][bar]
            rsi = ind['rsi'][bar]
            atr = ind['atr'][bar]
            exit_price = None
            reason = None

            if exit_type == 'trail':
                atr_mult = v5_cfg.get('atr_mult', 2.0)
                max_stop_pct = v5_cfg.get('max_stop_pct', 15.0)
                tm_bars = v5_cfg.get('time_max_bars', 10)
                if close > pos.highest_price:
                    pos.highest_price = close
                new_stop = pos.highest_price - atr * atr_mult
                hard_stop = entry_price * (1 - max_stop_pct / 100)
                if new_stop < hard_stop:
                    new_stop = hard_stop
                if v5_cfg.get('breakeven', False):
                    pnl_pct = (close - entry_price) / entry_price * 100
                    if pnl_pct >= v5_cfg.get('be_trigger', 3.0):
                        be_level = entry_price * (1 + KRAKEN_FEE * 2)
                        if new_stop < be_level:
                            new_stop = be_level
                if new_stop > pos.stop_price:
                    pos.stop_price = new_stop

                if close < hard_stop:
                    exit_price, reason = close, 'HARD STOP'
                elif tm_bars < 999 and bars_in >= tm_bars:
                    exit_price, reason = close, 'TIME MAX'
                elif (v5_cfg.get('rsi_recovery', False)
                      and bars_in >= 2
                      and rsi >= v5_cfg.get('rsi_rec_target', 45)):
                    exit_price, reason = close, 'RSI RECOVERY'
                elif close >= ind['dc_mid'][bar]:
                    exit_price, reason = close, 'DC TARGET'
                elif close >= ind['bb_mid'][bar]:
                    exit_price, reason = close, 'BB TARGET'
                elif close < pos.stop_price:
                    exit_price, reason = close, 'TRAIL STOP'

            if exit_price is not None:
                sells.append((pair, exit_price, reason, pos))

        for pair, exit_price, reason, pos in sells:
            gross = (exit_price - pos.entry_price) / pos.entry_price * pos.size_usd
            fees = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
            net = gross - fees
            equity += pos.size_usd + net
            last_exit_bar[pair] = bar
            last_exit_was_stop[pair] = 'STOP' in reason
            trades_fixed.append({
                'pair': pair, 'entry': pos.entry_price, 'exit': exit_price,
                'pnl': net, 'reason': reason, 'bars': bar - pos.entry_bar,
                'entry_bar': pos.entry_bar, 'exit_bar': bar,
                'size': pos.size_usd, 'equity_after': equity,
            })
            del positions[pair]

        # ENTRY CHECK
        buys = []
        for pair in coin_list:
            if pair in positions:
                continue
            ind = indicators[pair]
            if bar >= ind['n']:
                continue
            cd = COOLDOWN_AFTER_STOP if last_exit_was_stop.get(pair, False) else COOLDOWN_BARS
            if (bar - last_exit_bar.get(pair, -999)) < cd:
                continue
            ok, vol_ratio = check_entry_at_bar(ind, bar, v5_cfg)
            if ok:
                buys.append((pair, vol_ratio))

        invested = sum(p.size_usd for p in positions.values())
        available = equity - invested

        if len(positions) < max_pos and buys and available > 10:
            buys.sort(key=lambda x: x[1], reverse=True)
            slots = max_pos - len(positions)
            size_per_pos = available / slots
            for pair, vol_ratio in buys:
                if len(positions) >= max_pos:
                    break
                if size_per_pos < 10:
                    break
                ind = indicators[pair]
                ep = ind['closes'][bar]
                atr_val = ind['atr'][bar] or 0
                stop = ep - atr_val * v5_cfg.get('atr_mult', 2.0)
                hard = ep * (1 - v5_cfg.get('max_stop_pct', 15.0) / 100)
                if stop < hard:
                    stop = hard
                equity -= size_per_pos
                positions[pair] = OPos(pair=pair, entry_price=ep, entry_bar=bar,
                                       size_usd=size_per_pos, stop_price=stop, highest_price=ep)

        if equity + invested > peak_eq:
            peak_eq = equity + invested
        dd = (peak_eq - (equity + invested)) / peak_eq * 100 if peak_eq > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Close remaining
    for pair, pos in list(positions.items()):
        ind = indicators[pair]
        last_idx = min(ind['n'] - 1, max_bars - 1)
        lp = ind['closes'][last_idx]
        gross = (lp - pos.entry_price) / pos.entry_price * pos.size_usd
        fees = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
        net = gross - fees
        equity += pos.size_usd + net
        trades_fixed.append({
            'pair': pair, 'entry': pos.entry_price, 'exit': lp,
            'pnl': net, 'reason': 'END', 'bars': max_bars - pos.entry_bar,
            'entry_bar': pos.entry_bar, 'exit_bar': max_bars,
            'size': pos.size_usd, 'equity_after': equity,
        })

    trades_fixed_sorted = sorted(trades_fixed, key=lambda t: t['entry_bar'])

    print(f"\nFIXED trades: {len(trades_fixed)}")
    print(f"Final equity: ${equity:.2f}")
    total_pnl = equity - INITIAL_CAPITAL
    wins = [t for t in trades_fixed if t['pnl'] > 0]
    print(f"P&L: ${total_pnl:+.2f}")
    print(f"Win rate: {len(wins)/len(trades_fixed)*100:.1f}%" if trades_fixed else "N/A")

    print(f"\n{'#':>3} {'Pair':<15} {'Entry':>6} {'Exit':>6} {'Bars':>5} "
          f"{'Reason':<15} {'Size':>8} {'PnL':>10} {'Equity':>10}")
    print("-" * 95)
    for i, t in enumerate(trades_fixed_sorted):
        print(f"{i+1:>3} {t['pair']:<15} {t['entry_bar']:>6} {t['exit_bar']:>6} "
              f"{t['bars']:>5} {t['reason']:<15} ${t['size']:>7.0f} "
              f"${t['pnl']:>+9.2f} ${t['equity_after']:>9.2f}")

    # ================================================================
    # STAP 5: Comparison
    # ================================================================
    print("\n" + "=" * 100)
    print("STAP 5: VERGELIJKING")
    print("=" * 100)

    print(f"""
    Mega_vergelijk (non-realistic):  {len(trades)} trades, P&L ${result['pnl']:+.2f}
    Overnight (BUGGY, equity<=0):    {result_r['trades']} trade,  P&L ${result_r['pnl']:+.2f}
    Overnight (FIXED, equity<0):     {len(trades_fixed)} trades, P&L ${total_pnl:+.2f}

    ROOT CAUSE:
    overnight_optimizer.py line ~153: `if equity <= 0:`
    Should be: `if equity < 0:` (or track invested vs free cash properly)

    When max_pos=1 and you invest 100% of equity:
    - equity -= size_per_pos -> equity = $0.00
    - Next bar: `if equity <= 0:` -> True -> BREAK!
    - Position never evaluated for exit
    - Force-closed at END with massive loss
    """)


if __name__ == '__main__':
    main()

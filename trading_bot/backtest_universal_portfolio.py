"""
Portfolio Simulatie Bear Bounce Universal (3 modes)
====================================================
Realistische test met:
  - Max N posities tegelijk
  - Budget van $2,000
  - "First come first served" selectie (geen ranking)
  - 0.1% commissie per side
  - Chronologische event-based simulatie over ALLE coins tegelijk

Test scenario's per mode:
  A) 3 × $600  (max 3 posities, $600 per trade)
  B) 5 × $400  (max 5 posities, $400 per trade)
  C) 4 × $500  (max 4 posities, $500 per trade)
"""
import json
import os
import time
from datetime import datetime, timedelta

# === STRATEGY PARAMETERS (matching PineScript) ===
DONCHIAN_PERIOD = 20
RSI_DONCHIAN_MAX = 35
BB_PERIOD = 20
BB_DEV = 2.0
RSI_BUY_BB = 30
RSI_SELL_BB = 70
RSI_PERIOD = 14
ATR_PERIOD = 14
ATR_STOP_MULT = 2.0
COOLDOWN_BARS = 4
COMMISSION_PCT = 0.1


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_atr(highs, lows, closes, period=14):
    if len(highs) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return sum(trs[-period:]) / period


def calc_donchian(highs, lows, period=20):
    if len(highs) < period:
        return None, None, None
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    mid = (hh + ll) / 2
    return hh, ll, mid


def calc_bollinger(closes, period=20, dev=2.0):
    if len(closes) < period:
        return None, None, None
    recent = closes[-period:]
    mid = sum(recent) / period
    variance = sum((x - mid) ** 2 for x in recent) / period
    std = variance ** 0.5
    upper = mid + dev * std
    lower = mid - dev * std
    return mid, upper, lower


def extract_all_signals(all_candles, mode="Donchian Bounce"):
    """
    Extract alle entry en exit signalen per coin, chronologisch.
    Simuleert per-coin (als onbeperkt kapitaal) om alle mogelijke
    entry/exit momenten te vinden.
    """
    all_events = []
    min_bars = max(DONCHIAN_PERIOD, BB_PERIOD, RSI_PERIOD, ATR_PERIOD) + 5

    for pair, candles in all_candles.items():
        if len(candles) < min_bars:
            continue

        last_exit_bar = -999
        position = None
        start_bar = max(DONCHIAN_PERIOD, BB_PERIOD, RSI_PERIOD, ATR_PERIOD) + 2

        for i in range(start_bar, len(candles)):
            window = candles[:i + 1]
            closes = [c['close'] for c in window]
            highs = [c['high'] for c in window]
            lows = [c['low'] for c in window]

            rsi = calc_rsi(closes, RSI_PERIOD)
            atr = calc_atr(highs, lows, closes, ATR_PERIOD)

            # Donchian
            prev_highs = highs[:-1]
            prev_lows = lows[:-1]
            _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows, DONCHIAN_PERIOD)
            hh, ll, mid_channel = calc_donchian(highs, lows, DONCHIAN_PERIOD)

            # Bollinger
            bb_mid, bb_upper, bb_lower = calc_bollinger(closes, BB_PERIOD, BB_DEV)

            current = window[-1]
            prev_candle = window[-2]

            if position is None:
                in_cooldown = (i - last_exit_bar) < COOLDOWN_BARS
                if in_cooldown:
                    continue

                # Entry signals
                donchian_signal = (
                    prev_lowest is not None and
                    current['low'] <= prev_lowest and
                    rsi < RSI_DONCHIAN_MAX and
                    current['close'] > prev_candle['close']
                )
                bb_signal = (
                    bb_lower is not None and
                    current['close'] <= bb_lower and
                    rsi < RSI_BUY_BB and
                    current['close'] > prev_candle['close']
                )

                if mode == "Donchian Bounce":
                    long_entry = donchian_signal
                elif mode == "BB Mean Reversion":
                    long_entry = bb_signal
                else:
                    long_entry = donchian_signal and bb_signal

                if long_entry:
                    stop = current['close'] - atr * ATR_STOP_MULT
                    all_events.append({
                        'time': current['time'],
                        'pair': pair,
                        'type': 'ENTRY',
                        'price': current['close'],
                        'stop': stop,
                        'target_dc': mid_channel,
                        'target_bb': bb_mid,
                        'rsi': rsi,
                        'atr': atr,
                        'bar_idx': i,
                    })
                    position = {
                        'entry_price': current['close'],
                        'stop_price': stop,
                        'highest_price': current['close'],
                        'entry_bar': i,
                    }
            else:
                # Update trailing stop
                if current['close'] > position['highest_price']:
                    position['highest_price'] = current['close']
                new_stop = position['highest_price'] - atr * ATR_STOP_MULT
                if new_stop > position['stop_price']:
                    position['stop_price'] = new_stop

                exit_type = None

                # Target based on mode
                if mode == "Donchian Bounce":
                    hit_target = mid_channel is not None and current['close'] >= mid_channel
                elif mode == "BB Mean Reversion":
                    hit_target = bb_mid is not None and current['close'] >= bb_mid
                else:
                    hit_target = (
                        (mid_channel is not None and current['close'] >= mid_channel) or
                        (bb_mid is not None and current['close'] >= bb_mid)
                    )

                if hit_target:
                    exit_type = 'TARGET'
                elif mode in ("BB Mean Reversion", "Both (dual confirm)") and rsi > RSI_SELL_BB:
                    exit_type = 'RSI'
                elif current['close'] < position['stop_price']:
                    exit_type = 'STOP'

                if exit_type:
                    pnl_pct = (current['close'] - position['entry_price']) / position['entry_price'] * 100
                    all_events.append({
                        'time': current['time'],
                        'pair': pair,
                        'type': 'EXIT',
                        'exit_type': exit_type,
                        'price': current['close'],
                        'entry_price': position['entry_price'],
                        'pnl_pct': pnl_pct,
                        'bar_idx': i,
                    })
                    last_exit_bar = i
                    position = None

        # Close open position at end
        if position:
            last = candles[-1]
            pnl_pct = (last['close'] - position['entry_price']) / position['entry_price'] * 100
            all_events.append({
                'time': last['time'],
                'pair': pair,
                'type': 'EXIT',
                'exit_type': 'OPEN',
                'price': last['close'],
                'entry_price': position['entry_price'],
                'pnl_pct': pnl_pct,
                'bar_idx': len(candles) - 1,
            })

    # Sort chronologically (exits before entries at same time)
    all_events.sort(key=lambda x: (x['time'], x['type'] == 'ENTRY'))
    return all_events


def simulate_portfolio(events, capital_per_trade, max_positions):
    """
    Simulate portfolio with position limits and commission.
    First-come-first-served selection (no ranking).
    """
    positions = {}
    trades = []
    skipped = []

    for event in events:
        if event['type'] == 'ENTRY':
            if len(positions) >= max_positions:
                skipped.append(event)
                continue
            if event['pair'] in positions:
                continue

            volume = capital_per_trade / event['price']
            commission_entry = capital_per_trade * COMMISSION_PCT / 100
            positions[event['pair']] = {
                'entry_price': event['price'],
                'volume': volume,
                'entry_time': event['time'],
                'commission_entry': commission_entry,
            }

        elif event['type'] == 'EXIT':
            if event['pair'] not in positions:
                continue

            pos = positions[event['pair']]
            pnl_usd = pos['volume'] * (event['price'] - pos['entry_price'])
            commission_exit = abs(pos['volume'] * event['price']) * COMMISSION_PCT / 100
            total_commission = pos['commission_entry'] + commission_exit
            pnl_usd -= total_commission
            pnl_pct = (event['price'] - pos['entry_price']) / pos['entry_price'] * 100

            trades.append({
                'pair': event['pair'],
                'entry_price': pos['entry_price'],
                'exit_price': event['price'],
                'pnl_usd': pnl_usd,
                'pnl_pct': pnl_pct,
                'exit_type': event.get('exit_type', '?'),
                'commission': total_commission,
            })
            del positions[event['pair']]

    total_capital = capital_per_trade * max_positions

    if not trades:
        return {
            'capital_per_trade': capital_per_trade,
            'max_positions': max_positions,
            'total_capital': total_capital,
            'trades': 0,
            'skipped': len(skipped),
            'total_signals': len([e for e in events if e['type'] == 'ENTRY']),
            'total_pnl_usd': 0,
            'win_rate': 0,
            'avg_pnl_pct': 0,
            'avg_pnl_usd': 0,
            'max_loss_usd': 0,
            'max_win_usd': 0,
            'profit_factor': 0,
            'max_drawdown_usd': 0,
            'roi': 0,
            'targets': 0,
            'stops': 0,
            'rsi_exits': 0,
            'total_commission': 0,
        }

    wins = [t for t in trades if t['pnl_usd'] > 0]
    losses = [t for t in trades if t['pnl_usd'] <= 0]
    total_pnl = sum(t['pnl_usd'] for t in trades)
    total_commission = sum(t['commission'] for t in trades)

    gross_profit = sum(t['pnl_usd'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl_usd'] for t in losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999

    # Max drawdown (equity curve)
    equity = 0
    peak = 0
    max_dd = 0
    for t in trades:
        equity += t['pnl_usd']
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    worst = min(t['pnl_usd'] for t in trades)
    best = max(t['pnl_usd'] for t in trades)

    targets = len([t for t in trades if t['exit_type'] == 'TARGET'])
    stops = len([t for t in trades if t['exit_type'] == 'STOP'])
    rsi_exits = len([t for t in trades if t['exit_type'] == 'RSI'])

    return {
        'capital_per_trade': capital_per_trade,
        'max_positions': max_positions,
        'total_capital': total_capital,
        'trades': len(trades),
        'skipped': len(skipped),
        'total_signals': len([e for e in events if e['type'] == 'ENTRY']),
        'total_pnl_usd': round(total_pnl, 2),
        'win_rate': round(len(wins) / len(trades) * 100, 1),
        'avg_pnl_pct': round(sum(t['pnl_pct'] for t in trades) / len(trades), 2),
        'avg_pnl_usd': round(total_pnl / len(trades), 2),
        'max_loss_usd': round(worst, 2),
        'max_win_usd': round(best, 2),
        'profit_factor': round(profit_factor, 2) if profit_factor < 999 else 999,
        'max_drawdown_usd': round(max_dd, 2),
        'roi': round(total_pnl / total_capital * 100, 2),
        'targets': targets,
        'stops': stops,
        'rsi_exits': rsi_exits,
        'total_commission': round(total_commission, 2),
    }


# === MAIN ===
if __name__ == '__main__':
    CACHE_FILE = '/Users/oussama/Cryptogem/trading_bot/candle_cache_30d.json'

    if not os.path.exists(CACHE_FILE):
        print("ERROR: Run backtest_universal.py first to fetch candle data")
        exit(1)

    print("Loading cached candle data...")
    with open(CACHE_FILE, 'r') as f:
        all_candles = json.load(f)
    print(f"  {len(all_candles)} coins loaded")

    MODES = ["Donchian Bounce", "BB Mean Reversion", "Both (dual confirm)"]
    SCENARIOS = [
        (600, 3, "3×$600"),
        (500, 4, "4×$500"),
        (400, 5, "5×$400"),
    ]

    # === RUN ALL COMBINATIONS ===
    print(f"\n{'=' * 120}")
    print(f"{'PORTFOLIO SIMULATIE - BEAR BOUNCE UNIVERSAL (LAST ~30 DAYS)':^120}")
    print(f"{'Budget: ~$2,000 | Commission: 0.1% per side | First-come-first-served':^120}")
    print(f"{'=' * 120}")

    all_results = {}

    for mode in MODES:
        print(f"\nExtracting signals for: {mode}...")
        events = extract_all_signals(all_candles, mode)
        entry_count = len([e for e in events if e['type'] == 'ENTRY'])
        print(f"  Total entry signals: {entry_count}")

        mode_results = {}
        for capital, max_pos, label in SCENARIOS:
            r = simulate_portfolio(events, capital, max_pos)
            mode_results[label] = r

        all_results[mode] = mode_results

    # === PRINT COMPARISON ===
    for mode in MODES:
        mr = all_results[mode]
        labels = [label for _, _, label in SCENARIOS]

        print(f"\n{'=' * 100}")
        print(f"  MODE: {mode.upper()}")
        print(f"{'=' * 100}")

        header = f"{'Metric':<30}"
        for label in labels:
            header += f" {label:>20}"
        print(header)
        print("-" * 100)

        rows = [
            ("Total signals", lambda r: f"{r['total_signals']}"),
            ("Trades uitgevoerd", lambda r: f"{r['trades']}"),
            ("Signalen GEMIST", lambda r: f"{r['skipped']}"),
            ("% signals traded", lambda r: f"{r['trades']/r['total_signals']*100:.0f}%" if r['total_signals'] > 0 else "0%"),
            ("", None),
            ("Win rate", lambda r: f"{r['win_rate']}%"),
            ("Totaal P&L", lambda r: f"${r['total_pnl_usd']:+.2f}"),
            ("ROI", lambda r: f"{r['roi']}%"),
            ("Avg P&L/trade ($)", lambda r: f"${r['avg_pnl_usd']:+.2f}"),
            ("Avg P&L/trade (%)", lambda r: f"{r['avg_pnl_pct']:+.2f}%"),
            ("Profit Factor", lambda r: f"{r['profit_factor']}" if r['profit_factor'] < 100 else "inf"),
            ("", None),
            ("TARGET exits", lambda r: f"{r['targets']}"),
            ("STOP exits", lambda r: f"{r['stops']}"),
            ("RSI exits", lambda r: f"{r['rsi_exits']}"),
            ("", None),
            ("Max drawdown ($)", lambda r: f"${r['max_drawdown_usd']}"),
            ("Worst trade ($)", lambda r: f"${r['max_loss_usd']}"),
            ("Best trade ($)", lambda r: f"${r['max_win_usd']}"),
            ("Total commission", lambda r: f"${r['total_commission']}"),
        ]

        for label_row, fmt in rows:
            if fmt is None:
                print("-" * 100)
                continue
            line = f"{label_row:<30}"
            for label in labels:
                line += f" {fmt(mr[label]):>20}"
            print(line)

    # === GRAND COMPARISON (best scenario per mode) ===
    print(f"\n{'=' * 120}")
    print(f"{'OVERALL VERGELIJKING - BESTE SCENARIO PER MODE':^120}")
    print(f"{'=' * 120}")

    # Find best scenario per mode (by total P&L)
    print(f"\n{'Mode':<25} {'Best Config':>12} {'Trades':>8} {'Gemist':>8} {'WR%':>8} {'P&L':>12} {'ROI':>8} {'PF':>8} {'MaxDD':>10}")
    print("-" * 110)

    for mode in MODES:
        mr = all_results[mode]
        best_label = max(mr.keys(), key=lambda k: mr[k]['total_pnl_usd'])
        r = mr[best_label]
        pf_str = f"{r['profit_factor']:.2f}" if r['profit_factor'] < 100 else "inf"
        print(f"{mode:<25} {best_label:>12} {r['trades']:>8} {r['skipped']:>8} {r['win_rate']:>7.1f}% ${r['total_pnl_usd']:>+10.2f} {r['roi']:>7.2f}% {pf_str:>8} ${r['max_drawdown_usd']:>8.2f}")

    # Save
    save_data = {}
    for mode in MODES:
        save_data[mode] = {k: {kk: vv for kk, vv in v.items()} for k, v in all_results[mode].items()}

    with open('/Users/oussama/Cryptogem/trading_bot/backtest_universal_portfolio.json', 'w') as f:
        json.dump(save_data, f, indent=2)
    print(f"\nResults saved to backtest_universal_portfolio.json")

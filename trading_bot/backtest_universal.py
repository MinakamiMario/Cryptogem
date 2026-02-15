"""
Backtest Bear Bounce Universal Strategy (3 modes)
==================================================
Identical to PineScript "Bear Bounce Universal 4H":
  1. Donchian Bounce  - low <= prev DC lower + RSI < 35 + bounce
  2. BB Mean Reversion - close <= BB lower + RSI < 30 + bounce
  3. Both (dual confirm) - both signals must fire simultaneously

Exits per mode:
  Donchian: close >= DC mid channel → TARGET
  BB Mean Rev: close >= BB mid → TARGET, or RSI > 70 → RSI EXIT
  Both: close >= DC mid OR close >= BB mid → TARGET, or RSI > 70 → RSI EXIT
  All modes: trailing stop (ATR × 2.0)

Tested over last 30 days, all selected coins, per-coin (unlimited capital).
"""
import krakenex
import time
import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# === STRATEGY PARAMETERS (matching PineScript defaults) ===
# Donchian
DONCHIAN_PERIOD = 20
RSI_DONCHIAN_MAX = 35

# Bollinger
BB_PERIOD = 20
BB_DEV = 2.0
RSI_BUY_BB = 30
RSI_SELL_BB = 70

# Shared
RSI_PERIOD = 14
ATR_PERIOD = 14
ATR_STOP_MULT = 2.0
COOLDOWN_BARS = 4
CAPITAL_PER_TRADE = 600
COMMISSION_PCT = 0.1  # 0.1% per trade (matching PineScript)


# === INDICATOR FUNCTIONS ===

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


# === BACKTEST ENGINE ===

def backtest_coin(candles, pair, mode="Donchian Bounce"):
    """
    Run backtest on candle data for a specific strategy mode.
    mode: "Donchian Bounce", "BB Mean Reversion", "Both (dual confirm)"
    Returns dict with results.
    """
    min_bars = max(DONCHIAN_PERIOD, BB_PERIOD, RSI_PERIOD, ATR_PERIOD) + 5
    if len(candles) < min_bars:
        return None

    trades = []
    position = None
    last_exit_bar = -999

    # Buy & hold tracking
    first_close = candles[0]['close']
    last_close = candles[-1]['close']
    buy_hold_return = (last_close - first_close) / first_close * 100

    start_bar = max(DONCHIAN_PERIOD, BB_PERIOD, RSI_PERIOD, ATR_PERIOD) + 2

    for i in range(start_bar, len(candles)):
        window = candles[:i + 1]
        closes = [c['close'] for c in window]
        highs = [c['high'] for c in window]
        lows = [c['low'] for c in window]

        rsi = calc_rsi(closes, RSI_PERIOD)
        atr = calc_atr(highs, lows, closes, ATR_PERIOD)

        # Donchian on previous bars (excl current)
        prev_highs = highs[:-1]
        prev_lows = lows[:-1]
        _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows, DONCHIAN_PERIOD)

        # Donchian including current bar (for mid channel target)
        hh, ll, mid_channel = calc_donchian(highs, lows, DONCHIAN_PERIOD)

        # Bollinger Bands on closes
        bb_mid, bb_upper, bb_lower = calc_bollinger(closes, BB_PERIOD, BB_DEV)

        current = window[-1]
        prev = window[-2]

        if position is None:
            # === CHECK ENTRY ===
            in_cooldown = (i - last_exit_bar) < COOLDOWN_BARS
            if in_cooldown:
                continue

            # Donchian signal: low <= prev DC lower + RSI < 35 + bounce
            donchian_signal = (
                prev_lowest is not None and
                current['low'] <= prev_lowest and
                rsi < RSI_DONCHIAN_MAX and
                current['close'] > prev['close']
            )

            # BB signal: close <= BB lower + RSI < 30 + bounce
            bb_signal = (
                bb_lower is not None and
                current['close'] <= bb_lower and
                rsi < RSI_BUY_BB and
                current['close'] > prev['close']
            )

            # Combined entry based on mode
            if mode == "Donchian Bounce":
                long_entry = donchian_signal
            elif mode == "BB Mean Reversion":
                long_entry = bb_signal
            else:  # Both (dual confirm)
                long_entry = donchian_signal and bb_signal

            if long_entry:
                entry_price = current['close']
                stop = entry_price - atr * ATR_STOP_MULT
                volume = CAPITAL_PER_TRADE / entry_price
                # Commission on entry
                commission_entry = CAPITAL_PER_TRADE * COMMISSION_PCT / 100

                position = {
                    'entry_price': entry_price,
                    'volume': volume,
                    'stop_price': stop,
                    'highest_price': entry_price,
                    'entry_bar': i,
                    'entry_time': current['time'],
                    'commission': commission_entry,
                }

        else:
            # === CHECK EXIT ===
            # Update trailing stop
            if current['close'] > position['highest_price']:
                position['highest_price'] = current['close']
            new_stop = position['highest_price'] - atr * ATR_STOP_MULT
            if new_stop > position['stop_price']:
                position['stop_price'] = new_stop

            exit_type = None

            # Determine target based on mode
            if mode == "Donchian Bounce":
                hit_target = mid_channel is not None and current['close'] >= mid_channel
            elif mode == "BB Mean Reversion":
                hit_target = bb_mid is not None and current['close'] >= bb_mid
            else:  # Both
                hit_target = (
                    (mid_channel is not None and current['close'] >= mid_channel) or
                    (bb_mid is not None and current['close'] >= bb_mid)
                )

            # Exit 1: Target
            if hit_target:
                exit_type = 'TARGET'

            # Exit 2: RSI overbought (BB mode and Both mode only)
            elif mode in ("BB Mean Reversion", "Both (dual confirm)") and rsi > RSI_SELL_BB:
                exit_type = 'RSI'

            # Exit 3: Trailing stop
            elif current['close'] < position['stop_price']:
                exit_type = 'STOP'

            if exit_type:
                exit_price = current['close']
                pnl_pct = (exit_price - position['entry_price']) / position['entry_price'] * 100
                pnl_usd = position['volume'] * (exit_price - position['entry_price'])
                # Commission on exit
                commission_exit = abs(position['volume'] * exit_price) * COMMISSION_PCT / 100
                total_commission = position['commission'] + commission_exit
                pnl_usd -= total_commission

                trades.append({
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'pnl_pct': pnl_pct,
                    'pnl_usd': pnl_usd,
                    'type': exit_type,
                    'bars_held': i - position['entry_bar'],
                    'commission': total_commission,
                })
                last_exit_bar = i
                position = None

    # Close any open position at end
    if position:
        exit_price = candles[-1]['close']
        pnl_pct = (exit_price - position['entry_price']) / position['entry_price'] * 100
        pnl_usd = position['volume'] * (exit_price - position['entry_price'])
        commission_exit = abs(position['volume'] * exit_price) * COMMISSION_PCT / 100
        total_commission = position['commission'] + commission_exit
        pnl_usd -= total_commission

        trades.append({
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'pnl_pct': pnl_pct,
            'pnl_usd': pnl_usd,
            'type': 'OPEN',
            'bars_held': len(candles) - position['entry_bar'],
            'commission': total_commission,
        })

    if not trades:
        return {
            'pair': pair,
            'mode': mode,
            'trades': 0,
            'total_return': 0,
            'total_pnl_usd': 0,
            'win_rate': 0,
            'avg_pnl': 0,
            'max_dd': 0,
            'buy_hold': buy_hold_return,
            'alpha': -buy_hold_return,
            'profit_factor': 0,
            'avg_bars_held': 0,
            'targets': 0,
            'stops': 0,
            'rsi_exits': 0,
        }

    wins = [t for t in trades if t['pnl_usd'] > 0]
    losses_t = [t for t in trades if t['pnl_usd'] <= 0]
    total_pnl = sum(t['pnl_pct'] for t in trades)
    total_pnl_usd = sum(t['pnl_usd'] for t in trades)
    win_rate = len(wins) / len(trades) * 100

    gross_profit = sum(t['pnl_usd'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl_usd'] for t in losses_t)) if losses_t else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Max drawdown
    equity = 0
    peak = 0
    max_dd = 0
    for t in trades:
        equity += t['pnl_pct']
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    alpha = total_pnl - buy_hold_return
    avg_bars = sum(t['bars_held'] for t in trades) / len(trades)
    targets = len([t for t in trades if t['type'] == 'TARGET'])
    stops = len([t for t in trades if t['type'] == 'STOP'])
    rsi_exits = len([t for t in trades if t['type'] == 'RSI'])
    total_commission = sum(t['commission'] for t in trades)

    return {
        'pair': pair,
        'mode': mode,
        'trades': len(trades),
        'total_return': round(total_pnl, 2),
        'total_pnl_usd': round(total_pnl_usd, 2),
        'win_rate': round(win_rate, 1),
        'avg_pnl': round(total_pnl / len(trades), 2),
        'max_dd': round(max_dd, 2),
        'buy_hold': round(buy_hold_return, 2),
        'alpha': round(alpha, 2),
        'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 999,
        'avg_bars_held': round(avg_bars, 1),
        'targets': targets,
        'stops': stops,
        'rsi_exits': rsi_exits,
        'total_commission': round(total_commission, 2),
    }


# === MAIN ===
if __name__ == '__main__':
    from kraken_client import KrakenClient

    coins = os.getenv('COINS', '').split(',')
    api = krakenex.API()

    # Last 30 days + extra buffer for indicator warmup (need ~20 bars = ~3.3 days at 4H)
    # Fetch 45 days to ensure enough warmup data
    since = int((datetime.now() - timedelta(days=45)).timestamp())

    PAIR_MAP = KrakenClient.PAIR_MAP

    # === FETCH DATA ===
    CACHE_FILE = '/Users/oussama/Cryptogem/trading_bot/candle_cache_30d.json'

    use_cache = False
    if os.path.exists(CACHE_FILE):
        cache_age = time.time() - os.path.getmtime(CACHE_FILE)
        if cache_age < 14400:  # 4 hours
            use_cache = True

    all_candles = {}
    errors = []

    if use_cache:
        print("Loading cached candle data...")
        with open(CACHE_FILE, 'r') as f:
            all_candles = json.load(f)
        print(f"  {len(all_candles)} coins loaded from cache")
    else:
        total = len(coins)
        print(f"Fetching 4H candle data for {total} coins (last 45 days)...")
        for idx, pair in enumerate(coins):
            pair = pair.strip()
            if not pair:
                continue

            kraken_pair = PAIR_MAP.get(pair, pair.replace('/', ''))
            time.sleep(0.8)

            try:
                result = api.query_public('OHLC', {'pair': kraken_pair, 'interval': 240, 'since': since})
                if result.get('error') and len(result['error']) > 0:
                    errors.append(f"{pair}: {result['error']}")
                    continue

                data = result.get('result', {})
                candles = []
                for key, vals in data.items():
                    if key != 'last':
                        for c in vals:
                            candles.append({
                                'time': int(c[0]),
                                'open': float(c[1]),
                                'high': float(c[2]),
                                'low': float(c[3]),
                                'close': float(c[4]),
                                'vwap': float(c[5]),
                                'volume': float(c[6]),
                                'count': int(c[7]),
                            })
                        break

                if len(candles) >= 30:
                    all_candles[pair] = candles

                if (idx + 1) % 25 == 0 or idx + 1 == total:
                    print(f"  [{idx + 1}/{total}] fetched... ({len(all_candles)} coins OK, {len(errors)} errors)")

            except Exception as e:
                errors.append(f"{pair}: {str(e)}")

        # Save cache
        with open(CACHE_FILE, 'w') as f:
            json.dump(all_candles, f)
        print(f"\n  {len(all_candles)} coins fetched, {len(errors)} errors")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for e in errors[:10]:
            print(f"  {e}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")

    # === RUN BACKTESTS FOR ALL 3 MODES ===
    MODES = ["Donchian Bounce", "BB Mean Reversion", "Both (dual confirm)"]
    all_results = {}

    for mode in MODES:
        results = []
        for pair, candles in all_candles.items():
            bt = backtest_coin(candles, pair, mode)
            if bt:
                results.append(bt)
        results.sort(key=lambda x: x['alpha'], reverse=True)
        all_results[mode] = results

    # === PRINT RESULTS ===
    print(f"\n{'=' * 100}")
    print(f"{'BEAR BOUNCE UNIVERSAL BACKTEST - LAST ~30 DAYS':^100}")
    print(f"{'=' * 100}")
    print(f"Capital per trade: ${CAPITAL_PER_TRADE} | Commission: {COMMISSION_PCT}% per side")
    print(f"Coins tested: {len(all_candles)}")

    for mode in MODES:
        results = all_results[mode]
        with_trades = [r for r in results if r['trades'] > 0]
        positive_alpha = [r for r in with_trades if r['alpha'] > 0]

        total_trades = sum(r['trades'] for r in with_trades)
        total_pnl = sum(r['total_pnl_usd'] for r in with_trades)
        avg_wr = sum(r['win_rate'] for r in with_trades) / len(with_trades) if with_trades else 0
        total_targets = sum(r['targets'] for r in with_trades)
        total_stops = sum(r['stops'] for r in with_trades)
        total_rsi = sum(r['rsi_exits'] for r in with_trades)
        total_commission = sum(r['total_commission'] for r in with_trades)

        # Portfolio metrics
        wins_all = [r for r in with_trades if r['total_pnl_usd'] > 0]
        losses_all = [r for r in with_trades if r['total_pnl_usd'] <= 0]
        gross_profit = sum(r['total_pnl_usd'] for r in wins_all) if wins_all else 0
        gross_loss = abs(sum(r['total_pnl_usd'] for r in losses_all)) if losses_all else 0
        pf = gross_profit / gross_loss if gross_loss > 0 else 999

        print(f"\n{'=' * 100}")
        print(f"  MODE: {mode.upper()}")
        print(f"{'=' * 100}")
        print(f"  Coins with trades:  {len(with_trades)} / {len(results)}")
        print(f"  Positive alpha:     {len(positive_alpha)} coins")
        print(f"  Total trades:       {total_trades}")
        print(f"  Total P&L:          ${total_pnl:+.2f}")
        print(f"  Total commission:   ${total_commission:.2f}")
        print(f"  Avg win rate:       {avg_wr:.1f}%")
        print(f"  Portfolio PF:       {pf:.2f}")
        print(f"  Exits: TARGET={total_targets}  STOP={total_stops}  RSI={total_rsi}")

        if with_trades:
            avg_pnl_per_trade = total_pnl / total_trades
            print(f"  Avg P&L/trade:      ${avg_pnl_per_trade:+.2f}")

        # Top 20
        print(f"\n  {'Pair':<16} {'Trades':>6} {'Return':>8} {'P&L($)':>9} {'WR%':>6} {'PF':>6} {'DD%':>6} {'B&H%':>8} {'Alpha%':>8} {'Bars':>5} {'T/S/R':>7}")
        print(f"  {'-' * 96}")

        for r in results[:20]:
            if r['trades'] > 0:
                pf_str = f"{r['profit_factor']:.1f}" if r['profit_factor'] < 100 else "inf"
                tsr = f"{r['targets']}/{r['stops']}/{r['rsi_exits']}"
                print(f"  {r['pair']:<16} {r['trades']:>6} {r['total_return']:>7.1f}% {r['total_pnl_usd']:>+9.2f} {r['win_rate']:>5.1f}% {pf_str:>6} {r['max_dd']:>5.1f}% {r['buy_hold']:>7.1f}% {r['alpha']:>+7.1f}% {r['avg_bars_held']:>5.1f} {tsr:>7}")

        # Bottom 5
        bottom = [r for r in results[-5:] if r['trades'] > 0]
        if bottom:
            print(f"\n  BOTTOM 5:")
            for r in bottom:
                pf_str = f"{r['profit_factor']:.1f}" if r['profit_factor'] < 100 else "inf"
                tsr = f"{r['targets']}/{r['stops']}/{r['rsi_exits']}"
                print(f"  {r['pair']:<16} {r['trades']:>6} {r['total_return']:>7.1f}% {r['total_pnl_usd']:>+9.2f} {r['win_rate']:>5.1f}% {pf_str:>6} {r['max_dd']:>5.1f}% {r['buy_hold']:>7.1f}% {r['alpha']:>+7.1f}% {r['avg_bars_held']:>5.1f} {tsr:>7}")

    # === COMPARISON TABLE ===
    print(f"\n{'=' * 100}")
    print(f"{'STRATEGY COMPARISON':^100}")
    print(f"{'=' * 100}")
    print(f"{'Metric':<35} {'Donchian Bounce':>20} {'BB Mean Rev':>20} {'Both (dual)':>20}")
    print(f"{'-' * 100}")

    rows = []
    for mode in MODES:
        results = all_results[mode]
        wt = [r for r in results if r['trades'] > 0]
        tt = sum(r['trades'] for r in wt)
        tp = sum(r['total_pnl_usd'] for r in wt)
        wr = sum(r['win_rate'] for r in wt) / len(wt) if wt else 0
        targets = sum(r['targets'] for r in wt)
        stops = sum(r['stops'] for r in wt)
        rsi_ex = sum(r['rsi_exits'] for r in wt)
        pa = len([r for r in wt if r['alpha'] > 0])
        comm = sum(r['total_commission'] for r in wt)

        wins_a = [r for r in wt if r['total_pnl_usd'] > 0]
        losses_a = [r for r in wt if r['total_pnl_usd'] <= 0]
        gp = sum(r['total_pnl_usd'] for r in wins_a) if wins_a else 0
        gl = abs(sum(r['total_pnl_usd'] for r in losses_a)) if losses_a else 0
        pf = gp / gl if gl > 0 else 999

        rows.append({
            'coins_trading': len(wt),
            'total_trades': tt,
            'total_pnl': tp,
            'avg_wr': wr,
            'pf': pf,
            'positive_alpha': pa,
            'targets': targets,
            'stops': stops,
            'rsi_exits': rsi_ex,
            'avg_pnl_trade': tp / tt if tt > 0 else 0,
            'commission': comm,
        })

    metrics = [
        ('Coins with trades', lambda r: f"{r['coins_trading']}"),
        ('Total trades', lambda r: f"{r['total_trades']}"),
        ('Total P&L', lambda r: f"${r['total_pnl']:+.2f}"),
        ('Avg P&L/trade', lambda r: f"${r['avg_pnl_trade']:+.2f}"),
        ('Avg Win Rate', lambda r: f"{r['avg_wr']:.1f}%"),
        ('Profit Factor', lambda r: f"{r['pf']:.2f}" if r['pf'] < 100 else "inf"),
        ('Positive Alpha coins', lambda r: f"{r['positive_alpha']}"),
        ('TARGET exits', lambda r: f"{r['targets']}"),
        ('STOP exits', lambda r: f"{r['stops']}"),
        ('RSI exits', lambda r: f"{r['rsi_exits']}"),
        ('Total commission', lambda r: f"${r['commission']:.2f}"),
    ]

    for label, fmt in metrics:
        vals = [fmt(r) for r in rows]
        print(f"  {label:<33} {vals[0]:>20} {vals[1]:>20} {vals[2]:>20}")

    # === SAVE ALL RESULTS ===
    save_data = {}
    for mode in MODES:
        save_data[mode] = all_results[mode]

    with open('/Users/oussama/Cryptogem/trading_bot/backtest_universal_results.json', 'w') as f:
        json.dump(save_data, f, indent=2)
    print(f"\nResults saved to backtest_universal_results.json")

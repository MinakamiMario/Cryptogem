#!/usr/bin/env python3
"""
Deep Trade Analysis — Per-trade metrics collection for winners vs losers comparison.
Collects: MFE, MAE, BB width, volume stats, RSI, bars held, exit type, trend context.
"""
import json
import sys
import statistics
sys.path.insert(0, '/Users/oussama/Cryptogem/trading_bot')

from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

KRAKEN_FEE = 0.0026

# Load cache
with open('/Users/oussama/Cryptogem/trading_bot/candle_cache_60d.json') as f:
    all_candles = json.load(f)

coins = [k for k in all_candles if not k.startswith('_')]

# V3 params
V3_PARAMS = dict(
    donchian_period=20, bb_period=20, bb_dev=2.0,
    rsi_period=14, rsi_max=40, rsi_sell=70,
    atr_period=14, atr_stop_mult=2.0,
    max_stop_loss_pct=15.0,
    cooldown_bars=4, cooldown_after_stop=8,
    volume_min_pct=0.5,
    volume_spike_mult=2.0,
    breakeven_trigger_pct=3.0,
    time_max_bars=16,
)

def run_detailed_backtest():
    """Run single-pass backtest collecting detailed per-trade metrics."""
    p = V3_PARAMS
    detailed_trades = []

    for pair in coins:
        candles = all_candles.get(pair, [])
        if len(candles) < 50:
            continue

        # Strategy state
        last_exit_bar = -999
        last_exit_was_stop = False
        position = None  # dict with entry info

        for bar_idx in range(50, len(candles)):
            window = candles[:bar_idx + 1]
            closes = [c['close'] for c in window]
            highs = [c['high'] for c in window]
            lows = [c['low'] for c in window]
            volumes = [c.get('volume', 0) for c in window]

            min_bars = max(p['donchian_period'], p['bb_period'], p['rsi_period'], p['atr_period']) + 5
            if len(window) < min_bars:
                continue

            rsi = calc_rsi(closes, p['rsi_period'])
            atr = calc_atr(highs, lows, closes, p['atr_period'])

            prev_highs = highs[:-1]
            prev_lows = lows[:-1]
            _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows, p['donchian_period'])
            hh, ll, mid_channel = calc_donchian(highs, lows, p['donchian_period'])
            bb_mid, bb_upper, bb_lower = calc_bollinger(closes, p['bb_period'], p['bb_dev'])

            if any(v is None for v in [rsi, atr, prev_lowest, mid_channel, bb_mid, bb_lower]):
                continue

            current = candles[bar_idx]
            close = current['close']
            low_price = current['low']
            prev_close = candles[bar_idx - 1]['close']

            # === EXIT CHECK ===
            if position is not None:
                entry_price = position['entry_price']
                bars_in_trade = bar_idx - position['entry_bar']

                # Track MFE/MAE
                if close > position['highest_price']:
                    position['highest_price'] = close
                if close < position['lowest_price']:
                    position['lowest_price'] = close
                # Also track high/low of current bar
                if current['high'] > position['highest_price']:
                    position['highest_price'] = current['high']
                if current['low'] < position['lowest_price']:
                    position['lowest_price'] = current['low']

                # Update trailing stop
                new_stop = position['highest_price'] - atr * p['atr_stop_mult']
                hard_stop = entry_price * (1 - p['max_stop_loss_pct'] / 100)
                if new_stop < hard_stop:
                    new_stop = hard_stop

                # Break-even stop
                profit_pct = (close - entry_price) / entry_price * 100
                if profit_pct >= p['breakeven_trigger_pct']:
                    breakeven_level = entry_price * (1 + KRAKEN_FEE * 2)
                    if new_stop < breakeven_level:
                        new_stop = breakeven_level

                if new_stop > position['stop_price']:
                    position['stop_price'] = new_stop

                exit_reason = None
                exit_price = close

                # Exit 1: Hard stop
                if close < hard_stop:
                    exit_reason = 'HARD STOP'
                # Exit 2: Time max
                elif bars_in_trade >= p['time_max_bars']:
                    exit_reason = 'TIME MAX'
                # Exit 3: DC mid target
                elif close >= mid_channel:
                    exit_reason = 'DC TARGET'
                # Exit 4: BB mid target
                elif close >= bb_mid:
                    exit_reason = 'BB TARGET'
                # Exit 5: RSI overbought
                elif rsi > p['rsi_sell']:
                    exit_reason = 'RSI EXIT'
                # Exit 6: Trailing stop
                elif close < position['stop_price']:
                    exit_reason = 'TRAIL STOP'

                if exit_reason:
                    # Calculate P&L
                    gross_pnl = (exit_price - entry_price) / entry_price * 2000  # $2000 position
                    fee_cost = 2000 * KRAKEN_FEE + (2000 + gross_pnl) * KRAKEN_FEE
                    net_pnl = gross_pnl - fee_cost

                    # MFE/MAE
                    mfe_pct = (position['highest_price'] - entry_price) / entry_price * 100
                    mae_pct = (entry_price - position['lowest_price']) / entry_price * 100

                    trade_record = {
                        'pair': pair,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'entry_bar': position['entry_bar'],
                        'exit_bar': bar_idx,
                        'bars_held': bars_in_trade,
                        'entry_rsi': position['entry_rsi'],
                        'entry_vol_spike': position['entry_vol_spike'],
                        'entry_bb_width': position['entry_bb_width'],
                        'entry_bb_width_pct': position['entry_bb_width_pct'],
                        'entry_atr': position['entry_atr'],
                        'entry_atr_pct': position['entry_atr_pct'],
                        'avg_volume_20': position['avg_volume_20'],
                        'median_volume_20': position['median_volume_20'],
                        'coin_avg_daily_vol': position['coin_avg_daily_vol'],
                        'mfe_pct': mfe_pct,
                        'mae_pct': mae_pct,
                        'net_pnl': net_pnl,
                        'pnl_pct': (exit_price - entry_price) / entry_price * 100,
                        'exit_reason': exit_reason,
                        'is_winner': net_pnl > 0,
                        # Pre-entry trend context
                        'trend_5bar_pct': position['trend_5bar_pct'],
                        'trend_10bar_pct': position['trend_10bar_pct'],
                        'trend_20bar_pct': position['trend_20bar_pct'],
                        # MFE after 2 bars
                        'mfe_2bar_pct': position.get('mfe_2bar_pct', None),
                    }
                    detailed_trades.append(trade_record)

                    last_exit_bar = bar_idx
                    last_exit_was_stop = 'STOP' in exit_reason
                    position = None

                continue  # Don't check entry if we're in a position (even if we just exited)

            # === ENTRY CHECK ===
            # Cooldown
            cooldown_needed = p['cooldown_after_stop'] if last_exit_was_stop else p['cooldown_bars']
            if (bar_idx - last_exit_bar) < cooldown_needed:
                continue

            # Volume base filter
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * p['volume_min_pct']:
                continue

            # Dual confirm
            dc_signal = (low_price <= prev_lowest and rsi < p['rsi_max'] and close > prev_close)
            bb_signal = (close <= bb_lower and rsi < p['rsi_max'] and close > prev_close)

            if not (dc_signal and bb_signal):
                continue

            # Volume spike filter
            if vol_avg > 0 and volumes[-1] < vol_avg * p['volume_spike_mult']:
                continue

            # ENTRY
            vol_spike_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 0

            # Calculate BB width
            bb_width = bb_upper - bb_lower if bb_upper and bb_lower else 0
            bb_width_pct = bb_width / bb_mid * 100 if bb_mid and bb_mid > 0 else 0

            # ATR as percentage of price
            atr_pct = atr / close * 100 if close > 0 else 0

            # Pre-entry trend (how much did price drop before entry?)
            trend_5 = (close - candles[bar_idx - 5]['close']) / candles[bar_idx - 5]['close'] * 100 if bar_idx >= 5 else 0
            trend_10 = (close - candles[bar_idx - 10]['close']) / candles[bar_idx - 10]['close'] * 100 if bar_idx >= 10 else 0
            trend_20 = (close - candles[bar_idx - 20]['close']) / candles[bar_idx - 20]['close'] * 100 if bar_idx >= 20 else 0

            # Coin average daily volume (entire history)
            all_vols = [c.get('volume', 0) for c in candles[:bar_idx+1]]
            coin_avg_vol = sum(all_vols) / len(all_vols) if all_vols else 0

            # Median volume for last 20 bars
            recent_vols = volumes[-20:]
            median_vol = statistics.median(recent_vols) if recent_vols else 0

            stop_price = close - atr * p['atr_stop_mult']
            hard_stop_price = close * (1 - p['max_stop_loss_pct'] / 100)
            if stop_price < hard_stop_price:
                stop_price = hard_stop_price

            position = {
                'entry_price': close,
                'entry_bar': bar_idx,
                'stop_price': stop_price,
                'highest_price': close,
                'lowest_price': close,
                'entry_rsi': rsi,
                'entry_vol_spike': vol_spike_ratio,
                'entry_bb_width': bb_width,
                'entry_bb_width_pct': bb_width_pct,
                'entry_atr': atr,
                'entry_atr_pct': atr_pct,
                'avg_volume_20': vol_avg,
                'median_volume_20': median_vol,
                'coin_avg_daily_vol': coin_avg_vol,
                'trend_5bar_pct': trend_5,
                'trend_10bar_pct': trend_10,
                'trend_20bar_pct': trend_20,
            }

            # Track MFE after 2 bars (we'll update this)
            # We need to look ahead for this - do it after entry
            if bar_idx + 2 < len(candles):
                max_high_2 = max(candles[bar_idx + 1]['high'], candles[bar_idx + 2]['high'])
                mfe_2bar = (max_high_2 - close) / close * 100
                position['mfe_2bar_pct'] = mfe_2bar
            else:
                position['mfe_2bar_pct'] = 0

        # Close remaining position at end
        if position is not None:
            last_candle = candles[-1]
            entry_price = position['entry_price']
            exit_price = last_candle['close']
            gross_pnl = (exit_price - entry_price) / entry_price * 2000
            fee_cost = 2000 * KRAKEN_FEE + (2000 + gross_pnl) * KRAKEN_FEE
            net_pnl = gross_pnl - fee_cost

            mfe_pct = (position['highest_price'] - entry_price) / entry_price * 100
            mae_pct = (entry_price - position['lowest_price']) / entry_price * 100
            bars_in_trade = len(candles) - 1 - position['entry_bar']

            trade_record = {
                'pair': pair,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'entry_bar': position['entry_bar'],
                'exit_bar': len(candles) - 1,
                'bars_held': bars_in_trade,
                'entry_rsi': position['entry_rsi'],
                'entry_vol_spike': position['entry_vol_spike'],
                'entry_bb_width': position['entry_bb_width'],
                'entry_bb_width_pct': position['entry_bb_width_pct'],
                'entry_atr': position['entry_atr'],
                'entry_atr_pct': position['entry_atr_pct'],
                'avg_volume_20': position['avg_volume_20'],
                'median_volume_20': position['median_volume_20'],
                'coin_avg_daily_vol': position['coin_avg_daily_vol'],
                'mfe_pct': mfe_pct,
                'mae_pct': mae_pct,
                'net_pnl': net_pnl,
                'pnl_pct': (exit_price - entry_price) / entry_price * 100,
                'exit_reason': 'END',
                'is_winner': net_pnl > 0,
                'trend_5bar_pct': position['trend_5bar_pct'],
                'trend_10bar_pct': position['trend_10bar_pct'],
                'trend_20bar_pct': position['trend_20bar_pct'],
                'mfe_2bar_pct': position.get('mfe_2bar_pct', None),
            }
            detailed_trades.append(trade_record)
            position = None

    return detailed_trades


def safe_median(lst):
    return statistics.median(lst) if lst else 0

def safe_mean(lst):
    return statistics.mean(lst) if lst else 0

def analyze_trades(trades):
    """Compare winners vs losers across all dimensions."""
    winners = [t for t in trades if t['is_winner']]
    losers = [t for t in trades if not t['is_winner']]

    print("=" * 120)
    print("  DEEP TRADE ANALYSIS — V3 (RSI<40, VolSpike 2.0x, ATR 2.0x, BE 3%, TimeMax 16)")
    print("=" * 120)
    print(f"\n  Total trades: {len(trades)} | Winners: {len(winners)} | Losers: {len(losers)}")
    print(f"  Win rate: {len(winners)/len(trades)*100:.1f}%")
    print(f"  Total P&L: ${sum(t['net_pnl'] for t in trades):+,.2f}")
    print(f"  Winners P&L: ${sum(t['net_pnl'] for t in winners):+,.2f}")
    print(f"  Losers P&L: ${sum(t['net_pnl'] for t in losers):+,.2f}")

    # ========== PER TRADE DETAIL ==========
    print("\n" + "=" * 120)
    print("  ALL TRADES — SORTED BY P&L")
    print("=" * 120)
    sorted_trades = sorted(trades, key=lambda t: t['net_pnl'])
    print(f"  {'PAIR':<14} | {'Entry RSI':>9} | {'VolSpike':>8} | {'BB Width%':>9} | {'ATR%':>6} | {'MFE%':>6} | {'MAE%':>6} | {'MFE2b%':>7} | {'Bars':>4} | {'Trend5':>7} | {'Trend10':>8} | {'AvgVol':>12} | {'P&L':>10} | {'Exit':<12}")
    print("  " + "-" * 118)
    for t in sorted_trades:
        icon = "W" if t['is_winner'] else "L"
        mfe2 = f"{t['mfe_2bar_pct']:>6.2f}%" if t['mfe_2bar_pct'] is not None else "   N/A"
        print(f"  {icon} {t['pair']:<12} | {t['entry_rsi']:>9.1f} | {t['entry_vol_spike']:>7.1f}x | {t['entry_bb_width_pct']:>8.2f}% | {t['entry_atr_pct']:>5.2f}% | {t['mfe_pct']:>5.2f}% | {t['mae_pct']:>5.2f}% | {mfe2} | {t['bars_held']:>4} | {t['trend_5bar_pct']:>+6.1f}% | {t['trend_10bar_pct']:>+7.1f}% | {t['coin_avg_daily_vol']:>11.0f} | ${t['net_pnl']:>+8.2f} | {t['exit_reason']:<12}")

    # ========== DIMENSION COMPARISON ==========
    print("\n" + "=" * 120)
    print("  WINNERS vs LOSERS — DIMENSIONAL COMPARISON")
    print("=" * 120)

    dims = [
        ('A) Entry RSI', 'entry_rsi'),
        ('B) Volume Spike Ratio', 'entry_vol_spike'),
        ('C) BB Width %', 'entry_bb_width_pct'),
        ('D) ATR % (volatility)', 'entry_atr_pct'),
        ('E) MFE % (max favorable)', 'mfe_pct'),
        ('F) MAE % (max adverse)', 'mae_pct'),
        ('G) Bars Held', 'bars_held'),
        ('H) 5-bar Trend %', 'trend_5bar_pct'),
        ('I) 10-bar Trend %', 'trend_10bar_pct'),
        ('J) 20-bar Trend %', 'trend_20bar_pct'),
        ('K) Avg Volume (20-bar)', 'avg_volume_20'),
        ('L) Coin Avg Daily Volume', 'coin_avg_daily_vol'),
        ('M) MFE after 2 bars %', 'mfe_2bar_pct'),
    ]

    print(f"\n  {'DIMENSION':<30} | {'Winners Mean':>14} | {'Winners Med':>12} | {'Losers Mean':>14} | {'Losers Med':>12} | {'DIFF':>10} | {'INSIGHT':<40}")
    print("  " + "-" * 150)

    for name, key in dims:
        w_vals = [t[key] for t in winners if t[key] is not None]
        l_vals = [t[key] for t in losers if t[key] is not None]

        w_mean = safe_mean(w_vals)
        w_med = safe_median(w_vals)
        l_mean = safe_mean(l_vals)
        l_med = safe_median(l_vals)

        diff = w_mean - l_mean

        if key == 'entry_rsi':
            insight = "Losers have HIGHER RSI" if l_mean > w_mean else "Losers have LOWER RSI"
        elif key == 'entry_vol_spike':
            insight = "Losers have LOWER vol spike" if l_mean < w_mean else "Losers have HIGHER vol spike"
        elif key == 'entry_bb_width_pct':
            insight = "Losers have WIDER BB (more volatile)" if l_mean > w_mean else "Losers have NARROWER BB"
        elif key == 'mfe_pct':
            insight = f"Losers MFE much lower ({l_mean:.2f}% vs {w_mean:.2f}%)"
        elif key == 'mae_pct':
            insight = f"Losers MAE much higher ({l_mean:.2f}% vs {w_mean:.2f}%)"
        elif key == 'mfe_2bar_pct':
            insight = f"Losers early MFE: {l_mean:.2f}% vs winners {w_mean:.2f}%"
        elif key == 'coin_avg_daily_vol':
            insight = "Losers from LOW volume coins" if l_mean < w_mean else "Losers from HIGH volume coins"
        elif 'trend' in key:
            insight = f"Losers in {'stronger' if l_mean < w_mean else 'weaker'} downtrend"
        else:
            insight = ""

        print(f"  {name:<30} | {w_mean:>14.3f} | {w_med:>12.3f} | {l_mean:>14.3f} | {l_med:>12.3f} | {diff:>+10.3f} | {insight:<40}")

    # ========== MFE=0 ANALYSIS ==========
    print("\n" + "=" * 120)
    print("  MFE ANALYSIS — Trades where price NEVER went up")
    print("=" * 120)

    mfe_zero_losers = [t for t in losers if t['mfe_pct'] < 0.5]
    mfe_zero_winners = [t for t in winners if t['mfe_pct'] < 0.5]

    print(f"\n  Losers with MFE < 0.5%: {len(mfe_zero_losers)} / {len(losers)} ({len(mfe_zero_losers)/max(1,len(losers))*100:.0f}%)")
    print(f"  Winners with MFE < 0.5%: {len(mfe_zero_winners)} / {len(winners)} ({len(mfe_zero_winners)/max(1,len(winners))*100:.0f}%)")
    if mfe_zero_losers:
        print(f"  Total P&L from MFE<0.5% losers: ${sum(t['net_pnl'] for t in mfe_zero_losers):+,.2f}")

    # ========== EXIT TYPE DISTRIBUTION ==========
    print("\n" + "=" * 120)
    print("  EXIT TYPE DISTRIBUTION")
    print("=" * 120)

    from collections import Counter
    w_exits = Counter(t['exit_reason'] for t in winners)
    l_exits = Counter(t['exit_reason'] for t in losers)
    all_exits = set(w_exits.keys()) | set(l_exits.keys())

    print(f"\n  {'Exit Type':<15} | {'Winners':>8} | {'Losers':>8} | {'Total':>8}")
    print("  " + "-" * 50)
    for exit_type in sorted(all_exits):
        w = w_exits.get(exit_type, 0)
        l = l_exits.get(exit_type, 0)
        print(f"  {exit_type:<15} | {w:>8} | {l:>8} | {w+l:>8}")

    # ========== PER-COIN BREAKDOWN ==========
    print("\n" + "=" * 120)
    print("  PER-COIN P&L BREAKDOWN")
    print("=" * 120)

    from collections import defaultdict
    coin_pnl = defaultdict(lambda: {'trades': 0, 'wins': 0, 'total_pnl': 0, 'avg_vol': 0})
    for t in trades:
        coin_pnl[t['pair']]['trades'] += 1
        coin_pnl[t['pair']]['wins'] += 1 if t['is_winner'] else 0
        coin_pnl[t['pair']]['total_pnl'] += t['net_pnl']
        coin_pnl[t['pair']]['avg_vol'] = t['coin_avg_daily_vol']

    sorted_coins = sorted(coin_pnl.items(), key=lambda x: x[1]['total_pnl'])
    print(f"\n  {'COIN':<14} | {'Trades':>6} | {'Wins':>4} | {'WR':>6} | {'Total P&L':>12} | {'Avg Daily Vol':>14}")
    print("  " + "-" * 70)
    for pair, data in sorted_coins:
        wr = data['wins'] / data['trades'] * 100 if data['trades'] > 0 else 0
        icon = "L" if data['total_pnl'] < 0 else "W"
        print(f"  {icon} {pair:<12} | {data['trades']:>6} | {data['wins']:>4} | {wr:>5.0f}% | ${data['total_pnl']:>+10.2f} | {data['avg_vol']:>14.0f}")

    # ========== SPECIFIC COIN DEEP DIVE ==========
    for focus_coin in ['HUSDT', 'RENDERUSD', 'RENDER']:
        coin_trades = [t for t in trades if focus_coin in t['pair'].upper()]
        if coin_trades:
            print(f"\n  --- DEEP DIVE: {focus_coin} ---")
            for t in coin_trades:
                print(f"    Trade: entry=${t['entry_price']:.6f}, exit=${t['exit_price']:.6f}")
                print(f"      RSI: {t['entry_rsi']:.1f}, VolSpike: {t['entry_vol_spike']:.1f}x, BB Width: {t['entry_bb_width_pct']:.2f}%")
                print(f"      MFE: {t['mfe_pct']:.2f}%, MAE: {t['mae_pct']:.2f}%, MFE 2bar: {t.get('mfe_2bar_pct', 'N/A')}")
                print(f"      Bars: {t['bars_held']}, Trend5: {t['trend_5bar_pct']:+.1f}%, Trend10: {t['trend_10bar_pct']:+.1f}%")
                print(f"      P&L: ${t['net_pnl']:+.2f}, Exit: {t['exit_reason']}")

    return winners, losers


def propose_filters(trades, winners, losers):
    """Propose and test concrete filters."""
    print("\n" + "=" * 120)
    print("  PROPOSED SMART FILTERS")
    print("=" * 120)

    filters = {}

    # Filter 1: MFE 2-bar early exit
    # If MFE after 2 bars < threshold, the trade is likely dead
    for threshold in [0.3, 0.5, 1.0]:
        name = f"MFE_2bar < {threshold}%"
        blocked_losers = [t for t in losers if t['mfe_2bar_pct'] is not None and t['mfe_2bar_pct'] < threshold]
        blocked_winners = [t for t in winners if t['mfe_2bar_pct'] is not None and t['mfe_2bar_pct'] < threshold]
        saved_pnl = abs(sum(t['net_pnl'] for t in blocked_losers))
        lost_pnl = sum(t['net_pnl'] for t in blocked_winners)
        net_benefit = saved_pnl - lost_pnl
        filters[name] = {
            'blocked_losers': len(blocked_losers), 'blocked_winners': len(blocked_winners),
            'saved_pnl': saved_pnl, 'lost_pnl': lost_pnl, 'net_benefit': net_benefit
        }

    # Filter 2: Minimum coin daily volume
    vol_values = sorted([t['coin_avg_daily_vol'] for t in trades])
    for pct in [10, 25, 50]:
        idx = int(len(vol_values) * pct / 100)
        threshold = vol_values[idx] if idx < len(vol_values) else 0
        name = f"MinVolume > P{pct} ({threshold:.0f})"
        blocked_losers = [t for t in losers if t['coin_avg_daily_vol'] < threshold]
        blocked_winners = [t for t in winners if t['coin_avg_daily_vol'] < threshold]
        saved_pnl = abs(sum(t['net_pnl'] for t in blocked_losers))
        lost_pnl = sum(t['net_pnl'] for t in blocked_winners)
        net_benefit = saved_pnl - lost_pnl
        filters[name] = {
            'blocked_losers': len(blocked_losers), 'blocked_winners': len(blocked_winners),
            'saved_pnl': saved_pnl, 'lost_pnl': lost_pnl, 'net_benefit': net_benefit
        }

    # Filter 3: BB Width threshold (volatility)
    for threshold in [5, 8, 10, 15]:
        name = f"BB Width > {threshold}% (too volatile)"
        blocked_losers = [t for t in losers if t['entry_bb_width_pct'] > threshold]
        blocked_winners = [t for t in winners if t['entry_bb_width_pct'] > threshold]
        saved_pnl = abs(sum(t['net_pnl'] for t in blocked_losers))
        lost_pnl = sum(t['net_pnl'] for t in blocked_winners)
        net_benefit = saved_pnl - lost_pnl
        filters[name] = {
            'blocked_losers': len(blocked_losers), 'blocked_winners': len(blocked_winners),
            'saved_pnl': saved_pnl, 'lost_pnl': lost_pnl, 'net_benefit': net_benefit
        }

    # Filter 4: Strong downtrend before entry
    for threshold in [-10, -15, -20, -25]:
        name = f"Trend 10-bar < {threshold}% (too bearish)"
        blocked_losers = [t for t in losers if t['trend_10bar_pct'] < threshold]
        blocked_winners = [t for t in winners if t['trend_10bar_pct'] < threshold]
        saved_pnl = abs(sum(t['net_pnl'] for t in blocked_losers))
        lost_pnl = sum(t['net_pnl'] for t in blocked_winners)
        net_benefit = saved_pnl - lost_pnl
        filters[name] = {
            'blocked_losers': len(blocked_losers), 'blocked_winners': len(blocked_winners),
            'saved_pnl': saved_pnl, 'lost_pnl': lost_pnl, 'net_benefit': net_benefit
        }

    # Filter 5: RSI threshold variations
    for threshold in [30, 32, 35, 38]:
        name = f"RSI > {threshold} at entry (stricter)"
        blocked_losers = [t for t in losers if t['entry_rsi'] > threshold]
        blocked_winners = [t for t in winners if t['entry_rsi'] > threshold]
        saved_pnl = abs(sum(t['net_pnl'] for t in blocked_losers))
        lost_pnl = sum(t['net_pnl'] for t in blocked_winners)
        net_benefit = saved_pnl - lost_pnl
        filters[name] = {
            'blocked_losers': len(blocked_losers), 'blocked_winners': len(blocked_winners),
            'saved_pnl': saved_pnl, 'lost_pnl': lost_pnl, 'net_benefit': net_benefit
        }

    # Filter 6: Volume spike higher threshold
    for threshold in [2.5, 3.0, 4.0, 5.0]:
        name = f"VolSpike < {threshold}x (require higher)"
        blocked_losers = [t for t in losers if t['entry_vol_spike'] < threshold]
        blocked_winners = [t for t in winners if t['entry_vol_spike'] < threshold]
        saved_pnl = abs(sum(t['net_pnl'] for t in blocked_losers))
        lost_pnl = sum(t['net_pnl'] for t in blocked_winners)
        net_benefit = saved_pnl - lost_pnl
        filters[name] = {
            'blocked_losers': len(blocked_losers), 'blocked_winners': len(blocked_winners),
            'saved_pnl': saved_pnl, 'lost_pnl': lost_pnl, 'net_benefit': net_benefit
        }

    # Filter 7: ATR % (price volatility)
    for threshold in [3, 5, 7, 10]:
        name = f"ATR > {threshold}% (too volatile)"
        blocked_losers = [t for t in losers if t['entry_atr_pct'] > threshold]
        blocked_winners = [t for t in winners if t['entry_atr_pct'] > threshold]
        saved_pnl = abs(sum(t['net_pnl'] for t in blocked_losers))
        lost_pnl = sum(t['net_pnl'] for t in blocked_winners)
        net_benefit = saved_pnl - lost_pnl
        filters[name] = {
            'blocked_losers': len(blocked_losers), 'blocked_winners': len(blocked_winners),
            'saved_pnl': saved_pnl, 'lost_pnl': lost_pnl, 'net_benefit': net_benefit
        }

    # Filter 8: Trend 5-bar (very recent trend)
    for threshold in [-5, -8, -10]:
        name = f"Trend 5-bar < {threshold}% (crash in progress)"
        blocked_losers = [t for t in losers if t['trend_5bar_pct'] < threshold]
        blocked_winners = [t for t in winners if t['trend_5bar_pct'] < threshold]
        saved_pnl = abs(sum(t['net_pnl'] for t in blocked_losers))
        lost_pnl = sum(t['net_pnl'] for t in blocked_winners)
        net_benefit = saved_pnl - lost_pnl
        filters[name] = {
            'blocked_losers': len(blocked_losers), 'blocked_winners': len(blocked_winners),
            'saved_pnl': saved_pnl, 'lost_pnl': lost_pnl, 'net_benefit': net_benefit
        }

    # Print results sorted by net benefit
    sorted_filters = sorted(filters.items(), key=lambda x: x[1]['net_benefit'], reverse=True)

    print(f"\n  {'FILTER':<45} | {'Block L':>8} | {'Block W':>8} | {'Saved$':>10} | {'Lost$':>10} | {'Net$':>10} | {'Rating':<10}")
    print("  " + "-" * 120)
    for name, data in sorted_filters:
        rating = "GREAT" if data['net_benefit'] > 100 and data['blocked_winners'] == 0 else \
                 "GOOD" if data['net_benefit'] > 50 and data['blocked_winners'] <= 1 else \
                 "OK" if data['net_benefit'] > 0 else "BAD"
        print(f"  {name:<45} | {data['blocked_losers']:>8} | {data['blocked_winners']:>8} | ${data['saved_pnl']:>+8.0f} | ${data['lost_pnl']:>+8.0f} | ${data['net_benefit']:>+8.0f} | {rating:<10}")

    return sorted_filters


# ========== MAIN ==========
if __name__ == '__main__':
    print("Running detailed V3 backtest with per-trade metric collection...")
    trades = run_detailed_backtest()
    print(f"Collected {len(trades)} trades across all coins.\n")

    winners, losers = analyze_trades(trades)
    top_filters = propose_filters(trades, winners, losers)

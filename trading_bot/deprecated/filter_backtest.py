#!/usr/bin/env python3
"""
Filter Backtest — Test proposed smart filters by re-running the full V3 backtest
with each filter applied at ENTRY time, measuring impact on P&L, WR, PF, DD.

Also tests COMBINATION filters and an early-exit MFE filter.
"""
import json
import sys
import statistics
from collections import defaultdict

sys.path.insert(0, '/Users/oussama/Cryptogem/trading_bot')
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

KRAKEN_FEE = 0.0026
POSITION_SIZE = 2000

with open('/Users/oussama/Cryptogem/trading_bot/candle_cache_60d.json') as f:
    all_candles = json.load(f)

coins = [k for k in all_candles if not k.startswith('_')]

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


def run_filtered_backtest(filter_name, entry_filter_fn=None, exit_filter_fn=None,
                          early_exit_bars=0, early_exit_mfe_threshold=0):
    """
    Run V3 backtest with optional entry filter and/or early exit filter.

    entry_filter_fn: called at entry with (candles, bar_idx, indicators) -> True=allow entry
    exit_filter_fn: called each bar with (position, candles, bar_idx, indicators) -> True=force exit
    early_exit_bars: if >0, check MFE after this many bars
    early_exit_mfe_threshold: if MFE after early_exit_bars < this %, force exit
    """
    p = V3_PARAMS
    trades = []

    for pair in coins:
        candles = all_candles.get(pair, [])
        if len(candles) < 50:
            continue

        last_exit_bar = -999
        last_exit_was_stop = False
        position = None

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

            # === EXIT ===
            if position is not None:
                entry_price = position['entry_price']
                bars_in_trade = bar_idx - position['entry_bar']

                if close > position['highest_price']:
                    position['highest_price'] = close
                if current['high'] > position['highest_price']:
                    position['highest_price'] = current['high']
                if close < position['lowest_price']:
                    position['lowest_price'] = close
                if current['low'] < position['lowest_price']:
                    position['lowest_price'] = current['low']

                new_stop = position['highest_price'] - atr * p['atr_stop_mult']
                hard_stop = entry_price * (1 - p['max_stop_loss_pct'] / 100)
                if new_stop < hard_stop:
                    new_stop = hard_stop

                profit_pct = (close - entry_price) / entry_price * 100
                if profit_pct >= p['breakeven_trigger_pct']:
                    breakeven_level = entry_price * (1 + KRAKEN_FEE * 2)
                    if new_stop < breakeven_level:
                        new_stop = breakeven_level

                if new_stop > position['stop_price']:
                    position['stop_price'] = new_stop

                exit_reason = None

                # Early exit filter (MFE check after N bars)
                if early_exit_bars > 0 and bars_in_trade == early_exit_bars:
                    mfe_so_far = (position['highest_price'] - entry_price) / entry_price * 100
                    if mfe_so_far < early_exit_mfe_threshold:
                        exit_reason = f'EARLY_EXIT_{early_exit_bars}b'

                # Custom exit filter
                if exit_filter_fn and not exit_reason:
                    indicators = {
                        'rsi': rsi, 'atr': atr, 'atr_pct': atr / close * 100,
                        'mid_channel': mid_channel, 'bb_mid': bb_mid,
                        'bars_in_trade': bars_in_trade, 'close': close,
                        'profit_pct': profit_pct,
                        'mfe_pct': (position['highest_price'] - entry_price) / entry_price * 100,
                    }
                    if exit_filter_fn(position, candles, bar_idx, indicators):
                        exit_reason = 'CUSTOM EXIT'

                if not exit_reason:
                    if close < hard_stop:
                        exit_reason = 'HARD STOP'
                    elif bars_in_trade >= p['time_max_bars']:
                        exit_reason = 'TIME MAX'
                    elif close >= mid_channel:
                        exit_reason = 'DC TARGET'
                    elif close >= bb_mid:
                        exit_reason = 'BB TARGET'
                    elif rsi > p['rsi_sell']:
                        exit_reason = 'RSI EXIT'
                    elif close < position['stop_price']:
                        exit_reason = 'TRAIL STOP'

                if exit_reason:
                    exit_price = close
                    gross_pnl = (exit_price - entry_price) / entry_price * POSITION_SIZE
                    fee_cost = POSITION_SIZE * KRAKEN_FEE + (POSITION_SIZE + gross_pnl) * KRAKEN_FEE
                    net_pnl = gross_pnl - fee_cost

                    mfe_pct = (position['highest_price'] - entry_price) / entry_price * 100
                    mae_pct = (entry_price - position['lowest_price']) / entry_price * 100

                    trades.append({
                        'pair': pair,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'bars_held': bars_in_trade,
                        'mfe_pct': mfe_pct,
                        'mae_pct': mae_pct,
                        'net_pnl': net_pnl,
                        'exit_reason': exit_reason,
                        'is_winner': net_pnl > 0,
                    })

                    last_exit_bar = bar_idx
                    last_exit_was_stop = 'STOP' in exit_reason
                    position = None

                continue

            # === ENTRY ===
            cooldown_needed = p['cooldown_after_stop'] if last_exit_was_stop else p['cooldown_bars']
            if (bar_idx - last_exit_bar) < cooldown_needed:
                continue

            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * p['volume_min_pct']:
                continue

            dc_signal = (low_price <= prev_lowest and rsi < p['rsi_max'] and close > prev_close)
            bb_signal = (close <= bb_lower and rsi < p['rsi_max'] and close > prev_close)

            if not (dc_signal and bb_signal):
                continue

            if vol_avg > 0 and volumes[-1] < vol_avg * p['volume_spike_mult']:
                continue

            # Custom entry filter
            if entry_filter_fn:
                bb_width = bb_upper - bb_lower if bb_upper and bb_lower else 0
                bb_width_pct = bb_width / bb_mid * 100 if bb_mid > 0 else 0
                vol_spike_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 0
                atr_pct = atr / close * 100 if close > 0 else 0

                trend_5 = (close - candles[bar_idx - 5]['close']) / candles[bar_idx - 5]['close'] * 100 if bar_idx >= 5 else 0
                trend_10 = (close - candles[bar_idx - 10]['close']) / candles[bar_idx - 10]['close'] * 100 if bar_idx >= 10 else 0

                all_vols = [c.get('volume', 0) for c in candles[:bar_idx+1]]
                coin_avg_vol = sum(all_vols) / len(all_vols) if all_vols else 0

                indicators = {
                    'rsi': rsi, 'atr': atr, 'atr_pct': atr_pct,
                    'bb_width_pct': bb_width_pct, 'bb_mid': bb_mid,
                    'vol_spike': vol_spike_ratio, 'vol_avg': vol_avg,
                    'coin_avg_vol': coin_avg_vol,
                    'trend_5': trend_5, 'trend_10': trend_10,
                    'mid_channel': mid_channel, 'close': close,
                }

                if not entry_filter_fn(candles, bar_idx, indicators):
                    continue

            # ENTER
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
            }

        # Close remaining
        if position is not None:
            last_candle = candles[-1]
            entry_price = position['entry_price']
            exit_price = last_candle['close']
            gross_pnl = (exit_price - entry_price) / entry_price * POSITION_SIZE
            fee_cost = POSITION_SIZE * KRAKEN_FEE + (POSITION_SIZE + gross_pnl) * KRAKEN_FEE
            net_pnl = gross_pnl - fee_cost
            mfe_pct = (position['highest_price'] - entry_price) / entry_price * 100
            mae_pct = (entry_price - position['lowest_price']) / entry_price * 100
            bars_in_trade = len(candles) - 1 - position['entry_bar']

            trades.append({
                'pair': pair,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'bars_held': bars_in_trade,
                'mfe_pct': mfe_pct,
                'mae_pct': mae_pct,
                'net_pnl': net_pnl,
                'exit_reason': 'END',
                'is_winner': net_pnl > 0,
            })

    # Metrics
    total_pnl = sum(t['net_pnl'] for t in trades)
    wins = [t for t in trades if t['is_winner']]
    losses = [t for t in trades if not t['is_winner']]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    total_wins = sum(t['net_pnl'] for t in wins)
    total_losses = abs(sum(t['net_pnl'] for t in losses))
    pf = total_wins / total_losses if total_losses > 0 else float('inf')

    # Max drawdown
    equity = POSITION_SIZE
    peak = equity
    max_dd = 0
    for t in trades:
        equity += t['net_pnl']
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    avg_win = statistics.mean([t['net_pnl'] for t in wins]) if wins else 0
    avg_loss = statistics.mean([t['net_pnl'] for t in losses]) if losses else 0
    avg_bars = statistics.mean([t['bars_held'] for t in trades]) if trades else 0

    return {
        'name': filter_name,
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'pf': pf,
        'max_dd': max_dd,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'avg_bars': avg_bars,
        'trade_list': trades,
    }


# ========== DEFINE FILTERS ==========

def filter_none(candles, bar_idx, ind):
    """No filter - baseline."""
    return True

def filter_rsi_38(candles, bar_idx, ind):
    """Block entry if RSI > 38."""
    return ind['rsi'] <= 38

def filter_rsi_35(candles, bar_idx, ind):
    """Block entry if RSI > 35."""
    return ind['rsi'] <= 35

def filter_bb_width_lt_8(candles, bar_idx, ind):
    """Block entry if BB Width % < 8% (too low volatility = no room to bounce)."""
    return ind['bb_width_pct'] >= 8

def filter_bb_width_gt_35(candles, bar_idx, ind):
    """Block entry if BB Width % > 35% (extreme volatility)."""
    return ind['bb_width_pct'] <= 35

def filter_atr_lt_7(candles, bar_idx, ind):
    """Block entry if ATR% > 7 (extreme volatility)."""
    return ind['atr_pct'] <= 7

def filter_trend10_gt_neg25(candles, bar_idx, ind):
    """Block entry if 10-bar trend < -25% (extreme crash)."""
    return ind['trend_10'] >= -25

def filter_mae_stop_tighter(candles, bar_idx, ind):
    """Accept all entries but we'll test tighter stop separately."""
    return True

# === COMBINATION FILTERS ===

def filter_combo_rsi38_atr7(candles, bar_idx, ind):
    """RSI <= 38 AND ATR% <= 7."""
    return ind['rsi'] <= 38 and ind['atr_pct'] <= 7

def filter_combo_rsi38_trend25(candles, bar_idx, ind):
    """RSI <= 38 AND trend_10 >= -25%."""
    return ind['rsi'] <= 38 and ind['trend_10'] >= -25

def filter_bb_range_8_35(candles, bar_idx, ind):
    """BB Width between 8% and 35%."""
    return 8 <= ind['bb_width_pct'] <= 35

def filter_conservative_combo(candles, bar_idx, ind):
    """RSI <= 38 AND ATR% <= 7 AND trend_10 >= -25%."""
    return ind['rsi'] <= 38 and ind['atr_pct'] <= 7 and ind['trend_10'] >= -25

def filter_smart_volatility(candles, bar_idx, ind):
    """
    Smart vol: if BB width is narrow (<10%), require LOWER RSI (< 30) = deeper oversold.
    If BB width is wide (>10%), accept normal RSI < 40.
    This filters out "shallow dips in tight ranges" that don't bounce.
    """
    if ind['bb_width_pct'] < 10:
        return ind['rsi'] < 30
    return True

def filter_smart_vol_v2(candles, bar_idx, ind):
    """
    Smart vol V2:
    - Narrow BB (<10%): require RSI < 25 (very deep oversold only)
    - Medium BB (10-20%): normal (RSI < 40 already met)
    - Wide BB (>20%): require stronger vol spike > 3x
    """
    if ind['bb_width_pct'] < 10:
        return ind['rsi'] < 25
    elif ind['bb_width_pct'] > 20:
        return ind['vol_spike'] >= 3.0
    return True

def filter_mfe_2bar_lookback(candles, bar_idx, ind):
    """
    Look at the LAST 2 bars before entry: if the bounce was very weak
    (close barely above previous close by < 0.2%), skip.
    This is a proxy for momentum quality.
    """
    if bar_idx >= 2:
        prev2_close = candles[bar_idx - 2]['close']
        bounce_strength = (ind['close'] - prev2_close) / prev2_close * 100
        if bounce_strength < -2:  # Price still falling over 2 bars
            return False
    return True

def filter_distance_to_target(candles, bar_idx, ind):
    """
    Calculate distance from entry to target (DC mid or BB mid).
    If target is < 3% away, skip (not enough room for profit after fees).
    """
    target = min(ind['mid_channel'], ind['bb_mid'])
    distance_pct = (target - ind['close']) / ind['close'] * 100
    return distance_pct >= 3.0

def filter_distance_to_target_5(candles, bar_idx, ind):
    """Target must be >= 5% away."""
    target = min(ind['mid_channel'], ind['bb_mid'])
    distance_pct = (target - ind['close']) / ind['close'] * 100
    return distance_pct >= 5.0

def filter_distance_to_target_4(candles, bar_idx, ind):
    """Target must be >= 4% away."""
    target = min(ind['mid_channel'], ind['bb_mid'])
    distance_pct = (target - ind['close']) / ind['close'] * 100
    return distance_pct >= 4.0

def filter_target_risk_ratio(candles, bar_idx, ind):
    """
    Risk/Reward ratio: target distance must be >= 1.5x ATR stop distance.
    This ensures favorable R:R on every trade.
    """
    target = min(ind['mid_channel'], ind['bb_mid'])
    target_dist = target - ind['close']
    stop_dist = ind['atr'] * 2.0  # ATR stop mult
    if stop_dist > 0:
        rr = target_dist / stop_dist
        return rr >= 1.5
    return True

def filter_target_risk_ratio_2(candles, bar_idx, ind):
    """R:R >= 2.0."""
    target = min(ind['mid_channel'], ind['bb_mid'])
    target_dist = target - ind['close']
    stop_dist = ind['atr'] * 2.0
    if stop_dist > 0:
        rr = target_dist / stop_dist
        return rr >= 2.0
    return True


# ========== EARLY EXIT FILTERS ==========
# These are tested as modified exit logic, not entry filters

# ========== RUN ALL TESTS ==========

if __name__ == '__main__':
    print("=" * 130)
    print("  FILTER BACKTEST — Testing each proposed filter against V3 baseline")
    print("  Config: 1x$2000 all-in | V3 (RSI<40, VolSpike 2.0x, ATR 2.0x, BE 3%, TimeMax 16)")
    print("=" * 130)

    tests = [
        # Baseline
        ("V3 BASELINE (no filter)", None, None, 0, 0),

        # === ENTRY FILTERS ===
        ("Entry: RSI <= 38", filter_rsi_38, None, 0, 0),
        ("Entry: RSI <= 35", filter_rsi_35, None, 0, 0),
        ("Entry: BB Width >= 8%", filter_bb_width_lt_8, None, 0, 0),
        ("Entry: BB Width <= 35%", filter_bb_width_gt_35, None, 0, 0),
        ("Entry: ATR% <= 7", filter_atr_lt_7, None, 0, 0),
        ("Entry: Trend10 >= -25%", filter_trend10_gt_neg25, None, 0, 0),

        # === COMBINATION ENTRY FILTERS ===
        ("Combo: RSI<=38 + ATR<=7%", filter_combo_rsi38_atr7, None, 0, 0),
        ("Combo: RSI<=38 + Trend10>=-25%", filter_combo_rsi38_trend25, None, 0, 0),
        ("Combo: BB 8-35%", filter_bb_range_8_35, None, 0, 0),
        ("Combo: RSI<=38 + ATR<=7 + T10>=-25", filter_conservative_combo, None, 0, 0),

        # === SMART FILTERS ===
        ("Smart: Narrow BB=need deep RSI", filter_smart_volatility, None, 0, 0),
        ("Smart V2: BB-adaptive RSI+vol", filter_smart_vol_v2, None, 0, 0),
        ("Smart: 2-bar bounce quality", filter_mfe_2bar_lookback, None, 0, 0),

        # === TARGET DISTANCE FILTERS ===
        ("Target: dist >= 3%", filter_distance_to_target, None, 0, 0),
        ("Target: dist >= 4%", filter_distance_to_target_4, None, 0, 0),
        ("Target: dist >= 5%", filter_distance_to_target_5, None, 0, 0),
        ("Target: R:R >= 1.5", filter_target_risk_ratio, None, 0, 0),
        ("Target: R:R >= 2.0", filter_target_risk_ratio_2, None, 0, 0),

        # === EARLY EXIT FILTERS ===
        ("Early Exit: MFE<0.5% after 2 bars", None, None, 2, 0.5),
        ("Early Exit: MFE<1.0% after 2 bars", None, None, 2, 1.0),
        ("Early Exit: MFE<1.0% after 3 bars", None, None, 3, 1.0),
        ("Early Exit: MFE<0.5% after 3 bars", None, None, 3, 0.5),
        ("Early Exit: MFE<2.0% after 4 bars", None, None, 4, 2.0),

        # === BEST COMBO CANDIDATES ===
        # Combine best entry filter + best early exit
    ]

    results = []
    for name, entry_fn, exit_fn, ee_bars, ee_threshold in tests:
        r = run_filtered_backtest(name, entry_fn, exit_fn, ee_bars, ee_threshold)
        results.append(r)
        print(f"  {name:<45} | Trades: {r['trades']:>3} | WR: {r['win_rate']:>5.1f}% | "
              f"P&L: ${r['total_pnl']:>+9.2f} | PF: {r['pf']:>6.2f} | DD: {r['max_dd']:>5.1f}% | "
              f"AvgW: ${r['avg_win']:>+7.0f} | AvgL: ${r['avg_loss']:>+7.0f} | AvgBars: {r['avg_bars']:>4.1f}")

    # Now run best combinations
    print("\n" + "=" * 130)
    print("  BEST COMBINATION FILTERS")
    print("=" * 130)

    # Find best entry filter and best early exit
    baseline = results[0]

    # Build combo tests dynamically based on top results
    combo_tests = []

    # Combo 1: Smart Vol + early exit 2bar MFE<0.5%
    combo_tests.append(("COMBO: SmartVol + EE 2b<0.5%", filter_smart_volatility, None, 2, 0.5))
    # Combo 2: Target dist >= 3% + early exit
    combo_tests.append(("COMBO: TargDist>=3% + EE 2b<0.5%", filter_distance_to_target, None, 2, 0.5))
    # Combo 3: Target dist >= 4% + SmartVol
    combo_tests.append(("COMBO: TargDist>=4% + SmartVol",
                        lambda c,b,i: filter_distance_to_target_4(c,b,i) and filter_smart_volatility(c,b,i),
                        None, 0, 0))
    # Combo 4: BB range + R:R >= 1.5
    combo_tests.append(("COMBO: BB 8-35% + R:R>=1.5",
                        lambda c,b,i: filter_bb_range_8_35(c,b,i) and filter_target_risk_ratio(c,b,i),
                        None, 0, 0))
    # Combo 5: RSI<=38 + Target>=3% + EE
    combo_tests.append(("COMBO: RSI38 + Targ>=3% + EE2b",
                        lambda c,b,i: filter_rsi_38(c,b,i) and filter_distance_to_target(c,b,i),
                        None, 2, 0.5))
    # Combo 6: SmartV2 + Target>=4%
    combo_tests.append(("COMBO: SmartV2 + Targ>=4%",
                        lambda c,b,i: filter_smart_vol_v2(c,b,i) and filter_distance_to_target_4(c,b,i),
                        None, 0, 0))
    # Combo 7: SmartV2 + R:R>=1.5 + EE
    combo_tests.append(("COMBO: SmartV2 + R:R>=1.5 + EE2b",
                        lambda c,b,i: filter_smart_vol_v2(c,b,i) and filter_target_risk_ratio(c,b,i),
                        None, 2, 0.5))
    # Combo 8: Conservative but with target distance
    combo_tests.append(("COMBO: RSI38+ATR7+Targ>=3%",
                        lambda c,b,i: filter_combo_rsi38_atr7(c,b,i) and filter_distance_to_target(c,b,i),
                        None, 0, 0))
    # Combo 9: Everything smart together
    combo_tests.append(("COMBO: SmartV2+Targ>=3%+EE2b<0.5",
                        lambda c,b,i: filter_smart_vol_v2(c,b,i) and filter_distance_to_target(c,b,i),
                        None, 2, 0.5))
    # Combo 10: Only tighter time max (12 bars instead of 16) — test as early exit at 12
    combo_tests.append(("TimerTighter: TimeMax=12bars", None, None, 12, -999))  # -999 = always exit at bar 12

    for name, entry_fn, exit_fn, ee_bars, ee_threshold in combo_tests:
        r = run_filtered_backtest(name, entry_fn, exit_fn, ee_bars, ee_threshold)
        results.append(r)
        print(f"  {name:<45} | Trades: {r['trades']:>3} | WR: {r['win_rate']:>5.1f}% | "
              f"P&L: ${r['total_pnl']:>+9.2f} | PF: {r['pf']:>6.2f} | DD: {r['max_dd']:>5.1f}% | "
              f"AvgW: ${r['avg_win']:>+7.0f} | AvgL: ${r['avg_loss']:>+7.0f} | AvgBars: {r['avg_bars']:>4.1f}")

    # ========== FINAL RANKING ==========
    print("\n" + "=" * 130)
    print("  FINAL RANKING — Sorted by P&L")
    print("=" * 130)

    # Composite score
    for r in results:
        pnl_norm = min(1, max(0, (r['total_pnl'] + 2000) / 12000))
        pf_norm = min(1, max(0, (r['pf'] - 0.5) / 9.5))
        wr_norm = r['win_rate'] / 100
        dd_penalty = max(0, 1 - r['max_dd'] / 50)
        trade_norm = min(1, r['trades'] / 80)
        r['score'] = pnl_norm * 35 + pf_norm * 25 + wr_norm * 15 + dd_penalty * 15 + trade_norm * 10

    sorted_results = sorted(results, key=lambda x: x['score'], reverse=True)

    print(f"\n  {'#':>2} {'FILTER':<45} | {'Trades':>6} | {'WR':>6} | {'P&L':>12} | {'PF':>6} | {'DD':>6} | {'Score':>6} | {'vs Base':>10}")
    print("  " + "-" * 130)
    for i, r in enumerate(sorted_results):
        diff = r['total_pnl'] - baseline['total_pnl']
        marker = " <<<" if i == 0 else ""
        print(f"  {i+1:>2} {r['name']:<45} | {r['trades']:>6} | {r['win_rate']:>5.1f}% | "
              f"${r['total_pnl']:>+9.2f} | {r['pf']:>5.2f} | {r['max_dd']:>5.1f}% | {r['score']:>5.1f} | "
              f"${diff:>+8.2f}{marker}")

    # ========== IMPROVEMENT ANALYSIS ==========
    print("\n" + "=" * 130)
    print("  IMPROVEMENT ANALYSIS — Filters that BEAT baseline")
    print("=" * 130)

    improvements = [r for r in sorted_results if r['total_pnl'] > baseline['total_pnl'] and r['name'] != baseline['name']]

    if improvements:
        for r in improvements:
            diff = r['total_pnl'] - baseline['total_pnl']
            trades_diff = r['trades'] - baseline['trades']
            wr_diff = r['win_rate'] - baseline['win_rate']
            pf_diff = r['pf'] - baseline['pf']
            print(f"\n  {r['name']}")
            print(f"    P&L improvement:  ${diff:>+.2f}")
            print(f"    Trades:           {r['trades']} ({trades_diff:+d})")
            print(f"    Win Rate:         {r['win_rate']:.1f}% ({wr_diff:+.1f}%)")
            print(f"    Profit Factor:    {r['pf']:.2f} ({pf_diff:+.2f})")
            print(f"    Max Drawdown:     {r['max_dd']:.1f}%")

            # Show which trades were removed/added
            base_pairs = set(t['pair'] for t in baseline['trade_list'])
            filter_pairs = set(t['pair'] for t in r['trade_list'])
            removed = base_pairs - filter_pairs
            if removed:
                removed_trades = [t for t in baseline['trade_list'] if t['pair'] in removed]
                removed_pnl = sum(t['net_pnl'] for t in removed_trades)
                print(f"    Removed coins:    {', '.join(sorted(removed))} (P&L impact: ${removed_pnl:+.2f})")
    else:
        print("\n  No filter improved over baseline P&L. All filters reduce total P&L.")
        print("  This means the current V3 strategy is well-optimized for this period.")
        print("\n  However, filters may still improve RISK-ADJUSTED returns (PF, DD, WR):")

        risk_improvements = [r for r in sorted_results if r['name'] != baseline['name'] and
                            (r['pf'] > baseline['pf'] or r['max_dd'] < baseline['max_dd'] or r['win_rate'] > baseline['win_rate'])]
        for r in risk_improvements[:5]:
            pf_diff = r['pf'] - baseline['pf']
            dd_diff = r['max_dd'] - baseline['max_dd']
            wr_diff = r['win_rate'] - baseline['win_rate']
            pnl_diff = r['total_pnl'] - baseline['total_pnl']
            improvements_list = []
            if pf_diff > 0: improvements_list.append(f"PF {pf_diff:+.2f}")
            if dd_diff < 0: improvements_list.append(f"DD {dd_diff:+.1f}%")
            if wr_diff > 0: improvements_list.append(f"WR {wr_diff:+.1f}%")
            if improvements_list:
                print(f"    {r['name']:<45} | P&L ${pnl_diff:>+8.2f} | {', '.join(improvements_list)}")

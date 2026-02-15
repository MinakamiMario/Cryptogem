#!/usr/bin/env python3
"""
Backtest Timeframe Test
========================
Test de winnende V2 strategie op kortere timeframes:
  - 4H (240 min) — baseline, huidige setup
  - 2H (120 min) — meer trades, korter houden
  - 1H (60 min)  — maximale trade frequentie

Doel: bepalen of kortere timeframes meer winstgevend zijn door
hogere trade frequentie, of dat de strategie dan te veel noise oppikt.

Gebruik:
    python backtest_timeframe_test.py
"""
import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

load_dotenv(BASE_DIR / '.env')

KRAKEN_FEE = 0.0026

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('timeframe_test')


def fetch_candles_for_timeframe(interval_min=240, days=30):
    """Fetch candles for a specific timeframe interval."""
    cache_file = BASE_DIR / f'candle_cache_{interval_min}m_{days}d.json'

    if cache_file.exists():
        with open(cache_file) as f:
            cache = json.load(f)
        cache_age = time.time() - cache.get('_timestamp', 0)
        if cache_age < 14400:  # 4 uur cache
            coins = len([k for k in cache if not k.startswith('_')])
            logger.info(f"Cache geladen: {coins} coins, {interval_min}m/{days}d (age={cache_age/3600:.1f}h)")
            return cache

    from kraken_client import KrakenClient
    api_key = os.getenv('KRAKEN_API_KEY', '')
    private_key = os.getenv('KRAKEN_PRIVATE_KEY', '')
    client = KrakenClient(api_key, private_key)

    coins_str = os.getenv('COINS', '')
    coins = [c.strip() for c in coins_str.split(',') if c.strip()]

    since = int((datetime.now(timezone.utc) - timedelta(days=days + 3)).timestamp())
    cache = {'_timestamp': time.time(), '_days': days, '_interval': interval_min}
    fetched = 0
    errors = 0

    logger.info(f"Fetching {days}d candles ({interval_min}m interval) voor {len(coins)} coins...")

    for i, pair in enumerate(coins):
        try:
            candles = client.get_ohlc(pair, interval=interval_min, since=since)
            if candles and len(candles) >= 30:
                cache[pair] = candles
                fetched += 1
            if (i + 1) % 50 == 0:
                logger.info(f"  {i+1}/{len(coins)} ({fetched} OK, {errors} errors)")
        except Exception as e:
            errors += 1

    logger.info(f"Fetch compleet: {fetched} coins, {errors} errors ({interval_min}m interval)")

    with open(cache_file, 'w') as f:
        json.dump(cache, f)

    return cache


class DualConfirmV2:
    """Stripped-down V2 strategy for timeframe testing."""

    def __init__(self, rsi_max=40, atr_stop_mult=3.0, volume_spike_mult=2.0,
                 breakeven_trigger_pct=3.0, cooldown_bars=4, cooldown_stop=8,
                 donchian_period=20, bb_period=20, bb_dev=2.0,
                 max_stop_loss_pct=15.0):
        self.rsi_max = rsi_max
        self.atr_stop_mult = atr_stop_mult
        self.volume_spike_mult = volume_spike_mult
        self.breakeven_trigger_pct = breakeven_trigger_pct
        self.cooldown_bars = cooldown_bars
        self.cooldown_stop = cooldown_stop
        self.donchian_period = donchian_period
        self.bb_period = bb_period
        self.bb_dev = bb_dev
        self.max_stop_loss_pct = max_stop_loss_pct
        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0


@dataclass
class TestPosition:
    pair: str
    entry_price: float
    entry_bar: int
    stop_price: float
    highest_price: float
    size_usd: float


def run_backtest(all_candles, max_positions=1, position_size=2000,
                 interval_label="4H", use_vol_spike=True, use_breakeven=True):
    """Run single-coin V2 backtest on given candle data."""
    coins = [k for k in all_candles if not k.startswith('_')]

    strategies = {}
    for pair in coins:
        strategies[pair] = DualConfirmV2()

    max_bars = max(len(all_candles[pair]) for pair in coins if pair in all_candles and not pair.startswith('_'))

    positions = {}
    trades = []
    equity = max_positions * position_size
    initial_equity = equity
    peak_equity = equity
    max_dd = 0
    total_bars = 0

    for bar_idx in range(50, max_bars):
        buy_signals = []
        sell_signals = []

        for pair in coins:
            candles = all_candles.get(pair, [])
            if bar_idx >= len(candles):
                continue

            window = candles[:bar_idx + 1]
            strat = strategies[pair]
            strat.bar_count = len(window)

            closes = [c['close'] for c in window]
            highs = [c['high'] for c in window]
            lows = [c['low'] for c in window]
            volumes = [c.get('volume', 0) for c in window]

            min_bars_needed = max(strat.donchian_period, strat.bb_period, strat.rsi_max, 14) + 5
            if len(window) < min_bars_needed:
                continue

            rsi = calc_rsi(closes, 14)
            atr = calc_atr(highs, lows, closes, 14)
            _, prev_lowest, _ = calc_donchian(highs[:-1], lows[:-1], strat.donchian_period)
            hh, ll, mid_channel = calc_donchian(highs, lows, strat.donchian_period)
            bb_mid, bb_upper, bb_lower = calc_bollinger(closes, strat.bb_period, strat.bb_dev)

            if any(v is None for v in [rsi, atr, prev_lowest, mid_channel, bb_mid, bb_lower]):
                continue

            close = closes[-1]
            low_val = lows[-1]
            prev_close = closes[-2] if len(closes) > 1 else close

            pos = positions.get(pair)

            if pos:
                # EXIT logic
                if close > pos.highest_price:
                    pos.highest_price = close

                new_stop = pos.highest_price - atr * strat.atr_stop_mult
                hard_stop = pos.entry_price * (1 - strat.max_stop_loss_pct / 100)
                if new_stop < hard_stop:
                    new_stop = hard_stop

                # Break-even stop
                if use_breakeven:
                    profit_pct = (close - pos.entry_price) / pos.entry_price * 100
                    if profit_pct >= strat.breakeven_trigger_pct:
                        be_level = pos.entry_price * 1.006
                        if new_stop < be_level:
                            new_stop = be_level

                if new_stop > pos.stop_price:
                    pos.stop_price = new_stop

                reason = None
                is_stop = False

                if close < hard_stop:
                    reason = 'HARD STOP'
                    is_stop = True
                elif close >= mid_channel:
                    reason = 'DC TARGET'
                elif close >= bb_mid:
                    reason = 'BB TARGET'
                elif rsi > 70:
                    reason = 'RSI EXIT'
                elif close < pos.stop_price:
                    reason = 'TRAIL STOP'
                    is_stop = True

                if reason:
                    sell_signals.append((pair, close, reason, is_stop))
            else:
                # ENTRY logic
                cd_needed = strat.cooldown_stop if strat.last_exit_was_stop else strat.cooldown_bars
                if (strat.bar_count - strat.last_exit_bar) < cd_needed:
                    continue

                # Volume filters
                vol_avg = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 0
                if vol_avg > 0 and volumes[-1] < vol_avg * 0.5:
                    continue

                # Dual confirm
                dc_ok = (low_val <= prev_lowest and rsi < strat.rsi_max and close > prev_close)
                bb_ok = (close <= bb_lower and rsi < strat.rsi_max and close > prev_close)

                if not (dc_ok and bb_ok):
                    continue

                # Volume spike
                if use_vol_spike and vol_avg > 0:
                    if volumes[-1] < vol_avg * strat.volume_spike_mult:
                        continue

                stop = close - atr * strat.atr_stop_mult
                hard_s = close * (1 - strat.max_stop_loss_pct / 100)
                if stop < hard_s:
                    stop = hard_s

                vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1
                buy_signals.append((pair, close, stop, vol_ratio))

        # Process sells
        for pair, price, reason, is_stop in sell_signals:
            pos = positions[pair]
            gross_pnl = (price - pos.entry_price) / pos.entry_price * pos.size_usd
            fee = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross_pnl) * KRAKEN_FEE
            net_pnl = gross_pnl - fee
            equity += net_pnl
            bars_held = bar_idx - pos.entry_bar
            total_bars += bars_held

            strat = strategies[pair]
            strat.last_exit_bar = strat.bar_count
            strat.last_exit_was_stop = is_stop

            trades.append({
                'pair': pair, 'entry': pos.entry_price, 'exit': price,
                'pnl': net_pnl, 'reason': reason, 'bars': bars_held,
                'is_target': 'STOP' not in reason,
            })
            del positions[pair]

        # Process buys (ranked by volume ratio)
        if len(positions) < max_positions and buy_signals:
            buy_signals.sort(key=lambda x: x[3], reverse=True)
            for pair, price, stop, vol_r in buy_signals:
                if len(positions) >= max_positions:
                    break
                positions[pair] = TestPosition(pair, price, bar_idx, stop, price, position_size)

        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Close remaining
    for pair, pos in list(positions.items()):
        candles = all_candles.get(pair, [])
        if candles:
            price = candles[-1]['close']
            gross = (price - pos.entry_price) / pos.entry_price * pos.size_usd
            fee = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
            net = gross - fee
            equity += net
            trades.append({'pair': pair, 'entry': pos.entry_price, 'exit': price,
                           'pnl': net, 'reason': 'END', 'bars': max_bars - pos.entry_bar, 'is_target': False})

    # Metrics
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    avg_w = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_l = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    total_w = sum(t['pnl'] for t in wins)
    total_l = abs(sum(t['pnl'] for t in losses))
    pf = total_w / total_l if total_l > 0 else float('inf')
    roi = total_pnl / initial_equity * 100
    avg_bars = total_bars / len(trades) if trades else 0
    stops = len([t for t in trades if 'STOP' in t.get('reason', '')])
    targets = len([t for t in trades if t['is_target']])
    trades_per_day = len(trades) / (all_candles.get('_days', 30))

    return {
        'interval': interval_label,
        'trades': len(trades),
        'trades_per_day': trades_per_day,
        'wr': wr,
        'pnl': total_pnl,
        'roi': roi,
        'pf': pf,
        'max_dd': max_dd,
        'avg_win': avg_w,
        'avg_loss': avg_l,
        'avg_bars': avg_bars,
        'targets': targets,
        'stops': stops,
        'coins': len(coins),
        'max_bars': max_bars,
    }


def main():
    # Test timeframes: 4H (baseline), 2H, 1H
    timeframes = [
        (240, '4H', 60),   # 4H candles, 60 days
        (120, '2H', 30),   # 2H candles, 30 days (Kraken limit)
        (60,  '1H', 14),   # 1H candles, 14 days (Kraken limit smaller for 1H)
    ]

    print()
    print("=" * 120)
    print("  TIMEFRAME TEST — V2 strategie op verschillende timeframes")
    print("  Config: DualConfirm V2 | RSI<40 | VolSpike >2.0x | BE stop +3% | 1x$2000 | 0.26% fee")
    print("=" * 120)

    results = []

    for interval, label, days in timeframes:
        logger.info(f"\n=== Testing {label} ({interval}m) over {days} days ===")
        try:
            data = fetch_candles_for_timeframe(interval, days)
            coins = len([k for k in data if not k.startswith('_')])
            logger.info(f"Data: {coins} coins, {days} days, {label} candles")

            result = run_backtest(data, max_positions=1, position_size=2000,
                                  interval_label=label, use_vol_spike=True, use_breakeven=True)
            results.append(result)

            logger.info(f"  {label}: {result['trades']} trades ({result['trades_per_day']:.1f}/day), "
                         f"P&L ${result['pnl']:+.0f}, PF {result['pf']:.2f}, WR {result['wr']:.1f}%")
        except Exception as e:
            logger.error(f"Error testing {label}: {e}")
            import traceback
            traceback.print_exc()

    # Results table
    print()
    print("=" * 120)
    print("  RESULTATEN")
    print("=" * 120)
    print(f"  {'TF':>4} | {'Days':>4} | {'#TR':>4} | {'TR/DAY':>7} | {'WR':>6} | {'P&L':>10} | {'ROI':>8} | "
          f"{'PF':>6} | {'DD':>6} | {'AvgW':>8} | {'AvgL':>8} | {'AvgBars':>7} | {'TGT':>3} | {'STP':>3}")
    print("  " + "-" * 118)

    for r in results:
        print(f"  {r['interval']:>4} | {r.get('coins', 0):>4} | {r['trades']:>4} | "
              f"{r['trades_per_day']:>6.2f} | {r['wr']:>5.1f}% | "
              f"${r['pnl']:>+8.0f} | {r['roi']:>+6.1f}% | "
              f"{r['pf']:>5.2f} | {r['max_dd']:>5.1f}% | "
              f"${r['avg_win']:>+6.0f} | ${r['avg_loss']:>+6.0f} | "
              f"{r['avg_bars']:>6.1f} | {r['targets']:>3} | {r['stops']:>3}")

    # Comparison
    if len(results) >= 2:
        print()
        print("=" * 120)
        print("  VERGELIJKING")
        print("=" * 120)
        base = results[0]  # 4H
        for r in results[1:]:
            pnl_norm_base = base['pnl'] / base.get('coins', 285) * 285 if base.get('coins', 0) > 0 else 0
            pnl_norm = r['pnl'] / r.get('coins', 285) * 285 if r.get('coins', 0) > 0 else 0

            print(f"\n  {r['interval']} vs 4H (baseline):")
            print(f"    Trades/dag:     {r['trades_per_day']:.2f} vs {base['trades_per_day']:.2f} "
                  f"({r['trades_per_day']/max(0.01, base['trades_per_day']):.1f}x)")
            print(f"    Win Rate:       {r['wr']:.1f}% vs {base['wr']:.1f}% ({r['wr'] - base['wr']:+.1f}%)")
            print(f"    Profit Factor:  {r['pf']:.2f} vs {base['pf']:.2f}")
            print(f"    Max Drawdown:   {r['max_dd']:.1f}% vs {base['max_dd']:.1f}%")

    print()
    print("=" * 120)


if __name__ == '__main__':
    main()

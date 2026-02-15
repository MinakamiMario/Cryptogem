#!/usr/bin/env python3
"""
Backtest V4 DualConfirm op ALLE 532 dynamisch ontdekte Kraken coins
====================================================================
Downloadt verse candle data voor alle coins via Kraken API,
draait de V4 strategie (met V5 RSI Recovery exit), en vergelijkt
resultaten met de oude 289 hardcoded coins.

Gebruik:
    python backtest_532_coins.py                 # Download + backtest
    python backtest_532_coins.py --cache-only    # Alleen uit cache
    python backtest_532_coins.py --refresh       # Forceer verse data
"""
import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

load_dotenv(BASE_DIR / '.env')

CACHE_FILE = BASE_DIR / 'candle_cache_532.json'
KRAKEN_FEE = 0.0026  # 0.26%

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger('backtest_532')


# ============================================================
# DATA LOADING - Download alle candles van Kraken
# ============================================================

def download_all_candles(force_refresh=False) -> dict:
    """
    Download 4H candles voor alle dynamisch ontdekte Kraken USD pairs.
    Cached resultaat naar candle_cache_532.json.
    """
    # Check cache
    if not force_refresh and CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                cache = json.load(f)
            age_hours = (time.time() - cache.get('_timestamp', 0)) / 3600
            coin_count = len([k for k in cache if not k.startswith('_')])
            if age_hours < 24 and coin_count > 400:
                logger.info(f"Cache geladen: {coin_count} coins, "
                            f"{age_hours:.1f}h oud")
                return cache
            logger.info(f"Cache te oud ({age_hours:.1f}h) of te weinig coins "
                        f"({coin_count}), ververs...")
        except Exception as e:
            logger.warning(f"Cache laden gefaald: {e}")

    from kraken_client import KrakenClient
    client = KrakenClient('', '')  # Public API, geen keys nodig

    # Discover alle pairs
    pairs = client.discover_all_usd_pairs(force_refresh=True)
    pair_list = sorted(pairs.keys())
    logger.info(f"Downloading candles voor {len(pair_list)} coins...")

    all_candles = {
        '_timestamp': time.time(),
        '_date': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        '_coins': len(pair_list),
    }

    errors = 0
    skipped = 0
    downloaded = 0

    for i, pair in enumerate(pair_list):
        try:
            candles = client.get_ohlc(pair, interval=240)
            if candles and len(candles) >= 30:
                all_candles[pair] = candles
                downloaded += 1
            else:
                skipped += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                logger.warning(f"  Error {pair}: {e}")

        # Progress
        if (i + 1) % 50 == 0:
            logger.info(f"  {i+1}/{len(pair_list)} coins geladen "
                        f"(OK: {downloaded}, skip: {skipped}, err: {errors})")
            time.sleep(0.5)  # Gentle rate limiting

    logger.info(f"Download klaar: {downloaded} coins geladen, "
                f"{skipped} skipped, {errors} errors")

    # Save cache
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(all_candles, f)
        size_mb = CACHE_FILE.stat().st_size / 1024 / 1024
        logger.info(f"Cache opgeslagen: {CACHE_FILE.name} ({size_mb:.1f} MB)")
    except Exception as e:
        logger.warning(f"Cache opslaan gefaald: {e}")

    return all_candles


# ============================================================
# V4 DUALCONFIRM + V5 RSI RECOVERY STRATEGY
# ============================================================

class V4Strategy:
    """
    DualConfirm V4 + V5 RSI Recovery exit.
    Exact dezelfde parameters als de productie-strategie.

    Entry: DC+BB dual confirm, RSI<40, VolSpike>2x, VolConfirm>1x
    Exit: ATR 2.0x trail, BE+3%, TimeMax 10 bars, RSI Recovery target=47
    """

    def __init__(self):
        # Entry params
        self.donchian_period = 20
        self.bb_period = 20
        self.bb_dev = 2.0
        self.rsi_period = 14
        self.rsi_max = 40  # V4 param
        self.atr_period = 14
        self.atr_stop_mult = 2.0
        self.max_stop_loss_pct = 15.0
        self.cooldown_bars = 4
        self.cooldown_after_stop = 8
        self.volume_min_pct = 0.5
        self.volume_spike_mult = 2.0
        self.vol_confirm_mult = 1.0  # V4: >1x vorige bar

        # Exit params
        self.breakeven_trigger_pct = 3.0
        self.time_max_bars = 10
        self.rsi_sell = 70

        # V5: RSI Recovery exit
        self.rsi_recovery_target = 47
        self.rsi_recovery_min_bars = 2

        # State
        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def analyze(self, candles, position, pair):
        min_bars = max(self.donchian_period, self.bb_period,
                       self.rsi_period, self.atr_period) + 5
        if len(candles) < min_bars:
            return {'action': 'WAIT', 'reason': 'Niet genoeg data'}

        self.bar_count = len(candles)
        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]

        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)

        prev_highs = highs[:-1]
        prev_lows = lows[:-1]
        _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows,
                                          self.donchian_period)
        hh, ll, mid_channel = calc_donchian(highs, lows, self.donchian_period)
        bb_mid, bb_upper, bb_lower = calc_bollinger(closes, self.bb_period,
                                                    self.bb_dev)

        if any(v is None for v in [rsi, atr, prev_lowest, mid_channel,
                                   bb_mid, bb_lower]):
            return {'action': 'WAIT', 'reason': 'Indicators niet klaar'}

        current = candles[-1]
        close = current['close']
        low = current['low']
        prev_close = candles[-2]['close'] if len(candles) > 1 else close

        # ── EXIT LOGICA ──
        if position:
            entry_price = position['entry_price']
            bars_in_trade = self.bar_count - position['entry_bar']

            if close > position['highest_price']:
                position['highest_price'] = close

            new_stop = position['highest_price'] - atr * self.atr_stop_mult
            hard_stop = entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < hard_stop:
                new_stop = hard_stop

            # Break-even stop
            profit_pct = (close - entry_price) / entry_price * 100
            if profit_pct >= self.breakeven_trigger_pct:
                breakeven_level = entry_price * (1 + KRAKEN_FEE * 2)
                if new_stop < breakeven_level:
                    new_stop = breakeven_level

            if new_stop > position['stop_price']:
                position['stop_price'] = new_stop

            # Exit 1: Hard stop
            if close < hard_stop:
                return {'action': 'SELL', 'reason': 'HARD STOP',
                        'price': close}

            # Exit 2: Time max
            if bars_in_trade >= self.time_max_bars:
                return {'action': 'SELL', 'reason': 'TIME MAX',
                        'price': close}

            # Exit 3: V5 RSI Recovery exit
            if (bars_in_trade >= self.rsi_recovery_min_bars
                    and rsi >= self.rsi_recovery_target):
                return {'action': 'SELL', 'reason': 'RSI RECOVERY',
                        'price': close}

            # Exit 4: DC mid channel target
            if close >= mid_channel:
                return {'action': 'SELL', 'reason': 'DC TARGET',
                        'price': close}

            # Exit 5: BB mid target
            if close >= bb_mid:
                return {'action': 'SELL', 'reason': 'BB TARGET',
                        'price': close}

            # Exit 6: RSI overbought
            if rsi > self.rsi_sell:
                return {'action': 'SELL', 'reason': 'RSI EXIT',
                        'price': close}

            # Exit 7: Trailing stop
            if close < position['stop_price']:
                return {'action': 'SELL', 'reason': 'TRAIL STOP',
                        'price': close}

            return {'action': 'HOLD', 'price': close}

        # ── ENTRY LOGICA ──
        cooldown_needed = (self.cooldown_after_stop if self.last_exit_was_stop
                           else self.cooldown_bars)
        if (self.bar_count - self.last_exit_bar) < cooldown_needed:
            return {'action': 'WAIT', 'reason': 'Cooldown'}

        # Volume filter (base)
        if volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_min_pct:
                return {'action': 'WAIT', 'reason': 'Volume te laag'}

        # DUAL CONFIRM ENTRY
        dc_signal = (low <= prev_lowest and rsi < self.rsi_max
                     and close > prev_close)
        bb_signal = (close <= bb_lower and rsi < self.rsi_max
                     and close > prev_close)

        if not (dc_signal and bb_signal):
            return {'action': 'WAIT', 'reason': 'Geen dual confirm'}

        # Volume spike filter (>2x avg)
        if volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
                return {'action': 'WAIT', 'reason': 'Volume spike <2x'}

        # Volume bar-to-bar confirmation (>1x prev bar)
        if len(volumes) >= 2 and volumes[-2] > 0:
            if volumes[-1] / volumes[-2] < self.vol_confirm_mult:
                return {'action': 'WAIT', 'reason': 'Vol confirm <1x'}

        # ENTRY!
        stop = close - atr * self.atr_stop_mult
        hard_stop = close * (1 - self.max_stop_loss_pct / 100)
        if stop < hard_stop:
            stop = hard_stop

        # Quality score
        rsi_score = max(0, (self.rsi_max - rsi) / self.rsi_max)
        dc_depth = ((prev_lowest - low) / prev_lowest
                    if prev_lowest > 0 else 0)
        depth_score = min(1, dc_depth * 20)
        vol_score = 0
        if volumes and vol_avg > 0:
            vol_ratio = volumes[-1] / vol_avg
            vol_score = min(1, vol_ratio / 3)
        quality = rsi_score * 0.4 + depth_score * 0.3 + vol_score * 0.3

        return {'action': 'BUY', 'reason': 'DUAL CONFIRM V4+V5',
                'price': close, 'stop_price': stop, 'quality': quality}


# ============================================================
# PORTFOLIO BACKTEST ENGINE
# ============================================================

@dataclass
class BacktestPosition:
    pair: str
    entry_price: float
    entry_bar: int
    stop_price: float
    highest_price: float
    size_usd: float


def run_backtest(all_candles: dict, coin_list: List[str],
                 label: str = "", max_positions: int = 1,
                 position_size: float = 2000) -> dict:
    """
    Portfolio backtest: chronologisch over alle coins,
    1x$2000 all-in, volume ranking, V4+V5 strategie.
    """
    coins = [c for c in coin_list if c in all_candles]

    strategies = {pair: V4Strategy() for pair in coins}

    max_bars = max(
        len(all_candles[p]) for p in coins
        if p in all_candles
    ) if coins else 0

    positions = {}
    trades = []
    equity = max_positions * position_size
    initial_equity = equity
    peak_equity = equity
    max_dd = 0

    for bar_idx in range(50, max_bars):
        buy_signals = []
        sell_signals = []

        for pair in coins:
            candles = all_candles.get(pair, [])
            if bar_idx >= len(candles):
                continue

            window = candles[:bar_idx + 1]
            pos = positions.get(pair)

            pos_dict = None
            if pos:
                pos_dict = {
                    'entry_price': pos.entry_price,
                    'stop_price': pos.stop_price,
                    'highest_price': pos.highest_price,
                    'entry_bar': pos.entry_bar,
                }

            strategy = strategies[pair]
            signal = strategy.analyze(window, pos_dict, pair)

            if pos_dict and pos:
                pos.stop_price = pos_dict['stop_price']
                pos.highest_price = pos_dict['highest_price']

            if signal['action'] == 'SELL' and pair in positions:
                sell_signals.append((pair, signal))
            elif signal['action'] == 'BUY' and pair not in positions:
                buy_signals.append((pair, signal, candles[bar_idx]))

        # Process SELLS
        for pair, signal in sell_signals:
            pos = positions[pair]
            sell_price = signal['price']

            gross_pnl = ((sell_price - pos.entry_price) / pos.entry_price
                         * pos.size_usd)
            fee_cost = (pos.size_usd * KRAKEN_FEE
                        + (pos.size_usd + gross_pnl) * KRAKEN_FEE)
            net_pnl = gross_pnl - fee_cost

            equity += net_pnl
            bars_held = bar_idx - pos.entry_bar

            is_stop = 'STOP' in signal.get('reason', '')
            strategy = strategies[pair]
            strategy.last_exit_bar = strategy.bar_count
            strategy.last_exit_was_stop = is_stop

            trades.append({
                'pair': pair,
                'entry': pos.entry_price,
                'exit': sell_price,
                'pnl': net_pnl,
                'reason': signal['reason'],
                'bars': bars_held,
            })

            del positions[pair]

        # Process BUYS (volume ranking)
        if len(positions) < max_positions and buy_signals:
            def rank_signal(item):
                pair, sig, candle = item
                candles_data = all_candles.get(pair, [])
                vols = [c.get('volume', 0)
                        for c in candles_data[max(0, bar_idx-20):bar_idx+1]]
                if vols and len(vols) > 1:
                    avg_vol = sum(vols[:-1]) / max(1, len(vols) - 1)
                    if avg_vol > 0:
                        return vols[-1] / avg_vol
                return 0
            buy_signals.sort(key=rank_signal, reverse=True)

            for pair, signal, candle in buy_signals:
                if len(positions) >= max_positions:
                    break
                positions[pair] = BacktestPosition(
                    pair=pair,
                    entry_price=signal['price'],
                    entry_bar=bar_idx,
                    stop_price=signal.get('stop_price', signal['price'] * 0.85),
                    highest_price=signal['price'],
                    size_usd=position_size,
                )

        # Track drawdown
        if equity > peak_equity:
            peak_equity = equity
        dd = ((peak_equity - equity) / peak_equity * 100
              if peak_equity > 0 else 0)
        if dd > max_dd:
            max_dd = dd

    # Close remaining
    for pair, pos in list(positions.items()):
        candles = all_candles.get(pair, [])
        if candles:
            last_price = candles[-1]['close']
            gross_pnl = ((last_price - pos.entry_price) / pos.entry_price
                         * pos.size_usd)
            fee_cost = (pos.size_usd * KRAKEN_FEE
                        + (pos.size_usd + gross_pnl) * KRAKEN_FEE)
            net_pnl = gross_pnl - fee_cost
            equity += net_pnl
            trades.append({
                'pair': pair, 'entry': pos.entry_price,
                'exit': last_price, 'pnl': net_pnl,
                'reason': 'END', 'bars': max_bars - pos.entry_bar,
            })

    # Metrics
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    total_wins = sum(t['pnl'] for t in wins)
    total_losses = abs(sum(t['pnl'] for t in losses))
    pf = total_wins / total_losses if total_losses > 0 else float('inf')
    roi = total_pnl / initial_equity * 100 if initial_equity else 0

    return {
        'label': label,
        'coins_scanned': len(coins),
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'roi': roi,
        'pf': pf,
        'max_dd': max_dd,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'trade_list': trades,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Backtest V4+V5 op alle 532 Kraken coins')
    parser.add_argument('--cache-only', action='store_true',
                        help='Alleen bestaande cache gebruiken')
    parser.add_argument('--refresh', action='store_true',
                        help='Forceer verse candle data')
    args = parser.parse_args()

    # ── 1. Data laden ──
    if args.cache_only:
        if not CACHE_FILE.exists():
            logger.error(f"Geen cache gevonden: {CACHE_FILE}")
            sys.exit(1)
        with open(CACHE_FILE) as f:
            data = json.load(f)
        coin_count = len([k for k in data if not k.startswith('_')])
        logger.info(f"Cache geladen: {coin_count} coins")
    else:
        data = download_all_candles(force_refresh=args.refresh)

    all_coins = [k for k in data if not k.startswith('_')]

    # ── 2. Split in oude (PAIR_MAP) en nieuwe coins ──
    from kraken_client import KrakenClient
    old_coins = [c for c in all_coins if c in KrakenClient.PAIR_MAP]
    new_coins = [c for c in all_coins if c not in KrakenClient.PAIR_MAP]

    print()
    print("=" * 100)
    print("  BACKTEST V4+V5 DualConfirm — 532 COINS vs 289 COINS")
    print(f"  Strategie: DC+BB dual confirm, RSI<40, VolSpike>2x, "
          f"VolConfirm>1x, ATR 2.0x trail")
    print(f"  Exit: BE+3%, TimeMax 10 bars, RSI Recovery target=47")
    print(f"  Portfolio: 1x$2000 all-in, volume ranking")
    print(f"  Data: {data.get('_date', '?')} | "
          f"Coins met data: {len(all_coins)}")
    print("=" * 100)

    # ── 3. Backtests draaien ──
    configs = [
        ('A) ALLE 532 COINS (dynamisch)', all_coins),
        ('B) OUDE 289 COINS (hardcoded)', old_coins),
        ('C) ALLEEN NIEUWE 243 COINS', new_coins),
    ]

    results = []
    for label, coins in configs:
        logger.info(f"Backtest: {label} ({len(coins)} coins)...")
        r = run_backtest(data, coins, label=label)
        results.append(r)
        logger.info(f"  → {r['trades']} trades, WR {r['win_rate']:.1f}%, "
                    f"P&L ${r['total_pnl']:+,.0f}")

    # ── 4. Resultaten tonen ──
    print()
    print("=" * 100)
    print("  RESULTATEN")
    print("=" * 100)
    print(f"  {'CONFIG':<45} | {'COINS':>5} | {'#TR':>4} | {'W':>3} | "
          f"{'L':>3} | {'WR':>6} | {'P&L':>12} | {'ROI':>8} | "
          f"{'PF':>6} | {'DD':>6} | {'AvgW':>8} | {'AvgL':>8}")
    print("  " + "-" * 98)

    for r in results:
        print(f"  {r['label']:<45} | {r['coins_scanned']:>5} | "
              f"{r['trades']:>4} | {r['wins']:>3} | {r['losses']:>3} | "
              f"{r['win_rate']:>5.1f}% | ${r['total_pnl']:>+9,.0f} | "
              f"{r['roi']:>+6.1f}% | {r['pf']:>5.1f} | "
              f"{r['max_dd']:>5.1f}% | ${r['avg_win']:>+6.0f} | "
              f"${r['avg_loss']:>+6.0f}")

    # ── 5. Impact analyse ──
    r_all = results[0]
    r_old = results[1]
    r_new = results[2]

    print()
    print("=" * 100)
    print("  IMPACT ANALYSE: Nieuwe coins toevoegen")
    print("=" * 100)
    print(f"  Extra coins:        +{r_all['coins_scanned'] - r_old['coins_scanned']}")
    print(f"  Extra trades:       +{r_all['trades'] - r_old['trades']}")
    pnl_diff = r_all['total_pnl'] - r_old['total_pnl']
    print(f"  P&L verschil:       ${pnl_diff:+,.2f}")
    wr_diff = r_all['win_rate'] - r_old['win_rate']
    print(f"  WR verschil:        {wr_diff:+.1f}%")
    print(f"  Alleen nieuwe coins: {r_new['trades']} trades, "
          f"WR {r_new['win_rate']:.1f}%, P&L ${r_new['total_pnl']:+,.0f}")

    # ── 6. Trade details per groep ──
    for r in results:
        if r['trade_list']:
            print()
            print(f"  ── {r['label']} — TRADES ──")
            sorted_trades = sorted(r['trade_list'],
                                   key=lambda t: t['pnl'], reverse=True)
            for i, t in enumerate(sorted_trades):
                icon = "✅" if t['pnl'] > 0 else "❌"
                print(f"    {icon} {t['pair']:<14} | "
                      f"${t['entry']:.6f} → ${t['exit']:.6f} | "
                      f"P&L ${t['pnl']:>+9.2f} | {t['bars']:>3} bars | "
                      f"{t['reason']}")
                if i >= 29:  # Max 30 trades tonen
                    remaining = len(sorted_trades) - 30
                    if remaining > 0:
                        print(f"    ... en nog {remaining} meer trades")
                    break

    # ── 7. Exit reason analyse ──
    print()
    print("=" * 100)
    print("  EXIT REASON ANALYSE (alle 532 coins)")
    print("=" * 100)
    reasons = {}
    for t in r_all['trade_list']:
        reason = t['reason']
        if reason not in reasons:
            reasons[reason] = {'count': 0, 'pnl': 0, 'wins': 0}
        reasons[reason]['count'] += 1
        reasons[reason]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            reasons[reason]['wins'] += 1

    for reason, stats in sorted(reasons.items(),
                                key=lambda x: x[1]['count'], reverse=True):
        wr = (stats['wins'] / stats['count'] * 100
              if stats['count'] > 0 else 0)
        print(f"  {reason:<15} | {stats['count']:>3}x | "
              f"WR {wr:>5.1f}% | P&L ${stats['pnl']:>+9.2f}")

    print()
    print("=" * 100)
    verdict = "BETER" if pnl_diff > 0 else "SLECHTER"
    print(f"  CONCLUSIE: 532 coins is {verdict} dan 289 coins "
          f"(${pnl_diff:+,.0f} P&L verschil)")
    print("=" * 100)
    print()


if __name__ == '__main__':
    main()

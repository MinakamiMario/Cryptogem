#!/usr/bin/env python3
"""
V5 PORTFOLIO VERGELIJKING — 1x$2000 vs 3x$600 (eerlijke test)
===============================================================
Test V4 en V5 strategie met verschillende portfolio-configuraties:

  A. 1x$2000 V4 (huidige live)
  B. 1x$2000 V5 (RSI Recovery t=47)
  C. 1x$2000 V5 (RSI Recovery t=45, productie-aanbeveling)
  D. 3x$600  V4
  E. 3x$600  V5 (RSI Recovery t=47)
  F. 3x$600  V5 (RSI Recovery t=45)
  G. 2x$1000 V4
  H. 2x$1000 V5 (RSI Recovery t=47)

Alle configuraties gebruiken:
  - DualConfirm entry (DC+BB)
  - RSI<40, VolSpike>2x, VolConfirm>1x
  - ATR 2.0x trail, BE+3%, TimeMax 10 bars
  - 0.26% fee, 60 dagen, 285 coins

Gebruik:
    python backtest_v5_portfolio_compare.py
"""
import os
import sys
import json
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
from strategy import Position, Signal
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

load_dotenv(BASE_DIR / '.env')

CACHE_FILE = BASE_DIR / 'candle_cache_60d.json'
KRAKEN_FEE = 0.0026

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('v5_portfolio_compare')


def fetch_all_candles():
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        coin_count = len([k for k in cache if not k.startswith('_')])
        logger.info(f"Cache geladen: {coin_count} coins")
        return cache
    raise FileNotFoundError(f"Cache niet gevonden: {CACHE_FILE}")


# ============================================================
# V4/V5 STRATEGY — Identical to live V4 + optional RSI Recovery
# ============================================================

class V4V5Strategy:
    """V4 DualConfirm + optionele V5 RSI Recovery Exit."""

    def __init__(self,
                 # V4 standard params
                 donchian_period=20, bb_period=20, bb_dev=2.0,
                 rsi_period=14, rsi_max=40, rsi_sell=70,
                 atr_period=14, atr_stop_mult=2.0,
                 max_stop_loss_pct=15.0,
                 cooldown_bars=4, cooldown_after_stop=8,
                 volume_min_pct=0.5,
                 volume_spike_mult=2.0,
                 vol_confirm_mult=1.0,
                 breakeven_trigger_pct=3.0,
                 time_max_bars=10,
                 # V5: RSI Recovery Exit
                 use_rsi_recovery=False,
                 rsi_recovery_target=47,
                 rsi_recovery_min_bars=2,
                 ):
        self.donchian_period = donchian_period
        self.bb_period = bb_period
        self.bb_dev = bb_dev
        self.rsi_period = rsi_period
        self.rsi_max = rsi_max
        self.rsi_sell = rsi_sell
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.max_stop_loss_pct = max_stop_loss_pct
        self.cooldown_bars = cooldown_bars
        self.cooldown_after_stop = cooldown_after_stop
        self.volume_min_pct = volume_min_pct
        self.volume_spike_mult = volume_spike_mult
        self.vol_confirm_mult = vol_confirm_mult
        self.breakeven_trigger_pct = breakeven_trigger_pct
        self.time_max_bars = time_max_bars
        # V5
        self.use_rsi_recovery = use_rsi_recovery
        self.rsi_recovery_target = rsi_recovery_target
        self.rsi_recovery_min_bars = rsi_recovery_min_bars
        # State
        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def analyze(self, candles, position, pair):
        min_bars = max(self.donchian_period, self.bb_period, self.rsi_period, self.atr_period) + 5
        if len(candles) < min_bars:
            return Signal('WAIT', pair, 0, 'Niet genoeg data', confidence=0)

        self.bar_count = len(candles)
        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]

        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)

        prev_highs = highs[:-1]
        prev_lows = lows[:-1]
        _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows, self.donchian_period)
        hh, ll, mid_channel = calc_donchian(highs, lows, self.donchian_period)
        bb_mid, bb_upper, bb_lower = calc_bollinger(closes, self.bb_period, self.bb_dev)

        if any(v is None for v in [rsi, atr, prev_lowest, mid_channel, bb_mid, bb_lower]):
            return Signal('WAIT', pair, 0, 'Indicators niet klaar', confidence=0)

        current = candles[-1]
        close = current['close']
        low = current['low']
        prev_close = candles[-2]['close'] if len(candles) > 1 else close

        # ==========================================
        # EXIT LOGICA
        # ==========================================
        if position and position.side == 'long':
            entry_price = position.entry_price
            bars_in_trade = self.bar_count - position.entry_bar if hasattr(position, 'entry_bar') else 0

            if close > position.highest_price:
                position.highest_price = close

            new_stop = position.highest_price - atr * self.atr_stop_mult
            hard_stop = entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < hard_stop:
                new_stop = hard_stop

            # Break-even stop
            profit_pct = (close - entry_price) / entry_price * 100
            if profit_pct >= self.breakeven_trigger_pct:
                breakeven_level = entry_price * (1 + KRAKEN_FEE * 2)
                if new_stop < breakeven_level:
                    new_stop = breakeven_level

            if new_stop > position.stop_price:
                position.stop_price = new_stop

            # Exit 1: Hard max loss
            if close < hard_stop:
                return Signal('SELL', pair, close, 'HARD STOP', confidence=1.0)

            # Exit 2: Time max
            if bars_in_trade >= self.time_max_bars:
                return Signal('SELL', pair, close, 'TIME MAX', confidence=0.8)

            # Exit 3: V5 RSI Recovery Exit
            if self.use_rsi_recovery and bars_in_trade >= self.rsi_recovery_min_bars:
                if rsi >= self.rsi_recovery_target:
                    return Signal('SELL', pair, close, 'RSI RECOVERY', confidence=0.85)

            # Exit 4: DC mid channel target
            if close >= mid_channel:
                return Signal('SELL', pair, close, 'DC TARGET', confidence=0.9)

            # Exit 5: BB mid target
            if close >= bb_mid:
                return Signal('SELL', pair, close, 'BB TARGET', confidence=0.85)

            # Exit 6: RSI overbought
            if rsi > self.rsi_sell:
                return Signal('SELL', pair, close, 'RSI EXIT', confidence=0.8)

            # Exit 7: Trailing stop
            if close < position.stop_price:
                return Signal('SELL', pair, close, 'TRAIL STOP', confidence=1.0)

            return Signal('HOLD', pair, close, 'In positie', confidence=0.5)

        # ==========================================
        # ENTRY LOGICA
        # ==========================================
        cooldown_needed = self.cooldown_after_stop if self.last_exit_was_stop else self.cooldown_bars
        if (self.bar_count - self.last_exit_bar) < cooldown_needed:
            return Signal('WAIT', pair, close, 'Cooldown', confidence=0)

        # Volume filter
        vol_avg = 0
        if volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_min_pct:
                return Signal('WAIT', pair, close, 'Volume te laag', confidence=0)

        # DUAL CONFIRM ENTRY
        dc_signal = (low <= prev_lowest and rsi < self.rsi_max and close > prev_close)
        bb_signal = (close <= bb_lower and rsi < self.rsi_max and close > prev_close)

        if not (dc_signal and bb_signal):
            return Signal('WAIT', pair, close, 'Geen dual confirm', confidence=0)

        # Volume spike filter
        if volumes and vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
            return Signal('WAIT', pair, close, f'Volume spike <{self.volume_spike_mult}x', confidence=0)

        # Volume bar-to-bar confirmation
        if len(volumes) >= 2 and volumes[-2] > 0:
            if volumes[-1] / volumes[-2] < self.vol_confirm_mult:
                return Signal('WAIT', pair, close, f'Vol confirm <{self.vol_confirm_mult}x', confidence=0)

        # ENTRY!
        stop = close - atr * self.atr_stop_mult
        hard_stop = close * (1 - self.max_stop_loss_pct / 100)
        if stop < hard_stop:
            stop = hard_stop

        # Signal quality score (voor ranking)
        rsi_score = max(0, (self.rsi_max - rsi) / self.rsi_max)
        dc_depth = (prev_lowest - low) / prev_lowest if prev_lowest > 0 else 0
        depth_score = min(1, dc_depth * 20)
        vol_score = 0
        if volumes and vol_avg > 0:
            vol_ratio = volumes[-1] / vol_avg
            vol_score = min(1, vol_ratio / 3)
        quality = rsi_score * 0.4 + depth_score * 0.3 + vol_score * 0.3

        return Signal('BUY', pair, close, 'DUAL CONFIRM V4/V5',
                      confidence=quality, stop_price=stop)


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
    side: str = 'long'


def run_portfolio_backtest(all_candles, strategy_factory, max_positions=1,
                           position_size=2000, use_signal_ranking=True, label=""):
    """Portfolio-realistic backtest met chronologische bar-loop."""
    coins = [k for k in all_candles if not k.startswith('_')]

    strategies = {}
    for pair in coins:
        strategies[pair] = strategy_factory()

    max_bars = max(len(all_candles[pair]) for pair in coins if pair in all_candles)

    positions = {}
    trades = []
    skipped_signals = 0
    equity = max_positions * position_size
    initial_equity = equity
    peak_equity = equity
    max_dd = 0
    max_dd_usd = 0
    total_bars_in_trade = 0

    for bar_idx in range(50, max_bars):
        buy_signals = []
        sell_signals = []

        for pair in coins:
            candles = all_candles.get(pair, [])
            if bar_idx >= len(candles):
                continue

            window = candles[:bar_idx + 1]
            pos = positions.get(pair)

            mock_pos = None
            if pos:
                mock_pos = type('Pos', (), {
                    'entry_price': pos.entry_price,
                    'stop_price': pos.stop_price,
                    'highest_price': pos.highest_price,
                    'side': 'long',
                    'entry_bar': pos.entry_bar,
                })()

            strategy = strategies[pair]
            signal = strategy.analyze(window, mock_pos, pair)

            if signal.action == 'SELL' and pair in positions:
                sell_signals.append((pair, signal))
            elif signal.action == 'BUY' and pair not in positions:
                buy_signals.append((pair, signal, candles[bar_idx]))

        # Process SELLS first
        for pair, signal in sell_signals:
            pos = positions[pair]
            sell_price = signal.price

            gross_pnl = (sell_price - pos.entry_price) / pos.entry_price * pos.size_usd
            fee_cost = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross_pnl) * KRAKEN_FEE
            net_pnl = gross_pnl - fee_cost

            equity += net_pnl
            bars_held = bar_idx - pos.entry_bar
            total_bars_in_trade += bars_held

            is_stop = 'STOP' in signal.reason
            strategy = strategies[pair]
            strategy.last_exit_bar = strategy.bar_count
            strategy.last_exit_was_stop = is_stop

            trades.append({
                'pair': pair,
                'entry': pos.entry_price,
                'exit': sell_price,
                'pnl': net_pnl,
                'pnl_pct': (sell_price - pos.entry_price) / pos.entry_price * 100,
                'reason': signal.reason,
                'bars': bars_held,
                'size': pos.size_usd,
            })

            del positions[pair]

        # Process BUYS
        if len(positions) < max_positions and buy_signals:
            # Signal ranking by volume ratio
            if use_signal_ranking:
                def rank_signal(item):
                    pair, sig, candle = item
                    candles_data = all_candles.get(pair, [])
                    vols = [c.get('volume', 0) for c in candles_data[max(0, bar_idx-20):bar_idx+1]]
                    if vols and len(vols) > 1:
                        avg_vol = sum(vols[:-1]) / max(1, len(vols) - 1)
                        if avg_vol > 0:
                            return vols[-1] / avg_vol
                    return 0
                buy_signals.sort(key=rank_signal, reverse=True)

            for pair, signal, candle in buy_signals:
                if len(positions) >= max_positions:
                    skipped_signals += 1
                    continue

                positions[pair] = BacktestPosition(
                    pair=pair,
                    entry_price=signal.price,
                    entry_bar=bar_idx,
                    stop_price=signal.stop_price if signal.stop_price else signal.price * 0.85,
                    highest_price=signal.price,
                    size_usd=position_size,
                )

            # Count remaining skipped
            remaining = len(buy_signals) - (max_positions - len(positions) + len([p for p, s, c in buy_signals if p in positions]))
            if remaining > 0:
                skipped_signals += remaining

        # Track drawdown
        if equity > peak_equity:
            peak_equity = equity
        dd_usd = peak_equity - equity
        dd_pct = dd_usd / peak_equity * 100 if peak_equity > 0 else 0
        if dd_pct > max_dd:
            max_dd = dd_pct
            max_dd_usd = dd_usd

    # Close remaining positions
    for pair, pos in list(positions.items()):
        candles = all_candles.get(pair, [])
        if candles:
            last_price = candles[-1]['close']
            gross_pnl = (last_price - pos.entry_price) / pos.entry_price * pos.size_usd
            fee_cost = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross_pnl) * KRAKEN_FEE
            net_pnl = gross_pnl - fee_cost
            equity += net_pnl
            trades.append({
                'pair': pair, 'entry': pos.entry_price, 'exit': last_price,
                'pnl': net_pnl, 'pnl_pct': (last_price - pos.entry_price) / pos.entry_price * 100,
                'reason': 'END', 'bars': max_bars - pos.entry_bar, 'size': pos.size_usd,
            })

    # Calculate metrics
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    total_wins = sum(t['pnl'] for t in wins)
    total_losses = abs(sum(t['pnl'] for t in losses))
    pf = total_wins / total_losses if total_losses > 0 else float('inf')
    roi = total_pnl / initial_equity * 100
    avg_bars = total_bars_in_trade / len(trades) if trades else 0

    # Exit reason breakdown
    exit_reasons = {}
    for t in trades:
        r = t['reason']
        if r not in exit_reasons:
            exit_reasons[r] = {'count': 0, 'pnl': 0}
        exit_reasons[r]['count'] += 1
        exit_reasons[r]['pnl'] += t['pnl']

    return {
        'label': label,
        'max_positions': max_positions,
        'position_size': position_size,
        'initial_equity': initial_equity,
        'trades': len(trades),
        'skipped_signals': skipped_signals,
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'roi': roi,
        'pf': pf,
        'max_dd_pct': max_dd,
        'max_dd_usd': max_dd_usd,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'avg_bars': avg_bars,
        'best_trade': max(trades, key=lambda t: t['pnl']) if trades else None,
        'worst_trade': min(trades, key=lambda t: t['pnl']) if trades else None,
        'exit_reasons': exit_reasons,
        'trade_list': trades,
        'coins_used': len(coins),
    }


# ============================================================
# MAIN
# ============================================================

def main():
    data = fetch_all_candles()

    print()
    print("=" * 130)
    print("  V5 PORTFOLIO VERGELIJKING — 1x$2000 vs 3x$600 vs 2x$1000 (eerlijke V4/V5 test)")
    print("  Entry: DualConfirm (DC+BB) | RSI<40 | VolSpike>2x | VolConfirm>1x")
    print("  Exit: ATR 2.0x trail | BE+3% | TimeMax 10 bars | ±RSI Recovery")
    print("  Fee: 0.26% | 60 dagen | 285 coins | Volume ranking")
    print("=" * 130)

    # ==========================================
    # Define test configurations
    # ==========================================
    configs = [
        # 1x$2000 (all-in)
        {'label': '1x$2000 V4 (baseline)',      'max_pos': 1, 'size': 2000, 'rsi_rec': False, 'rsi_rec_t': 0},
        {'label': '1x$2000 V5 (RSI rec t=47)',   'max_pos': 1, 'size': 2000, 'rsi_rec': True,  'rsi_rec_t': 47},
        {'label': '1x$2000 V5 (RSI rec t=45)',   'max_pos': 1, 'size': 2000, 'rsi_rec': True,  'rsi_rec_t': 45},

        # 3x$600
        {'label': '3x$600  V4',                  'max_pos': 3, 'size': 600,  'rsi_rec': False, 'rsi_rec_t': 0},
        {'label': '3x$600  V5 (RSI rec t=47)',   'max_pos': 3, 'size': 600,  'rsi_rec': True,  'rsi_rec_t': 47},
        {'label': '3x$600  V5 (RSI rec t=45)',   'max_pos': 3, 'size': 600,  'rsi_rec': True,  'rsi_rec_t': 45},

        # 2x$1000
        {'label': '2x$1000 V4',                  'max_pos': 2, 'size': 1000, 'rsi_rec': False, 'rsi_rec_t': 0},
        {'label': '2x$1000 V5 (RSI rec t=47)',   'max_pos': 2, 'size': 1000, 'rsi_rec': True,  'rsi_rec_t': 47},

        # Bonus: 3x$667 (gelijke kapitaal $2000)
        {'label': '3x$667  V4 (=$2000)',         'max_pos': 3, 'size': 667,  'rsi_rec': False, 'rsi_rec_t': 0},
        {'label': '3x$667  V5 t=47 (=$2000)',    'max_pos': 3, 'size': 667,  'rsi_rec': True,  'rsi_rec_t': 47},
    ]

    results = []

    for i, cfg in enumerate(configs):
        def make_strategy(rr=cfg['rsi_rec'], rrt=cfg['rsi_rec_t']):
            return V4V5Strategy(
                use_rsi_recovery=rr,
                rsi_recovery_target=rrt,
                rsi_recovery_min_bars=2,
            )

        result = run_portfolio_backtest(
            data, make_strategy,
            max_positions=cfg['max_pos'],
            position_size=cfg['size'],
            use_signal_ranking=True,
            label=cfg['label'],
        )
        results.append(result)

        logger.info(f"  [{i+1}/{len(configs)}] {cfg['label']}: "
                     f"P&L ${result['total_pnl']:+,.0f}, PF {result['pf']:.2f}, "
                     f"WR {result['win_rate']:.1f}%, {result['trades']} trades")

    # ==========================================
    # RESULTATEN TABEL
    # ==========================================
    print()
    print("=" * 145)
    print("  RESULTATEN OVERZICHT")
    print("=" * 145)
    print(f"  {'CONFIG':<35} | {'KAP':>6} | {'#TR':>4} | {'SKIP':>4} | {'WR':>6} | "
          f"{'P&L':>12} | {'ROI':>8} | {'PF':>7} | {'DD%':>6} | {'DD$':>7} | "
          f"{'AvgW':>8} | {'AvgL':>8} | {'Bars':>5}")
    print("  " + "-" * 143)

    for r in results:
        print(f"  {r['label']:<35} | ${r['initial_equity']:>4,} | {r['trades']:>4} | "
              f"{r['skipped_signals']:>4} | {r['win_rate']:>5.1f}% | "
              f"${r['total_pnl']:>+10,.0f} | {r['roi']:>+6.1f}% | {r['pf']:>6.2f} | "
              f"{r['max_dd_pct']:>5.1f}% | ${r['max_dd_usd']:>5,.0f} | "
              f"${r['avg_win']:>+6,.0f} | ${r['avg_loss']:>+6,.0f} | {r['avg_bars']:>4.1f}")

    # ==========================================
    # GROEPSVERGELIJKING: 1x$2000 vs 3x$600 vs 2x$1000
    # ==========================================
    print()
    print("=" * 145)
    print("  GROEPSVERGELIJKING (V5 t=47 per sizing)")
    print("=" * 145)

    groups = [
        ('1x$2000', [r for r in results if '1x$2000' in r['label'] and 't=47' in r['label']][0] if any('1x$2000' in r['label'] and 't=47' in r['label'] for r in results) else None),
        ('3x$600',  [r for r in results if '3x$600' in r['label'] and 't=47' in r['label']][0] if any('3x$600' in r['label'] and 't=47' in r['label'] for r in results) else None),
        ('2x$1000', [r for r in results if '2x$1000' in r['label'] and 't=47' in r['label']][0] if any('2x$1000' in r['label'] and 't=47' in r['label'] for r in results) else None),
        ('3x$667',  [r for r in results if '3x$667' in r['label'] and 't=47' in r['label']][0] if any('3x$667' in r['label'] and 't=47' in r['label'] for r in results) else None),
    ]

    for name, r in groups:
        if r is None:
            continue
        print(f"\n  {name:>8}  V5 (t=47)")
        print(f"  {'─' * 40}")
        print(f"    Kapitaal:       ${r['initial_equity']:,}")
        print(f"    Trades:         {r['trades']} (geskipped: {r['skipped_signals']})")
        print(f"    Win Rate:       {r['win_rate']:.1f}%")
        print(f"    P&L:            ${r['total_pnl']:+,.2f}")
        print(f"    ROI:            {r['roi']:+.1f}%")
        print(f"    Profit Factor:  {r['pf']:.2f}")
        print(f"    Max Drawdown:   {r['max_dd_pct']:.1f}% (${r['max_dd_usd']:,.0f})")
        print(f"    Avg Bars:       {r['avg_bars']:.1f}")

        if r['best_trade']:
            bt = r['best_trade']
            print(f"    Beste trade:    {bt['pair']} ${bt['pnl']:+,.2f} ({bt['reason']})")
        if r['worst_trade']:
            wt = r['worst_trade']
            print(f"    Slechtste:      {wt['pair']} ${wt['pnl']:+,.2f} ({wt['reason']})")

    # ==========================================
    # EXIT REASON BREAKDOWN per config
    # ==========================================
    print()
    print("=" * 145)
    print("  EXIT REASONS (V5 t=47 per sizing)")
    print("=" * 145)

    for name, r in groups:
        if r is None:
            continue
        print(f"\n  {name} V5:")
        for reason, data in sorted(r['exit_reasons'].items(), key=lambda x: -x[1]['count']):
            print(f"    {reason:<15} {data['count']:>3}x  P&L ${data['pnl']:>+10,.2f}")

    # ==========================================
    # TRADE DETAIL voor 3x$600 V5
    # ==========================================
    r3x600_v5 = next((r for r in results if '3x$600' in r['label'] and 't=47' in r['label']), None)
    if r3x600_v5 and r3x600_v5['trade_list']:
        print()
        print("=" * 145)
        print("  TRADE DETAIL: 3x$600 V5 (RSI Recovery t=47)")
        print("=" * 145)
        for i, t in enumerate(r3x600_v5['trade_list']):
            icon = "✅" if t['pnl'] > 0 else "❌"
            print(f"  {icon} {i+1:>2}. {t['pair']:<14} | "
                  f"${t['entry']:.6f} → ${t['exit']:.6f} | "
                  f"P&L ${t['pnl']:>+8.2f} ({t['pnl_pct']:>+6.2f}%) | "
                  f"{t['bars']:>3} bars | {t['reason']}")

    # ==========================================
    # TRADE DETAIL voor 1x$2000 V5
    # ==========================================
    r1x2000_v5 = next((r for r in results if '1x$2000' in r['label'] and 't=47' in r['label']), None)
    if r1x2000_v5 and r1x2000_v5['trade_list']:
        print()
        print("=" * 145)
        print("  TRADE DETAIL: 1x$2000 V5 (RSI Recovery t=47)")
        print("=" * 145)
        for i, t in enumerate(r1x2000_v5['trade_list']):
            icon = "✅" if t['pnl'] > 0 else "❌"
            print(f"  {icon} {i+1:>2}. {t['pair']:<14} | "
                  f"${t['entry']:.6f} → ${t['exit']:.6f} | "
                  f"P&L ${t['pnl']:>+8.2f} ({t['pnl_pct']:>+6.2f}%) | "
                  f"{t['bars']:>3} bars | {t['reason']}")

    # ==========================================
    # V4 vs V5 IMPROVEMENT per sizing
    # ==========================================
    print()
    print("=" * 145)
    print("  V4 → V5 VERBETERING per sizing")
    print("=" * 145)

    sizing_pairs = [
        ('1x$2000', '1x$2000 V4', '1x$2000 V5 (RSI rec t=47)'),
        ('3x$600',  '3x$600  V4', '3x$600  V5 (RSI rec t=47)'),
        ('2x$1000', '2x$1000 V4', '2x$1000 V5 (RSI rec t=47)'),
        ('3x$667',  '3x$667  V4', '3x$667  V5 t=47 (=$2000)'),
    ]

    for name, v4_label, v5_label in sizing_pairs:
        v4 = next((r for r in results if r['label'] == v4_label), None)
        v5 = next((r for r in results if r['label'] == v5_label), None)
        if v4 and v5:
            pnl_diff = v5['total_pnl'] - v4['total_pnl']
            wr_diff = v5['win_rate'] - v4['win_rate']
            pf_diff = v5['pf'] - v4['pf']
            print(f"  {name:>8}: P&L ${pnl_diff:>+8,.0f} | WR {wr_diff:>+5.1f}% | PF {pf_diff:>+7.2f} | "
                  f"V4: ${v4['total_pnl']:>+9,.0f} → V5: ${v5['total_pnl']:>+9,.0f}")

    # ==========================================
    # CONCLUSIE
    # ==========================================
    print()
    print("=" * 145)
    print("  CONCLUSIE")
    print("=" * 145)

    best = max(results, key=lambda x: x['total_pnl'])
    best_roi = max(results, key=lambda x: x['roi'])
    safest = min(results, key=lambda x: x['max_dd_pct'])
    most_trades = max(results, key=lambda x: x['trades'])

    print(f"\n  🏆 HOOGSTE P&L:     {best['label']:<35} ${best['total_pnl']:>+10,.0f} (ROI {best['roi']:+.1f}%)")
    print(f"  📈 HOOGSTE ROI:     {best_roi['label']:<35} {best_roi['roi']:>+8.1f}%")
    print(f"  🛡️  LAAGSTE DD:      {safest['label']:<35} {safest['max_dd_pct']:.1f}%")
    print(f"  📊 MEESTE TRADES:   {most_trades['label']:<35} {most_trades['trades']} trades")

    print()
    print("=" * 145)


if __name__ == '__main__':
    main()

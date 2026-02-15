#!/usr/bin/env python3
"""
V5 EXPERIMENT SUITE — Exit-verbeteringen, periodevariaties, outlier-detectie
=============================================================================
Test categorieën:
  A. EXIT IMPROVEMENTS: Dynamic TimeMax, adaptive ATR, RSI recovery exit
  B. PERIOD VARIATIONS: DC/BB periodes (15, 25, 30 i.p.v. 20)
  C. OUTLIER DETECTION: ZEUS-filter (extreme oversold + massive volume)
  D. ATR MULTIPLIER SWEEP: 1.5x - 3.0x trailing stop
  E. BREAKEVEN TRIGGER SWEEP: 2%-5% trigger variations
  F. BEST COMBOS: Top vondsten combineren

Gebruik:
    python backtest_v5_experiments.py
"""
import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Tuple, Callable

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
from strategy import Position, Signal
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

load_dotenv(BASE_DIR / '.env')

CACHE_FILE = BASE_DIR / 'candle_cache_60d.json'
KRAKEN_FEE = 0.0026

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('v5_experiments')


def fetch_all_candles():
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        coin_count = len([k for k in cache if not k.startswith('_')])
        logger.info(f"Cache geladen: {coin_count} coins")
        return cache
    raise FileNotFoundError(f"Cache niet gevonden: {CACHE_FILE}")


# ============================================================
# ENHANCED V5 STRATEGY — Supports all experiment parameters
# ============================================================

class V5ExperimentStrategy:
    """Extended strategy met alle V5 experiment knobs."""

    def __init__(self,
                 # Base params
                 donchian_period=20, bb_period=20, bb_dev=2.0,
                 rsi_period=14, rsi_max=40, rsi_sell=70,
                 atr_period=14, atr_stop_mult=2.0,
                 max_stop_loss_pct=15.0,
                 cooldown_bars=4, cooldown_after_stop=8,
                 volume_min_pct=0.5,
                 # V4 standard features
                 use_volume_spike=True,
                 volume_spike_mult=2.0,
                 use_vol_confirm=True,
                 vol_confirm_mult=1.0,
                 use_breakeven_stop=True,
                 breakeven_trigger_pct=3.0,
                 use_time_max=True,
                 time_max_bars=10,
                 # V5 EXPERIMENT: ADX filter
                 use_adx=False,
                 adx_threshold=20,
                 # V5 EXPERIMENT: Dynamic TimeMax (longer for recovering trades)
                 use_dynamic_time_max=False,
                 dynamic_time_max_rsi_threshold=45,  # If RSI recovering above this, extend time
                 dynamic_time_max_extension=6,       # Extra bars allowed
                 # V5 EXPERIMENT: Adaptive ATR (tighter when winning, wider when losing)
                 use_adaptive_atr=False,
                 adaptive_atr_profit_mult=1.5,   # ATR mult when in profit (tighter)
                 adaptive_atr_loss_mult=2.5,      # ATR mult when in loss (wider)
                 # V5 EXPERIMENT: RSI recovery exit (exit when RSI recovers to neutral)
                 use_rsi_recovery_exit=False,
                 rsi_recovery_target=50,
                 rsi_recovery_min_bars=3,  # Min bars before RSI exit kicks in
                 # V5 EXPERIMENT: Outlier boost (bigger position on extreme signals)
                 use_outlier_boost=False,
                 outlier_rsi_threshold=15,
                 outlier_vol_threshold=5.0,
                 # V5 EXPERIMENT: Consecutive red candle filter
                 use_consec_red_filter=False,
                 consec_red_min=3,
                 # V5 EXPERIMENT: Higher low confirmation
                 use_higher_low=False,
                 ):
        # Store all params
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

        self.use_volume_spike = use_volume_spike
        self.volume_spike_mult = volume_spike_mult
        self.use_vol_confirm = use_vol_confirm
        self.vol_confirm_mult = vol_confirm_mult
        self.use_breakeven_stop = use_breakeven_stop
        self.breakeven_trigger_pct = breakeven_trigger_pct
        self.use_time_max = use_time_max
        self.time_max_bars = time_max_bars

        # V5 experiments
        self.use_adx = use_adx
        self.adx_threshold = adx_threshold
        self.use_dynamic_time_max = use_dynamic_time_max
        self.dynamic_time_max_rsi_threshold = dynamic_time_max_rsi_threshold
        self.dynamic_time_max_extension = dynamic_time_max_extension
        self.use_adaptive_atr = use_adaptive_atr
        self.adaptive_atr_profit_mult = adaptive_atr_profit_mult
        self.adaptive_atr_loss_mult = adaptive_atr_loss_mult
        self.use_rsi_recovery_exit = use_rsi_recovery_exit
        self.rsi_recovery_target = rsi_recovery_target
        self.rsi_recovery_min_bars = rsi_recovery_min_bars
        self.use_outlier_boost = use_outlier_boost
        self.outlier_rsi_threshold = outlier_rsi_threshold
        self.outlier_vol_threshold = outlier_vol_threshold
        self.use_consec_red_filter = use_consec_red_filter
        self.consec_red_min = consec_red_min
        self.use_higher_low = use_higher_low

        # State
        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def _calc_adx(self, highs, lows, closes, period=14):
        """Calculate ADX (Average Directional Index)."""
        if len(highs) < period * 2:
            return None
        plus_dm = []
        minus_dm = []
        tr_list = []
        for i in range(1, len(highs)):
            up_move = highs[i] - highs[i-1]
            down_move = lows[i-1] - lows[i]
            plus_dm.append(max(up_move, 0) if up_move > down_move else 0)
            minus_dm.append(max(down_move, 0) if down_move > up_move else 0)
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            tr_list.append(tr)

        if len(tr_list) < period:
            return None

        smoothed_tr = sum(tr_list[:period])
        smoothed_plus = sum(plus_dm[:period])
        smoothed_minus = sum(minus_dm[:period])

        dx_values = []
        for i in range(period, len(tr_list)):
            smoothed_tr = smoothed_tr - smoothed_tr/period + tr_list[i]
            smoothed_plus = smoothed_plus - smoothed_plus/period + plus_dm[i]
            smoothed_minus = smoothed_minus - smoothed_minus/period + minus_dm[i]

            if smoothed_tr == 0:
                continue
            plus_di = 100 * smoothed_plus / smoothed_tr
            minus_di = 100 * smoothed_minus / smoothed_tr

            di_sum = plus_di + minus_di
            if di_sum == 0:
                dx_values.append(0)
            else:
                dx_values.append(100 * abs(plus_di - minus_di) / di_sum)

        if len(dx_values) < period:
            return None

        adx = sum(dx_values[:period]) / period
        for i in range(period, len(dx_values)):
            adx = (adx * (period - 1) + dx_values[i]) / period
        return adx

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

            # Base or adaptive ATR
            if self.use_adaptive_atr:
                profit_pct = (close - entry_price) / entry_price * 100
                if profit_pct > 0:
                    eff_atr_mult = self.adaptive_atr_profit_mult
                else:
                    eff_atr_mult = self.adaptive_atr_loss_mult
            else:
                eff_atr_mult = self.atr_stop_mult

            new_stop = position.highest_price - atr * eff_atr_mult
            hard_stop = entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < hard_stop:
                new_stop = hard_stop

            # Break-even stop
            if self.use_breakeven_stop:
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

            # Exit 2: Time max (with optional dynamic extension)
            if self.use_time_max:
                effective_max = self.time_max_bars
                if self.use_dynamic_time_max and rsi > self.dynamic_time_max_rsi_threshold:
                    effective_max = self.time_max_bars + self.dynamic_time_max_extension
                if bars_in_trade >= effective_max:
                    return Signal('SELL', pair, close, 'TIME MAX', confidence=0.8)

            # Exit 3: RSI recovery exit
            if self.use_rsi_recovery_exit and bars_in_trade >= self.rsi_recovery_min_bars:
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

        # Volume filter (base)
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
        if self.use_volume_spike and volumes:
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
                return Signal('WAIT', pair, close, f'Volume spike <{self.volume_spike_mult}x', confidence=0)

        # Volume bar-to-bar confirmation
        if self.use_vol_confirm and len(volumes) >= 2 and volumes[-2] > 0:
            if volumes[-1] / volumes[-2] < self.vol_confirm_mult:
                return Signal('WAIT', pair, close, f'Vol confirm <{self.vol_confirm_mult}x prev bar', confidence=0)

        # ADX filter
        if self.use_adx:
            adx = self._calc_adx(highs, lows, closes)
            if adx is not None and adx < self.adx_threshold:
                return Signal('WAIT', pair, close, f'ADX {adx:.1f} < {self.adx_threshold}', confidence=0)

        # Consecutive red candle filter
        if self.use_consec_red_filter:
            red_count = 0
            for i in range(len(candles)-2, max(0, len(candles)-10), -1):
                if candles[i]['close'] < candles[i]['open']:
                    red_count += 1
                else:
                    break
            if red_count < self.consec_red_min:
                return Signal('WAIT', pair, close, f'Only {red_count} consec red (need {self.consec_red_min})', confidence=0)

        # Higher low confirmation (current low > lowest of last 3 bars)
        if self.use_higher_low and len(lows) >= 4:
            recent_low = min(lows[-4:-1])
            if low <= recent_low:
                return Signal('WAIT', pair, close, 'No higher low', confidence=0)

        # ENTRY!
        stop = close - atr * self.atr_stop_mult
        hard_stop = close * (1 - self.max_stop_loss_pct / 100)
        if stop < hard_stop:
            stop = hard_stop

        # Quality score
        rsi_score = max(0, (self.rsi_max - rsi) / self.rsi_max)
        dc_depth = (prev_lowest - low) / prev_lowest if prev_lowest > 0 else 0
        depth_score = min(1, dc_depth * 20)
        vol_score = 0
        if volumes and vol_avg > 0:
            vol_ratio = volumes[-1] / vol_avg
            vol_score = min(1, vol_ratio / 3)
        quality = rsi_score * 0.4 + depth_score * 0.3 + vol_score * 0.3

        # Outlier flag (for potential boost)
        is_outlier = (rsi < self.outlier_rsi_threshold and
                      vol_avg > 0 and volumes[-1] / vol_avg > self.outlier_vol_threshold)

        return Signal('BUY', pair, close, 'V5 ENTRY' + (' [OUTLIER]' if is_outlier else ''),
                      confidence=quality, stop_price=stop)


# ============================================================
# PORTFOLIO BACKTEST ENGINE (reused from combined winner)
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
    coins = [k for k in all_candles if not k.startswith('_')]
    strategies = {}
    for pair in coins:
        strategies[pair] = strategy_factory()

    max_bars = max(len(all_candles[pair]) for pair in coins if pair in all_candles and not pair.startswith('_'))

    positions = {}
    trades = []
    equity = max_positions * position_size
    initial_equity = equity
    peak_equity = equity
    max_dd = 0
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
                'pair': pair, 'entry': pos.entry_price, 'exit': sell_price,
                'pnl': net_pnl, 'reason': signal.reason, 'bars': bars_held,
                'is_target': not is_stop and 'TIME' not in signal.reason,
            })
            del positions[pair]

        # Process BUYS
        if len(positions) < max_positions and buy_signals:
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
                    break
                positions[pair] = BacktestPosition(
                    pair=pair, entry_price=signal.price, entry_bar=bar_idx,
                    stop_price=signal.stop_price if signal.stop_price else signal.price * 0.85,
                    highest_price=signal.price, size_usd=position_size,
                )

        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Close remaining
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
                'pnl': net_pnl, 'reason': 'END', 'bars': max_bars - pos.entry_bar,
                'is_target': False,
            })

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
    targets = len([t for t in trades if t['is_target']])
    stops = len([t for t in trades if 'STOP' in t.get('reason', '')])

    return {
        'label': label, 'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'win_rate': win_rate, 'total_pnl': total_pnl, 'roi': roi, 'pf': pf,
        'max_dd': max_dd, 'avg_win': avg_win, 'avg_loss': avg_loss, 'avg_bars': avg_bars,
        'targets': targets, 'stops': stops, 'trade_list': trades,
    }


# ============================================================
# MAIN — RUN ALL EXPERIMENTS
# ============================================================

def v4_baseline():
    """V4 baseline factory."""
    return V5ExperimentStrategy()  # All V4 defaults


def print_result_row(r, baseline_pnl=0):
    diff = r['total_pnl'] - baseline_pnl
    pf_str = f"{r['pf']:.2f}" if r['pf'] < 9999 else "INF"
    print(f"  {r['label']:<55} | {r['trades']:>3}tr | {r['win_rate']:>5.1f}% | "
          f"${r['total_pnl']:>+8.0f} ({diff:>+6.0f}) | PF {pf_str:>7} | DD {r['max_dd']:>4.1f}% | "
          f"AvgB {r['avg_bars']:>4.1f}")


def main():
    data = fetch_all_candles()

    print()
    print("=" * 130)
    print("  V5 EXPERIMENT SUITE — Exit-verbeteringen, periodevariaties, outlier-detectie")
    print("  Base: V4 DualConfirm | VolSpike>2x | VolConfirm>1x | BE+3% | TimeMax 10 | ATR 2.0x | RSI<40 | 1x$2000")
    print("=" * 130)

    # ==========================================
    # BASELINE V4
    # ==========================================
    print("\n  [A] V4 BASELINE")
    print("  " + "-" * 128)

    baseline = run_portfolio_backtest(data, v4_baseline, label="V4 BASELINE (reference)")
    print_result_row(baseline)
    base_pnl = baseline['total_pnl']

    # ==========================================
    # CATEGORY A: EXIT IMPROVEMENTS
    # ==========================================
    print(f"\n  [B] EXIT IMPROVEMENTS")
    print("  " + "-" * 128)

    exit_tests = [
        # Dynamic TimeMax: extend time if RSI recovering
        ("DynTimeMax: +6 bars if RSI>45", dict(use_dynamic_time_max=True, dynamic_time_max_rsi_threshold=45, dynamic_time_max_extension=6)),
        ("DynTimeMax: +4 bars if RSI>40", dict(use_dynamic_time_max=True, dynamic_time_max_rsi_threshold=40, dynamic_time_max_extension=4)),
        ("DynTimeMax: +8 bars if RSI>50", dict(use_dynamic_time_max=True, dynamic_time_max_rsi_threshold=50, dynamic_time_max_extension=8)),

        # Adaptive ATR (tighter when winning)
        ("AdaptiveATR: profit=1.5x, loss=2.5x", dict(use_adaptive_atr=True, adaptive_atr_profit_mult=1.5, adaptive_atr_loss_mult=2.5)),
        ("AdaptiveATR: profit=1.0x, loss=3.0x", dict(use_adaptive_atr=True, adaptive_atr_profit_mult=1.0, adaptive_atr_loss_mult=3.0)),
        ("AdaptiveATR: profit=1.8x, loss=2.2x", dict(use_adaptive_atr=True, adaptive_atr_profit_mult=1.8, adaptive_atr_loss_mult=2.2)),

        # RSI recovery exit
        ("RSI Recovery Exit: target=50, min 3 bars", dict(use_rsi_recovery_exit=True, rsi_recovery_target=50, rsi_recovery_min_bars=3)),
        ("RSI Recovery Exit: target=45, min 2 bars", dict(use_rsi_recovery_exit=True, rsi_recovery_target=45, rsi_recovery_min_bars=2)),
        ("RSI Recovery Exit: target=55, min 4 bars", dict(use_rsi_recovery_exit=True, rsi_recovery_target=55, rsi_recovery_min_bars=4)),

        # TimeMax variations
        ("TimeMax = 8 bars (shorter)", dict(time_max_bars=8)),
        ("TimeMax = 12 bars (longer)", dict(time_max_bars=12)),
        ("TimeMax = 15 bars (much longer)", dict(time_max_bars=15)),
        ("TimeMax = OFF (no time limit)", dict(use_time_max=False)),

        # BreakEven trigger variations
        ("BE trigger = 2% (earlier)", dict(breakeven_trigger_pct=2.0)),
        ("BE trigger = 4% (later)", dict(breakeven_trigger_pct=4.0)),
        ("BE trigger = 5% (much later)", dict(breakeven_trigger_pct=5.0)),
        ("BE trigger = OFF", dict(use_breakeven_stop=False)),
    ]

    exit_results = []
    for name, params in exit_tests:
        def factory(p=params):
            return V5ExperimentStrategy(**p)
        r = run_portfolio_backtest(data, factory, label=name)
        exit_results.append(r)
        print_result_row(r, base_pnl)

    # ==========================================
    # CATEGORY B: ATR MULTIPLIER SWEEP
    # ==========================================
    print(f"\n  [C] ATR MULTIPLIER SWEEP")
    print("  " + "-" * 128)

    atr_results = []
    for atr_mult in [1.0, 1.2, 1.5, 1.8, 2.0, 2.2, 2.5, 3.0, 3.5]:
        def factory(m=atr_mult):
            return V5ExperimentStrategy(atr_stop_mult=m)
        r = run_portfolio_backtest(data, factory, label=f"ATR stop = {atr_mult}x")
        atr_results.append(r)
        print_result_row(r, base_pnl)

    # ==========================================
    # CATEGORY C: PERIOD VARIATIONS
    # ==========================================
    print(f"\n  [D] DONCHIAN/BB PERIOD VARIATIONS")
    print("  " + "-" * 128)

    period_results = []
    for dc_per in [10, 15, 20, 25, 30]:
        for bb_per in [15, 20, 25, 30]:
            if dc_per == 20 and bb_per == 20:
                continue  # Skip baseline
            def factory(d=dc_per, b=bb_per):
                return V5ExperimentStrategy(donchian_period=d, bb_period=b)
            r = run_portfolio_backtest(data, factory, label=f"DC={dc_per} BB={bb_per}")
            period_results.append(r)
            print_result_row(r, base_pnl)

    # ==========================================
    # CATEGORY D: ENTRY FILTER VARIATIONS
    # ==========================================
    print(f"\n  [E] ENTRY FILTER EXPERIMENTS")
    print("  " + "-" * 128)

    entry_results = []
    entry_tests = [
        # ADX variations (confirmed winner from round 1)
        ("ADX > 15", dict(use_adx=True, adx_threshold=15)),
        ("ADX > 20", dict(use_adx=True, adx_threshold=20)),
        ("ADX > 25", dict(use_adx=True, adx_threshold=25)),

        # RSI threshold variations
        ("RSI < 30 (stricter)", dict(rsi_max=30)),
        ("RSI < 35 (tighter)", dict(rsi_max=35)),
        ("RSI < 45 (looser)", dict(rsi_max=45)),

        # Volume spike variations
        ("VolSpike > 1.5x (looser)", dict(volume_spike_mult=1.5)),
        ("VolSpike > 2.5x (tighter)", dict(volume_spike_mult=2.5)),
        ("VolSpike > 3.0x (much tighter)", dict(volume_spike_mult=3.0)),

        # Higher low confirmation
        ("Higher Low filter", dict(use_higher_low=True)),

        # Combined: ADX + period tuning
        ("ADX>20 + DC=15 BB=15", dict(use_adx=True, adx_threshold=20, donchian_period=15, bb_period=15)),
        ("ADX>20 + DC=25 BB=25", dict(use_adx=True, adx_threshold=20, donchian_period=25, bb_period=25)),
    ]

    for name, params in entry_tests:
        def factory(p=params):
            return V5ExperimentStrategy(**p)
        r = run_portfolio_backtest(data, factory, label=name)
        entry_results.append(r)
        print_result_row(r, base_pnl)

    # ==========================================
    # CATEGORY E: COMBINED BEST CONFIGS
    # ==========================================
    print(f"\n  [F] COMBINED BEST CONFIGURATIONS")
    print("  " + "-" * 128)

    combo_results = []
    combo_tests = [
        # ADX + exit improvements
        ("ADX>20 + DynTimeMax(RSI>45,+6b)", dict(use_adx=True, adx_threshold=20, use_dynamic_time_max=True, dynamic_time_max_rsi_threshold=45, dynamic_time_max_extension=6)),
        ("ADX>20 + AdaptiveATR(1.5/2.5)", dict(use_adx=True, adx_threshold=20, use_adaptive_atr=True, adaptive_atr_profit_mult=1.5, adaptive_atr_loss_mult=2.5)),
        ("ADX>20 + RSI Recovery(50)", dict(use_adx=True, adx_threshold=20, use_rsi_recovery_exit=True, rsi_recovery_target=50)),
        ("ADX>20 + TimeMax=12", dict(use_adx=True, adx_threshold=20, time_max_bars=12)),
        ("ADX>20 + TimeMax=15", dict(use_adx=True, adx_threshold=20, time_max_bars=15)),
        ("ADX>20 + BE=2%", dict(use_adx=True, adx_threshold=20, breakeven_trigger_pct=2.0)),
        ("ADX>20 + ATR=1.5x", dict(use_adx=True, adx_threshold=20, atr_stop_mult=1.5)),
        ("ADX>20 + ATR=2.5x", dict(use_adx=True, adx_threshold=20, atr_stop_mult=2.5)),

        # ADX + multiple exit tweaks
        ("ADX>20 + DynTime + AdaptATR", dict(use_adx=True, adx_threshold=20, use_dynamic_time_max=True, use_adaptive_atr=True, adaptive_atr_profit_mult=1.5, adaptive_atr_loss_mult=2.5)),
        ("ADX>20 + RSI Recovery + BE=2%", dict(use_adx=True, adx_threshold=20, use_rsi_recovery_exit=True, rsi_recovery_target=50, breakeven_trigger_pct=2.0)),
        ("ADX>20 + TimeMax=OFF + ATR=2.5x", dict(use_adx=True, adx_threshold=20, use_time_max=False, atr_stop_mult=2.5)),

        # Best period + ADX
        ("ADX>20 + VolSpike>2.5x", dict(use_adx=True, adx_threshold=20, volume_spike_mult=2.5)),
        ("ADX>20 + RSI<35", dict(use_adx=True, adx_threshold=20, rsi_max=35)),
        ("ADX>20 + RSI<35 + TimeMax=12", dict(use_adx=True, adx_threshold=20, rsi_max=35, time_max_bars=12)),

        # Kitchen sink
        ("FULL V5: ADX>20+DynTime+AdaptATR+BE=2%", dict(
            use_adx=True, adx_threshold=20,
            use_dynamic_time_max=True, dynamic_time_max_rsi_threshold=45, dynamic_time_max_extension=6,
            use_adaptive_atr=True, adaptive_atr_profit_mult=1.5, adaptive_atr_loss_mult=2.5,
            breakeven_trigger_pct=2.0,
        )),
        ("FULL V5b: ADX>20+RSIRecov+TimeMax=15+ATR=2.5", dict(
            use_adx=True, adx_threshold=20,
            use_rsi_recovery_exit=True, rsi_recovery_target=50,
            time_max_bars=15, atr_stop_mult=2.5,
        )),
    ]

    for name, params in combo_tests:
        def factory(p=params):
            return V5ExperimentStrategy(**p)
        r = run_portfolio_backtest(data, factory, label=name)
        combo_results.append(r)
        print_result_row(r, base_pnl)

    # ==========================================
    # SUMMARY: TOP 10 OVERALL
    # ==========================================
    all_results = [baseline] + exit_results + atr_results + period_results + entry_results + combo_results

    # Sort by P&L first, then by PF
    all_sorted = sorted(all_results, key=lambda x: (x['total_pnl'], x['pf']), reverse=True)

    print()
    print("=" * 130)
    print("  TOP 15 OVERALL (gesorteerd op P&L)")
    print("=" * 130)

    for i, r in enumerate(all_sorted[:15]):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"#{i+1:>2}"
        diff = r['total_pnl'] - base_pnl
        pf_str = f"{r['pf']:.2f}" if r['pf'] < 9999 else "INF"
        print(f"  {medal} {r['label']:<55} | {r['trades']:>3}tr | WR {r['win_rate']:>5.1f}% | "
              f"P&L ${r['total_pnl']:>+8.0f} ({diff:>+6.0f}) | PF {pf_str:>7} | DD {r['max_dd']:>4.1f}%")

    # Also sort by win rate (quality metric)
    wr_sorted = sorted([r for r in all_results if r['trades'] >= 5],
                        key=lambda x: (x['win_rate'], x['pf']), reverse=True)

    print()
    print("=" * 130)
    print("  TOP 10 BY WIN RATE (min 5 trades)")
    print("=" * 130)

    for i, r in enumerate(wr_sorted[:10]):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"#{i+1:>2}"
        diff = r['total_pnl'] - base_pnl
        pf_str = f"{r['pf']:.2f}" if r['pf'] < 9999 else "INF"
        print(f"  {medal} {r['label']:<55} | {r['trades']:>3}tr | WR {r['win_rate']:>5.1f}% | "
              f"P&L ${r['total_pnl']:>+8.0f} ({diff:>+6.0f}) | PF {pf_str:>7} | DD {r['max_dd']:>4.1f}%")

    # TRADE DETAILS for top 3
    print()
    print("=" * 130)
    print("  TOP 3 TRADE DETAILS")
    print("=" * 130)

    for i, r in enumerate(all_sorted[:3]):
        medal = ["🥇", "🥈", "🥉"][i]
        print(f"\n  {medal} {r['label']}")
        print(f"     {r['trades']}tr | WR {r['win_rate']:.1f}% | P&L ${r['total_pnl']:+,.2f} | PF {r['pf']:.2f} | DD {r['max_dd']:.1f}%")
        for t in r['trade_list']:
            icon = "✅" if t['pnl'] > 0 else "❌"
            print(f"     {icon} {t['pair']:<14} | ${t['entry']:.4f} → ${t['exit']:.4f} | "
                  f"P&L ${t['pnl']:>+8.2f} | {t['bars']:>2}b | {t['reason']}")

    # ==========================================
    # V5 RECOMMENDATION
    # ==========================================
    print()
    print("=" * 130)
    print("  V5 AANBEVELING")
    print("=" * 130)

    best = all_sorted[0]
    diff = best['total_pnl'] - base_pnl
    pf_str = f"{best['pf']:.2f}" if best['pf'] < 9999 else "INF"

    print(f"\n  BEST OVERALL: {best['label']}")
    print(f"  {best['trades']}tr | WR {best['win_rate']:.1f}% | P&L ${best['total_pnl']:+,.2f} ({diff:+,.2f} vs V4) | PF {pf_str} | DD {best['max_dd']:.1f}%")

    # Find best quality (WR * PF with min trades)
    quality_sorted = sorted([r for r in all_results if r['trades'] >= 5],
                            key=lambda x: x['win_rate'] * min(x['pf'], 200), reverse=True)
    if quality_sorted:
        best_q = quality_sorted[0]
        diff_q = best_q['total_pnl'] - base_pnl
        pf_q = f"{best_q['pf']:.2f}" if best_q['pf'] < 9999 else "INF"
        print(f"\n  BEST QUALITY: {best_q['label']}")
        print(f"  {best_q['trades']}tr | WR {best_q['win_rate']:.1f}% | P&L ${best_q['total_pnl']:+,.2f} ({diff_q:+,.2f} vs V4) | PF {pf_q} | DD {best_q['max_dd']:.1f}%")

    print()
    print(f"  Totaal {len(all_results)} configuraties getest.")
    print("=" * 130)


if __name__ == '__main__':
    main()

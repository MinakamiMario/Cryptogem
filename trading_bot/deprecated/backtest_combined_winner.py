#!/usr/bin/env python3
"""
Backtest GECOMBINEERDE WINNAAR
==============================
Combineert de beste elementen uit alle 3 optimalisatie-agents:

  ENTRY  (Agent 1): Volume spike >2.0x filter → PF 8.13, WR 75%
  EXIT   (Agent 2): Break-even stop +3% trigger → PF 3.08, +$144
  PORTF  (Agent 3): 1x$2000 all-in + vol ranking → PF 5.38, WR 62.5%

Test configuraties:
  1. BASELINE:     Origineel DualConfirm (ATR 3.0x, DC+BB, RSI<35)
  2. ENTRY ONLY:   + Volume spike >2.0x
  3. EXIT ONLY:    + Break-even stop +3%
  4. PORTF ONLY:   1x$2000 all-in
  5. ENTRY+EXIT:   Volume spike + Break-even
  6. ENTRY+PORTF:  Volume spike + 1x$2000
  7. EXIT+PORTF:   Break-even + 1x$2000
  8. ALL THREE:    Volume spike + Break-even + 1x$2000 (MEGA COMBO)
  9. CONSERVATIVE: Volume spike + Break-even + 2x$1000
  10. ALL + VOL FILTER: MEGA COMBO + coins Vol>P50

Gebruik:
    python backtest_combined_winner.py
"""
import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Tuple

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
from strategy import Position, Signal
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

load_dotenv(BASE_DIR / '.env')

CACHE_FILE = BASE_DIR / 'candle_cache_60d.json'
KRAKEN_FEE = 0.0026  # 0.26%

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('backtest_combined')


# ============================================================
# DATA LOADING
# ============================================================

def fetch_all_candles(days=60):
    """Load candles from cache."""
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        coin_count = len([k for k in cache if not k.startswith('_')])
        logger.info(f"Cache geladen: {coin_count} coins, {cache.get('_days')}d")
        return cache

    raise FileNotFoundError(f"Cache niet gevonden: {CACHE_FILE}")


# ============================================================
# COMBINED STRATEGY (all 3 agent winners merged)
# ============================================================

class CombinedWinnerStrategy:
    """
    DualConfirm met alle optimalisaties uit de 3 agents:
    - Entry: optionele volume spike filter (>2.0x avg volume)
    - Exit: optionele break-even stop (na +3% winst, stop naar entry)
    - Portfolio: configureerbaar max posities en sizing
    """

    def __init__(self,
                 # Base DualConfirm params
                 donchian_period=20, bb_period=20, bb_dev=2.0,
                 rsi_period=14, rsi_max=35, rsi_sell=70,
                 atr_period=14, atr_stop_mult=2.0,
                 max_stop_loss_pct=15.0,
                 cooldown_bars=4, cooldown_after_stop=8,
                 volume_min_pct=0.5,
                 # AGENT 1 - Entry: Volume spike filter
                 use_volume_spike=False,
                 volume_spike_mult=2.0,
                 # AGENT 1b - Entry: Volume bar-to-bar confirmation
                 use_vol_confirm=False,
                 vol_confirm_mult=1.5,
                 # AGENT 2 - Exit: Break-even stop
                 use_breakeven_stop=False,
                 breakeven_trigger_pct=3.0,  # Na +3% winst → stop naar entry
                 # AGENT 2 - Exit: Time max
                 use_time_max=False,
                 time_max_bars=16,
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

        # Agent 1: Volume spike
        self.use_volume_spike = use_volume_spike
        self.volume_spike_mult = volume_spike_mult
        # Agent 1b: Volume bar-to-bar confirmation
        self.use_vol_confirm = use_vol_confirm
        self.vol_confirm_mult = vol_confirm_mult

        # Agent 2: Break-even stop & Time max
        self.use_breakeven_stop = use_breakeven_stop
        self.breakeven_trigger_pct = breakeven_trigger_pct
        self.use_time_max = use_time_max
        self.time_max_bars = time_max_bars

        # State
        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def analyze(self, candles, position, pair):
        """Analyze met gecombineerde entry/exit logica."""
        min_bars = max(self.donchian_period, self.bb_period, self.rsi_period, self.atr_period) + 5
        if len(candles) < min_bars:
            return Signal('WAIT', pair, 0, 'Niet genoeg data', confidence=0)

        self.bar_count = len(candles)
        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]

        # Indicators
        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)

        # Donchian op VORIGE bars
        prev_highs = highs[:-1]
        prev_lows = lows[:-1]
        _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows, self.donchian_period)

        # Donchian inclusief huidige bar
        hh, ll, mid_channel = calc_donchian(highs, lows, self.donchian_period)

        # Bollinger Bands
        bb_mid, bb_upper, bb_lower = calc_bollinger(closes, self.bb_period, self.bb_dev)

        if any(v is None for v in [rsi, atr, prev_lowest, mid_channel, bb_mid, bb_lower]):
            return Signal('WAIT', pair, 0, 'Indicators niet klaar', confidence=0)

        current = candles[-1]
        close = current['close']
        low = current['low']
        prev_close = candles[-2]['close'] if len(candles) > 1 else close

        # ==========================================
        # EXIT LOGICA (enhanced met Agent 2 winners)
        # ==========================================
        if position and position.side == 'long':
            entry_price = position.entry_price
            bars_in_trade = self.bar_count - position.entry_bar if hasattr(position, 'entry_bar') else 0

            # Update trailing stop
            if close > position.highest_price:
                position.highest_price = close

            new_stop = position.highest_price - atr * self.atr_stop_mult
            hard_stop = entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < hard_stop:
                new_stop = hard_stop

            # AGENT 2: Break-even stop
            if self.use_breakeven_stop:
                profit_pct = (close - entry_price) / entry_price * 100
                if profit_pct >= self.breakeven_trigger_pct:
                    # Stop mag niet onder entry prijs (+ fee buffer)
                    breakeven_level = entry_price * (1 + KRAKEN_FEE * 2)
                    if new_stop < breakeven_level:
                        new_stop = breakeven_level

            if new_stop > position.stop_price:
                position.stop_price = new_stop

            # Exit 1: Hard max loss
            if close < hard_stop:
                return Signal('SELL', pair, close, 'HARD STOP', confidence=1.0)

            # Exit 2: AGENT 2 - Time max (force exit)
            if self.use_time_max and bars_in_trade >= self.time_max_bars:
                return Signal('SELL', pair, close, 'TIME MAX', confidence=0.8)

            # Exit 3: DC mid channel target
            if close >= mid_channel:
                return Signal('SELL', pair, close, 'DC TARGET', confidence=0.9)

            # Exit 4: BB mid target
            if close >= bb_mid:
                return Signal('SELL', pair, close, 'BB TARGET', confidence=0.85)

            # Exit 5: RSI overbought
            if rsi > self.rsi_sell:
                return Signal('SELL', pair, close, 'RSI EXIT', confidence=0.8)

            # Exit 6: Trailing stop
            if close < position.stop_price:
                return Signal('SELL', pair, close, 'TRAIL STOP', confidence=1.0)

            return Signal('HOLD', pair, close, 'In positie', confidence=0.5)

        # ==========================================
        # ENTRY LOGICA (enhanced met Agent 1 winners)
        # ==========================================
        # Cooldown check
        cooldown_needed = self.cooldown_after_stop if self.last_exit_was_stop else self.cooldown_bars
        if (self.bar_count - self.last_exit_bar) < cooldown_needed:
            return Signal('WAIT', pair, close, 'Cooldown', confidence=0)

        # Volume filter (base)
        if volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_min_pct:
                return Signal('WAIT', pair, close, 'Volume te laag', confidence=0)

        # DUAL CONFIRM ENTRY
        # Donchian: prijs raakt vorige laagste + RSI oversold + bounce
        dc_signal = (low <= prev_lowest and rsi < self.rsi_max and close > prev_close)
        # Bollinger: prijs onder lower band + RSI oversold + bounce
        bb_signal = (close <= bb_lower and rsi < self.rsi_max and close > prev_close)

        if not (dc_signal and bb_signal):
            return Signal('WAIT', pair, close, 'Geen dual confirm', confidence=0)

        # AGENT 1: Volume spike filter
        if self.use_volume_spike and volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
                return Signal('WAIT', pair, close, f'Volume spike <{self.volume_spike_mult}x', confidence=0)

        # AGENT 1b: Volume bar-to-bar confirmation (stijgend volume op bounce)
        if self.use_vol_confirm and len(volumes) >= 2 and volumes[-2] > 0:
            if volumes[-1] / volumes[-2] < self.vol_confirm_mult:
                return Signal('WAIT', pair, close, f'Vol confirm <{self.vol_confirm_mult}x prev bar', confidence=0)

        # ENTRY!
        stop = close - atr * self.atr_stop_mult
        hard_stop = close * (1 - self.max_stop_loss_pct / 100)
        if stop < hard_stop:
            stop = hard_stop

        # Bereken signal quality score
        rsi_score = max(0, (self.rsi_max - rsi) / self.rsi_max)
        dc_depth = (prev_lowest - low) / prev_lowest if prev_lowest > 0 else 0
        depth_score = min(1, dc_depth * 20)
        vol_score = 0
        if volumes and vol_avg > 0:
            vol_ratio = volumes[-1] / vol_avg
            vol_score = min(1, vol_ratio / 3)
        quality = rsi_score * 0.4 + depth_score * 0.3 + vol_score * 0.3

        return Signal('BUY', pair, close, 'DUAL CONFIRM + OPTIMIZED',
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


def run_portfolio_backtest(all_candles, strategy_factory, max_positions=2,
                           position_size=1000, use_signal_ranking=False,
                           coin_filter_fn=None, label=""):
    """
    Portfolio-realistic backtest:
    - Chronologisch per bar over alle coins
    - Max posities beperkt
    - Fee 0.26% per trade (in + out)
    - Optionele signal ranking (Agent 3 winnaar: volume ratio)
    - Optionele coin filtering
    """
    coins = [k for k in all_candles if not k.startswith('_')]

    # Optioneel: filter coins op volume
    if coin_filter_fn:
        coins = coin_filter_fn(all_candles, coins)

    # Maak strategy instanties per coin
    strategies = {}
    for pair in coins:
        strategies[pair] = strategy_factory()

    # Bepaal bar range
    max_bars = max(len(all_candles[pair]) for pair in coins if pair in all_candles and not pair.startswith('_'))

    positions = {}  # pair -> BacktestPosition
    trades = []
    equity = max_positions * position_size
    initial_equity = equity
    peak_equity = equity
    max_dd = 0
    total_bars_in_trade = 0

    for bar_idx in range(50, max_bars):
        # Collect signals voor alle coins
        buy_signals = []
        sell_signals = []

        for pair in coins:
            candles = all_candles.get(pair, [])
            if bar_idx >= len(candles):
                continue

            window = candles[:bar_idx + 1]
            pos = positions.get(pair)

            # Maak een mock Position voor de strategy
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

            # P&L berekening
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
                'reason': signal.reason,
                'bars': bars_held,
                'is_target': not is_stop and 'TIME' not in signal.reason,
            })

            del positions[pair]

        # Process BUYS (only if slots available)
        if len(positions) < max_positions and buy_signals:
            # AGENT 3: Signal ranking by volume ratio (best first)
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
                    pair=pair,
                    entry_price=signal.price,
                    entry_bar=bar_idx,
                    stop_price=signal.stop_price if signal.stop_price else signal.price * 0.85,
                    highest_price=signal.price,
                    size_usd=position_size,
                )

        # Track drawdown
        if equity > peak_equity:
            peak_equity = equity
        dd = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Close remaining positions at last price
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

    # Bereken metrics
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
    stop_pnl = sum(t['pnl'] for t in trades if 'STOP' in t.get('reason', ''))

    # Composite score
    pnl_norm = min(1, max(0, (total_pnl + 2000) / 6000))
    pf_norm = min(1, max(0, (pf - 0.5) / 4.5))
    wr_norm = win_rate / 100
    dd_penalty = max(0, 1 - max_dd / 50)
    trade_norm = min(1, len(trades) / 50)
    score = pnl_norm * 40 + pf_norm * 20 + wr_norm * 10 + dd_penalty * 20 + trade_norm * 10

    return {
        'label': label,
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
        'avg_bars': avg_bars,
        'targets': targets,
        'stops': stops,
        'stop_pnl': stop_pnl,
        'score': score,
        'trade_list': trades,
        'coins_used': len(coins),
    }


def vol_filter_p50(all_candles, coins):
    """Filter coins op volume > P50 ($5,145 daily)."""
    vol_data = []
    for pair in coins:
        candles = all_candles.get(pair, [])
        if not candles:
            continue
        avg_vol = sum(c.get('volume', 0) for c in candles[-30:]) / min(30, len(candles))
        vol_data.append((pair, avg_vol))

    if not vol_data:
        return coins

    vol_data.sort(key=lambda x: x[1])
    p50_idx = len(vol_data) // 2
    p50_val = vol_data[p50_idx][1] if vol_data else 0

    filtered = [pair for pair, vol in vol_data if vol >= p50_val]
    return filtered


# ============================================================
# MAIN
# ============================================================

def main():
    data = fetch_all_candles(60)

    print()
    print("=" * 120)
    print("  GECOMBINEERDE WINNAAR BACKTEST — Alle 3 agent-resultaten samengevoegd")
    print("  Base: DualConfirm | ATR 3.0x trail | Smart cooldown | 0.26% fee | 60 dagen")
    print("=" * 120)

    # ==========================================
    # Define all test configurations
    # ==========================================
    configs = [
        # 1. BASELINE: origineel
        {
            'label': 'BASELINE: 2x$1000 origineel',
            'max_pos': 2, 'size': 1000,
            'vol_spike': False, 'breakeven': False, 'ranking': False, 'vol_filter': False,
        },
        # 2. ENTRY ONLY: + volume spike >2.0x
        {
            'label': 'ENTRY: + Volume spike >2.0x',
            'max_pos': 2, 'size': 1000,
            'vol_spike': True, 'breakeven': False, 'ranking': False, 'vol_filter': False,
        },
        # 3. EXIT ONLY: + break-even +3%
        {
            'label': 'EXIT: + Break-even stop +3%',
            'max_pos': 2, 'size': 1000,
            'vol_spike': False, 'breakeven': True, 'ranking': False, 'vol_filter': False,
        },
        # 4. PORTFOLIO ONLY: 1x$2000 all-in
        {
            'label': 'PORTFOLIO: 1x$2000 all-in',
            'max_pos': 1, 'size': 2000,
            'vol_spike': False, 'breakeven': False, 'ranking': True, 'vol_filter': False,
        },
        # 5. ENTRY + EXIT
        {
            'label': 'ENTRY+EXIT: VolSpike + BreakEven',
            'max_pos': 2, 'size': 1000,
            'vol_spike': True, 'breakeven': True, 'ranking': False, 'vol_filter': False,
        },
        # 6. ENTRY + PORTFOLIO
        {
            'label': 'ENTRY+PORTF: VolSpike + 1x$2000',
            'max_pos': 1, 'size': 2000,
            'vol_spike': True, 'breakeven': False, 'ranking': True, 'vol_filter': False,
        },
        # 7. EXIT + PORTFOLIO
        {
            'label': 'EXIT+PORTF: BreakEven + 1x$2000',
            'max_pos': 1, 'size': 2000,
            'vol_spike': False, 'breakeven': True, 'ranking': True, 'vol_filter': False,
        },
        # 8. ALL THREE: MEGA COMBO
        {
            'label': '★ MEGA COMBO: VolSpike+BE+1x$2000',
            'max_pos': 1, 'size': 2000,
            'vol_spike': True, 'breakeven': True, 'ranking': True, 'vol_filter': False,
        },
        # 9. CONSERVATIVE: alle verbeteringen met 2x$1000
        {
            'label': 'SAFE: VolSpike+BE+2x$1000',
            'max_pos': 2, 'size': 1000,
            'vol_spike': True, 'breakeven': True, 'ranking': True, 'vol_filter': False,
        },
        # 10. ALL + VOL FILTER
        {
            'label': '★ ULTRA: VolSpike+BE+1x$2k+VolFilter',
            'max_pos': 1, 'size': 2000,
            'vol_spike': True, 'breakeven': True, 'ranking': True, 'vol_filter': True,
        },
        # 11. 3x$667 versies
        {
            'label': 'BASELINE: 3x$667 origineel',
            'max_pos': 3, 'size': 667,
            'vol_spike': False, 'breakeven': False, 'ranking': False, 'vol_filter': False,
        },
        {
            'label': '3x$667: VolSpike+BE',
            'max_pos': 3, 'size': 667,
            'vol_spike': True, 'breakeven': True, 'ranking': False, 'vol_filter': False,
        },
        {
            'label': '3x$667: VolSpike+BE+ranking',
            'max_pos': 3, 'size': 667,
            'vol_spike': True, 'breakeven': True, 'ranking': True, 'vol_filter': False,
        },
        # 12. RSI 40 variant (Agent 1 #3)
        {
            'label': 'RSI<40 + 2x$1000',
            'max_pos': 2, 'size': 1000,
            'vol_spike': False, 'breakeven': False, 'ranking': False, 'vol_filter': False,
            'rsi_max': 40,
        },
        {
            'label': 'RSI<40 + VolSpike + BE + 1x$2000',
            'max_pos': 1, 'size': 2000,
            'vol_spike': True, 'breakeven': True, 'ranking': True, 'vol_filter': False,
            'rsi_max': 40,
        },
    ]

    results = []

    for i, cfg in enumerate(configs):
        rsi_max = cfg.get('rsi_max', 35)

        def make_strategy(vs=cfg['vol_spike'], be=cfg['breakeven'], rm=rsi_max):
            return CombinedWinnerStrategy(
                use_volume_spike=vs,
                volume_spike_mult=2.0,
                use_breakeven_stop=be,
                breakeven_trigger_pct=3.0,
                rsi_max=rm,
            )

        coin_filter = vol_filter_p50 if cfg.get('vol_filter', False) else None

        result = run_portfolio_backtest(
            data, make_strategy,
            max_positions=cfg['max_pos'],
            position_size=cfg['size'],
            use_signal_ranking=cfg.get('ranking', False),
            coin_filter_fn=coin_filter,
            label=cfg['label'],
        )
        results.append(result)

        logger.info(f"  [{i+1}/{len(configs)}] {cfg['label']}: P&L ${result['total_pnl']:+.0f}, "
                     f"PF {result['pf']:.2f}, WR {result['win_rate']:.1f}%, "
                     f"{result['trades']} trades")

    # ==========================================
    # RESULTS TABLE
    # ==========================================
    print()
    print("=" * 140)
    print("  RESULTATEN OVERZICHT")
    print("=" * 140)
    print(f"  {'CONFIG':<50} | {'#TR':>4} | {'WR':>6} | {'P&L':>12} | {'ROI':>8} | {'PF':>6} | {'DD':>6} | {'AvgW':>8} | {'AvgL':>8} | {'TGT':>3} | {'STP':>3} | {'SCORE':>6}")
    print("  " + "-" * 138)

    baseline_pnl = results[0]['total_pnl'] if results else 0

    for r in results:
        diff = r['total_pnl'] - baseline_pnl
        star = ' ***' if r == max(results, key=lambda x: x['score']) else ''
        print(f"  {r['label']:<50} | {r['trades']:>4} | {r['win_rate']:>5.1f}% | "
              f"${r['total_pnl']:>+9.0f} | {r['roi']:>+6.1f}% | {r['pf']:>5.2f} | "
              f"{r['max_dd']:>5.1f}% | ${r['avg_win']:>+6.0f} | ${r['avg_loss']:>+6.0f} | "
              f"{r['targets']:>3} | {r['stops']:>3} | {r['score']:>5.1f}{star}")

    # ==========================================
    # SORTED BY SCORE
    # ==========================================
    print()
    print("=" * 140)
    print("  RANKING OP COMPOSITE SCORE (P&L 40% + PF 20% + WR 10% + DD-penalty 20% + Trades 10%)")
    print("=" * 140)

    sorted_results = sorted(results, key=lambda x: x['score'], reverse=True)

    for i, r in enumerate(sorted_results):
        diff = r['total_pnl'] - baseline_pnl
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"#{i+1}"
        print(f"  {medal:<4} {r['label']:<48} | P&L ${r['total_pnl']:>+9.0f} ({diff:>+7.0f}) | "
              f"PF {r['pf']:>5.2f} | WR {r['win_rate']:>5.1f}% | DD {r['max_dd']:>5.1f}% | "
              f"Score {r['score']:>5.1f}")

    # ==========================================
    # TOP 3 DETAIL
    # ==========================================
    print()
    print("=" * 140)
    print("  TOP 3 GEDETAILLEERD")
    print("=" * 140)

    for i, r in enumerate(sorted_results[:3]):
        diff = r['total_pnl'] - baseline_pnl
        medal = ["🥇 WINNAAR", "🥈 RUNNER-UP", "🥉 DERDE"][i]
        print(f"\n  {'=' * 80}")
        print(f"  {medal}: {r['label']}")
        print(f"  {'=' * 80}")
        print(f"    Trades:         {r['trades']}")
        print(f"    Win Rate:       {r['win_rate']:.1f}%")
        print(f"    Total P&L:      ${r['total_pnl']:+,.2f} ({diff:+,.2f} vs baseline)")
        print(f"    ROI:            {r['roi']:+.1f}%")
        print(f"    Profit Factor:  {r['pf']:.2f}")
        print(f"    Max Drawdown:   {r['max_dd']:.1f}%")
        print(f"    Avg Win:        ${r['avg_win']:+.2f}")
        print(f"    Avg Loss:       ${r['avg_loss']:+.2f}")
        print(f"    Avg Bars:       {r['avg_bars']:.1f}")
        print(f"    Targets:        {r['targets']} | Stops: {r['stops']} (stop P&L: ${r['stop_pnl']:+.0f})")
        print(f"    Coins Used:     {r['coins_used']}")
        print(f"    Composite:      {r['score']:.1f}")

        # Show individual trades
        if r['trade_list']:
            print(f"\n    TRADES:")
            for j, t in enumerate(r['trade_list'][:20]):  # First 20
                icon = "✅" if t['pnl'] > 0 else "❌"
                print(f"      {icon} {t['pair']:<12} | "
                      f"${t['entry']:.4f} → ${t['exit']:.4f} | "
                      f"P&L ${t['pnl']:>+8.2f} | {t['bars']:>3} bars | {t['reason']}")
            if len(r['trade_list']) > 20:
                print(f"      ... en {len(r['trade_list']) - 20} meer trades")

    # ==========================================
    # CONCLUSIE
    # ==========================================
    best = sorted_results[0]
    print()
    print("=" * 140)
    print("  CONCLUSIE")
    print("=" * 140)
    print(f"\n  ABSOLUTE WINNAAR: {best['label']}")
    print(f"  P&L: ${best['total_pnl']:+,.2f} | PF: {best['pf']:.2f} | WR: {best['win_rate']:.1f}% | DD: {best['max_dd']:.1f}%")
    print(f"  vs Baseline: ${best['total_pnl'] - baseline_pnl:+,.2f} ({(best['total_pnl'] - baseline_pnl)/max(1, abs(baseline_pnl))*100:+.0f}%)")
    print()

    # Agent contribution breakdown
    entry_only = next((r for r in results if 'ENTRY:' in r['label']), None)
    exit_only = next((r for r in results if 'EXIT:' in r['label']), None)
    port_only = next((r for r in results if 'PORTFOLIO:' in r['label']), None)

    if entry_only and exit_only and port_only:
        print(f"  Agent Bijdragen (individueel vs baseline):")
        print(f"    Entry  (Volume spike >2.0x):  ${entry_only['total_pnl'] - baseline_pnl:+,.0f}")
        print(f"    Exit   (Break-even +3%):      ${exit_only['total_pnl'] - baseline_pnl:+,.0f}")
        print(f"    Portf  (1x$2000 all-in):      ${port_only['total_pnl'] - baseline_pnl:+,.0f}")
        print(f"    Combined:                     ${best['total_pnl'] - baseline_pnl:+,.0f}")

    print()
    print("=" * 140)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Backtest EXTRA ENTRY FILTERS op V3 baseline
=============================================
V3 baseline: RSI<40 + VolSpike>2x + Break-even stop + 1x$2000 all-in
  => 19 trades, WR 78.9%, P&L $5,090, PF 18.16, DD 5.8%

Test extra filters:
  A) MOMENTUM FILTER: Prijs BOVEN of ONDER 50-SMA
  B) RSI DIVERGENCE: RSI[0] > RSI[-3] terwijl prijs daalt
  C) VOLUME CONFIRMATION: Volume entry bar > 1.5x vorige bar
  D) CANDLE PATTERN: Hammer candle (lower wick > 2x body)
  E) BB SQUEEZE: BB width < mediaan BB width

Gebruik:
    python backtest_extra_filters.py
"""
import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Tuple

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from strategy import Signal, calc_rsi, calc_atr, calc_donchian, calc_bollinger

CACHE_FILE = BASE_DIR / 'candle_cache_60d.json'
KRAKEN_FEE = 0.0026

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('backtest_filters')


# ============================================================
# DATA LOADING
# ============================================================

def fetch_all_candles():
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        coin_count = len([k for k in cache if not k.startswith('_')])
        logger.info(f"Cache geladen: {coin_count} coins")
        return cache
    raise FileNotFoundError(f"Cache niet gevonden: {CACHE_FILE}")


# ============================================================
# EXTRA FILTER STRATEGIES (subclassed from V3 baseline)
# ============================================================

class V3BaselineStrategy:
    """
    V3 baseline: DualConfirm + RSI<40 + VolSpike>2x + Break-even stop.
    Dit is de referentie-strategie.
    """

    def __init__(self,
                 donchian_period=20, bb_period=20, bb_dev=2.0,
                 rsi_period=14, rsi_max=40, rsi_sell=70,
                 atr_period=14, atr_stop_mult=2.0,
                 max_stop_loss_pct=15.0,
                 cooldown_bars=4, cooldown_after_stop=8,
                 volume_min_pct=0.5,
                 volume_spike_mult=2.0,
                 breakeven_trigger_pct=3.0,
                 # Extra filter flags
                 filter_name="NONE",
                 # A) Momentum filter
                 use_sma_filter=False,
                 sma_period=50,
                 sma_direction="above",  # "above" = prijs boven SMA, "below" = onder
                 # B) RSI divergence
                 use_rsi_divergence=False,
                 rsi_div_lookback=3,
                 # C) Volume confirmation (bar-to-bar)
                 use_vol_confirmation=False,
                 vol_confirm_mult=1.5,
                 # D) Hammer candle
                 use_hammer_filter=False,
                 hammer_wick_ratio=2.0,
                 # E) BB squeeze
                 use_bb_squeeze=False,
                 bb_squeeze_lookback=50,
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
        self.breakeven_trigger_pct = breakeven_trigger_pct

        # Extra filters
        self.filter_name = filter_name
        self.use_sma_filter = use_sma_filter
        self.sma_period = sma_period
        self.sma_direction = sma_direction
        self.use_rsi_divergence = use_rsi_divergence
        self.rsi_div_lookback = rsi_div_lookback
        self.use_vol_confirmation = use_vol_confirmation
        self.vol_confirm_mult = vol_confirm_mult
        self.use_hammer_filter = use_hammer_filter
        self.hammer_wick_ratio = hammer_wick_ratio
        self.use_bb_squeeze = use_bb_squeeze
        self.bb_squeeze_lookback = bb_squeeze_lookback

        # State
        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def _calc_sma(self, closes, period):
        """Simple Moving Average."""
        if len(closes) < period:
            return None
        return sum(closes[-period:]) / period

    def _calc_bb_width(self, closes, period, dev):
        """BB width = (upper - lower) / mid."""
        mid, upper, lower = calc_bollinger(closes, period, dev)
        if mid and mid > 0:
            return (upper - lower) / mid
        return None

    def _is_hammer(self, candle):
        """Hammer candle: lower wick > hammer_wick_ratio * body size."""
        o, h, l, c = candle['open'], candle['high'], candle['low'], candle['close']
        body = abs(c - o)
        if body < 1e-10:
            body = 1e-10  # Prevent division by zero
        lower_wick = min(o, c) - l
        return lower_wick > self.hammer_wick_ratio * body

    def analyze(self, candles, position, pair):
        min_bars = max(self.donchian_period, self.bb_period, self.rsi_period,
                       self.atr_period, self.sma_period if self.use_sma_filter else 0,
                       self.bb_squeeze_lookback if self.use_bb_squeeze else 0) + 5
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
        # EXIT LOGICA (identiek aan V3)
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

            if close < hard_stop:
                return Signal('SELL', pair, close, 'HARD STOP', confidence=1.0)
            if close >= mid_channel:
                return Signal('SELL', pair, close, 'DC TARGET', confidence=0.9)
            if close >= bb_mid:
                return Signal('SELL', pair, close, 'BB TARGET', confidence=0.85)
            if rsi > self.rsi_sell:
                return Signal('SELL', pair, close, 'RSI EXIT', confidence=0.8)
            if close < position.stop_price:
                return Signal('SELL', pair, close, 'TRAIL STOP', confidence=1.0)

            return Signal('HOLD', pair, close, 'In positie', confidence=0.5)

        # ==========================================
        # ENTRY LOGICA
        # ==========================================
        cooldown_needed = self.cooldown_after_stop if self.last_exit_was_stop else self.cooldown_bars
        if (self.bar_count - self.last_exit_bar) < cooldown_needed:
            return Signal('WAIT', pair, close, 'Cooldown', confidence=0)

        # Base volume filter
        if volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_min_pct:
                return Signal('WAIT', pair, close, 'Volume te laag', confidence=0)

        # DUAL CONFIRM ENTRY
        dc_signal = (low <= prev_lowest and rsi < self.rsi_max and close > prev_close)
        bb_signal = (close <= bb_lower and rsi < self.rsi_max and close > prev_close)

        if not (dc_signal and bb_signal):
            return Signal('WAIT', pair, close, 'Geen dual confirm', confidence=0)

        # Volume spike filter (V3 baseline)
        if volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
                return Signal('WAIT', pair, close, f'Volume spike <{self.volume_spike_mult}x', confidence=0)

        # ==================================================
        # EXTRA FILTERS (new - test each independently)
        # ==================================================

        # A) MOMENTUM FILTER: SMA50
        if self.use_sma_filter:
            sma = self._calc_sma(closes, self.sma_period)
            if sma is not None:
                if self.sma_direction == "above" and close < sma:
                    return Signal('WAIT', pair, close, f'Prijs onder SMA{self.sma_period}', confidence=0)
                elif self.sma_direction == "below" and close > sma:
                    return Signal('WAIT', pair, close, f'Prijs boven SMA{self.sma_period}', confidence=0)

        # B) RSI DIVERGENCE: RSI stijgt terwijl prijs daalt
        if self.use_rsi_divergence:
            if len(candles) > self.rsi_div_lookback + self.rsi_period + 1:
                # RSI nu vs RSI lookback bars geleden
                rsi_now = rsi
                closes_past = [c['close'] for c in candles[:-(self.rsi_div_lookback)]]
                rsi_past = calc_rsi(closes_past, self.rsi_period)
                price_now = close
                price_past = candles[-(self.rsi_div_lookback + 1)]['close']

                # Bullish divergence: prijs daalt maar RSI stijgt
                bullish_div = (price_now < price_past) and (rsi_now > rsi_past)
                if not bullish_div:
                    return Signal('WAIT', pair, close, 'Geen RSI bullish divergence', confidence=0)

        # C) VOLUME CONFIRMATION: volume entry bar > 1.5x vorige bar
        if self.use_vol_confirmation:
            if len(volumes) >= 2 and volumes[-2] > 0:
                if volumes[-1] < volumes[-2] * self.vol_confirm_mult:
                    return Signal('WAIT', pair, close,
                                  f'Vol bar-to-bar <{self.vol_confirm_mult}x', confidence=0)

        # D) HAMMER CANDLE
        if self.use_hammer_filter:
            if not self._is_hammer(current):
                return Signal('WAIT', pair, close, 'Geen hammer candle', confidence=0)

        # E) BB SQUEEZE: BB width < mediaan van lookback
        if self.use_bb_squeeze:
            # Bereken BB widths over de laatste N bars
            bb_widths = []
            for i in range(self.bb_squeeze_lookback):
                idx = len(closes) - i
                if idx >= self.bb_period:
                    w = self._calc_bb_width(closes[:idx], self.bb_period, self.bb_dev)
                    if w is not None:
                        bb_widths.append(w)
            if bb_widths:
                current_width = bb_widths[0]
                median_width = sorted(bb_widths)[len(bb_widths) // 2]
                if current_width >= median_width:
                    return Signal('WAIT', pair, close, 'BB niet in squeeze', confidence=0)

        # ENTRY!
        stop = close - atr * self.atr_stop_mult
        hard_stop = close * (1 - self.max_stop_loss_pct / 100)
        if stop < hard_stop:
            stop = hard_stop

        rsi_score = max(0, (self.rsi_max - rsi) / self.rsi_max)
        dc_depth = (prev_lowest - low) / prev_lowest if prev_lowest > 0 else 0
        depth_score = min(1, dc_depth * 20)
        vol_score = 0
        if volumes and vol_avg > 0:
            vol_ratio = volumes[-1] / vol_avg
            vol_score = min(1, vol_ratio / 3)
        quality = rsi_score * 0.4 + depth_score * 0.3 + vol_score * 0.3

        return Signal('BUY', pair, close, f'DUAL CONFIRM + {self.filter_name}',
                       confidence=quality, stop_price=stop)


# ============================================================
# PORTFOLIO BACKTEST ENGINE (from combined_winner)
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
                           position_size=2000, use_signal_ranking=True,
                           label=""):
    coins = [k for k in all_candles if not k.startswith('_')]

    strategies = {}
    for pair in coins:
        strategies[pair] = strategy_factory()

    max_bars = max(len(all_candles[pair]) for pair in coins
                   if pair in all_candles and not pair.startswith('_'))

    positions = {}
    trades = []
    equity = max_positions * position_size
    initial_equity = equity
    peak_equity = equity
    max_dd = 0
    total_bars_in_trade = 0

    for bar_idx in range(55, max_bars):  # Start later for SMA50
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
                'reason': signal.reason,
                'bars': bars_held,
                'is_target': not is_stop,
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
        'trade_list': trades,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    data = fetch_all_candles()

    print()
    print("=" * 140)
    print("  EXTRA ENTRY FILTER BACKTEST — V3 Baseline + Extra Filters")
    print("  V3 Base: DualConfirm | RSI<40 | VolSpike>2x | Break-even +3% | 1x$2000 | 0.26% fee | 60d")
    print("=" * 140)

    # ==========================================
    # Test configuraties
    # ==========================================
    configs = [
        # 0. V3 BASELINE (referentie)
        {
            'label': 'V3 BASELINE (referentie)',
            'factory': lambda: V3BaselineStrategy(filter_name="V3_BASE"),
        },

        # A) MOMENTUM: Prijs BOVEN SMA50 (trending up)
        {
            'label': 'A1) SMA50 ABOVE (trend up)',
            'factory': lambda: V3BaselineStrategy(
                filter_name="SMA50_ABOVE",
                use_sma_filter=True, sma_period=50, sma_direction="above"
            ),
        },
        # A) MOMENTUM: Prijs ONDER SMA50 (dip buying)
        {
            'label': 'A2) SMA50 BELOW (dip buy)',
            'factory': lambda: V3BaselineStrategy(
                filter_name="SMA50_BELOW",
                use_sma_filter=True, sma_period=50, sma_direction="below"
            ),
        },
        # A) MOMENTUM: SMA20 variants
        {
            'label': 'A3) SMA20 ABOVE (trend up)',
            'factory': lambda: V3BaselineStrategy(
                filter_name="SMA20_ABOVE",
                use_sma_filter=True, sma_period=20, sma_direction="above"
            ),
        },
        {
            'label': 'A4) SMA20 BELOW (dip buy)',
            'factory': lambda: V3BaselineStrategy(
                filter_name="SMA20_BELOW",
                use_sma_filter=True, sma_period=20, sma_direction="below"
            ),
        },

        # B) RSI DIVERGENCE: RSI stijgt terwijl prijs daalt (bullish div)
        {
            'label': 'B1) RSI DIV lookback=3',
            'factory': lambda: V3BaselineStrategy(
                filter_name="RSI_DIV_3",
                use_rsi_divergence=True, rsi_div_lookback=3
            ),
        },
        {
            'label': 'B2) RSI DIV lookback=5',
            'factory': lambda: V3BaselineStrategy(
                filter_name="RSI_DIV_5",
                use_rsi_divergence=True, rsi_div_lookback=5
            ),
        },

        # C) VOLUME CONFIRMATION: volume entry > 1.5x vorige bar
        {
            'label': 'C1) VOL CONFIRM >1.5x prev',
            'factory': lambda: V3BaselineStrategy(
                filter_name="VOL_CONF_1.5x",
                use_vol_confirmation=True, vol_confirm_mult=1.5
            ),
        },
        {
            'label': 'C2) VOL CONFIRM >1.2x prev',
            'factory': lambda: V3BaselineStrategy(
                filter_name="VOL_CONF_1.2x",
                use_vol_confirmation=True, vol_confirm_mult=1.2
            ),
        },
        {
            'label': 'C3) VOL CONFIRM >2.0x prev',
            'factory': lambda: V3BaselineStrategy(
                filter_name="VOL_CONF_2.0x",
                use_vol_confirmation=True, vol_confirm_mult=2.0
            ),
        },

        # D) HAMMER CANDLE: lower wick > 2x body
        {
            'label': 'D1) HAMMER wick>2x body',
            'factory': lambda: V3BaselineStrategy(
                filter_name="HAMMER_2x",
                use_hammer_filter=True, hammer_wick_ratio=2.0
            ),
        },
        {
            'label': 'D2) HAMMER wick>1.5x body',
            'factory': lambda: V3BaselineStrategy(
                filter_name="HAMMER_1.5x",
                use_hammer_filter=True, hammer_wick_ratio=1.5
            ),
        },
        {
            'label': 'D3) HAMMER wick>1.0x body',
            'factory': lambda: V3BaselineStrategy(
                filter_name="HAMMER_1.0x",
                use_hammer_filter=True, hammer_wick_ratio=1.0
            ),
        },

        # E) BB SQUEEZE: BB width < mediaan
        {
            'label': 'E1) BB SQUEEZE <median (50bar)',
            'factory': lambda: V3BaselineStrategy(
                filter_name="BB_SQUEEZE_50",
                use_bb_squeeze=True, bb_squeeze_lookback=50
            ),
        },
        {
            'label': 'E2) BB SQUEEZE <median (20bar)',
            'factory': lambda: V3BaselineStrategy(
                filter_name="BB_SQUEEZE_20",
                use_bb_squeeze=True, bb_squeeze_lookback=20
            ),
        },

        # COMBINATIES van de beste individuele filters
        {
            'label': 'F1) RSI DIV + HAMMER 1.5x',
            'factory': lambda: V3BaselineStrategy(
                filter_name="RSI_DIV+HAMMER",
                use_rsi_divergence=True, rsi_div_lookback=3,
                use_hammer_filter=True, hammer_wick_ratio=1.5,
            ),
        },
        {
            'label': 'F2) RSI DIV + BB SQUEEZE',
            'factory': lambda: V3BaselineStrategy(
                filter_name="RSI_DIV+BB_SQ",
                use_rsi_divergence=True, rsi_div_lookback=3,
                use_bb_squeeze=True, bb_squeeze_lookback=50,
            ),
        },
        {
            'label': 'F3) HAMMER + BB SQUEEZE',
            'factory': lambda: V3BaselineStrategy(
                filter_name="HAMMER+BB_SQ",
                use_hammer_filter=True, hammer_wick_ratio=1.5,
                use_bb_squeeze=True, bb_squeeze_lookback=50,
            ),
        },
        {
            'label': 'F4) RSI DIV + VOL CONF 1.5x',
            'factory': lambda: V3BaselineStrategy(
                filter_name="RSI_DIV+VOL_CONF",
                use_rsi_divergence=True, rsi_div_lookback=3,
                use_vol_confirmation=True, vol_confirm_mult=1.5,
            ),
        },
        {
            'label': 'F5) ALL FILTERS (A2+B1+C1+D2+E1)',
            'factory': lambda: V3BaselineStrategy(
                filter_name="ALL_FILTERS",
                use_sma_filter=True, sma_period=50, sma_direction="below",
                use_rsi_divergence=True, rsi_div_lookback=3,
                use_vol_confirmation=True, vol_confirm_mult=1.5,
                use_hammer_filter=True, hammer_wick_ratio=1.5,
                use_bb_squeeze=True, bb_squeeze_lookback=50,
            ),
        },
    ]

    results = []

    for i, cfg in enumerate(configs):
        result = run_portfolio_backtest(
            data, cfg['factory'],
            max_positions=1,
            position_size=2000,
            use_signal_ranking=True,
            label=cfg['label'],
        )
        results.append(result)
        logger.info(f"  [{i+1}/{len(configs)}] {cfg['label']}: "
                     f"{result['trades']} trades, WR {result['win_rate']:.1f}%, "
                     f"P&L ${result['total_pnl']:+.0f}, PF {result['pf']:.2f}, "
                     f"DD {result['max_dd']:.1f}%")

    # ==========================================
    # RESULTS TABLES
    # ==========================================
    baseline = results[0]

    print()
    print("=" * 160)
    print("  RESULTATEN OVERZICHT — Extra Entry Filters vs V3 Baseline")
    print("=" * 160)
    print(f"  {'FILTER':<42} | {'#TR':>4} | {'W':>3} | {'L':>3} | {'WR%':>6} | {'P&L':>12} | {'ROI%':>8} | {'PF':>8} | {'DD%':>6} | {'AvgW':>8} | {'AvgL':>8} | {'TGT':>3} | {'STP':>3} | {'vs BL':>10}")
    print("  " + "-" * 158)

    for r in results:
        diff = r['total_pnl'] - baseline['total_pnl']
        pf_str = f"{r['pf']:.2f}" if r['pf'] < 999 else "INF"
        marker = ""
        if r['pf'] > baseline['pf'] and r['pf'] < 999 and r['trades'] >= 5:
            marker = " <<"
        if r['max_dd'] < baseline['max_dd'] and r['pf'] > baseline['pf'] * 0.8 and r['trades'] >= 5:
            marker = " *"
        if r['pf'] > baseline['pf'] and r['max_dd'] < baseline['max_dd'] and r['trades'] >= 5:
            marker = " ***"

        print(f"  {r['label']:<42} | {r['trades']:>4} | {r['wins']:>3} | {r['losses']:>3} | "
              f"{r['win_rate']:>5.1f}% | ${r['total_pnl']:>+9.0f} | {r['roi']:>+6.1f}% | "
              f"{pf_str:>8} | {r['max_dd']:>5.1f}% | ${r['avg_win']:>+6.0f} | ${r['avg_loss']:>+6.0f} | "
              f"{r['targets']:>3} | {r['stops']:>3} | ${diff:>+8.0f}{marker}")

    # ==========================================
    # PER-CATEGORIE SAMENVATTING
    # ==========================================
    print()
    print("=" * 140)
    print("  PER-CATEGORIE SAMENVATTING")
    print("=" * 140)

    categories = {
        'A) MOMENTUM (SMA)': [r for r in results if r['label'].startswith('A')],
        'B) RSI DIVERGENCE': [r for r in results if r['label'].startswith('B')],
        'C) VOLUME CONFIRM': [r for r in results if r['label'].startswith('C')],
        'D) HAMMER CANDLE': [r for r in results if r['label'].startswith('D')],
        'E) BB SQUEEZE': [r for r in results if r['label'].startswith('E')],
        'F) COMBINATIES': [r for r in results if r['label'].startswith('F')],
    }

    for cat_name, cat_results in categories.items():
        print(f"\n  --- {cat_name} ---")
        if not cat_results:
            print(f"    Geen resultaten")
            continue

        best = max(cat_results, key=lambda x: x['pf'] if x['trades'] >= 3 else 0)
        print(f"    Baseline: {baseline['trades']}tr, WR {baseline['win_rate']:.1f}%, "
              f"P&L ${baseline['total_pnl']:+,.0f}, PF {baseline['pf']:.2f}, DD {baseline['max_dd']:.1f}%")

        for r in cat_results:
            diff_pnl = r['total_pnl'] - baseline['total_pnl']
            diff_pf = r['pf'] - baseline['pf'] if r['pf'] < 999 and baseline['pf'] < 999 else 0
            diff_dd = r['max_dd'] - baseline['max_dd']
            pf_str = f"{r['pf']:.2f}" if r['pf'] < 999 else "INF"

            verdict = "WORSE" if r['total_pnl'] < baseline['total_pnl'] else "BETTER"
            if r['trades'] < 3:
                verdict = "TOO FEW"
            elif r['pf'] > baseline['pf'] and r['max_dd'] <= baseline['max_dd']:
                verdict = "WINNER"
            elif r['pf'] > baseline['pf']:
                verdict = "PF BETTER"
            elif r['max_dd'] < baseline['max_dd'] and r['pf'] >= baseline['pf'] * 0.8:
                verdict = "DD BETTER"

            print(f"    {r['label']:<38} | {r['trades']:>3}tr WR {r['win_rate']:>5.1f}% "
                  f"P&L ${r['total_pnl']:>+8.0f} PF {pf_str:>8} DD {r['max_dd']:>5.1f}% "
                  f"| dP&L ${diff_pnl:>+7.0f} dDD {diff_dd:>+5.1f}% | {verdict}")

    # ==========================================
    # WINNAAR ANALYSE
    # ==========================================
    print()
    print("=" * 140)
    print("  WINNAAR ANALYSE")
    print("=" * 140)

    # Filter: minstens 5 trades
    viable = [r for r in results[1:] if r['trades'] >= 5]

    # Criteria 1: PF > baseline
    pf_winners = sorted([r for r in viable if r['pf'] > baseline['pf'] and r['pf'] < 999],
                         key=lambda x: x['pf'], reverse=True)

    # Criteria 2: DD < baseline met vergelijkbare PF
    dd_winners = sorted([r for r in viable if r['max_dd'] < baseline['max_dd']
                          and r['pf'] >= baseline['pf'] * 0.8],
                         key=lambda x: x['max_dd'])

    # Criteria 3: Overall betere P&L
    pnl_winners = sorted([r for r in viable if r['total_pnl'] > baseline['total_pnl']],
                          key=lambda x: x['total_pnl'], reverse=True)

    print(f"\n  V3 Baseline: {baseline['trades']}tr, WR {baseline['win_rate']:.1f}%, "
          f"P&L ${baseline['total_pnl']:+,.0f}, PF {baseline['pf']:.2f}, DD {baseline['max_dd']:.1f}%")

    print(f"\n  PF WINNAARS (PF > {baseline['pf']:.2f}):")
    if pf_winners:
        for r in pf_winners[:5]:
            print(f"    {r['label']:<42} PF {r['pf']:.2f} (+{r['pf']-baseline['pf']:.2f}) | "
                  f"{r['trades']}tr WR {r['win_rate']:.1f}% P&L ${r['total_pnl']:+,.0f} DD {r['max_dd']:.1f}%")
    else:
        print(f"    Geen filters verbeteren PF boven baseline.")

    print(f"\n  DD WINNAARS (DD < {baseline['max_dd']:.1f}% met PF >= {baseline['pf']*0.8:.2f}):")
    if dd_winners:
        for r in dd_winners[:5]:
            print(f"    {r['label']:<42} DD {r['max_dd']:.1f}% ({r['max_dd']-baseline['max_dd']:+.1f}%) | "
                  f"PF {r['pf']:.2f} {r['trades']}tr WR {r['win_rate']:.1f}% P&L ${r['total_pnl']:+,.0f}")
    else:
        print(f"    Geen filters verbeteren DD met acceptabele PF.")

    print(f"\n  P&L WINNAARS (P&L > ${baseline['total_pnl']:+,.0f}):")
    if pnl_winners:
        for r in pnl_winners[:5]:
            print(f"    {r['label']:<42} P&L ${r['total_pnl']:+,.0f} (+${r['total_pnl']-baseline['total_pnl']:,.0f}) | "
                  f"PF {r['pf']:.2f} {r['trades']}tr WR {r['win_rate']:.1f}% DD {r['max_dd']:.1f}%")
    else:
        print(f"    Geen filters verbeteren P&L boven baseline.")

    # ==========================================
    # TRADE DETAILS voor top resultaten
    # ==========================================
    print()
    print("=" * 140)
    print("  TRADE DETAILS — V3 Baseline")
    print("=" * 140)

    for t in baseline['trade_list']:
        icon = "WIN" if t['pnl'] > 0 else "LOSS"
        print(f"    [{icon:>4}] {t['pair']:<14} | ${t['entry']:.6f} -> ${t['exit']:.6f} | "
              f"P&L ${t['pnl']:>+8.2f} | {t['bars']:>3} bars | {t['reason']}")

    # Show trade details for best filter (if different from baseline)
    all_results_with_trades = [r for r in viable if r['trade_list']]
    if pf_winners:
        best_filter = pf_winners[0]
        print()
        print(f"  TRADE DETAILS — {best_filter['label']}")
        print("  " + "-" * 100)
        for t in best_filter['trade_list']:
            icon = "WIN" if t['pnl'] > 0 else "LOSS"
            print(f"    [{icon:>4}] {t['pair']:<14} | ${t['entry']:.6f} -> ${t['exit']:.6f} | "
                  f"P&L ${t['pnl']:>+8.2f} | {t['bars']:>3} bars | {t['reason']}")

    # ==========================================
    # CONCLUSIE
    # ==========================================
    print()
    print("=" * 140)
    print("  CONCLUSIE")
    print("=" * 140)

    any_winner = bool(pf_winners or dd_winners)

    if any_winner:
        print("\n  Er zijn filters die de V3 baseline verbeteren!")
        if pf_winners:
            best = pf_winners[0]
            print(f"\n  BESTE PF FILTER: {best['label']}")
            print(f"    Trades: {best['trades']}, WR: {best['win_rate']:.1f}%, "
                  f"P&L: ${best['total_pnl']:+,.0f}, PF: {best['pf']:.2f}, DD: {best['max_dd']:.1f}%")
        if dd_winners:
            best = dd_winners[0]
            print(f"\n  BESTE DD FILTER: {best['label']}")
            print(f"    Trades: {best['trades']}, WR: {best['win_rate']:.1f}%, "
                  f"P&L: ${best['total_pnl']:+,.0f}, PF: {best['pf']:.2f}, DD: {best['max_dd']:.1f}%")
    else:
        print("\n  GEEN EXTRA FILTER VERBETERT DE V3 BASELINE SIGNIFICANT.")
        print("  De V3 strategie is al sterk geoptimaliseerd.")
        print("  Extra filters filteren signalen weg die winstgevend waren,")
        print("  of produceren te weinig trades voor statistisch betrouwbare conclusies.")

    print()
    print("=" * 140)


if __name__ == '__main__':
    main()

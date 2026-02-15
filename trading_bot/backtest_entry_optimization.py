#!/usr/bin/env python3
"""
Backtest Entry Signal Optimalisatie
------------------------------------
Systematisch testen van entry signaal varianten voor de DualConfirm bounce strategie.

Varianten:
  A) RSI thresholds: 30, 35, 40, 45
  B) Donchian periodes: 15, 20, 25, 30
  C) BB deviation: 1.5, 2.0, 2.5
  D) Single confirm: alleen DC, alleen BB, vs DUAL
  E) Momentum filters: EMA50 trend, volume spike, multi-bar bounce
  F) Bounce depth: diepere bounces filteren

Alle tests:
  - Portfolio-realistisch: max posities, chronologisch, 0.26% fee
  - ATR 3.0x trailing stop (bewezen verbetering)
  - Smart cooldown (8 bars na stop)
  - Volume filter (>=50% avg)
  - Beide configs: 2x$1000 en 3x$700

Gebruik:
    python backtest_entry_optimization.py
"""
import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
from strategy import Position, Signal
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

load_dotenv(BASE_DIR / '.env')

CACHE_FILE = BASE_DIR / 'candle_cache_60d.json'
KRAKEN_FEE = 0.0026  # 0.26%

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('backtest_entry_opt')


# ============================================================
# DATA FETCHING (hergebruik cache)
# ============================================================

def fetch_all_candles(days=60):
    """Fetch 4H candles voor alle coins. Cache resultaat."""
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            cache = json.load(f)
        cache_age = time.time() - cache.get('_timestamp', 0)
        if cache_age < 14400 and cache.get('_days', 0) >= days:
            coin_count = len([k for k in cache if not k.startswith('_')])
            logger.info(f"Cache geladen: {coin_count} coins, {cache.get('_days')}d (age={cache_age/3600:.1f}h)")
            return cache

    from kraken_client import KrakenClient
    api_key = os.getenv('KRAKEN_API_KEY', '')
    private_key = os.getenv('KRAKEN_PRIVATE_KEY', '')
    client = KrakenClient(api_key, private_key)

    coins_str = os.getenv('COINS', '')
    coins = [c.strip() for c in coins_str.split(',') if c.strip()]

    since = int((datetime.now(timezone.utc) - timedelta(days=days + 5)).timestamp())
    cache = {'_timestamp': time.time(), '_days': days}
    fetched = 0
    errors = 0

    logger.info(f"Fetching {days}d candles voor {len(coins)} coins...")

    for i, pair in enumerate(coins):
        try:
            candles = client.get_ohlc(pair, interval=240, since=since)
            if candles and len(candles) >= 30:
                cache[pair] = candles
                fetched += 1
            if (i + 1) % 50 == 0:
                logger.info(f"  {i+1}/{len(coins)} ({fetched} OK, {errors} errors)")
        except Exception as e:
            errors += 1

    logger.info(f"Fetch compleet: {fetched} coins, {errors} errors")

    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f)

    return cache


# ============================================================
# HELPER: EMA BEREKENING
# ============================================================

def calc_ema(values, period):
    """Bereken Exponential Moving Average."""
    if len(values) < period:
        return None
    # Start met SMA
    sma = sum(values[:period]) / period
    multiplier = 2 / (period + 1)
    ema = sma
    for val in values[period:]:
        ema = (val - ema) * multiplier + ema
    return ema


# ============================================================
# FLEXIBELE ENTRY STRATEGY
# ============================================================

class FlexibleEntryStrategy:
    """
    DualConfirm strategie met volledig configureerbare entry signalen.
    Exit logica blijft identiek (ATR 3.0x trail, DC/BB mid target, RSI>70, 15% hard cap).
    """

    def __init__(self,
                 # Donchian parameters
                 donchian_period=20,
                 use_donchian=True,       # False = skip DC check
                 # Bollinger parameters
                 bb_period=20,
                 bb_dev=2.0,
                 use_bb=True,             # False = skip BB check
                 # RSI parameters
                 rsi_period=14,
                 rsi_max=35,              # Unified RSI threshold
                 rsi_sell=70,
                 # ATR / Stop parameters
                 atr_period=14,
                 atr_stop_mult=3.0,       # ATR 3.0x (bewezen optimaal)
                 max_stop_loss_pct=15.0,
                 # Cooldown
                 cooldown_bars=4,
                 cooldown_after_stop=8,
                 # Volume filter
                 volume_min_pct=0.5,      # Min volume als fractie van avg (0.5 = 50%)
                 # Bounce bevestiging
                 require_bounce=True,     # close > prev close
                 # MOMENTUM FILTERS (nieuw)
                 ema_trend_filter=False,  # Alleen kopen als close > EMA50
                 ema_period=50,
                 volume_spike_filter=False, # Alleen bij volume > 1.5x avg
                 volume_spike_mult=1.5,
                 multi_bar_bounce=False,  # 2 opeenvolgende groene candles
                 # BOUNCE DEPTH FILTER (nieuw)
                 min_bounce_depth_pct=0.0, # Min % dat low onder DC lower moet zijn
                 # CONFIRM MODE
                 confirm_mode='dual',     # 'dual', 'dc_only', 'bb_only', 'either'
                 ):
        # Core params
        self.donchian_period = donchian_period
        self.use_donchian = use_donchian
        self.bb_period = bb_period
        self.bb_dev = bb_dev
        self.use_bb = use_bb
        self.rsi_period = rsi_period
        self.rsi_max = rsi_max
        self.rsi_sell = rsi_sell
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.max_stop_loss_pct = max_stop_loss_pct
        self.cooldown_bars = cooldown_bars
        self.cooldown_after_stop = cooldown_after_stop
        self.volume_min_pct = volume_min_pct
        self.require_bounce = require_bounce

        # Momentum filters
        self.ema_trend_filter = ema_trend_filter
        self.ema_period = ema_period
        self.volume_spike_filter = volume_spike_filter
        self.volume_spike_mult = volume_spike_mult
        self.multi_bar_bounce = multi_bar_bounce

        # Bounce depth
        self.min_bounce_depth_pct = min_bounce_depth_pct

        # Confirm mode
        self.confirm_mode = confirm_mode

        # State
        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def analyze(self, candles, position, pair):
        """Analyze met flexibele entry logica, vaste exit logica."""
        min_bars = max(self.donchian_period, self.bb_period, self.rsi_period,
                       self.atr_period, self.ema_period if self.ema_trend_filter else 0) + 5
        if len(candles) < min_bars:
            return Signal('WAIT', pair, 0, 'Niet genoeg data', confidence=0)

        self.bar_count = len(candles)

        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]

        # Indicators
        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)

        # Donchian op VORIGE bars (excl huidige)
        prev_highs = highs[:-1]
        prev_lows = lows[:-1]
        _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows, self.donchian_period)

        # Donchian inclusief huidige bar (voor mid channel target)
        hh, ll, mid_channel = calc_donchian(highs, lows, self.donchian_period)

        # Bollinger Bands
        bb_mid, bb_upper, bb_lower = calc_bollinger(closes, self.bb_period, self.bb_dev)

        current = candles[-1]
        prev = candles[-2]

        if position is None:
            # === CHECK ENTRY ===
            active_cooldown = self.cooldown_after_stop if self.last_exit_was_stop else self.cooldown_bars
            in_cooldown = (self.bar_count - self.last_exit_bar) < active_cooldown

            if in_cooldown:
                return Signal('WAIT', pair, current['close'],
                              'Cooldown', rsi=rsi, confidence=0)

            # --- RSI check (geldt voor alle modes) ---
            rsi_ok = rsi < self.rsi_max

            # --- Bounce check ---
            bounce_ok = True
            if self.require_bounce:
                bounce_ok = current['close'] > prev['close']

            # --- Donchian check ---
            donchian_ok = True
            if self.use_donchian and self.confirm_mode in ('dual', 'dc_only', 'either'):
                donchian_ok = (
                    prev_lowest is not None and
                    current['low'] <= prev_lowest
                )

            # --- BB check ---
            bb_ok = True
            if self.use_bb and self.confirm_mode in ('dual', 'bb_only', 'either'):
                bb_ok = (
                    bb_lower is not None and
                    current['close'] <= bb_lower
                )

            # --- Confirm mode logic ---
            if self.confirm_mode == 'dual':
                entry_confirmed = donchian_ok and bb_ok
            elif self.confirm_mode == 'dc_only':
                entry_confirmed = donchian_ok
            elif self.confirm_mode == 'bb_only':
                entry_confirmed = bb_ok
            elif self.confirm_mode == 'either':
                entry_confirmed = donchian_ok or bb_ok
            else:
                entry_confirmed = donchian_ok and bb_ok

            # --- Volume minimum filter ---
            volume_ok = True
            if self.volume_min_pct > 0:
                volumes = [c.get('volume', 0) for c in candles[-20:]]
                avg_vol = sum(volumes) / len(volumes) if volumes else 0
                current_vol = current.get('volume', 0)
                volume_ok = current_vol >= avg_vol * self.volume_min_pct

            # --- MOMENTUM FILTERS ---

            # EMA trend filter: alleen kopen als close > EMA
            ema_ok = True
            if self.ema_trend_filter:
                ema_val = calc_ema(closes, self.ema_period)
                if ema_val is not None:
                    ema_ok = current['close'] > ema_val

            # Volume spike filter: volume moet > multiplier * avg zijn
            vol_spike_ok = True
            if self.volume_spike_filter:
                volumes = [c.get('volume', 0) for c in candles[-20:]]
                avg_vol = sum(volumes) / len(volumes) if volumes else 0
                current_vol = current.get('volume', 0)
                vol_spike_ok = current_vol >= avg_vol * self.volume_spike_mult

            # Multi-bar bounce: 2 opeenvolgende groene candles
            multi_bounce_ok = True
            if self.multi_bar_bounce and len(candles) >= 3:
                prev2 = candles[-3]
                multi_bounce_ok = (
                    current['close'] > prev['close'] and
                    prev['close'] > prev2['close']
                )

            # Bounce depth filter
            depth_ok = True
            if self.min_bounce_depth_pct > 0 and prev_lowest and prev_lowest > 0:
                depth_pct = (prev_lowest - current['low']) / prev_lowest * 100
                depth_ok = depth_pct >= self.min_bounce_depth_pct

            # --- ALLE CHECKS COMBINEREN ---
            all_ok = (
                entry_confirmed and rsi_ok and bounce_ok and volume_ok and
                ema_ok and vol_spike_ok and multi_bounce_ok and depth_ok
            )

            if all_ok:
                stop = current['close'] - atr * self.atr_stop_mult
                max_stop = current['close'] * (1 - self.max_stop_loss_pct / 100)
                if stop < max_stop:
                    stop = max_stop

                target = mid_channel
                if bb_mid and (target is None or bb_mid < target):
                    target = bb_mid

                return Signal(
                    'BUY', pair, current['close'],
                    f"Entry: RSI={rsi:.1f}, mode={self.confirm_mode}",
                    stop_price=stop, target_price=target,
                    rsi=rsi, confidence=0.90
                )

            return Signal('WAIT', pair, current['close'],
                          'Geen signaal', rsi=rsi, confidence=0)

        else:
            # === EXIT LOGICA (identiek voor alle varianten) ===
            # ATR 3.0x trailing stop + DC/BB mid target + RSI>70 + 15% hard cap

            if current['close'] > position.highest_price:
                position.highest_price = current['close']
            new_stop = position.highest_price - atr * self.atr_stop_mult
            max_stop = position.entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < max_stop:
                new_stop = max_stop
            if new_stop > position.stop_price:
                position.stop_price = new_stop

            pnl_pct = (current['close'] - position.entry_price) / position.entry_price * 100

            # Hard stop
            hard_stop = position.entry_price * (1 - self.max_stop_loss_pct / 100)
            if current['close'] < hard_stop:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = True
                return Signal('SELL_STOP', pair, current['close'],
                              f"Hard stop: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.95)

            # DC mid target
            if mid_channel and current['close'] >= mid_channel:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = False
                return Signal('SELL_TARGET', pair, current['close'],
                              f"DC target: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.9)

            # BB mid target
            if bb_mid and current['close'] >= bb_mid:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = False
                return Signal('SELL_TARGET', pair, current['close'],
                              f"BB target: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.9)

            # RSI overbought
            if rsi > self.rsi_sell:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = False
                return Signal('SELL_TARGET', pair, current['close'],
                              f"RSI exit: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.85)

            # Trailing stop
            if current['close'] < position.stop_price:
                self.last_exit_bar = self.bar_count
                self.last_exit_was_stop = True
                return Signal('SELL_STOP', pair, current['close'],
                              f"Trail stop: P&L={pnl_pct:+.1f}%",
                              rsi=rsi, confidence=0.95)

            return Signal('HOLD', pair, current['close'],
                          f"Holding: P&L={pnl_pct:+.1f}%",
                          stop_price=position.stop_price, rsi=rsi)


# ============================================================
# SIGNAL EXTRACTION & PORTFOLIO SIMULATION
# ============================================================

def extract_signals(cache, strategy_kwargs):
    """Extract alle signalen chronologisch uit alle coins."""
    all_events = []
    coins = [k for k in cache if not k.startswith('_')]

    for pair in coins:
        candles = cache[pair]
        if not isinstance(candles, list) or len(candles) < 30:
            continue

        strat = FlexibleEntryStrategy(**strategy_kwargs)
        position = None

        for i in range(25, len(candles)):
            window = candles[:i + 1]
            current = candles[i]
            bar_time = current['time']

            signal = strat.analyze(window, position, pair)

            if signal.action == 'BUY' and position is None:
                all_events.append({
                    'time': bar_time,
                    'pair': pair,
                    'action': 'BUY',
                    'price': signal.price,
                    'stop_price': signal.stop_price,
                    'target_price': signal.target_price,
                    'rsi': signal.rsi,
                    'bar_idx': i,
                })
                position = Position(
                    pair=pair,
                    entry_price=signal.price,
                    volume=1,
                    stop_price=signal.stop_price,
                    highest_price=signal.price,
                    entry_time=bar_time,
                )

            elif signal.action in ('SELL_TARGET', 'SELL_STOP') and position is not None:
                all_events.append({
                    'time': bar_time,
                    'pair': pair,
                    'action': signal.action,
                    'price': signal.price,
                    'rsi': signal.rsi,
                    'entry_price': position.entry_price,
                    'bar_idx': i,
                })
                position = None

            elif position is not None:
                if current['close'] > position.highest_price:
                    position.highest_price = current['close']

    all_events.sort(key=lambda x: x['time'])
    return all_events


def simulate_portfolio(events, max_positions, capital_per_trade, commission):
    """Portfolio simulatie."""
    positions = {}
    closed_trades = []

    for event in events:
        if event['action'] in ('SELL_TARGET', 'SELL_STOP'):
            pair = event['pair']
            if pair in positions:
                pos = positions[pair]
                entry_price = pos['entry_price']
                exit_price = event['price']
                volume = pos['volume']

                gross_pnl = (exit_price - entry_price) * volume
                entry_fee = entry_price * volume * commission
                exit_fee = exit_price * volume * commission
                net_pnl = gross_pnl - entry_fee - exit_fee

                closed_trades.append({
                    'pair': pair,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pnl': net_pnl,
                    'pnl_pct': (exit_price - entry_price) / entry_price * 100,
                    'exit_type': 'TARGET' if event['action'] == 'SELL_TARGET' else 'STOP',
                    'capital_used': pos['capital_used'],
                })
                del positions[pair]

        elif event['action'] == 'BUY':
            pair = event['pair']
            if pair in positions or len(positions) >= max_positions:
                continue

            cap = capital_per_trade
            volume = cap / event['price']
            positions[pair] = {
                'entry_price': event['price'],
                'volume': volume,
                'entry_time': event['time'],
                'capital_used': cap,
            }

    return closed_trades


def calc_results(trades, capital_per_trade, max_positions):
    """Bereken alle statistieken voor een set trades."""
    total = len(trades)
    if total == 0:
        return None

    wins = [t for t in trades if t['pnl'] >= 0]
    losses = [t for t in trades if t['pnl'] < 0]
    total_pnl = sum(t['pnl'] for t in trades)
    gross_wins = sum(t['pnl'] for t in wins)
    gross_losses = abs(sum(t['pnl'] for t in losses))

    wr = len(wins) / total * 100
    pf = gross_wins / gross_losses if gross_losses > 0 else 999
    avg_pnl = total_pnl / total
    total_capital = capital_per_trade * max_positions
    roi = total_pnl / total_capital * 100
    avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0

    stop_trades = [t for t in trades if t['exit_type'] == 'STOP']
    target_trades = [t for t in trades if t['exit_type'] == 'TARGET']

    return {
        'trades': total,
        'wins': len(wins),
        'losses': len(losses),
        'wr': wr,
        'pnl': total_pnl,
        'roi': roi,
        'pf': pf,
        'avg_pnl': avg_pnl,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'stop_count': len(stop_trades),
        'target_count': len(target_trades),
        'stop_pnl': sum(t['pnl'] for t in stop_trades),
        'target_pnl': sum(t['pnl'] for t in target_trades),
    }


def run_variant(cache, name, strategy_kwargs, configs):
    """Run een entry variant voor alle configs en return resultaten."""
    events = extract_signals(cache, strategy_kwargs)
    results = {}

    for config_name, max_pos, capital in configs:
        trades = simulate_portfolio(events, max_pos, capital, KRAKEN_FEE)
        r = calc_results(trades, capital, max_pos)
        if r:
            r['name'] = name
            r['config'] = config_name
            results[config_name] = r
        else:
            results[config_name] = {
                'name': name, 'config': config_name,
                'trades': 0, 'wins': 0, 'losses': 0,
                'wr': 0, 'pnl': 0, 'roi': 0, 'pf': 0,
                'avg_pnl': 0, 'avg_win': 0, 'avg_loss': 0,
                'stop_count': 0, 'target_count': 0,
                'stop_pnl': 0, 'target_pnl': 0,
            }

    return results


# ============================================================
# MAIN - ALLE VARIANTEN TESTEN
# ============================================================

def main():
    print(f"\n{'='*130}")
    print(f"  ENTRY SIGNAL OPTIMALISATIE - 60 DAGEN BACKTEST")
    print(f"  Base: DualConfirm | ATR 3.0x trail | Smart cooldown 8 bars | Volume >=50% avg | 0.26% fee")
    print(f"{'='*130}\n")

    # 1. Fetch data
    cache = fetch_all_candles(days=60)
    coin_count = len([k for k in cache if not k.startswith('_')])
    logger.info(f"Data geladen: {coin_count} coins")

    configs = [
        ('2x$1000', 2, 1000),
        ('3x$700', 3, 700),
    ]

    # Base params die voor alle varianten gelden
    base = {
        'atr_stop_mult': 3.0,
        'max_stop_loss_pct': 15.0,
        'cooldown_bars': 4,
        'cooldown_after_stop': 8,
        'volume_min_pct': 0.5,
        'rsi_sell': 70,
        'rsi_period': 14,
        'atr_period': 14,
    }

    all_results = {}  # {variant_name: {config_name: results}}

    # ============================================================
    # BASELINE: Huidige strategie
    # ============================================================
    print(f"  [0/6] BASELINE...")
    r = run_variant(cache, "BASELINE (DC+BB, RSI<35, DC20, BB2.0)",
                    {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                     'rsi_max': 35, 'confirm_mode': 'dual'}, configs)
    all_results['baseline'] = r

    # ============================================================
    # A) RSI THRESHOLDS
    # ============================================================
    print(f"  [1/6] RSI threshold varianten...")
    for rsi_val in [25, 30, 35, 40, 45]:
        name = f"A) RSI < {rsi_val}"
        r = run_variant(cache, name,
                        {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                         'rsi_max': rsi_val, 'confirm_mode': 'dual'}, configs)
        all_results[f'rsi_{rsi_val}'] = r

    # ============================================================
    # B) DONCHIAN PERIODES
    # ============================================================
    print(f"  [2/6] Donchian periode varianten...")
    for dc_period in [10, 15, 20, 25, 30]:
        name = f"B) DC period={dc_period}"
        r = run_variant(cache, name,
                        {**base, 'donchian_period': dc_period, 'bb_period': 20, 'bb_dev': 2.0,
                         'rsi_max': 35, 'confirm_mode': 'dual'}, configs)
        all_results[f'dc_{dc_period}'] = r

    # ============================================================
    # C) BB DEVIATION
    # ============================================================
    print(f"  [3/6] BB deviation varianten...")
    for bb_dev in [1.5, 1.75, 2.0, 2.25, 2.5]:
        name = f"C) BB dev={bb_dev}"
        r = run_variant(cache, name,
                        {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': bb_dev,
                         'rsi_max': 35, 'confirm_mode': 'dual'}, configs)
        all_results[f'bb_{bb_dev}'] = r

    # ============================================================
    # D) CONFIRM MODES
    # ============================================================
    print(f"  [4/6] Confirm mode varianten...")
    for mode in ['dual', 'dc_only', 'bb_only', 'either']:
        name = f"D) Confirm={mode}"
        r = run_variant(cache, name,
                        {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                         'rsi_max': 35, 'confirm_mode': mode}, configs)
        all_results[f'mode_{mode}'] = r

    # ============================================================
    # E) MOMENTUM FILTERS
    # ============================================================
    print(f"  [5/6] Momentum filter varianten...")

    # E1: EMA50 trend filter
    name = "E1) + EMA50 trend filter"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                     'rsi_max': 35, 'confirm_mode': 'dual',
                     'ema_trend_filter': True, 'ema_period': 50}, configs)
    all_results['ema50'] = r

    # E2: EMA20 trend filter (korter)
    name = "E2) + EMA20 trend filter"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                     'rsi_max': 35, 'confirm_mode': 'dual',
                     'ema_trend_filter': True, 'ema_period': 20}, configs)
    all_results['ema20'] = r

    # E3: Volume spike (>1.5x avg)
    name = "E3) + Volume spike >1.5x"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                     'rsi_max': 35, 'confirm_mode': 'dual',
                     'volume_spike_filter': True, 'volume_spike_mult': 1.5}, configs)
    all_results['vol_spike_1.5'] = r

    # E4: Volume spike (>2.0x avg)
    name = "E4) + Volume spike >2.0x"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                     'rsi_max': 35, 'confirm_mode': 'dual',
                     'volume_spike_filter': True, 'volume_spike_mult': 2.0}, configs)
    all_results['vol_spike_2.0'] = r

    # E5: Multi-bar bounce (2 groene candles)
    name = "E5) + Multi-bar bounce (2 green)"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                     'rsi_max': 35, 'confirm_mode': 'dual',
                     'multi_bar_bounce': True}, configs)
    all_results['multi_bounce'] = r

    # ============================================================
    # F) BOUNCE DEPTH FILTERS
    # ============================================================
    print(f"  [6/6] Bounce depth varianten...")
    for depth in [0.5, 1.0, 2.0, 3.0]:
        name = f"F) Min depth >= {depth}%"
        r = run_variant(cache, name,
                        {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                         'rsi_max': 35, 'confirm_mode': 'dual',
                         'min_bounce_depth_pct': depth}, configs)
        all_results[f'depth_{depth}'] = r

    # ============================================================
    # COMBO VARIANTEN - Beste individuele combinaties
    # ============================================================
    print(f"  [BONUS] Combo varianten...")

    # Combo 1: RSI<40 + DC15 (meer signalen)
    name = "COMBO1: RSI<40 + DC15"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 15, 'bb_period': 20, 'bb_dev': 2.0,
                     'rsi_max': 40, 'confirm_mode': 'dual'}, configs)
    all_results['combo_rsi40_dc15'] = r

    # Combo 2: RSI<40 + BB1.75 (meer signalen)
    name = "COMBO2: RSI<40 + BB1.75"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 1.75,
                     'rsi_max': 40, 'confirm_mode': 'dual'}, configs)
    all_results['combo_rsi40_bb175'] = r

    # Combo 3: RSI<40 + DC_only (relaxed)
    name = "COMBO3: RSI<40 + DC only"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                     'rsi_max': 40, 'confirm_mode': 'dc_only'}, configs)
    all_results['combo_rsi40_dc_only'] = r

    # Combo 4: RSI<40 + BB_only (relaxed)
    name = "COMBO4: RSI<40 + BB only"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                     'rsi_max': 40, 'confirm_mode': 'bb_only'}, configs)
    all_results['combo_rsi40_bb_only'] = r

    # Combo 5: RSI<40 + either (zeer relaxed)
    name = "COMBO5: RSI<40 + either DC|BB"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                     'rsi_max': 40, 'confirm_mode': 'either'}, configs)
    all_results['combo_rsi40_either'] = r

    # Combo 6: RSI<45 + DC15 + BB1.75 (max signalen)
    name = "COMBO6: RSI<45 + DC15 + BB1.75"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 15, 'bb_period': 20, 'bb_dev': 1.75,
                     'rsi_max': 45, 'confirm_mode': 'dual'}, configs)
    all_results['combo_max_signals'] = r

    # Combo 7: RSI<30 + depth>1% (strenger = betere kwaliteit?)
    name = "COMBO7: RSI<30 + depth>1%"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                     'rsi_max': 30, 'confirm_mode': 'dual',
                     'min_bounce_depth_pct': 1.0}, configs)
    all_results['combo_strict'] = r

    # Combo 8: DC_only + RSI<40 + vol spike (populaire combo)
    name = "COMBO8: DC only + RSI<40 + vol>1.5x"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                     'rsi_max': 40, 'confirm_mode': 'dc_only',
                     'volume_spike_filter': True, 'volume_spike_mult': 1.5}, configs)
    all_results['combo_dc_vol'] = r

    # Combo 9: Either + RSI<40 + multi-bar bounce (medium relaxed)
    name = "COMBO9: Either + RSI<40 + multi-bar"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 20, 'bb_period': 20, 'bb_dev': 2.0,
                     'rsi_max': 40, 'confirm_mode': 'either',
                     'multi_bar_bounce': True}, configs)
    all_results['combo_either_multi'] = r

    # Combo 10: RSI<40 + BB1.75 + DC15 + either (max max)
    name = "COMBO10: RSI<40 + BB1.75 + DC15 + either"
    r = run_variant(cache, name,
                    {**base, 'donchian_period': 15, 'bb_period': 20, 'bb_dev': 1.75,
                     'rsi_max': 40, 'confirm_mode': 'either'}, configs)
    all_results['combo_ultra_relaxed'] = r

    # ============================================================
    # RESULTATEN TABEL
    # ============================================================
    print(f"\n{'='*130}")
    print(f"  RESULTATEN OVERZICHT")
    print(f"{'='*130}")

    for config_name, max_pos, capital in configs:
        print(f"\n  {'='*126}")
        print(f"  CONFIG: {config_name} (max {max_pos} pos, ${capital}/trade, ${max_pos*capital} totaal)")
        print(f"  {'='*126}")
        print(f"  {'VARIANT':<45} | {'#':>3} | {'WR':>5} | {'P&L':>10} | {'ROI':>6} | {'PF':>5} | "
              f"{'AvgW':>7} | {'AvgL':>7} | {'TGT':>3} | {'STP':>3} | {'STP P&L':>8}")
        print(f"  {'-'*126}")

        # Collect all results for this config
        config_data = []
        for key, variant_results in all_results.items():
            r = variant_results.get(config_name)
            if r:
                config_data.append(r)

        # Sort by P&L
        config_data.sort(key=lambda x: x.get('pnl', 0), reverse=True)

        # Print baseline apart
        baseline_r = all_results.get('baseline', {}).get(config_name)
        baseline_pnl = baseline_r['pnl'] if baseline_r else 0

        for i, r in enumerate(config_data):
            diff = r['pnl'] - baseline_pnl
            diff_str = f"({'+' if diff >= 0 else ''}{diff:.0f})"
            marker = " ***" if i < 3 else ""

            name_short = r['name'][:44]
            print(f"  {name_short:<45} | {r['trades']:>3} | {r['wr']:>4.1f}% | "
                  f"${r['pnl']:>+8.2f} | {r['roi']:>+5.1f}% | {r['pf']:>5.2f} | "
                  f"${r['avg_win']:>+6.2f} | ${r['avg_loss']:>+6.2f} | "
                  f"{r.get('target_count',0):>3} | {r.get('stop_count',0):>3} | "
                  f"${r.get('stop_pnl',0):>+7.0f} {diff_str:>8}{marker}")

    # ============================================================
    # TOP 3 PER CONFIG
    # ============================================================
    print(f"\n{'='*130}")
    print(f"  TOP 3 ENTRY CONFIGURATIES")
    print(f"{'='*130}")

    for config_name, max_pos, capital in configs:
        print(f"\n  --- {config_name} ---")
        baseline_r = all_results.get('baseline', {}).get(config_name)
        baseline_pnl = baseline_r['pnl'] if baseline_r else 0
        baseline_pf = baseline_r['pf'] if baseline_r else 0
        baseline_wr = baseline_r['wr'] if baseline_r else 0
        baseline_trades = baseline_r['trades'] if baseline_r else 0

        print(f"  BASELINE: {baseline_trades} trades | WR {baseline_wr:.1f}% | "
              f"P&L ${baseline_pnl:+.2f} | PF {baseline_pf:.2f}")
        print()

        # Get all results for this config, exclude baseline
        config_data = []
        for key, variant_results in all_results.items():
            if key == 'baseline':
                continue
            r = variant_results.get(config_name)
            if r and r['trades'] > 0:
                config_data.append(r)

        # Ranking: primair op PnL, maar ook kijken naar PF en WR
        # Score = P&L normalisatie (50%) + PF normalisatie (30%) + WR normalisatie (20%)
        if config_data:
            max_pnl = max(r['pnl'] for r in config_data) if config_data else 1
            min_pnl = min(r['pnl'] for r in config_data) if config_data else 0
            pnl_range = max_pnl - min_pnl if max_pnl != min_pnl else 1

            max_pf = max(r['pf'] for r in config_data) if config_data else 1
            min_pf = min(r['pf'] for r in config_data) if config_data else 0
            pf_range = max_pf - min_pf if max_pf != min_pf else 1

            max_wr = max(r['wr'] for r in config_data) if config_data else 1
            min_wr = min(r['wr'] for r in config_data) if config_data else 0
            wr_range = max_wr - min_wr if max_wr != min_wr else 1

            for r in config_data:
                pnl_score = (r['pnl'] - min_pnl) / pnl_range
                pf_score = (r['pf'] - min_pf) / pf_range
                wr_score = (r['wr'] - min_wr) / wr_range
                # Min trade filter: penalize very few trades
                trade_penalty = 0
                if r['trades'] < 10:
                    trade_penalty = 0.3
                elif r['trades'] < 20:
                    trade_penalty = 0.1
                r['composite_score'] = pnl_score * 0.50 + pf_score * 0.30 + wr_score * 0.20 - trade_penalty

            config_data.sort(key=lambda x: x['composite_score'], reverse=True)

            for i, r in enumerate(config_data[:5]):
                diff_pnl = r['pnl'] - baseline_pnl
                diff_pf = r['pf'] - baseline_pf
                print(f"  #{i+1} {r['name']}")
                print(f"      {r['trades']} trades | WR {r['wr']:.1f}% | "
                      f"P&L ${r['pnl']:+.2f} ({'+' if diff_pnl >= 0 else ''}{diff_pnl:.2f} vs baseline) | "
                      f"PF {r['pf']:.2f} ({'+' if diff_pf >= 0 else ''}{diff_pf:.2f}) | "
                      f"Score: {r['composite_score']:.3f}")
                print(f"      Targets: {r.get('target_count',0)} | Stops: {r.get('stop_count',0)} "
                      f"(stop P&L: ${r.get('stop_pnl',0):+.0f}) | "
                      f"Avg win: ${r['avg_win']:+.2f} | Avg loss: ${r['avg_loss']:+.2f}")
                print()

    # ============================================================
    # AANBEVELING
    # ============================================================
    print(f"\n{'='*130}")
    print(f"  AANBEVELING")
    print(f"{'='*130}")
    print()

    for config_name, max_pos, capital in configs:
        config_data = []
        for key, variant_results in all_results.items():
            if key == 'baseline':
                continue
            r = variant_results.get(config_name)
            if r and r['trades'] > 0:
                config_data.append(r)

        if config_data:
            # Best by composite score
            best_composite = max(config_data, key=lambda x: x.get('composite_score', 0))
            # Best by pure P&L
            best_pnl = max(config_data, key=lambda x: x['pnl'])
            # Best by PF (min 15 trades)
            pf_candidates = [r for r in config_data if r['trades'] >= 15]
            best_pf = max(pf_candidates, key=lambda x: x['pf']) if pf_candidates else None

            baseline_r = all_results.get('baseline', {}).get(config_name)
            baseline_pnl = baseline_r['pnl'] if baseline_r else 0

            print(f"  {config_name}:")
            print(f"    BESTE OVERALL (composite): {best_composite['name']}")
            print(f"      P&L ${best_composite['pnl']:+.2f} ({'+' if best_composite['pnl']-baseline_pnl >= 0 else ''}{best_composite['pnl']-baseline_pnl:.2f} vs baseline)")
            print(f"      PF {best_composite['pf']:.2f} | WR {best_composite['wr']:.1f}% | {best_composite['trades']} trades")
            print()
            print(f"    BESTE P&L: {best_pnl['name']}")
            print(f"      P&L ${best_pnl['pnl']:+.2f} | PF {best_pnl['pf']:.2f} | {best_pnl['trades']} trades")
            if best_pf:
                print()
                print(f"    BESTE PF (>=15 trades): {best_pf['name']}")
                print(f"      PF {best_pf['pf']:.2f} | P&L ${best_pf['pnl']:+.2f} | {best_pf['trades']} trades")
            print()

    print(f"{'='*130}\n")


if __name__ == '__main__':
    main()

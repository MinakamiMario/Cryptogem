#!/usr/bin/env python3
"""
MEGA STRATEGIE VERGELIJKING — Alle varianten op 532 coins
==========================================================
Test ALLE strategie-varianten die ooit zijn gebouwd op de
volledige dynamische 532 coins dataset (60 dagen, 4H candles).

Strategieën:
  1.  BASELINE V3:      DC+BB, RSI<35, geen vol filters
  2.  V3 + VolSpike:    + volume spike >2x
  3.  V3 + BE stop:     + break-even +3%
  4.  V4 DUALCONFIRM:   RSI<40, VolSpike>2x, VolConfirm>1x, BE+3%, TimeMax 10
  5.  V5 RSI REC 47:    V4 + RSI Recovery exit target=47, min_bars=2
  6.  V5 RSI REC 45:    V4 + RSI Recovery exit target=45, min_bars=2 (productie)
  7.  V5 RSI REC 42:    V4 + RSI Recovery exit target=42, min_bars=2 (conservatief)
  8.  V4 ZONDER VOL:    V4 maar zonder volume spike/confirm filters
  9.  V4 + ADX FILTER:  V4 + ADX<25 trend filter
  10. V4 + DC=15:       Kortere Donchian period
  11. V4 + ATR 1.5x:    Tightere trailing stop
  12. V4 + ATR 3.0x:    Lossere trailing stop
  13. V4 + TimeMax 16:  Langere time limit
  14. V4 + RSI<35:      Strengere RSI entry
  15. V5 + 2x$1000:     V5 winner maar met 2 posities
  16. V5 + 3x$667:      V5 winner maar met 3 posities
  17. V5 + VolSpike 3x:  V5 met strengere volume spike
  18. V5 + VolSpike 1.5x: V5 met lossere volume spike
  19. V5 + BB dev 1.8:  V5 met tightere BB
  20. V5 + BB dev 2.2:  V5 met lossere BB

Gebruik:
    python backtest_mega_compare.py              # Gebruik bestaande cache
    python backtest_mega_compare.py --refresh    # Download verse data eerst
"""
import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

load_dotenv(BASE_DIR / '.env')

CACHE_FILE = BASE_DIR / 'candle_cache_532.json'
KRAKEN_FEE = 0.0026

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('mega_compare')


# ============================================================
# DATA
# ============================================================

def load_data(force_refresh=False) -> dict:
    """Laad candle data uit cache of download."""
    if not force_refresh and CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            data = json.load(f)
        coins = len([k for k in data if not k.startswith('_')])
        age_h = (time.time() - data.get('_timestamp', 0)) / 3600
        logger.info(f"Cache: {coins} coins, {age_h:.1f}h oud")
        return data

    # Download via het andere script
    logger.info("Downloading verse candle data...")
    from backtest_532_coins import download_all_candles
    return download_all_candles(force_refresh=True)


# ============================================================
# CONFIGURABLE STRATEGY
# ============================================================

def calc_adx(highs, lows, closes, period=14):
    """Bereken ADX (Average Directional Index)."""
    if len(highs) < period + 1:
        return None
    plus_dm = []
    minus_dm = []
    tr_list = []
    for i in range(1, len(highs)):
        up = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i] - closes[i-1]))
        tr_list.append(tr)

    if len(tr_list) < period:
        return None

    atr_val = sum(tr_list[-period:]) / period
    if atr_val == 0:
        return 0

    plus_di = (sum(plus_dm[-period:]) / period) / atr_val * 100
    minus_di = (sum(minus_dm[-period:]) / period) / atr_val * 100

    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0
    dx = abs(plus_di - minus_di) / di_sum * 100
    return dx


class ConfigurableStrategy:
    """
    Universele strategie met alle parameters configureerbaar.
    Elke strategie-variant is gewoon een andere config dict.
    """

    def __init__(self, cfg: dict):
        # Entry
        self.donchian_period = cfg.get('dc_period', 20)
        self.bb_period = cfg.get('bb_period', 20)
        self.bb_dev = cfg.get('bb_dev', 2.0)
        self.rsi_period = cfg.get('rsi_period', 14)
        self.rsi_max = cfg.get('rsi_max', 40)
        self.atr_period = cfg.get('atr_period', 14)
        self.volume_min_pct = cfg.get('vol_min_pct', 0.5)

        # Entry filters
        self.use_volume_spike = cfg.get('vol_spike', False)
        self.volume_spike_mult = cfg.get('vol_spike_mult', 2.0)
        self.use_vol_confirm = cfg.get('vol_confirm', False)
        self.vol_confirm_mult = cfg.get('vol_confirm_mult', 1.0)
        self.use_adx_filter = cfg.get('adx_filter', False)
        self.adx_max = cfg.get('adx_max', 25)

        # Exit
        self.atr_stop_mult = cfg.get('atr_mult', 2.0)
        self.max_stop_loss_pct = cfg.get('max_stop_pct', 15.0)
        self.use_breakeven = cfg.get('breakeven', False)
        self.breakeven_trigger = cfg.get('be_trigger', 3.0)
        self.use_time_max = cfg.get('time_max', False)
        self.time_max_bars = cfg.get('time_max_bars', 10)
        self.rsi_sell = cfg.get('rsi_sell', 70)

        # V5: RSI Recovery exit
        self.use_rsi_recovery = cfg.get('rsi_recovery', False)
        self.rsi_recovery_target = cfg.get('rsi_rec_target', 47)
        self.rsi_recovery_min_bars = cfg.get('rsi_rec_min_bars', 2)

        # Cooldown
        self.cooldown_bars = cfg.get('cooldown_bars', 4)
        self.cooldown_after_stop = cfg.get('cooldown_stop', 8)

        # State
        self.last_exit_bar = -999
        self.last_exit_was_stop = False
        self.bar_count = 0

    def analyze(self, candles, position, pair):
        min_bars = max(self.donchian_period, self.bb_period,
                       self.rsi_period, self.atr_period) + 5
        if len(candles) < min_bars:
            return {'action': 'WAIT'}

        self.bar_count = len(candles)
        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]

        rsi = calc_rsi(closes, self.rsi_period)
        atr = calc_atr(highs, lows, closes, self.atr_period)
        _, prev_lowest, _ = calc_donchian(highs[:-1], lows[:-1],
                                          self.donchian_period)
        hh, ll, mid_channel = calc_donchian(highs, lows, self.donchian_period)
        bb_mid, bb_upper, bb_lower = calc_bollinger(
            closes, self.bb_period, self.bb_dev)

        if any(v is None for v in [rsi, atr, prev_lowest, mid_channel,
                                   bb_mid, bb_lower]):
            return {'action': 'WAIT'}

        close = candles[-1]['close']
        low = candles[-1]['low']
        prev_close = candles[-2]['close'] if len(candles) > 1 else close

        # ── EXIT ──
        if position:
            entry_price = position['entry_price']
            bars_in = self.bar_count - position['entry_bar']

            if close > position['highest_price']:
                position['highest_price'] = close

            new_stop = position['highest_price'] - atr * self.atr_stop_mult
            hard_stop = entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < hard_stop:
                new_stop = hard_stop

            # Break-even
            if self.use_breakeven:
                pnl_pct = (close - entry_price) / entry_price * 100
                if pnl_pct >= self.breakeven_trigger:
                    be_level = entry_price * (1 + KRAKEN_FEE * 2)
                    if new_stop < be_level:
                        new_stop = be_level

            if new_stop > position['stop_price']:
                position['stop_price'] = new_stop

            if close < hard_stop:
                return {'action': 'SELL', 'reason': 'HARD STOP',
                        'price': close}

            if self.use_time_max and bars_in >= self.time_max_bars:
                return {'action': 'SELL', 'reason': 'TIME MAX',
                        'price': close}

            if (self.use_rsi_recovery
                    and bars_in >= self.rsi_recovery_min_bars
                    and rsi >= self.rsi_recovery_target):
                return {'action': 'SELL', 'reason': 'RSI RECOVERY',
                        'price': close}

            if close >= mid_channel:
                return {'action': 'SELL', 'reason': 'DC TARGET',
                        'price': close}
            if close >= bb_mid:
                return {'action': 'SELL', 'reason': 'BB TARGET',
                        'price': close}
            if rsi > self.rsi_sell:
                return {'action': 'SELL', 'reason': 'RSI EXIT',
                        'price': close}
            if close < position['stop_price']:
                return {'action': 'SELL', 'reason': 'TRAIL STOP',
                        'price': close}

            return {'action': 'HOLD', 'price': close}

        # ── ENTRY ──
        cd = (self.cooldown_after_stop if self.last_exit_was_stop
              else self.cooldown_bars)
        if (self.bar_count - self.last_exit_bar) < cd:
            return {'action': 'WAIT'}

        # Base volume
        if volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_min_pct:
                return {'action': 'WAIT'}

        # Dual confirm
        dc_sig = (low <= prev_lowest and rsi < self.rsi_max
                  and close > prev_close)
        bb_sig = (close <= bb_lower and rsi < self.rsi_max
                  and close > prev_close)
        if not (dc_sig and bb_sig):
            return {'action': 'WAIT'}

        # Volume spike
        if self.use_volume_spike and volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
                return {'action': 'WAIT'}

        # Volume confirm
        if (self.use_vol_confirm and len(volumes) >= 2
                and volumes[-2] > 0):
            if volumes[-1] / volumes[-2] < self.vol_confirm_mult:
                return {'action': 'WAIT'}

        # ADX filter
        if self.use_adx_filter:
            adx = calc_adx(highs, lows, closes)
            if adx is not None and adx > self.adx_max:
                return {'action': 'WAIT'}

        # Entry!
        stop = close - atr * self.atr_stop_mult
        hard_stop = close * (1 - self.max_stop_loss_pct / 100)
        if stop < hard_stop:
            stop = hard_stop

        # Quality score (voor ranking)
        rsi_sc = max(0, (self.rsi_max - rsi) / self.rsi_max)
        dc_d = (prev_lowest - low) / prev_lowest if prev_lowest > 0 else 0
        d_sc = min(1, dc_d * 20)
        v_sc = 0
        if volumes and vol_avg > 0:
            v_sc = min(1, volumes[-1] / vol_avg / 3)
        quality = rsi_sc * 0.4 + d_sc * 0.3 + v_sc * 0.3

        return {'action': 'BUY', 'price': close, 'stop_price': stop,
                'quality': quality}


# ============================================================
# BACKTEST ENGINE
# ============================================================

@dataclass
class Pos:
    pair: str
    entry_price: float
    entry_bar: int
    stop_price: float
    highest_price: float
    size_usd: float


def run_backtest(data, coins, cfg, max_pos=1, pos_size=2000,
                 use_ranking=True, label=""):
    """Portfolio backtest met ConfigurableStrategy."""
    coin_list = [c for c in coins if c in data]
    strategies = {p: ConfigurableStrategy(cfg) for p in coin_list}

    max_bars = max(len(data[p]) for p in coin_list) if coin_list else 0

    positions = {}
    trades = []
    equity = max_pos * pos_size
    initial_eq = equity
    peak_eq = equity
    max_dd = 0
    equity_curve = []

    for bar in range(50, max_bars):
        buys = []
        sells = []

        for pair in coin_list:
            candles = data.get(pair, [])
            if bar >= len(candles):
                continue

            window = candles[:bar + 1]
            pos = positions.get(pair)
            pos_d = None
            if pos:
                pos_d = {'entry_price': pos.entry_price,
                         'stop_price': pos.stop_price,
                         'highest_price': pos.highest_price,
                         'entry_bar': pos.entry_bar}

            sig = strategies[pair].analyze(window, pos_d, pair)

            if pos_d and pos:
                pos.stop_price = pos_d['stop_price']
                pos.highest_price = pos_d['highest_price']

            if sig['action'] == 'SELL' and pair in positions:
                sells.append((pair, sig))
            elif sig['action'] == 'BUY' and pair not in positions:
                buys.append((pair, sig, candles[bar]))

        # Sells
        for pair, sig in sells:
            pos = positions[pair]
            sp = sig['price']
            gross = (sp - pos.entry_price) / pos.entry_price * pos.size_usd
            fees = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
            net = gross - fees
            equity += net
            bars_h = bar - pos.entry_bar
            is_stop = 'STOP' in sig.get('reason', '')
            s = strategies[pair]
            s.last_exit_bar = s.bar_count
            s.last_exit_was_stop = is_stop
            trades.append({'pair': pair, 'entry': pos.entry_price,
                           'exit': sp, 'pnl': net, 'reason': sig['reason'],
                           'bars': bars_h})
            del positions[pair]

        # Buys (ranking)
        if len(positions) < max_pos and buys:
            if use_ranking:
                def rank(item):
                    p, s, c = item
                    cd = data.get(p, [])
                    vs = [x.get('volume', 0)
                          for x in cd[max(0, bar-20):bar+1]]
                    if vs and len(vs) > 1:
                        avg = sum(vs[:-1]) / max(1, len(vs)-1)
                        if avg > 0:
                            return vs[-1] / avg
                    return 0
                buys.sort(key=rank, reverse=True)

            for pair, sig, candle in buys:
                if len(positions) >= max_pos:
                    break
                positions[pair] = Pos(
                    pair=pair, entry_price=sig['price'],
                    entry_bar=bar,
                    stop_price=sig.get('stop_price', sig['price'] * 0.85),
                    highest_price=sig['price'], size_usd=pos_size)

        # DD
        if equity > peak_eq:
            peak_eq = equity
        dd = (peak_eq - equity) / peak_eq * 100 if peak_eq > 0 else 0
        if dd > max_dd:
            max_dd = dd
        equity_curve.append(equity)

    # Close remaining
    for pair, pos in list(positions.items()):
        candles = data.get(pair, [])
        if candles:
            lp = candles[-1]['close']
            gross = (lp - pos.entry_price) / pos.entry_price * pos.size_usd
            fees = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
            net = gross - fees
            equity += net
            trades.append({'pair': pair, 'entry': pos.entry_price,
                           'exit': lp, 'pnl': net, 'reason': 'END',
                           'bars': max_bars - pos.entry_bar})

    # Metrics
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    avg_w = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
    avg_l = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else float('inf')
    roi = total_pnl / initial_eq * 100 if initial_eq else 0
    avg_bars = (sum(t['bars'] for t in trades) / len(trades)
                if trades else 0)

    # Composite score
    pnl_n = min(1, max(0, (total_pnl + 2000) / 8000))
    pf_n = min(1, max(0, (pf - 0.5) / 9.5))
    wr_n = wr / 100
    dd_p = max(0, 1 - max_dd / 50)
    tr_n = min(1, len(trades) / 50)
    score = pnl_n * 35 + pf_n * 20 + wr_n * 15 + dd_p * 20 + tr_n * 10

    # Exit reason breakdown
    reasons = {}
    for t in trades:
        r = t['reason']
        reasons.setdefault(r, {'n': 0, 'pnl': 0, 'wins': 0})
        reasons[r]['n'] += 1
        reasons[r]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            reasons[r]['wins'] += 1

    return {
        'label': label, 'coins': len(coin_list),
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'wr': wr, 'pnl': total_pnl, 'roi': roi, 'pf': pf,
        'dd': max_dd, 'avg_w': avg_w, 'avg_l': avg_l,
        'avg_bars': avg_bars, 'score': score,
        'reasons': reasons, 'trade_list': trades,
    }


# ============================================================
# STRATEGY CONFIGS
# ============================================================

def get_all_configs():
    """Alle strategie-varianten als config dicts."""
    return [
        # ── BASELINE / V3 VARIANTEN ──
        {
            'name': '1.  V3 BASELINE',
            'desc': 'DC+BB, RSI<35, geen vol filters, ATR 3.0x',
            'cfg': {'rsi_max': 35, 'atr_mult': 3.0,
                    'vol_spike': False, 'vol_confirm': False,
                    'breakeven': False, 'time_max': False,
                    'rsi_recovery': False},
            'max_pos': 2, 'pos_size': 1000,
        },
        {
            'name': '2.  V3 + VolSpike',
            'desc': 'V3 + volume spike >2x',
            'cfg': {'rsi_max': 35, 'atr_mult': 3.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': False,
                    'breakeven': False, 'time_max': False,
                    'rsi_recovery': False},
            'max_pos': 2, 'pos_size': 1000,
        },
        {
            'name': '3.  V3 + BE stop',
            'desc': 'V3 + break-even +3%',
            'cfg': {'rsi_max': 35, 'atr_mult': 3.0,
                    'vol_spike': False, 'vol_confirm': False,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': False, 'rsi_recovery': False},
            'max_pos': 2, 'pos_size': 1000,
        },

        # ── V4 VARIANTEN ──
        {
            'name': '4.  V4 DUALCONFIRM',
            'desc': 'RSI<40, VolSpk>2x, VolCnf>1x, BE+3%, TMax10',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': False},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '5.  V4 ZONDER VOL',
            'desc': 'V4 maar zonder vol spike/confirm',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': False, 'vol_confirm': False,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': False},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '6.  V4 + ADX<25',
            'desc': 'V4 + ADX trend filter',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'adx_filter': True, 'adx_max': 25,
                    'rsi_recovery': False},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '7.  V4 + RSI<35',
            'desc': 'V4 met strengere RSI entry',
            'cfg': {'rsi_max': 35, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': False},
            'max_pos': 1, 'pos_size': 2000,
        },

        # ── V5 RSI RECOVERY VARIANTEN ──
        {
            'name': '8.  V5 RSI REC 47',
            'desc': 'V4 + RSI Recovery target=47',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 47,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '9.  V5 RSI REC 45 ★',
            'desc': 'V4 + RSI Recovery target=45 (PRODUCTIE)',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '10. V5 RSI REC 42',
            'desc': 'V4 + RSI Recovery target=42 (conservatief)',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 42,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '11. V5 RSI REC 50',
            'desc': 'V4 + RSI Recovery target=50 (agressief)',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 50,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },

        # ── ATR VARIANTEN ──
        {
            'name': '12. V5 + ATR 1.5x',
            'desc': 'Tightere trailing stop',
            'cfg': {'rsi_max': 40, 'atr_mult': 1.5,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '13. V5 + ATR 2.5x',
            'desc': 'Iets lossere trailing',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.5,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '14. V5 + ATR 3.0x',
            'desc': 'Lossere trailing stop',
            'cfg': {'rsi_max': 40, 'atr_mult': 3.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },

        # ── DONCHIAN PERIOD VARIANTEN ──
        {
            'name': '15. V5 + DC=15',
            'desc': 'Kortere Donchian lookback',
            'cfg': {'dc_period': 15, 'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '16. V5 + DC=25',
            'desc': 'Langere Donchian lookback',
            'cfg': {'dc_period': 25, 'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },

        # ── TIME MAX VARIANTEN ──
        {
            'name': '17. V5 + TMax 6',
            'desc': 'Kortere time limit (24h)',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 6,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '18. V5 + TMax 16',
            'desc': 'Langere time limit (64h)',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 16,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '19. V5 GEEN TMax',
            'desc': 'Geen time limit',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': False,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },

        # ── BB DEVIATION VARIANTEN ──
        {
            'name': '20. V5 + BB 1.8',
            'desc': 'Tightere Bollinger',
            'cfg': {'bb_dev': 1.8, 'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '21. V5 + BB 2.2',
            'desc': 'Lossere Bollinger',
            'cfg': {'bb_dev': 2.2, 'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },

        # ── VOL SPIKE VARIANTEN ──
        {
            'name': '22. V5 + VolSpk 1.5x',
            'desc': 'Lossere volume spike',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 1.5,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '23. V5 + VolSpk 3.0x',
            'desc': 'Strengere volume spike',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 3.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },

        # ── PORTFOLIO VARIANTEN ──
        {
            'name': '24. V5 + 2x$1000',
            'desc': 'V5 winner met 2 posities',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 2, 'pos_size': 1000,
        },
        {
            'name': '25. V5 + 3x$667',
            'desc': 'V5 winner met 3 posities',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 3, 'pos_size': 667,
        },

        # ── BREAK-EVEN VARIANTEN ──
        {
            'name': '26. V5 + BE 2%',
            'desc': 'Eerdere break-even trigger',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 2.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '27. V5 + BE 5%',
            'desc': 'Latere break-even trigger',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 5.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '28. V5 GEEN BE',
            'desc': 'Zonder break-even stop',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': False,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2},
            'max_pos': 1, 'pos_size': 2000,
        },

        # ── COOLDOWN VARIANTEN ──
        {
            'name': '29. V5 + CD 2/4',
            'desc': 'Kortere cooldown',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2,
                    'cooldown_bars': 2, 'cooldown_stop': 4},
            'max_pos': 1, 'pos_size': 2000,
        },
        {
            'name': '30. V5 + CD 6/12',
            'desc': 'Langere cooldown',
            'cfg': {'rsi_max': 40, 'atr_mult': 2.0,
                    'vol_spike': True, 'vol_spike_mult': 2.0,
                    'vol_confirm': True, 'vol_confirm_mult': 1.0,
                    'breakeven': True, 'be_trigger': 3.0,
                    'time_max': True, 'time_max_bars': 10,
                    'rsi_recovery': True, 'rsi_rec_target': 45,
                    'rsi_rec_min_bars': 2,
                    'cooldown_bars': 6, 'cooldown_stop': 12},
            'max_pos': 1, 'pos_size': 2000,
        },
    ]


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()

    data = load_data(args.refresh)
    all_coins = sorted([k for k in data if not k.startswith('_')])
    n_coins = len(all_coins)

    configs = get_all_configs()

    print()
    print("=" * 140)
    print("  MEGA STRATEGIE VERGELIJKING — Alle varianten op 532 dynamische coins")
    print(f"  Data: {data.get('_date', '?')} | Coins: {n_coins} | "
          f"Timeframe: 4H | Periode: ~60 dagen")
    print(f"  Fee: 0.26% per trade (in+out) | Strategieën: {len(configs)}")
    print("=" * 140)

    results = []
    for i, c in enumerate(configs):
        r = run_backtest(data, all_coins, c['cfg'],
                         max_pos=c['max_pos'], pos_size=c['pos_size'],
                         label=c['name'])
        results.append(r)
        logger.info(f"  [{i+1:>2}/{len(configs)}] {c['name']}: "
                     f"{r['trades']}tr, WR {r['wr']:.0f}%, "
                     f"P&L ${r['pnl']:+,.0f}, PF {r['pf']:.1f}")

    # ── RESULTATEN TABEL ──
    print()
    print("=" * 160)
    print("  RESULTATEN")
    print("=" * 160)
    print(f"  {'#':<4} {'STRATEGIE':<28} | {'BESCHRIJVING':<42} | "
          f"{'#TR':>4} | {'W':>3}-{'L':>3} | {'WR':>6} | "
          f"{'P&L':>10} | {'ROI':>7} | {'PF':>6} | "
          f"{'DD':>6} | {'AvgW':>7} | {'AvgL':>7} | "
          f"{'Bars':>4} | {'SCORE':>5}")
    print("  " + "-" * 158)

    for r in results:
        c = next(x for x in configs if x['name'] == r['label'])
        pf_str = f"{r['pf']:>5.1f}" if r['pf'] < 999 else "  INF"
        print(f"  {r['label']:<32} | {c['desc']:<42} | "
              f"{r['trades']:>4} | {r['wins']:>3}-{r['losses']:>3} | "
              f"{r['wr']:>5.1f}% | ${r['pnl']:>+8,.0f} | "
              f"{r['roi']:>+6.1f}% | {pf_str} | "
              f"{r['dd']:>5.1f}% | ${r['avg_w']:>+5.0f} | "
              f"${r['avg_l']:>+5.0f} | "
              f"{r['avg_bars']:>4.1f} | {r['score']:>5.1f}")

    # ── RANKING ──
    ranked = sorted(results, key=lambda x: x['score'], reverse=True)
    print()
    print("=" * 140)
    print("  RANKING OP COMPOSITE SCORE (P&L 35% + PF 20% + WR 15% + "
          "DD-penalty 20% + Trades 10%)")
    print("=" * 140)

    medals = ['🥇', '🥈', '🥉']
    for i, r in enumerate(ranked):
        m = medals[i] if i < 3 else f"#{i+1:>2}"
        pf_s = f"{r['pf']:.1f}" if r['pf'] < 999 else "INF"
        print(f"  {m:<4} {r['label']:<32} | "
              f"P&L ${r['pnl']:>+8,.0f} | PF {pf_s:>5} | "
              f"WR {r['wr']:>5.1f}% | DD {r['dd']:>5.1f}% | "
              f"{r['trades']:>2}tr | Score {r['score']:>5.1f}")

    # ── TOP 5 DETAIL ──
    print()
    print("=" * 140)
    print("  TOP 5 GEDETAILLEERD")
    print("=" * 140)

    for i, r in enumerate(ranked[:5]):
        c = next(x for x in configs if x['name'] == r['label'])
        m = medals[i] if i < 3 else f"#{i+1}"
        pf_s = f"{r['pf']:.1f}" if r['pf'] < 999 else "INF"
        print(f"\n  {'─' * 90}")
        print(f"  {m} {r['label']} — {c['desc']}")
        print(f"  {'─' * 90}")
        print(f"    Portfolio:    {c['max_pos']}x${c['pos_size']}")
        print(f"    Trades:       {r['trades']} "
              f"({r['wins']}W / {r['losses']}L)")
        print(f"    Win Rate:     {r['wr']:.1f}%")
        print(f"    P&L:          ${r['pnl']:+,.2f}")
        print(f"    ROI:          {r['roi']:+.1f}%")
        print(f"    Profit Factor:{pf_s}")
        print(f"    Max Drawdown: {r['dd']:.1f}%")
        print(f"    Avg Win:      ${r['avg_w']:+,.2f}")
        print(f"    Avg Loss:     ${r['avg_l']:+,.2f}")
        print(f"    Avg Bars:     {r['avg_bars']:.1f} ({r['avg_bars']*4:.0f}h)")

        # Exit reasons
        if r['reasons']:
            print(f"\n    Exit Reasons:")
            for reason, st in sorted(r['reasons'].items(),
                                     key=lambda x: x[1]['n'], reverse=True):
                wr = st['wins'] / st['n'] * 100 if st['n'] else 0
                print(f"      {reason:<15} {st['n']:>3}x | "
                      f"WR {wr:>5.1f}% | P&L ${st['pnl']:>+9,.2f}")

        # Trades
        if r['trade_list']:
            sorted_t = sorted(r['trade_list'],
                              key=lambda t: t['pnl'], reverse=True)
            print(f"\n    Trades (gesorteerd op P&L):")
            for j, t in enumerate(sorted_t[:15]):
                icon = "✅" if t['pnl'] > 0 else "❌"
                print(f"      {icon} {t['pair']:<14} | "
                      f"P&L ${t['pnl']:>+9.2f} | "
                      f"{t['bars']:>2} bars | {t['reason']}")
            if len(sorted_t) > 15:
                print(f"      ... en nog {len(sorted_t) - 15} meer")

    # ── PARAMETER SENSITIVITY ANALYSE ──
    print()
    print("=" * 140)
    print("  PARAMETER SENSITIVITY ANALYSE")
    print("=" * 140)

    # RSI Recovery targets
    rsi_targets = [(r, next(x for x in configs if x['name'] == r['label']))
                   for r in results
                   if 'RSI REC' in r['label']]
    if rsi_targets:
        print("\n  RSI Recovery Target Sweep:")
        for r, c in sorted(rsi_targets,
                           key=lambda x: x[1]['cfg'].get('rsi_rec_target', 0)):
            tgt = c['cfg'].get('rsi_rec_target', '?')
            pf_s = f"{r['pf']:.1f}" if r['pf'] < 999 else "INF"
            print(f"    target={tgt:>2} | {r['trades']:>2}tr | "
                  f"WR {r['wr']:>5.1f}% | P&L ${r['pnl']:>+8,.0f} | "
                  f"PF {pf_s:>5} | DD {r['dd']:>5.1f}%")

    # ATR mult
    atr_vars = [(r, next(x for x in configs if x['name'] == r['label']))
                for r in results
                if 'ATR' in r['label'] or r['label'] == '9.  V5 RSI REC 45 ★']
    if atr_vars:
        print("\n  ATR Multiplier Sweep:")
        for r, c in sorted(atr_vars,
                           key=lambda x: x[1]['cfg'].get('atr_mult', 0)):
            mult = c['cfg'].get('atr_mult', '?')
            pf_s = f"{r['pf']:.1f}" if r['pf'] < 999 else "INF"
            print(f"    ATR {mult}x | {r['trades']:>2}tr | "
                  f"WR {r['wr']:>5.1f}% | P&L ${r['pnl']:>+8,.0f} | "
                  f"PF {pf_s:>5} | DD {r['dd']:>5.1f}%")

    # Portfolio sizing
    port_vars = [(r, next(x for x in configs if x['name'] == r['label']))
                 for r in results
                 if any(x in r['label'] for x in ['2x$1000', '3x$667',
                                                   'V5 RSI REC 45'])]
    if port_vars:
        print("\n  Portfolio Sizing:")
        for r, c in port_vars:
            pf_s = f"{r['pf']:.1f}" if r['pf'] < 999 else "INF"
            print(f"    {c['max_pos']}x${c['pos_size']:<4} | "
                  f"{r['trades']:>2}tr | WR {r['wr']:>5.1f}% | "
                  f"P&L ${r['pnl']:>+8,.0f} | PF {pf_s:>5} | "
                  f"DD {r['dd']:>5.1f}%")

    # BB deviation
    bb_vars = [(r, next(x for x in configs if x['name'] == r['label']))
               for r in results
               if 'BB' in r['label'] or r['label'] == '9.  V5 RSI REC 45 ★']
    if bb_vars:
        print("\n  Bollinger Deviation:")
        for r, c in sorted(bb_vars,
                           key=lambda x: x[1]['cfg'].get('bb_dev', 2.0)):
            dev = c['cfg'].get('bb_dev', 2.0)
            pf_s = f"{r['pf']:.1f}" if r['pf'] < 999 else "INF"
            print(f"    BB dev={dev} | {r['trades']:>2}tr | "
                  f"WR {r['wr']:>5.1f}% | P&L ${r['pnl']:>+8,.0f} | "
                  f"PF {pf_s:>5} | DD {r['dd']:>5.1f}%")

    # ── CONCLUSIE ──
    best = ranked[0]
    worst = ranked[-1]
    v5_prod = next((r for r in results if '★' in r['label']), None)

    print()
    print("=" * 140)
    print("  CONCLUSIE")
    print("=" * 140)
    pf_b = f"{best['pf']:.1f}" if best['pf'] < 999 else "INF"
    print(f"\n  🏆 BESTE:   {best['label']}")
    print(f"     P&L ${best['pnl']:+,.0f} | PF {pf_b} | "
          f"WR {best['wr']:.1f}% | DD {best['dd']:.1f}% | "
          f"{best['trades']}tr | Score {best['score']:.1f}")

    pf_w = f"{worst['pf']:.1f}" if worst['pf'] < 999 else "INF"
    print(f"\n  💀 SLECHTSTE: {worst['label']}")
    print(f"     P&L ${worst['pnl']:+,.0f} | PF {pf_w} | "
          f"WR {worst['wr']:.1f}% | DD {worst['dd']:.1f}% | "
          f"{worst['trades']}tr | Score {worst['score']:.1f}")

    if v5_prod:
        pf_p = f"{v5_prod['pf']:.1f}" if v5_prod['pf'] < 999 else "INF"
        diff = best['pnl'] - v5_prod['pnl']
        print(f"\n  📌 PRODUCTIE (V5 RSI45): "
              f"P&L ${v5_prod['pnl']:+,.0f} | PF {pf_p} | "
              f"WR {v5_prod['wr']:.1f}%")
        if best['label'] != v5_prod['label']:
            print(f"     Verschil met beste: ${diff:+,.0f}")
        else:
            print(f"     ✅ Productie IS de beste strategie!")

    print()
    print("=" * 140)


if __name__ == '__main__':
    main()

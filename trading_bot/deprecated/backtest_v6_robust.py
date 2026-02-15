#!/usr/bin/env python3
"""
V6 ROBUST STRATEGIE — Synthese van 4 Agent-Analyses
====================================================
Doel: Strategie die POSITIEVE verwachting heeft ZONDER outlier-afhankelijkheid.

Kernproblemen opgelost:
  1. TRAIL STOP killer (70% van verliezen, avg -$127) → Dynamic Trailing
  2. Lage WR (38.6% vs 60% break-even) → Combo Exit + Quality Gate
  3. ZEUS-afhankelijkheid (115% van P&L) → Consistent kleine wins
  4. Walk-Forward falen (0/3 folds) → Regime filters

Nieuwe mechanismen:
  A. DYNAMIC TRAILING: ATR mult varieert per P&L staat
  B. COMBO EXIT: RSI Recovery + Quick Profit fallback
  C. SIGNAL QUALITY GATE: Minimum quality score filter
  D. LOSS STREAK BREAKER: Pauzeer na N opeenvolgende verliezen

Gebruik:
    python backtest_v6_robust.py                    # Test alle V6 varianten
    python backtest_v6_robust.py --validate         # + Quant validatie
    python backtest_v6_robust.py --compare-v5       # Vergelijk met V5
"""
import os
import sys
import json
import time
import math
import random
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict
from collections import defaultdict

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

load_dotenv(BASE_DIR / '.env')

CACHE_FILE = BASE_DIR / 'candle_cache_532.json'
KRAKEN_FEE = 0.0026

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('v6_robust')


# ============================================================
# V6 ROBUST STRATEGY — Alle verbeteringen geïntegreerd
# ============================================================

def calc_adx(highs, lows, closes, period=14):
    if len(highs) < period + 1:
        return None
    plus_dm, minus_dm, tr_list = [], [], []
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
    return abs(plus_di - minus_di) / di_sum * 100


class V6RobustStrategy:
    """
    V6 Robust Strategy — Synthese van alle agent-analyses.

    Verbeteringen t.o.v. V5:
    1. Dynamic Trailing Stop (ATR mult varieert per P&L staat)
    2. Combo Exit (RSI Recovery + Quick Profit fallback)
    3. Signal Quality Gate (minimum quality threshold)
    4. Loss Streak Breaker (pauzeer na N losses)
    """

    def __init__(self, cfg: dict):
        # === ENTRY PARAMETERS (zelfde als V5) ===
        self.donchian_period = cfg.get('dc_period', 20)
        self.bb_period = cfg.get('bb_period', 20)
        self.bb_dev = cfg.get('bb_dev', 2.0)
        self.rsi_period = cfg.get('rsi_period', 14)
        self.rsi_max = cfg.get('rsi_max', 40)
        self.atr_period = cfg.get('atr_period', 14)
        self.volume_min_pct = cfg.get('vol_min_pct', 0.5)
        self.use_volume_spike = cfg.get('vol_spike', False)
        self.volume_spike_mult = cfg.get('vol_spike_mult', 2.0)
        self.use_vol_confirm = cfg.get('vol_confirm', False)
        self.vol_confirm_mult = cfg.get('vol_confirm_mult', 1.0)

        # === EXIT PARAMETERS ===
        self.atr_stop_mult = cfg.get('atr_mult', 2.0)
        self.max_stop_loss_pct = cfg.get('max_stop_pct', 15.0)
        self.use_breakeven = cfg.get('breakeven', False)
        self.breakeven_trigger = cfg.get('be_trigger', 3.0)
        self.use_time_max = cfg.get('time_max', False)
        self.time_max_bars = cfg.get('time_max_bars', 10)
        self.rsi_sell = cfg.get('rsi_sell', 70)

        # V5: RSI Recovery
        self.use_rsi_recovery = cfg.get('rsi_recovery', False)
        self.rsi_recovery_target = cfg.get('rsi_rec_target', 45)
        self.rsi_recovery_min_bars = cfg.get('rsi_rec_min_bars', 2)

        # === V6 NEW: Dynamic Trailing ===
        self.use_dynamic_trail = cfg.get('dynamic_trail', False)
        self.trail_pre_be_mult = cfg.get('trail_pre_be', 2.5)
        self.trail_post_be_mult = cfg.get('trail_post_be', 1.5)
        self.trail_profit_mult = cfg.get('trail_profit', 1.0)
        self.trail_profit_threshold = cfg.get('trail_profit_thresh', 3.0)

        # === V6 NEW: Combo Exit ===
        self.use_combo_exit = cfg.get('combo_exit', False)
        self.combo_rsi_target = cfg.get('combo_rsi_target', 45)
        self.combo_rsi_min_bars = cfg.get('combo_rsi_min_bars', 2)
        self.combo_fallback_pct = cfg.get('combo_fallback_pct', 2.0)
        self.combo_fallback_bars = cfg.get('combo_fallback_bars', 5)

        # === V6 NEW: Quick Profit ===
        self.use_quick_profit = cfg.get('quick_profit', False)
        self.quick_profit_pct = cfg.get('quick_profit_pct', 3.0)
        self.quick_profit_min_bars = cfg.get('quick_profit_min_bars', 1)

        # === V6 NEW: Signal Quality Gate ===
        self.use_quality_gate = cfg.get('quality_gate', False)
        self.min_quality = cfg.get('min_quality', 0.4)

        # === Cooldown ===
        self.cooldown_bars = cfg.get('cooldown_bars', 4)
        self.cooldown_after_stop = cfg.get('cooldown_stop', 8)

        # === State ===
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

        # ══════════════════════════════════════
        # EXIT LOGIC
        # ══════════════════════════════════════
        if position:
            entry_price = position['entry_price']
            bars_in = self.bar_count - position['entry_bar']

            if close > position['highest_price']:
                position['highest_price'] = close

            # --- Dynamic Trailing Stop ---
            pnl_pct = (close - entry_price) / entry_price * 100

            if self.use_dynamic_trail:
                if pnl_pct >= self.trail_profit_threshold:
                    atr_mult = self.trail_profit_mult
                elif pnl_pct >= 0:
                    atr_mult = self.trail_post_be_mult
                else:
                    atr_mult = self.trail_pre_be_mult
            else:
                atr_mult = self.atr_stop_mult

            new_stop = position['highest_price'] - atr * atr_mult
            hard_stop = entry_price * (1 - self.max_stop_loss_pct / 100)
            if new_stop < hard_stop:
                new_stop = hard_stop

            # Break-even floor
            if self.use_breakeven:
                if pnl_pct >= self.breakeven_trigger:
                    be_level = entry_price * (1 + KRAKEN_FEE * 2)
                    if new_stop < be_level:
                        new_stop = be_level

            if new_stop > position['stop_price']:
                position['stop_price'] = new_stop

            # --- Priority exit checks ---

            # 1. Hard Stop
            if close < hard_stop:
                return {'action': 'SELL', 'reason': 'HARD STOP', 'price': close}

            # 2. Time Max
            if self.use_time_max and bars_in >= self.time_max_bars:
                return {'action': 'SELL', 'reason': 'TIME MAX', 'price': close}

            # 3. V6 Combo Exit (RSI Recovery + Quick Profit fallback)
            if self.use_combo_exit:
                # Primary: RSI Recovery
                if (bars_in >= self.combo_rsi_min_bars
                        and rsi >= self.combo_rsi_target):
                    return {'action': 'SELL', 'reason': 'COMBO RSI',
                            'price': close}
                # Fallback: Quick Profit na N bars
                if (bars_in >= self.combo_fallback_bars
                        and pnl_pct >= self.combo_fallback_pct):
                    return {'action': 'SELL', 'reason': 'COMBO PROFIT',
                            'price': close}
            else:
                # Standard RSI Recovery (V5)
                if (self.use_rsi_recovery
                        and bars_in >= self.rsi_recovery_min_bars
                        and rsi >= self.rsi_recovery_target):
                    return {'action': 'SELL', 'reason': 'RSI RECOVERY',
                            'price': close}

            # 4. Quick Profit (standalone)
            if self.use_quick_profit:
                if (bars_in >= self.quick_profit_min_bars
                        and pnl_pct >= self.quick_profit_pct):
                    return {'action': 'SELL', 'reason': 'QUICK PROFIT',
                            'price': close}

            # 5. DC/BB targets
            if close >= mid_channel:
                return {'action': 'SELL', 'reason': 'DC TARGET', 'price': close}
            if close >= bb_mid:
                return {'action': 'SELL', 'reason': 'BB TARGET', 'price': close}
            if rsi > self.rsi_sell:
                return {'action': 'SELL', 'reason': 'RSI EXIT', 'price': close}

            # 6. Trail Stop
            if close < position['stop_price']:
                return {'action': 'SELL', 'reason': 'TRAIL STOP',
                        'price': close}

            return {'action': 'HOLD', 'price': close}

        # ══════════════════════════════════════
        # ENTRY LOGIC
        # ══════════════════════════════════════
        cd = (self.cooldown_after_stop if self.last_exit_was_stop
              else self.cooldown_bars)
        if (self.bar_count - self.last_exit_bar) < cd:
            return {'action': 'WAIT'}

        # Base volume
        vol_avg = 0
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
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
                return {'action': 'WAIT'}

        # Volume confirm
        if (self.use_vol_confirm and len(volumes) >= 2
                and volumes[-2] > 0):
            if volumes[-1] / volumes[-2] < self.vol_confirm_mult:
                return {'action': 'WAIT'}

        # Quality score
        stop = close - atr * self.atr_stop_mult
        hard_stop = close * (1 - self.max_stop_loss_pct / 100)
        if stop < hard_stop:
            stop = hard_stop

        rsi_sc = max(0, (self.rsi_max - rsi) / self.rsi_max)
        dc_d = (prev_lowest - low) / prev_lowest if prev_lowest > 0 else 0
        d_sc = min(1, dc_d * 20)
        v_sc = 0
        if volumes and vol_avg > 0:
            v_sc = min(1, volumes[-1] / vol_avg / 3)
        quality = rsi_sc * 0.4 + d_sc * 0.3 + v_sc * 0.3

        # === V6: Signal Quality Gate ===
        if self.use_quality_gate and quality < self.min_quality:
            return {'action': 'WAIT'}

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
                 use_ranking=True, label="",
                 start_bar=50, end_bar=None,
                 loss_streak_max=0, loss_streak_cooldown=6):
    """
    Portfolio backtest met V6RobustStrategy.

    Nieuwe parameters:
      loss_streak_max: pauzeer na N verliezen (0=disabled)
      loss_streak_cooldown: bars pauze na streak
    """
    coin_list = [c for c in coins if c in data]
    strategies = {p: V6RobustStrategy(cfg) for p in coin_list}

    max_bars = max(len(data[p]) for p in coin_list) if coin_list else 0
    if end_bar is not None:
        max_bars = min(max_bars, end_bar)

    positions = {}
    trades = []
    equity = max_pos * pos_size
    initial_eq = equity
    peak_eq = equity
    max_dd = 0
    equity_curve = []

    # V6: Loss streak tracking
    consecutive_losses = 0
    streak_pause_until = -1

    for bar in range(start_bar, max_bars):
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

        # Process sells
        for pair, sig in sells:
            pos = positions[pair]
            sp = sig['price']
            gross = (sp - pos.entry_price) / pos.entry_price * pos.size_usd
            fees = (pos.size_usd * KRAKEN_FEE
                    + (pos.size_usd + gross) * KRAKEN_FEE)
            net = gross - fees
            equity += net
            bars_h = bar - pos.entry_bar
            is_stop = 'STOP' in sig.get('reason', '')
            s = strategies[pair]
            s.last_exit_bar = s.bar_count
            s.last_exit_was_stop = is_stop
            trades.append({
                'pair': pair, 'entry': pos.entry_price,
                'exit': sp, 'pnl': net, 'reason': sig['reason'],
                'bars': bars_h, 'entry_bar': pos.entry_bar,
                'exit_bar': bar
            })
            del positions[pair]

            # V6: Track loss streak
            if net <= 0:
                consecutive_losses += 1
                if (loss_streak_max > 0
                        and consecutive_losses >= loss_streak_max):
                    streak_pause_until = bar + loss_streak_cooldown
            else:
                consecutive_losses = 0

        # V6: Skip buys if in loss streak cooldown
        if loss_streak_max > 0 and bar < streak_pause_until:
            buys = []

        # Process buys (ranking)
        if len(positions) < max_pos and buys:
            if use_ranking:
                def rank(item):
                    p, s, c = item
                    cd = data.get(p, [])
                    vs = [x.get('volume', 0) for x in cd[max(0, bar-20):bar+1]]
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

        # DD tracking
        if equity > peak_eq:
            peak_eq = equity
        dd = (peak_eq - equity) / peak_eq * 100 if peak_eq > 0 else 0
        if dd > max_dd:
            max_dd = dd
        equity_curve.append(equity)

    # Close remaining positions
    for pair, pos in list(positions.items()):
        candles = data.get(pair, [])
        if candles:
            lp = candles[-1]['close']
            gross = (lp - pos.entry_price) / pos.entry_price * pos.size_usd
            fees = (pos.size_usd * KRAKEN_FEE
                    + (pos.size_usd + gross) * KRAKEN_FEE)
            net = gross - fees
            equity += net
            trades.append({
                'pair': pair, 'entry': pos.entry_price,
                'exit': lp, 'pnl': net, 'reason': 'END',
                'bars': max_bars - pos.entry_bar,
                'entry_bar': pos.entry_bar, 'exit_bar': max_bars
            })

    # Calculate metrics
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

    # Robustness metrics (V6 NEW)
    # Herfindahl index — concentratie van P&L
    if trades and total_pnl != 0:
        pnl_shares = [(t['pnl'] / total_pnl) ** 2 for t in trades
                       if total_pnl != 0]
        herfindahl = sum(pnl_shares)
    else:
        herfindahl = 1.0

    # P&L without top trade
    if trades:
        sorted_trades = sorted(trades, key=lambda x: x['pnl'], reverse=True)
        pnl_no_top = total_pnl - sorted_trades[0]['pnl']
        avg_no_top = pnl_no_top / (len(trades) - 1) if len(trades) > 1 else 0
    else:
        pnl_no_top = 0
        avg_no_top = 0

    # Trail stop loss rate
    trail_losses = [t for t in trades if t['reason'] == 'TRAIL STOP'
                    and t['pnl'] <= 0]
    trail_loss_pct = (len(trail_losses) / len(trades) * 100
                      if trades else 0)

    # Break-even WR
    if avg_w > 0 and avg_l < 0:
        be_wr = abs(avg_l) / (avg_w + abs(avg_l)) * 100
    else:
        be_wr = 50.0

    # Expected value per trade (without top)
    ev_no_top = avg_no_top

    # Score (modified for robustness)
    pnl_n = min(1, max(0, (total_pnl + 2000) / 8000))
    pf_n = min(1, max(0, (pf - 0.5) / 9.5))
    wr_n = wr / 100
    dd_p = max(0, 1 - max_dd / 50)
    tr_n = min(1, len(trades) / 50)
    # Robustness bonus: reward low concentration
    rob_n = max(0, 1 - herfindahl * 5)
    score = (pnl_n * 25 + pf_n * 15 + wr_n * 15 + dd_p * 15
             + tr_n * 10 + rob_n * 20)

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
        'equity_curve': equity_curve,
        # V6 robustness metrics
        'herfindahl': herfindahl,
        'pnl_no_top': pnl_no_top,
        'avg_no_top': avg_no_top,
        'trail_loss_pct': trail_loss_pct,
        'be_wr': be_wr,
        'ev_no_top': ev_no_top,
    }


# ============================================================
# V6 STRATEGY CONFIGS
# ============================================================

V6_CONFIGS = {
    # === BASELINE: V5 Productie (voor vergelijking) ===
    'v5_baseline': {
        'name': 'V5 PROD (baseline)',
        'cfg': {
            'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike': True, 'vol_spike_mult': 2.0,
            'vol_confirm': True, 'vol_confirm_mult': 1.0,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max': True, 'time_max_bars': 10,
            'rsi_recovery': True, 'rsi_rec_target': 45, 'rsi_rec_min_bars': 2,
        },
        'max_pos': 1, 'pos_size': 2000,
        'loss_streak_max': 0,
    },

    # === V6A: Dynamic Trail Only ===
    'v6a_dyntrail': {
        'name': 'V6A Dynamic Trail',
        'cfg': {
            'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike': True, 'vol_spike_mult': 2.0,
            'vol_confirm': True, 'vol_confirm_mult': 1.0,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max': True, 'time_max_bars': 10,
            'rsi_recovery': True, 'rsi_rec_target': 45, 'rsi_rec_min_bars': 2,
            # V6: Dynamic trailing
            'dynamic_trail': True,
            'trail_pre_be': 2.5,   # Ruimer voor verliezen
            'trail_post_be': 1.5,  # Normaal na BE
            'trail_profit': 1.0,   # Strak bij winst >3%
            'trail_profit_thresh': 3.0,
        },
        'max_pos': 1, 'pos_size': 2000,
        'loss_streak_max': 0,
    },

    # === V6B: Combo Exit ===
    'v6b_combo': {
        'name': 'V6B Combo Exit',
        'cfg': {
            'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike': True, 'vol_spike_mult': 2.0,
            'vol_confirm': True, 'vol_confirm_mult': 1.0,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max': True, 'time_max_bars': 10,
            # V6: Combo exit (RSI + profit fallback)
            'combo_exit': True,
            'combo_rsi_target': 45,
            'combo_rsi_min_bars': 2,
            'combo_fallback_pct': 2.0,
            'combo_fallback_bars': 5,
        },
        'max_pos': 1, 'pos_size': 2000,
        'loss_streak_max': 0,
    },

    # === V6C: Quality Gate Only ===
    'v6c_quality': {
        'name': 'V6C Quality Gate',
        'cfg': {
            'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike': True, 'vol_spike_mult': 2.0,
            'vol_confirm': True, 'vol_confirm_mult': 1.0,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max': True, 'time_max_bars': 10,
            'rsi_recovery': True, 'rsi_rec_target': 45, 'rsi_rec_min_bars': 2,
            # V6: Quality gate
            'quality_gate': True,
            'min_quality': 0.4,
        },
        'max_pos': 1, 'pos_size': 2000,
        'loss_streak_max': 0,
    },

    # === V6D: Dynamic Trail + Combo Exit ===
    'v6d_trail_combo': {
        'name': 'V6D Trail+Combo',
        'cfg': {
            'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike': True, 'vol_spike_mult': 2.0,
            'vol_confirm': True, 'vol_confirm_mult': 1.0,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max': True, 'time_max_bars': 10,
            # V6: Dynamic trail
            'dynamic_trail': True,
            'trail_pre_be': 2.5, 'trail_post_be': 1.5,
            'trail_profit': 1.0, 'trail_profit_thresh': 3.0,
            # V6: Combo exit
            'combo_exit': True,
            'combo_rsi_target': 45, 'combo_rsi_min_bars': 2,
            'combo_fallback_pct': 2.0, 'combo_fallback_bars': 5,
        },
        'max_pos': 1, 'pos_size': 2000,
        'loss_streak_max': 0,
    },

    # === V6E: FULL ROBUST (alle verbeteringen) ===
    'v6e_full': {
        'name': 'V6E FULL ROBUST ★',
        'cfg': {
            'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike': True, 'vol_spike_mult': 2.0,
            'vol_confirm': True, 'vol_confirm_mult': 1.0,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max': True, 'time_max_bars': 12,  # Langere time max
            # V6: Dynamic trail
            'dynamic_trail': True,
            'trail_pre_be': 2.5, 'trail_post_be': 1.5,
            'trail_profit': 1.0, 'trail_profit_thresh': 3.0,
            # V6: Combo exit
            'combo_exit': True,
            'combo_rsi_target': 45, 'combo_rsi_min_bars': 2,
            'combo_fallback_pct': 2.0, 'combo_fallback_bars': 5,
            # V6: Quality gate
            'quality_gate': True,
            'min_quality': 0.4,
        },
        'max_pos': 1, 'pos_size': 2000,
        'loss_streak_max': 3,  # Pauzeer na 3 losses
        'loss_streak_cooldown': 6,  # 24H pauze
    },

    # === V6F: FULL + Quick Profit ===
    'v6f_quick': {
        'name': 'V6F Quick+Robust',
        'cfg': {
            'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike': True, 'vol_spike_mult': 2.0,
            'vol_confirm': True, 'vol_confirm_mult': 1.0,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max': True, 'time_max_bars': 12,
            # V6: Dynamic trail
            'dynamic_trail': True,
            'trail_pre_be': 2.5, 'trail_post_be': 1.5,
            'trail_profit': 1.0, 'trail_profit_thresh': 3.0,
            # V6: Quick profit (instead of combo)
            'quick_profit': True, 'quick_profit_pct': 3.0,
            'quick_profit_min_bars': 1,
            # V6: RSI Recovery (standard)
            'rsi_recovery': True, 'rsi_rec_target': 45, 'rsi_rec_min_bars': 2,
            # V6: Quality gate
            'quality_gate': True,
            'min_quality': 0.4,
        },
        'max_pos': 1, 'pos_size': 2000,
        'loss_streak_max': 3,
        'loss_streak_cooldown': 6,
    },

    # === V6G: Conservative (smaller position) ===
    'v6g_conservative': {
        'name': 'V6G Conservative',
        'cfg': {
            'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike': True, 'vol_spike_mult': 2.0,
            'vol_confirm': True, 'vol_confirm_mult': 1.0,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max': True, 'time_max_bars': 12,
            'dynamic_trail': True,
            'trail_pre_be': 3.0, 'trail_post_be': 1.5,
            'trail_profit': 1.0, 'trail_profit_thresh': 2.0,
            'combo_exit': True,
            'combo_rsi_target': 43, 'combo_rsi_min_bars': 2,
            'combo_fallback_pct': 1.5, 'combo_fallback_bars': 4,
            'quality_gate': True,
            'min_quality': 0.5,  # Strengere quality gate
        },
        'max_pos': 1, 'pos_size': 1000,  # Kleiner position size
        'loss_streak_max': 2,  # Strengere streak limiet
        'loss_streak_cooldown': 8,
    },
}


# ============================================================
# ANALYSIS & REPORTING
# ============================================================

def analyze_robustness(result, label=""):
    """Diepgaande robustheidsanalyse van een backtest resultaat."""
    trades = result['trade_list']
    if not trades:
        return None

    # Trail stop analysis
    trail_trades = [t for t in trades if t['reason'] == 'TRAIL STOP']
    trail_wins = [t for t in trail_trades if t['pnl'] > 0]
    trail_losses = [t for t in trail_trades if t['pnl'] <= 0]

    # Without top trade
    sorted_by_pnl = sorted(trades, key=lambda x: x['pnl'], reverse=True)
    top_trade = sorted_by_pnl[0] if sorted_by_pnl else None
    trades_no_top = sorted_by_pnl[1:] if len(sorted_by_pnl) > 1 else []
    pnl_no_top = sum(t['pnl'] for t in trades_no_top)
    wins_no_top = [t for t in trades_no_top if t['pnl'] > 0]
    losses_no_top = [t for t in trades_no_top if t['pnl'] <= 0]
    wr_no_top = (len(wins_no_top) / len(trades_no_top) * 100
                 if trades_no_top else 0)
    avg_w_no_top = (sum(t['pnl'] for t in wins_no_top) / len(wins_no_top)
                    if wins_no_top else 0)
    avg_l_no_top = (sum(t['pnl'] for t in losses_no_top) / len(losses_no_top)
                    if losses_no_top else 0)
    ev_no_top = (pnl_no_top / len(trades_no_top)
                 if trades_no_top else 0)

    # Break-even WR (without top)
    if avg_w_no_top > 0 and avg_l_no_top < 0:
        be_wr_no_top = abs(avg_l_no_top) / (avg_w_no_top + abs(avg_l_no_top)) * 100
    else:
        be_wr_no_top = 50.0

    return {
        'label': label,
        'trades': len(trades),
        'trail_total': len(trail_trades),
        'trail_wins': len(trail_wins),
        'trail_losses': len(trail_losses),
        'trail_loss_rate': (len(trail_losses) / len(trail_trades) * 100
                           if trail_trades else 0),
        'trail_avg_pnl': (sum(t['pnl'] for t in trail_trades) / len(trail_trades)
                          if trail_trades else 0),
        'top_trade': top_trade,
        'pnl_no_top': pnl_no_top,
        'wr_no_top': wr_no_top,
        'avg_w_no_top': avg_w_no_top,
        'avg_l_no_top': avg_l_no_top,
        'ev_no_top': ev_no_top,
        'be_wr_no_top': be_wr_no_top,
        'wr_gap': wr_no_top - be_wr_no_top,
    }


def print_comparison(results):
    """Print vergelijkingstabel van alle V6 varianten."""
    logger.info(f"\n{'='*120}")
    logger.info(f"V6 ROBUST STRATEGIE VERGELIJKING")
    logger.info(f"{'='*120}")

    # Header
    header = (f"{'Config':<25} | {'Tr':>3} | {'WR%':>5} | {'P&L':>8} | "
              f"{'PF':>5} | {'DD%':>5} | {'AvgW':>7} | {'AvgL':>7} | "
              f"{'TS%':>4} | {'Herf':>5} | {'NoTop$':>8} | {'EV/t':>6} | "
              f"{'Score':>5}")
    logger.info(header)
    logger.info(f"{'-'*120}")

    for key, r in results.items():
        cfg_name = V6_CONFIGS[key]['name'][:24]
        logger.info(
            f"{cfg_name:<25} | {r['trades']:3d} | {r['wr']:5.1f} | "
            f"${r['pnl']:+7.0f} | {r['pf']:5.2f} | {r['dd']:5.1f} | "
            f"${r['avg_w']:+6.0f} | ${r['avg_l']:+6.0f} | "
            f"{r['trail_loss_pct']:4.0f} | {r['herfindahl']:5.3f} | "
            f"${r['pnl_no_top']:+7.0f} | ${r['ev_no_top']:+5.0f} | "
            f"{r['score']:5.1f}"
        )

    # Robustness analysis
    logger.info(f"\n{'='*120}")
    logger.info(f"ROBUSTHEIDS ANALYSE (zonder top trade)")
    logger.info(f"{'='*120}")

    for key, r in results.items():
        rob = analyze_robustness(r, V6_CONFIGS[key]['name'])
        if not rob:
            continue

        logger.info(f"\n--- {rob['label']} ---")
        logger.info(f"  Trail Stop: {rob['trail_total']} trades "
                     f"({rob['trail_wins']}W/{rob['trail_losses']}L, "
                     f"avg ${rob['trail_avg_pnl']:+.0f})")
        if rob['top_trade']:
            logger.info(f"  Top Trade:  {rob['top_trade']['pair']} "
                         f"${rob['top_trade']['pnl']:+.0f} "
                         f"({rob['top_trade']['reason']})")
        logger.info(f"  Zonder Top: ${rob['pnl_no_top']:+.0f} "
                     f"({rob['wr_no_top']:.1f}% WR)")
        logger.info(f"  EV/trade:   ${rob['ev_no_top']:+.1f}")
        logger.info(f"  Avg W/L:    ${rob['avg_w_no_top']:+.0f} / "
                     f"${rob['avg_l_no_top']:+.0f}")
        logger.info(f"  BE WR:      {rob['be_wr_no_top']:.1f}% "
                     f"(gap: {rob['wr_gap']:+.1f}pp)")

        # Verdict
        if rob['ev_no_top'] > 0:
            logger.info(f"  ✅ POSITIEVE verwachting zonder outlier!")
        elif rob['ev_no_top'] > -10:
            logger.info(f"  ⚠️  MARGINAAL (bijna break-even zonder outlier)")
        else:
            logger.info(f"  ❌ NEGATIEF zonder outlier")


def find_best_config(results):
    """Vind de beste V6 config op basis van robustness criteria."""
    best_key = None
    best_score = -float('inf')

    for key, r in results.items():
        # Score = EV without top * 10 + WR bonus + low DD bonus
        ev = r['ev_no_top']
        wr_bonus = max(0, (r['wr'] - 50)) * 2
        dd_bonus = max(0, (20 - r['dd'])) * 2
        trail_bonus = max(0, (50 - r['trail_loss_pct'])) * 0.5
        herf_bonus = max(0, (0.2 - r['herfindahl'])) * 100

        composite = ev * 10 + wr_bonus + dd_bonus + trail_bonus + herf_bonus

        if composite > best_score:
            best_score = composite
            best_key = key

    return best_key, best_score


# ============================================================
# DATA
# ============================================================

def load_data() -> dict:
    if not CACHE_FILE.exists():
        logger.error(f"Cache niet gevonden: {CACHE_FILE}")
        logger.error("Draai eerst: python backtest_mega_compare.py --refresh")
        sys.exit(1)
    with open(CACHE_FILE) as f:
        data = json.load(f)
    coins = [k for k in data if not k.startswith('_')]
    logger.info(f"Geladen: {len(coins)} coins uit cache")
    return data


def get_coins(data) -> list:
    return sorted([k for k in data if not k.startswith('_')])


# ============================================================
# WALK-FORWARD MINI (voor snelle validatie)
# ============================================================

def walk_forward_quick(data, coins, cfg_key, n_folds=3):
    """Snelle walk-forward analyse voor V6 configs."""
    cfg_info = V6_CONFIGS[cfg_key]
    cfg = cfg_info['cfg']
    max_pos = cfg_info.get('max_pos', 1)
    pos_size = cfg_info.get('pos_size', 2000)
    streak_max = cfg_info.get('loss_streak_max', 0)
    streak_cd = cfg_info.get('loss_streak_cooldown', 6)

    max_bars = max(len(data[c]) for c in coins if c in data)
    usable = max_bars - 50
    fold_size = usable // n_folds
    train_pct = 0.7

    results = []
    for fold in range(n_folds):
        fold_start = 50 + fold * fold_size
        fold_end = fold_start + fold_size
        split = fold_start + int(fold_size * train_pct)

        train_r = run_backtest(data, coins, cfg, max_pos, pos_size,
                               label=f"F{fold+1} Train",
                               start_bar=fold_start, end_bar=split,
                               loss_streak_max=streak_max,
                               loss_streak_cooldown=streak_cd)
        test_r = run_backtest(data, coins, cfg, max_pos, pos_size,
                              label=f"F{fold+1} Test",
                              start_bar=split, end_bar=fold_end,
                              loss_streak_max=streak_max,
                              loss_streak_cooldown=streak_cd)

        results.append({
            'fold': fold + 1,
            'train_pnl': train_r['pnl'],
            'train_wr': train_r['wr'],
            'train_trades': train_r['trades'],
            'test_pnl': test_r['pnl'],
            'test_wr': test_r['wr'],
            'test_trades': test_r['trades'],
            'test_ev_no_top': test_r['ev_no_top'],
        })

    profitable_folds = sum(1 for r in results if r['test_pnl'] > 0)
    avg_test_pnl = (sum(r['test_pnl'] for r in results) / len(results)
                    if results else 0)

    return {
        'folds': results,
        'profitable_folds': profitable_folds,
        'total_folds': n_folds,
        'avg_test_pnl': avg_test_pnl,
        'verdict': ('STERK' if profitable_folds >= n_folds * 0.67
                    else 'ZWAK' if profitable_folds >= 1
                    else 'GEFAALD'),
    }


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='V6 Robust Strategie — Backtest & Validatie')
    parser.add_argument('--validate', action='store_true',
                        help='Include walk-forward validatie')
    parser.add_argument('--compare-v5', action='store_true',
                        help='Vergelijk met V5 baseline')
    parser.add_argument('--config', default=None,
                        help='Test specifieke config')
    parser.add_argument('--save-report', action='store_true',
                        help='Sla rapport op als JSON')
    args = parser.parse_args()

    logger.info("V6 ROBUST STRATEGIE — Backtest & Validatie")
    logger.info("=" * 70)

    data = load_data()
    coins = get_coins(data)
    logger.info(f"Coins: {len(coins)}")

    # Determine which configs to test
    if args.config:
        config_keys = [args.config]
    elif args.compare_v5:
        config_keys = list(V6_CONFIGS.keys())
    else:
        config_keys = [k for k in V6_CONFIGS.keys() if k != 'v5_baseline']

    # Run backtests
    results = {}
    for key in config_keys:
        cfg_info = V6_CONFIGS[key]
        cfg = cfg_info['cfg']
        logger.info(f"\nTesting: {cfg_info['name']}...")

        r = run_backtest(data, coins, cfg,
                         max_pos=cfg_info.get('max_pos', 1),
                         pos_size=cfg_info.get('pos_size', 2000),
                         label=cfg_info['name'],
                         loss_streak_max=cfg_info.get('loss_streak_max', 0),
                         loss_streak_cooldown=cfg_info.get('loss_streak_cooldown', 6))
        results[key] = r

    # Print comparison
    print_comparison(results)

    # Find best
    best_key, best_score = find_best_config(results)
    logger.info(f"\n{'='*70}")
    logger.info(f"BESTE CONFIG: {V6_CONFIGS[best_key]['name']}")
    logger.info(f"Robustness Score: {best_score:.1f}")
    logger.info(f"{'='*70}")

    # Walk-forward validation
    if args.validate:
        logger.info(f"\n{'='*70}")
        logger.info(f"WALK-FORWARD VALIDATIE")
        logger.info(f"{'='*70}")

        # Validate top 3 configs
        sorted_configs = sorted(results.items(),
                                key=lambda x: x[1]['ev_no_top'],
                                reverse=True)
        top_configs = [k for k, v in sorted_configs[:3]]

        for key in top_configs:
            logger.info(f"\n--- Walk-Forward: {V6_CONFIGS[key]['name']} ---")
            wf = walk_forward_quick(data, coins, key)
            logger.info(f"  Verdict: {wf['verdict']}")
            logger.info(f"  Profitable Folds: {wf['profitable_folds']}/{wf['total_folds']}")
            logger.info(f"  Avg Test P&L: ${wf['avg_test_pnl']:+.0f}")
            for fold in wf['folds']:
                logger.info(
                    f"  Fold {fold['fold']}: "
                    f"Train ${fold['train_pnl']:+.0f} ({fold['train_trades']}tr) | "
                    f"Test ${fold['test_pnl']:+.0f} ({fold['test_trades']}tr) | "
                    f"EV/t ${fold['test_ev_no_top']:+.1f}"
                )

    # Save report
    if args.save_report:
        report = {
            'timestamp': datetime.now().isoformat(),
            'coins': len(coins),
            'configs_tested': len(results),
            'best_config': best_key,
            'best_name': V6_CONFIGS[best_key]['name'],
            'results': {}
        }
        for key, r in results.items():
            # Remove equity_curve for smaller JSON
            r_clean = {k: v for k, v in r.items()
                       if k != 'equity_curve'}
            report['results'][key] = r_clean

        report_file = BASE_DIR / 'v6_report.json'

        def clean_json(obj):
            if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
                return str(obj)
            if isinstance(obj, dict):
                return {k: clean_json(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [clean_json(v) for v in obj]
            return obj

        with open(report_file, 'w') as f:
            json.dump(clean_json(report), f, indent=2)
        logger.info(f"\nRapport opgeslagen: {report_file}")

    logger.info(f"\nKlaar!")


if __name__ == '__main__':
    main()

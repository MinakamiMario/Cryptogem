#!/usr/bin/env python3
"""
QUANT RESEARCHER — Walk-Forward + Monte Carlo Validatie Framework
=================================================================
Beantwoordt de kernvraag: "Heb ik een echte edge of is het toeval/ZEUS-geluk?"

Analyses:
  1. Walk-Forward: Train op window A, test op window B (rollend)
  2. Monte Carlo: Shuffle trades, bootstrap P&L distributie
  3. ZEUS-afhankelijkheid: Strategie met/zonder outliers
  4. Statistische significantie: p-waarden, confidence intervals

Gebruik:
    python quant_researcher.py                    # Volledige analyse
    python quant_researcher.py --quick            # Snelle versie (minder sims)
    python quant_researcher.py --config v5_prod   # Specifieke config
    python quant_researcher.py --all-configs      # Top 5 configs vergelijken
"""
import os
import sys
import json
import time
import random
import math
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
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
logger = logging.getLogger('quant_researcher')


# ============================================================
# HERGEBRUIK: ConfigurableStrategy + backtest engine
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


class ConfigurableStrategy:
    def __init__(self, cfg: dict):
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
        self.use_adx_filter = cfg.get('adx_filter', False)
        self.adx_max = cfg.get('adx_max', 25)
        self.atr_stop_mult = cfg.get('atr_mult', 2.0)
        self.max_stop_loss_pct = cfg.get('max_stop_pct', 15.0)
        self.use_breakeven = cfg.get('breakeven', False)
        self.breakeven_trigger = cfg.get('be_trigger', 3.0)
        self.use_time_max = cfg.get('time_max', False)
        self.time_max_bars = cfg.get('time_max_bars', 10)
        self.rsi_sell = cfg.get('rsi_sell', 70)
        self.use_rsi_recovery = cfg.get('rsi_recovery', False)
        self.rsi_recovery_target = cfg.get('rsi_rec_target', 47)
        self.rsi_recovery_min_bars = cfg.get('rsi_rec_min_bars', 2)
        self.cooldown_bars = cfg.get('cooldown_bars', 4)
        self.cooldown_after_stop = cfg.get('cooldown_stop', 8)
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
            if self.use_breakeven:
                pnl_pct = (close - entry_price) / entry_price * 100
                if pnl_pct >= self.breakeven_trigger:
                    be_level = entry_price * (1 + KRAKEN_FEE * 2)
                    if new_stop < be_level:
                        new_stop = be_level
            if new_stop > position['stop_price']:
                position['stop_price'] = new_stop

            if close < hard_stop:
                return {'action': 'SELL', 'reason': 'HARD STOP', 'price': close}
            if self.use_time_max and bars_in >= self.time_max_bars:
                return {'action': 'SELL', 'reason': 'TIME MAX', 'price': close}
            if (self.use_rsi_recovery
                    and bars_in >= self.rsi_recovery_min_bars
                    and rsi >= self.rsi_recovery_target):
                return {'action': 'SELL', 'reason': 'RSI RECOVERY', 'price': close}
            if close >= mid_channel:
                return {'action': 'SELL', 'reason': 'DC TARGET', 'price': close}
            if close >= bb_mid:
                return {'action': 'SELL', 'reason': 'BB TARGET', 'price': close}
            if rsi > self.rsi_sell:
                return {'action': 'SELL', 'reason': 'RSI EXIT', 'price': close}
            if close < position['stop_price']:
                return {'action': 'SELL', 'reason': 'TRAIL STOP', 'price': close}
            return {'action': 'HOLD', 'price': close}

        # ── ENTRY ──
        cd = (self.cooldown_after_stop if self.last_exit_was_stop
              else self.cooldown_bars)
        if (self.bar_count - self.last_exit_bar) < cd:
            return {'action': 'WAIT'}
        if volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_min_pct:
                return {'action': 'WAIT'}
        dc_sig = (low <= prev_lowest and rsi < self.rsi_max
                  and close > prev_close)
        bb_sig = (close <= bb_lower and rsi < self.rsi_max
                  and close > prev_close)
        if not (dc_sig and bb_sig):
            return {'action': 'WAIT'}
        if self.use_volume_spike and volumes:
            vol_avg = sum(volumes[-20:]) / min(20, len(volumes))
            if vol_avg > 0 and volumes[-1] < vol_avg * self.volume_spike_mult:
                return {'action': 'WAIT'}
        if (self.use_vol_confirm and len(volumes) >= 2
                and volumes[-2] > 0):
            if volumes[-1] / volumes[-2] < self.vol_confirm_mult:
                return {'action': 'WAIT'}
        if self.use_adx_filter:
            adx_val = calc_adx(highs, lows, closes)
            if adx_val is not None and adx_val > self.adx_max:
                return {'action': 'WAIT'}

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

        return {'action': 'BUY', 'price': close, 'stop_price': stop,
                'quality': quality}


@dataclass
class Pos:
    pair: str
    entry_price: float
    entry_bar: int
    stop_price: float
    highest_price: float
    size_usd: float


# ============================================================
# BACKTEST ENGINE — uitgebreid met bar-range support
# ============================================================

def run_backtest(data, coins, cfg, max_pos=1, pos_size=2000,
                 use_ranking=True, label="",
                 start_bar=50, end_bar=None):
    """
    Portfolio backtest met ConfigurableStrategy.
    start_bar/end_bar: voor walk-forward window selectie.
    Retourneert uitgebreid resultaat met trade_list + equity_curve.
    """
    coin_list = [c for c in coins if c in data]
    strategies = {p: ConfigurableStrategy(cfg) for p in coin_list}

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
                           'bars': bars_h, 'entry_bar': pos.entry_bar,
                           'exit_bar': bar})
            del positions[pair]

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
            last_idx = min(len(candles) - 1, max_bars - 1) if end_bar else len(candles) - 1
            lp = candles[last_idx]['close']
            gross = (lp - pos.entry_price) / pos.entry_price * pos.size_usd
            fees = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
            net = gross - fees
            equity += net
            trades.append({'pair': pair, 'entry': pos.entry_price,
                           'exit': lp, 'pnl': net, 'reason': 'END',
                           'bars': max_bars - pos.entry_bar,
                           'entry_bar': pos.entry_bar, 'exit_bar': max_bars})

    return calc_metrics(trades, equity, initial_eq, peak_eq, max_dd,
                        equity_curve, label, len(coin_list))


def calc_metrics(trades, equity, initial_eq, peak_eq, max_dd,
                 equity_curve, label, n_coins):
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
    avg_bars = sum(t['bars'] for t in trades) / len(trades) if trades else 0

    pnl_n = min(1, max(0, (total_pnl + 2000) / 8000))
    pf_n = min(1, max(0, (pf - 0.5) / 9.5))
    wr_n = wr / 100
    dd_p = max(0, 1 - max_dd / 50)
    tr_n = min(1, len(trades) / 50)
    score = pnl_n * 35 + pf_n * 20 + wr_n * 15 + dd_p * 20 + tr_n * 10

    reasons = {}
    for t in trades:
        r = t['reason']
        reasons.setdefault(r, {'n': 0, 'pnl': 0, 'wins': 0})
        reasons[r]['n'] += 1
        reasons[r]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            reasons[r]['wins'] += 1

    return {
        'label': label, 'coins': n_coins,
        'trades': len(trades), 'wins': len(wins), 'losses': len(losses),
        'wr': wr, 'pnl': total_pnl, 'roi': roi, 'pf': pf,
        'dd': max_dd, 'avg_w': avg_w, 'avg_l': avg_l,
        'avg_bars': avg_bars, 'score': score,
        'reasons': reasons, 'trade_list': trades,
        'equity_curve': equity_curve,
    }


# ============================================================
# STRATEGY CONFIGS
# ============================================================

CONFIGS = {
    'v5_prod': {
        'name': 'V5 RSI REC 45 (PRODUCTIE)',
        'cfg': {
            'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike': True, 'vol_spike_mult': 2.0,
            'vol_confirm': True, 'vol_confirm_mult': 1.0,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max': True, 'time_max_bars': 10,
            'rsi_recovery': True, 'rsi_rec_target': 45, 'rsi_rec_min_bars': 2,
        },
        'max_pos': 1, 'pos_size': 2000,
    },
    'v5_volspk3': {
        'name': 'V5 + VolSpk 3.0x (BESTE SCORE)',
        'cfg': {
            'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike': True, 'vol_spike_mult': 3.0,
            'vol_confirm': True, 'vol_confirm_mult': 1.0,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max': True, 'time_max_bars': 10,
            'rsi_recovery': True, 'rsi_rec_target': 45, 'rsi_rec_min_bars': 2,
        },
        'max_pos': 1, 'pos_size': 2000,
    },
    'v4_base': {
        'name': 'V4 DUALCONFIRM',
        'cfg': {
            'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike': True, 'vol_spike_mult': 2.0,
            'vol_confirm': True, 'vol_confirm_mult': 1.0,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max': True, 'time_max_bars': 10,
        },
        'max_pos': 1, 'pos_size': 2000,
    },
    'v3_volspike': {
        'name': 'V3 + VolSpike',
        'cfg': {
            'rsi_max': 35, 'atr_mult': 3.0,
            'vol_spike': True, 'vol_spike_mult': 2.0,
        },
        'max_pos': 2, 'pos_size': 1000,
    },
    'v5_rec47': {
        'name': 'V5 RSI REC 47',
        'cfg': {
            'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike': True, 'vol_spike_mult': 2.0,
            'vol_confirm': True, 'vol_confirm_mult': 1.0,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max': True, 'time_max_bars': 10,
            'rsi_recovery': True, 'rsi_rec_target': 47, 'rsi_rec_min_bars': 2,
        },
        'max_pos': 1, 'pos_size': 2000,
    },
}


# ============================================================
# DATA LADEN
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


def get_max_bars(data, coins) -> int:
    return max(len(data[c]) for c in coins if c in data)


# ============================================================
# 1. WALK-FORWARD ANALYSE
# ============================================================

def walk_forward_analysis(data, coins, config_key='v5_prod',
                          n_folds=5, train_pct=0.7):
    """
    Walk-forward analyse: train op 70%, test op 30%, rollend.

    De data wordt in n_folds overlappende windows verdeeld.
    Per fold: backtest op train-window EN test-window apart.
    Vergelijk in-sample vs out-of-sample performance.
    """
    cfg_info = CONFIGS[config_key]
    cfg = cfg_info['cfg']
    max_pos = cfg_info['max_pos']
    pos_size = cfg_info['pos_size']

    total_bars = get_max_bars(data, coins)
    usable_bars = total_bars - 50  # eerste 50 bars = indicator warmup

    fold_size = usable_bars // n_folds
    overlap = int(fold_size * 0.3)  # 30% overlap voor continuiteit

    logger.info(f"\n{'='*70}")
    logger.info(f"WALK-FORWARD ANALYSE: {cfg_info['name']}")
    logger.info(f"{'='*70}")
    logger.info(f"Totaal bars: {total_bars} | Bruikbaar: {usable_bars} | "
                f"Folds: {n_folds} | Train: {train_pct*100:.0f}%")

    results = []

    for fold in range(n_folds):
        # Window berekening
        fold_start = 50 + fold * (fold_size - overlap)
        fold_end = min(fold_start + fold_size, total_bars)

        if fold_end - fold_start < 30:  # minimum window
            continue

        train_end = fold_start + int((fold_end - fold_start) * train_pct)
        test_start = train_end
        test_end = fold_end

        train_bars = train_end - fold_start
        test_bars = test_end - test_start

        # Train backtest
        train_result = run_backtest(
            data, coins, cfg, max_pos=max_pos, pos_size=pos_size,
            label=f"Fold {fold+1} TRAIN",
            start_bar=fold_start, end_bar=train_end)

        # Test backtest (out-of-sample)
        test_result = run_backtest(
            data, coins, cfg, max_pos=max_pos, pos_size=pos_size,
            label=f"Fold {fold+1} TEST",
            start_bar=test_start, end_bar=test_end)

        results.append({
            'fold': fold + 1,
            'train_bars': train_bars,
            'test_bars': test_bars,
            'train': train_result,
            'test': test_result,
        })

        logger.info(f"\nFold {fold+1}: bars {fold_start}-{fold_end} "
                     f"(train: {train_bars}, test: {test_bars})")
        logger.info(f"  TRAIN: {train_result['trades']}tr | "
                     f"WR {train_result['wr']:.1f}% | "
                     f"P&L ${train_result['pnl']:+,.0f} | "
                     f"PF {train_result['pf']:.1f}")
        logger.info(f"  TEST:  {test_result['trades']}tr | "
                     f"WR {test_result['wr']:.1f}% | "
                     f"P&L ${test_result['pnl']:+,.0f} | "
                     f"PF {test_result['pf']:.1f}")

    # Aggregeer walk-forward resultaten
    wf_summary = aggregate_walk_forward(results)
    return wf_summary


def aggregate_walk_forward(results):
    """Aggregeer walk-forward resultaten en bereken degradatie."""
    if not results:
        return {'verdict': 'GEEN DATA', 'folds': 0}

    train_pnls = [r['train']['pnl'] for r in results]
    test_pnls = [r['test']['pnl'] for r in results]
    train_wrs = [r['train']['wr'] for r in results]
    test_wrs = [r['test']['wr'] for r in results]
    train_pfs = [r['train']['pf'] for r in results if r['train']['pf'] != float('inf')]
    test_pfs = [r['test']['pf'] for r in results if r['test']['pf'] != float('inf')]

    avg_train_pnl = sum(train_pnls) / len(train_pnls)
    avg_test_pnl = sum(test_pnls) / len(test_pnls)
    avg_train_wr = sum(train_wrs) / len(train_wrs)
    avg_test_wr = sum(test_wrs) / len(test_wrs)
    avg_train_pf = sum(train_pfs) / len(train_pfs) if train_pfs else 0
    avg_test_pf = sum(test_pfs) / len(test_pfs) if test_pfs else 0

    # Degradatie berekenen
    pnl_degradation = ((avg_test_pnl - avg_train_pnl) / abs(avg_train_pnl) * 100
                       if avg_train_pnl != 0 else 0)
    wr_degradation = avg_test_wr - avg_train_wr

    # Folds waar test winstgevend is
    test_profitable = sum(1 for p in test_pnls if p > 0)
    test_positive_wr = sum(1 for w in test_wrs if w > 50)

    # Verdict
    if test_profitable == len(test_pnls) and pnl_degradation > -30:
        verdict = 'STERK'
    elif test_profitable >= len(test_pnls) * 0.6:
        verdict = 'MATIG'
    elif test_profitable >= 1:
        verdict = 'ZWAK'
    else:
        verdict = 'GEFAALD'

    summary = {
        'verdict': verdict,
        'folds': len(results),
        'avg_train_pnl': avg_train_pnl,
        'avg_test_pnl': avg_test_pnl,
        'avg_train_wr': avg_train_wr,
        'avg_test_wr': avg_test_wr,
        'avg_train_pf': avg_train_pf,
        'avg_test_pf': avg_test_pf,
        'pnl_degradation_pct': pnl_degradation,
        'wr_degradation_pct': wr_degradation,
        'test_profitable_folds': test_profitable,
        'test_positive_wr_folds': test_positive_wr,
        'fold_details': results,
    }

    logger.info(f"\n{'─'*50}")
    logger.info(f"WALK-FORWARD SAMENVATTING")
    logger.info(f"{'─'*50}")
    logger.info(f"Verdict: {verdict}")
    logger.info(f"Folds winstgevend (test): {test_profitable}/{len(results)}")
    logger.info(f"Gem. Train P&L: ${avg_train_pnl:+,.0f} | "
                f"Gem. Test P&L: ${avg_test_pnl:+,.0f}")
    logger.info(f"Gem. Train WR: {avg_train_wr:.1f}% | "
                f"Gem. Test WR: {avg_test_wr:.1f}%")
    logger.info(f"P&L degradatie: {pnl_degradation:+.1f}% | "
                f"WR degradatie: {wr_degradation:+.1f}pp")

    return summary


# ============================================================
# 2. MONTE CARLO SIMULATIE
# ============================================================

def monte_carlo_simulation(data, coins, config_key='v5_prod',
                           n_simulations=10000, seed=42):
    """
    Monte Carlo simulatie:
    1. Draai een volledige backtest → verzamel individuele trade P&Ls
    2. Shuffle de trade-volgorde N keer → bootstrap P&L distributie
    3. Bereken confidence intervals en p-waarde

    Beantwoordt: "Als ik dezelfde trades in willekeurige volgorde had gedaan,
    hoe vaak was ik dan winstgevend geweest?"
    """
    cfg_info = CONFIGS[config_key]
    cfg = cfg_info['cfg']

    logger.info(f"\n{'='*70}")
    logger.info(f"MONTE CARLO SIMULATIE: {cfg_info['name']}")
    logger.info(f"{'='*70}")

    # Volledige backtest
    result = run_backtest(data, coins, cfg,
                          max_pos=cfg_info['max_pos'],
                          pos_size=cfg_info['pos_size'],
                          label="MC Baseline")

    trade_pnls = [t['pnl'] for t in result['trade_list']]
    actual_pnl = result['pnl']
    actual_dd = result['dd']
    n_trades = len(trade_pnls)

    if n_trades < 5:
        logger.warning(f"Te weinig trades ({n_trades}) voor Monte Carlo")
        return {'verdict': 'TE WEINIG TRADES', 'n_trades': n_trades}

    logger.info(f"Baseline: {n_trades} trades | P&L ${actual_pnl:+,.0f} | "
                f"DD {actual_dd:.1f}%")
    logger.info(f"Simulaties: {n_simulations:,}")

    random.seed(seed)

    sim_pnls = []
    sim_dds = []
    sim_wrs = []
    sim_pfs = []
    initial_eq = cfg_info['max_pos'] * cfg_info['pos_size']

    for i in range(n_simulations):
        # Shuffle trade P&Ls (willekeurige volgorde)
        shuffled = trade_pnls.copy()
        random.shuffle(shuffled)

        # Bereken equity curve
        eq = initial_eq
        peak = eq
        max_dd_sim = 0
        wins = 0

        for pnl in shuffled:
            eq += pnl
            if pnl > 0:
                wins += 1
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100 if peak > 0 else 0
            if dd > max_dd_sim:
                max_dd_sim = dd

        total_sim_pnl = sum(shuffled)
        sim_pnls.append(total_sim_pnl)
        sim_dds.append(max_dd_sim)
        sim_wrs.append(wins / n_trades * 100 if n_trades > 0 else 0)
        total_wins = sum(p for p in shuffled if p > 0)
        total_loss = abs(sum(p for p in shuffled if p <= 0))
        sim_pfs.append(total_wins / total_loss if total_loss > 0 else float('inf'))

    # Statistieken
    sim_pnls.sort()
    sim_dds.sort()

    # P-waarde: hoe vaak is random P&L >= actual P&L?
    # (voor shuffled is P&L altijd gelijk, maar DD varieert)
    # De echte vraag: hoe vaak is de DD lager dan actual?
    worse_dd = sum(1 for d in sim_dds if d >= actual_dd)
    dd_percentile = worse_dd / n_simulations * 100

    # Confidence intervals voor P&L (als proxy voor expectation)
    ci_5 = sim_pnls[int(n_simulations * 0.05)]
    ci_25 = sim_pnls[int(n_simulations * 0.25)]
    ci_50 = sim_pnls[int(n_simulations * 0.50)]
    ci_75 = sim_pnls[int(n_simulations * 0.75)]
    ci_95 = sim_pnls[int(n_simulations * 0.95)]

    # DD confidence intervals
    dd_5 = sim_dds[int(n_simulations * 0.05)]
    dd_50 = sim_dds[int(n_simulations * 0.50)]
    dd_95 = sim_dds[int(n_simulations * 0.95)]

    # Probability of ruin (equity <= 0)
    ruin_count = sum(1 for _ in range(min(1000, n_simulations))
                     if simulate_ruin(trade_pnls, initial_eq))
    prob_ruin = ruin_count / min(1000, n_simulations) * 100

    # Profit probability
    profit_count = sum(1 for p in sim_pnls if p > 0)
    prob_profit = profit_count / n_simulations * 100

    summary = {
        'verdict': 'WINSTGEVEND' if prob_profit > 60 else 'ONZEKER' if prob_profit > 40 else 'NEGATIEF',
        'n_trades': n_trades,
        'actual_pnl': actual_pnl,
        'actual_dd': actual_dd,
        'n_simulations': n_simulations,
        'prob_profit': prob_profit,
        'prob_ruin': prob_ruin,
        'ci_5': ci_5,
        'ci_25': ci_25,
        'ci_50': ci_50,
        'ci_75': ci_75,
        'ci_95': ci_95,
        'dd_best_5': dd_5,
        'dd_median': dd_50,
        'dd_worst_5': dd_95,
        'dd_percentile': dd_percentile,
        'avg_pnl': sum(sim_pnls) / len(sim_pnls),
        'std_pnl': calc_std(sim_pnls),
        'trade_pnls': trade_pnls,
    }

    logger.info(f"\n{'─'*50}")
    logger.info(f"MONTE CARLO RESULTATEN ({n_simulations:,} simulaties)")
    logger.info(f"{'─'*50}")
    logger.info(f"Kans op winst: {prob_profit:.1f}%")
    logger.info(f"Kans op ruin:  {prob_ruin:.1f}%")
    logger.info(f"\nP&L Confidence Intervals:")
    logger.info(f"  5% (worst):  ${ci_5:+,.0f}")
    logger.info(f"  25%:         ${ci_25:+,.0f}")
    logger.info(f"  50% (med):   ${ci_50:+,.0f}")
    logger.info(f"  75%:         ${ci_75:+,.0f}")
    logger.info(f"  95% (best):  ${ci_95:+,.0f}")
    logger.info(f"\nDrawdown Distributie:")
    logger.info(f"  Best 5%:     {dd_5:.1f}%")
    logger.info(f"  Mediaan:     {dd_50:.1f}%")
    logger.info(f"  Worst 5%:    {dd_95:.1f}%")
    logger.info(f"  Actual DD:   {actual_dd:.1f}% "
                f"(beter dan {dd_percentile:.0f}% van simulaties)")

    return summary


def simulate_ruin(trade_pnls, initial_eq):
    """Simuleer of equity naar 0 gaat met willekeurige trade volgorde."""
    shuffled = trade_pnls.copy()
    random.shuffle(shuffled)
    eq = initial_eq
    for pnl in shuffled:
        eq += pnl
        if eq <= 0:
            return True
    return False


def calc_std(values):
    """Bereken standaarddeviatie."""
    if len(values) < 2:
        return 0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


# ============================================================
# 3. ZEUS-AFHANKELIJKHEID ANALYSE
# ============================================================

def zeus_dependency_analysis(data, coins, config_key='v5_prod',
                             n_mc_sims=5000):
    """
    Analyseer hoe afhankelijk de strategie is van outlier trades.

    1. Volledige backtest met alle trades
    2. Verwijder top-N trades (ZEUS-achtige outliers)
    3. Herbereken metrics zonder outliers
    4. Monte Carlo zonder outliers
    """
    cfg_info = CONFIGS[config_key]
    cfg = cfg_info['cfg']

    logger.info(f"\n{'='*70}")
    logger.info(f"ZEUS-AFHANKELIJKHEID ANALYSE: {cfg_info['name']}")
    logger.info(f"{'='*70}")

    result = run_backtest(data, coins, cfg,
                          max_pos=cfg_info['max_pos'],
                          pos_size=cfg_info['pos_size'],
                          label="Zeus Baseline")

    trades = result['trade_list']
    if not trades:
        return {'verdict': 'GEEN TRADES'}

    # Sorteer op P&L (hoogste eerst)
    sorted_trades = sorted(trades, key=lambda t: t['pnl'], reverse=True)

    logger.info(f"\nTop 10 trades:")
    for i, t in enumerate(sorted_trades[:10]):
        pct = t['pnl'] / result['pnl'] * 100 if result['pnl'] != 0 else 0
        logger.info(f"  #{i+1}: {t['pair']:15s} | ${t['pnl']:+8,.0f} | "
                     f"{t['reason']:15s} | {pct:5.1f}% van totaal")

    # Analyse met progressieve verwijdering van top trades
    scenarios = []
    for remove_n in range(0, min(6, len(sorted_trades))):
        remaining = sorted_trades[remove_n:]
        total_pnl = sum(t['pnl'] for t in remaining)
        wins = sum(1 for t in remaining if t['pnl'] > 0)
        losses = sum(1 for t in remaining if t['pnl'] <= 0)
        wr = wins / len(remaining) * 100 if remaining else 0
        tw = sum(t['pnl'] for t in remaining if t['pnl'] > 0)
        tl = abs(sum(t['pnl'] for t in remaining if t['pnl'] <= 0))
        pf = tw / tl if tl > 0 else float('inf')

        # Concentratie: hoeveel % komt van top-N trades?
        removed_pnl = sum(t['pnl'] for t in sorted_trades[:remove_n]) if remove_n > 0 else 0
        concentration = removed_pnl / result['pnl'] * 100 if result['pnl'] != 0 else 0

        scenarios.append({
            'removed': remove_n,
            'trades': len(remaining),
            'pnl': total_pnl,
            'wr': wr,
            'pf': pf,
            'concentration': concentration,
            'removed_trades': [t['pair'] for t in sorted_trades[:remove_n]],
        })

    # Herfindahl-index (concentratie maat)
    pnls_abs = [abs(t['pnl']) for t in trades]
    total_abs = sum(pnls_abs)
    herfindahl = sum((p / total_abs) ** 2 for p in pnls_abs) if total_abs > 0 else 0

    # Monte Carlo zonder de #1 trade (ZEUS-test)
    logger.info(f"\nMonte Carlo ZONDER top trade ({sorted_trades[0]['pair']}):")
    remaining_pnls = [t['pnl'] for t in sorted_trades[1:]]

    random.seed(42)
    mc_pnls = []
    initial_eq = cfg_info['max_pos'] * cfg_info['pos_size']
    for _ in range(n_mc_sims):
        shuffled = remaining_pnls.copy()
        random.shuffle(shuffled)
        mc_pnls.append(sum(shuffled))

    mc_pnls.sort()
    prob_profit_no_zeus = sum(1 for p in mc_pnls if p > 0) / len(mc_pnls) * 100

    # Expectation per trade
    avg_per_trade_all = result['pnl'] / len(trades) if trades else 0
    avg_per_trade_no_top = sum(remaining_pnls) / len(remaining_pnls) if remaining_pnls else 0

    # Verdict
    top1_pct = sorted_trades[0]['pnl'] / result['pnl'] * 100 if result['pnl'] != 0 else 0
    if top1_pct > 70:
        verdict = 'EXTREEM AFHANKELIJK'
    elif top1_pct > 50:
        verdict = 'STERK AFHANKELIJK'
    elif top1_pct > 30:
        verdict = 'MATIG AFHANKELIJK'
    else:
        verdict = 'GEDIVERSIFIEERD'

    summary = {
        'verdict': verdict,
        'top1_trade': sorted_trades[0]['pair'],
        'top1_pnl': sorted_trades[0]['pnl'],
        'top1_pct': top1_pct,
        'herfindahl_index': herfindahl,
        'scenarios': scenarios,
        'avg_per_trade_all': avg_per_trade_all,
        'avg_per_trade_no_top': avg_per_trade_no_top,
        'prob_profit_no_zeus': prob_profit_no_zeus,
        'mc_ci_5_no_zeus': mc_pnls[int(len(mc_pnls) * 0.05)],
        'mc_ci_50_no_zeus': mc_pnls[int(len(mc_pnls) * 0.50)],
        'mc_ci_95_no_zeus': mc_pnls[int(len(mc_pnls) * 0.95)],
    }

    logger.info(f"\n{'─'*50}")
    logger.info(f"ZEUS-AFHANKELIJKHEID RESULTATEN")
    logger.info(f"{'─'*50}")
    logger.info(f"Verdict: {verdict}")
    logger.info(f"Top trade: {sorted_trades[0]['pair']} = "
                f"${sorted_trades[0]['pnl']:+,.0f} ({top1_pct:.1f}% van totaal)")
    logger.info(f"Herfindahl Index: {herfindahl:.4f} "
                f"({'hoog' if herfindahl > 0.15 else 'normaal'})")
    logger.info(f"\nVerwachting per trade:")
    logger.info(f"  Met alle trades:    ${avg_per_trade_all:+,.0f}")
    logger.info(f"  Zonder top trade:   ${avg_per_trade_no_top:+,.0f}")

    logger.info(f"\nProgressieve verwijdering:")
    for s in scenarios:
        logger.info(f"  Zonder top-{s['removed']}: {s['trades']}tr | "
                     f"P&L ${s['pnl']:+,.0f} | WR {s['wr']:.1f}% | "
                     f"PF {s['pf']:.1f} | Concentratie: {s['concentration']:.1f}%")

    logger.info(f"\nMonte Carlo zonder #{sorted_trades[0]['pair']}:")
    logger.info(f"  Kans op winst: {prob_profit_no_zeus:.1f}%")
    logger.info(f"  5% CI:  ${summary['mc_ci_5_no_zeus']:+,.0f}")
    logger.info(f"  50% CI: ${summary['mc_ci_50_no_zeus']:+,.0f}")
    logger.info(f"  95% CI: ${summary['mc_ci_95_no_zeus']:+,.0f}")

    return summary


# ============================================================
# 4. STATISTISCHE SIGNIFICANTIE
# ============================================================

def statistical_significance(data, coins, config_key='v5_prod',
                             n_random=5000, seed=42):
    """
    Test of de strategie statistisch significant beter is dan random.

    Methode: Vergelijk met random entry/exit strategie:
    - Random entry op willekeurige bars
    - Exit na gemiddeld hetzelfde aantal bars als echte strategie
    - Bereken hoe vaak random beter presteert (= p-waarde)
    """
    cfg_info = CONFIGS[config_key]
    cfg = cfg_info['cfg']

    logger.info(f"\n{'='*70}")
    logger.info(f"STATISTISCHE SIGNIFICANTIE: {cfg_info['name']}")
    logger.info(f"{'='*70}")

    # Echte strategie
    result = run_backtest(data, coins, cfg,
                          max_pos=cfg_info['max_pos'],
                          pos_size=cfg_info['pos_size'],
                          label="Sig Baseline")

    actual_pnl = result['pnl']
    actual_trades = result['trades']
    avg_hold = result['avg_bars']

    if actual_trades < 3:
        return {'verdict': 'TE WEINIG TRADES'}

    logger.info(f"Strategie: {actual_trades}tr | P&L ${actual_pnl:+,.0f} | "
                f"Gem. hold: {avg_hold:.1f} bars")

    # Random benchmarks
    random.seed(seed)
    coin_list = [c for c in coins if c in data]
    pos_size = cfg_info['pos_size']
    random_pnls = []

    for sim in range(n_random):
        # Genereer random trades met vergelijkbare parameters
        sim_pnl = 0
        for _ in range(actual_trades):
            # Pick willekeurige coin en willekeurig instapmoment
            coin = random.choice(coin_list)
            candles = data.get(coin, [])
            if len(candles) < 60:
                continue

            entry_bar = random.randint(50, len(candles) - int(avg_hold) - 2)
            exit_bar = min(entry_bar + max(1, int(avg_hold + random.gauss(0, 2))),
                           len(candles) - 1)

            entry_price = candles[entry_bar]['close']
            exit_price = candles[exit_bar]['close']

            gross = (exit_price - entry_price) / entry_price * pos_size
            fees = pos_size * KRAKEN_FEE + (pos_size + gross) * KRAKEN_FEE
            net = gross - fees
            sim_pnl += net

        random_pnls.append(sim_pnl)

    random_pnls.sort()

    # P-waarde: hoeveel % van random is beter dan onze strategie?
    better_count = sum(1 for p in random_pnls if p >= actual_pnl)
    p_value = better_count / n_random

    # Z-score
    avg_random = sum(random_pnls) / len(random_pnls)
    std_random = calc_std(random_pnls)
    z_score = (actual_pnl - avg_random) / std_random if std_random > 0 else 0

    # Percentile
    rank = sum(1 for p in random_pnls if p < actual_pnl)
    percentile = rank / n_random * 100

    # Sharpe-achtige ratio (excess return / volatiliteit)
    trade_returns = [t['pnl'] / pos_size for t in result['trade_list']]
    avg_return = sum(trade_returns) / len(trade_returns) if trade_returns else 0
    std_return = calc_std(trade_returns) if len(trade_returns) > 1 else 1
    sharpe = avg_return / std_return if std_return > 0 else 0
    # Annualiseer (4H bars, ~2190 bars/jaar, handelen ~actual_trades keer per 60d)
    trades_per_year = actual_trades * (365 / 60)
    sharpe_annual = sharpe * math.sqrt(trades_per_year) if trades_per_year > 0 else 0

    # Verdict
    if p_value < 0.01:
        verdict = 'ZEER SIGNIFICANT (p<0.01)'
    elif p_value < 0.05:
        verdict = 'SIGNIFICANT (p<0.05)'
    elif p_value < 0.10:
        verdict = 'MARGINAAL (p<0.10)'
    else:
        verdict = 'NIET SIGNIFICANT'

    summary = {
        'verdict': verdict,
        'p_value': p_value,
        'z_score': z_score,
        'percentile': percentile,
        'actual_pnl': actual_pnl,
        'avg_random_pnl': avg_random,
        'std_random_pnl': std_random,
        'sharpe_per_trade': sharpe,
        'sharpe_annual': sharpe_annual,
        'random_ci_5': random_pnls[int(n_random * 0.05)],
        'random_ci_50': random_pnls[int(n_random * 0.50)],
        'random_ci_95': random_pnls[int(n_random * 0.95)],
        'n_random': n_random,
    }

    logger.info(f"\n{'─'*50}")
    logger.info(f"SIGNIFICANTIE RESULTATEN ({n_random:,} random benchmarks)")
    logger.info(f"{'─'*50}")
    logger.info(f"Verdict: {verdict}")
    logger.info(f"P-waarde: {p_value:.4f}")
    logger.info(f"Z-score: {z_score:.2f}")
    logger.info(f"Percentile: {percentile:.1f}% (beter dan {percentile:.0f}% random)")
    logger.info(f"\nStrategie P&L: ${actual_pnl:+,.0f}")
    logger.info(f"Random gem.:   ${avg_random:+,.0f} (std: ${std_random:,.0f})")
    logger.info(f"\nRandom CI:")
    logger.info(f"  5%:  ${summary['random_ci_5']:+,.0f}")
    logger.info(f"  50%: ${summary['random_ci_50']:+,.0f}")
    logger.info(f"  95%: ${summary['random_ci_95']:+,.0f}")
    logger.info(f"\nSharpe Ratio:")
    logger.info(f"  Per trade:   {sharpe:.3f}")
    logger.info(f"  Jaarlijks:   {sharpe_annual:.2f}")

    return summary


# ============================================================
# 5. GECOMBINEERD RAPPORT
# ============================================================

def generate_report(wf, mc, zeus, sig, config_name):
    """Genereer een gecombineerd eindrapport."""
    logger.info(f"\n{'='*70}")
    logger.info(f"{'='*70}")
    logger.info(f"  QUANT RESEARCHER — EINDRAPPORT")
    logger.info(f"  Strategie: {config_name}")
    logger.info(f"  Datum: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info(f"{'='*70}")
    logger.info(f"{'='*70}")

    # Overall verdict
    scores = {
        'Walk-Forward': 1 if wf['verdict'] == 'STERK' else 0.5 if wf['verdict'] == 'MATIG' else 0,
        'Monte Carlo': 1 if mc['verdict'] == 'WINSTGEVEND' else 0.5 if mc['verdict'] == 'ONZEKER' else 0,
        'Zeus-onafhankelijk': 1 if zeus['verdict'] == 'GEDIVERSIFIEERD' else 0.5 if zeus['verdict'] == 'MATIG AFHANKELIJK' else 0,
        'Significantie': 1 if 'SIGNIFICANT' in sig['verdict'] and 'NIET' not in sig['verdict'] else 0.5 if 'MARGINAAL' in sig['verdict'] else 0,
    }
    overall_score = sum(scores.values()) / len(scores)

    if overall_score >= 0.75:
        overall = 'PRODUCTIE-KLAAR'
    elif overall_score >= 0.5:
        overall = 'VOORZICHTIG HANDELEN'
    elif overall_score >= 0.25:
        overall = 'MEER VALIDATIE NODIG'
    else:
        overall = 'NIET AANBEVOLEN'

    logger.info(f"\n  OVERALL VERDICT: {overall} ({overall_score*100:.0f}%)")
    logger.info(f"  {'─'*50}")

    for test, score in scores.items():
        icon = '+' if score == 1 else '~' if score == 0.5 else '-'
        logger.info(f"  [{icon}] {test}: {score*100:.0f}%")

    logger.info(f"\n  DETAILS PER TEST:")
    logger.info(f"  {'─'*50}")

    # Walk-Forward
    logger.info(f"\n  1. WALK-FORWARD ({wf['verdict']})")
    logger.info(f"     Folds winstgevend: {wf['test_profitable_folds']}/{wf['folds']}")
    logger.info(f"     Train P&L gem: ${wf['avg_train_pnl']:+,.0f} | "
                f"Test P&L gem: ${wf['avg_test_pnl']:+,.0f}")
    logger.info(f"     Degradatie: {wf['pnl_degradation_pct']:+.1f}%")

    # Monte Carlo
    logger.info(f"\n  2. MONTE CARLO ({mc['verdict']})")
    logger.info(f"     Kans op winst: {mc['prob_profit']:.1f}%")
    logger.info(f"     Kans op ruin: {mc['prob_ruin']:.1f}%")
    logger.info(f"     P&L range (5-95%): ${mc['ci_5']:+,.0f} tot ${mc['ci_95']:+,.0f}")

    # Zeus
    logger.info(f"\n  3. ZEUS-AFHANKELIJKHEID ({zeus['verdict']})")
    logger.info(f"     Top trade: {zeus['top1_trade']} = {zeus['top1_pct']:.1f}% van P&L")
    logger.info(f"     Verwachting per trade (all): ${zeus['avg_per_trade_all']:+,.0f}")
    logger.info(f"     Verwachting per trade (no top): ${zeus['avg_per_trade_no_top']:+,.0f}")
    logger.info(f"     Kans op winst zonder top: {zeus['prob_profit_no_zeus']:.1f}%")

    # Significantie
    logger.info(f"\n  4. SIGNIFICANTIE ({sig['verdict']})")
    logger.info(f"     P-waarde: {sig['p_value']:.4f}")
    logger.info(f"     Z-score: {sig['z_score']:.2f}")
    logger.info(f"     Sharpe (jaarlijks): {sig['sharpe_annual']:.2f}")
    logger.info(f"     Beter dan {sig['percentile']:.0f}% random strategieen")

    # Aanbevelingen
    logger.info(f"\n  AANBEVELINGEN:")
    logger.info(f"  {'─'*50}")

    if zeus['top1_pct'] > 50:
        logger.info(f"  [!] Hoge concentratie in {zeus['top1_trade']}. "
                     f"Overweeg position sizing te beperken per coin.")

    if wf['pnl_degradation_pct'] < -50:
        logger.info(f"  [!] Grote in-sample vs out-of-sample degradatie. "
                     f"Mogelijke overfitting.")

    if sig['p_value'] > 0.05:
        logger.info(f"  [!] Niet statistisch significant. "
                     f"Meer data (langere testperiode) nodig.")

    if mc['prob_ruin'] > 5:
        logger.info(f"  [!] Ruinkans > 5%. Overweeg kleinere positiegrootte.")

    if overall_score >= 0.5:
        logger.info(f"  [+] Strategie heeft potentie. Paper trade minimaal 30 dagen "
                     f"voor live deployment.")

    if mc['prob_profit'] > 60 and sig['p_value'] < 0.10:
        logger.info(f"  [+] Positieve verwachtingswaarde bevestigd door "
                     f"meerdere analyses.")

    logger.info(f"\n{'='*70}")

    return {
        'overall': overall,
        'overall_score': overall_score,
        'scores': scores,
        'walk_forward': wf,
        'monte_carlo': mc,
        'zeus': zeus,
        'significance': sig,
    }


# ============================================================
# MULTI-CONFIG VERGELIJKING
# ============================================================

def compare_configs(data, coins, config_keys=None, quick=False):
    """Vergelijk meerdere configs op alle Quant Researcher metrics."""
    if config_keys is None:
        config_keys = list(CONFIGS.keys())

    n_mc = 2000 if quick else 10000
    n_rand = 1000 if quick else 5000
    n_folds = 3 if quick else 5

    all_reports = {}

    for key in config_keys:
        cfg_info = CONFIGS[key]
        logger.info(f"\n\n{'#'*70}")
        logger.info(f"# ANALYSEREN: {cfg_info['name']}")
        logger.info(f"{'#'*70}")

        wf = walk_forward_analysis(data, coins, key, n_folds=n_folds)
        mc = monte_carlo_simulation(data, coins, key, n_simulations=n_mc)
        zeus = zeus_dependency_analysis(data, coins, key, n_mc_sims=n_mc // 2)
        sig = statistical_significance(data, coins, key, n_random=n_rand)

        report = generate_report(wf, mc, zeus, sig, cfg_info['name'])
        all_reports[key] = report

    # Vergelijkingstabel
    logger.info(f"\n\n{'='*70}")
    logger.info(f"VERGELIJKINGSTABEL — ALLE CONFIGS")
    logger.info(f"{'='*70}")
    logger.info(f"{'Config':<30} | {'Score':>5} | {'WF':>6} | {'MC%':>5} | "
                f"{'Zeus%':>5} | {'p-val':>6} | {'Sharpe':>6} | Verdict")
    logger.info(f"{'-'*100}")

    for key in config_keys:
        r = all_reports[key]
        name = CONFIGS[key]['name'][:28]
        logger.info(
            f"{name:<30} | {r['overall_score']*100:5.0f} | "
            f"{r['walk_forward']['verdict']:>6} | "
            f"{r['monte_carlo']['prob_profit']:5.1f} | "
            f"{r['zeus']['top1_pct']:5.1f} | "
            f"{r['significance']['p_value']:6.4f} | "
            f"{r['significance']['sharpe_annual']:6.2f} | "
            f"{r['overall']}"
        )

    return all_reports


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Quant Researcher — Walk-Forward + Monte Carlo Validatie')
    parser.add_argument('--config', default='v5_prod',
                        choices=list(CONFIGS.keys()),
                        help='Strategie config om te analyseren')
    parser.add_argument('--all-configs', action='store_true',
                        help='Vergelijk alle configs')
    parser.add_argument('--quick', action='store_true',
                        help='Snelle versie (minder simulaties)')
    parser.add_argument('--mc-only', action='store_true',
                        help='Alleen Monte Carlo')
    parser.add_argument('--wf-only', action='store_true',
                        help='Alleen Walk-Forward')
    parser.add_argument('--zeus-only', action='store_true',
                        help='Alleen Zeus-afhankelijkheid')
    parser.add_argument('--sig-only', action='store_true',
                        help='Alleen Significantie')
    args = parser.parse_args()

    logger.info("Quant Researcher — Walk-Forward + Monte Carlo Validatie")
    logger.info("=" * 70)

    data = load_data()
    coins = get_coins(data)
    logger.info(f"Coins: {len(coins)} | Config: {args.config}")

    n_mc = 2000 if args.quick else 10000
    n_rand = 1000 if args.quick else 5000
    n_folds = 3 if args.quick else 5

    if args.all_configs:
        compare_configs(data, coins, quick=args.quick)
        return

    config_key = args.config
    cfg_info = CONFIGS[config_key]

    if args.mc_only:
        monte_carlo_simulation(data, coins, config_key, n_simulations=n_mc)
        return
    if args.wf_only:
        walk_forward_analysis(data, coins, config_key, n_folds=n_folds)
        return
    if args.zeus_only:
        zeus_dependency_analysis(data, coins, config_key, n_mc_sims=n_mc // 2)
        return
    if args.sig_only:
        statistical_significance(data, coins, config_key, n_random=n_rand)
        return

    # Volledige analyse
    wf = walk_forward_analysis(data, coins, config_key, n_folds=n_folds)
    mc = monte_carlo_simulation(data, coins, config_key, n_simulations=n_mc)
    zeus = zeus_dependency_analysis(data, coins, config_key, n_mc_sims=n_mc // 2)
    sig = statistical_significance(data, coins, config_key, n_random=n_rand)

    report = generate_report(wf, mc, zeus, sig, cfg_info['name'])

    # Save report
    report_file = BASE_DIR / f'quant_report_{config_key}.json'
    # Convert non-serializable values
    def clean_for_json(obj):
        if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
            return str(obj)
        if isinstance(obj, dict):
            return {k: clean_for_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [clean_for_json(v) for v in obj]
        return obj

    with open(report_file, 'w') as f:
        json.dump(clean_for_json(report), f, indent=2)
    logger.info(f"\nRapport opgeslagen: {report_file}")


if __name__ == '__main__':
    main()

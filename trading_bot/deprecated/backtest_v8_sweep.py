#!/usr/bin/env python3
"""
V8 MEGA SWEEP — Fixed Stop Parameter Optimalisatie + Walk-Forward Validatie
===========================================================================
Bouwt voort op V7 ontdekking: Fixed 8% Stop = enige config met POSITIEVE EV zonder outlier.

Sweep:
  1. Fixed stop percentage: 3%, 4%, 5%, 6%, 7%, 8%, 9%, 10%, 12%, 15%
  2. TimeMax variaties: 8, 10, 12 bars
  3. Met/zonder Quality Gate (0.4, 0.5)
  4. Met/zonder Combo Exit
  5. Met/zonder RSI Recovery target variaties (43, 45, 47)
  6. Position size: $1000, $1500, $2000

Walk-forward validatie op top configs.

Gebruik:
    python backtest_v8_sweep.py               # Volledige sweep
    python backtest_v8_sweep.py --quick        # Snelle sweep (minder combinaties)
    python backtest_v8_sweep.py --top N        # Toon top N resultaten
"""
import os
import sys
import json
import math
import argparse
import logging
import itertools
from datetime import datetime
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
logger = logging.getLogger('v8_sweep')


# ============================================================
# V8 STRATEGY — Fixed Stop + Configureerbare Exits
# ============================================================

class V8Strategy:
    """
    V8 Strategy — Trail Stop Eliminatie + Fixed Stop Loss.

    Kernverandering t.o.v. V5/V6:
    - GEEN ATR trailing stop (0% WR bewezen)
    - Fixed percentage stop als bescherming
    - Focus op target-based exits (RSI Recovery, DC Target, BB Target)
    """

    def __init__(self, cfg: dict):
        # === ENTRY ===
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

        # === EXIT: Fixed Stop ===
        self.fixed_stop_pct = cfg.get('fixed_stop_pct', 8.0)

        # === EXIT: Time Max ===
        self.use_time_max = cfg.get('time_max', True)
        self.time_max_bars = cfg.get('time_max_bars', 10)

        # === EXIT: RSI Recovery ===
        self.use_rsi_recovery = cfg.get('rsi_recovery', True)
        self.rsi_recovery_target = cfg.get('rsi_rec_target', 45)
        self.rsi_recovery_min_bars = cfg.get('rsi_rec_min_bars', 2)

        # === EXIT: Combo Exit ===
        self.use_combo_exit = cfg.get('combo_exit', False)
        self.combo_rsi_target = cfg.get('combo_rsi_target', 45)
        self.combo_rsi_min_bars = cfg.get('combo_rsi_min_bars', 2)
        self.combo_fallback_pct = cfg.get('combo_fallback_pct', 2.0)
        self.combo_fallback_bars = cfg.get('combo_fallback_bars', 5)

        # === EXIT: Break-even ===
        self.use_breakeven = cfg.get('breakeven', False)
        self.breakeven_trigger = cfg.get('be_trigger', 3.0)

        # === ENTRY: Quality Gate ===
        self.use_quality_gate = cfg.get('quality_gate', False)
        self.min_quality = cfg.get('min_quality', 0.4)

        # === State ===
        self.cooldown_bars = cfg.get('cooldown_bars', 4)
        self.cooldown_after_stop = cfg.get('cooldown_stop', 8)
        self.rsi_sell = cfg.get('rsi_sell', 70)
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
        # EXIT LOGIC — V8: No Trail Stop
        # ══════════════════════════════════════
        if position:
            entry_price = position['entry_price']
            bars_in = self.bar_count - position['entry_bar']
            pnl_pct = (close - entry_price) / entry_price * 100

            # 1. FIXED STOP — percentage-based hard floor
            if pnl_pct <= -self.fixed_stop_pct:
                return {'action': 'SELL', 'reason': 'FIXED STOP', 'price': close}

            # 2. TIME MAX
            if self.use_time_max and bars_in >= self.time_max_bars:
                return {'action': 'SELL', 'reason': 'TIME MAX', 'price': close}

            # 3. COMBO EXIT or RSI RECOVERY
            if self.use_combo_exit:
                if (bars_in >= self.combo_rsi_min_bars
                        and rsi >= self.combo_rsi_target):
                    return {'action': 'SELL', 'reason': 'COMBO RSI', 'price': close}
                if (bars_in >= self.combo_fallback_bars
                        and pnl_pct >= self.combo_fallback_pct):
                    return {'action': 'SELL', 'reason': 'COMBO PROFIT', 'price': close}
            elif self.use_rsi_recovery:
                if (bars_in >= self.rsi_recovery_min_bars
                        and rsi >= self.rsi_recovery_target):
                    return {'action': 'SELL', 'reason': 'RSI RECOVERY', 'price': close}

            # 4. DC/BB TARGETS
            if close >= mid_channel:
                return {'action': 'SELL', 'reason': 'DC TARGET', 'price': close}
            if close >= bb_mid:
                return {'action': 'SELL', 'reason': 'BB TARGET', 'price': close}
            if rsi > self.rsi_sell:
                return {'action': 'SELL', 'reason': 'RSI EXIT', 'price': close}

            # 5. NO TRAIL STOP — gewoon HOLD
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
        rsi_sc = max(0, (self.rsi_max - rsi) / self.rsi_max)
        dc_d = (prev_lowest - low) / prev_lowest if prev_lowest > 0 else 0
        d_sc = min(1, dc_d * 20)
        v_sc = 0
        if volumes and vol_avg > 0:
            v_sc = min(1, volumes[-1] / vol_avg / 3)
        quality = rsi_sc * 0.4 + d_sc * 0.3 + v_sc * 0.3

        if self.use_quality_gate and quality < self.min_quality:
            return {'action': 'WAIT'}

        stop = close * (1 - self.fixed_stop_pct / 100)

        return {'action': 'BUY', 'price': close, 'stop_price': stop,
                'quality': quality}


# ============================================================
# BACKTEST ENGINE (clean V8 version)
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
                 label="", start_bar=50, end_bar=None):
    coin_list = [c for c in coins if c in data]
    strategies = {p: V8Strategy(cfg) for p in coin_list}

    max_bars = max(len(data[p]) for p in coin_list) if coin_list else 0
    if end_bar is not None:
        max_bars = min(max_bars, end_bar)

    positions = {}
    trades = []
    equity = max_pos * pos_size
    initial_eq = equity
    peak_eq = equity
    max_dd = 0

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

        # Process buys (volume ranking)
        if len(positions) < max_pos and buys:
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

    # Close remaining
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

    # Without top trade
    if trades:
        sorted_trades = sorted(trades, key=lambda x: x['pnl'], reverse=True)
        pnl_no_top = total_pnl - sorted_trades[0]['pnl']
        top_trade = sorted_trades[0]
    else:
        pnl_no_top = 0
        top_trade = None

    n_no_top = len(trades) - 1 if len(trades) > 1 else 1
    ev_no_top = pnl_no_top / n_no_top if n_no_top > 0 else 0

    # WR without top
    if len(trades) > 1:
        trades_nt = sorted_trades[1:]
        wins_nt = [t for t in trades_nt if t['pnl'] > 0]
        wr_no_top = len(wins_nt) / len(trades_nt) * 100
    else:
        wr_no_top = 0

    # Herfindahl
    if trades and total_pnl != 0:
        herf = sum((t['pnl'] / total_pnl) ** 2 for t in trades)
    else:
        herf = 1.0

    # Exit reasons
    reasons = {}
    for t in trades:
        r = t['reason']
        reasons.setdefault(r, {'n': 0, 'pnl': 0, 'wins': 0})
        reasons[r]['n'] += 1
        reasons[r]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            reasons[r]['wins'] += 1

    # Fixed stop stats
    fixed_stops = [t for t in trades if t['reason'] == 'FIXED STOP']
    fixed_stop_count = len(fixed_stops)
    fixed_stop_pnl = sum(t['pnl'] for t in fixed_stops)

    return {
        'label': label, 'trades': len(trades), 'wr': wr,
        'pnl': total_pnl, 'pf': pf, 'dd': max_dd,
        'avg_w': avg_w, 'avg_l': avg_l,
        'pnl_no_top': pnl_no_top, 'ev_no_top': ev_no_top,
        'wr_no_top': wr_no_top, 'herf': herf,
        'top_trade': top_trade,
        'reasons': reasons, 'trade_list': trades,
        'fixed_stops': fixed_stop_count,
        'fixed_stop_pnl': fixed_stop_pnl,
    }


# ============================================================
# WALK-FORWARD VALIDATION
# ============================================================

def walk_forward(data, coins, cfg, pos_size=2000, n_folds=3):
    max_bars = max(len(data[c]) for c in coins if c in data)
    usable = max_bars - 50
    fold_size = usable // n_folds

    results = []
    for fold in range(n_folds):
        fold_start = 50 + fold * fold_size
        fold_end = fold_start + fold_size
        split = fold_start + int(fold_size * 0.7)

        train = run_backtest(data, coins, cfg, pos_size=pos_size,
                             start_bar=fold_start, end_bar=split)
        test = run_backtest(data, coins, cfg, pos_size=pos_size,
                            start_bar=split, end_bar=fold_end)

        results.append({
            'fold': fold + 1,
            'train_pnl': train['pnl'], 'train_trades': train['trades'],
            'test_pnl': test['pnl'], 'test_trades': test['trades'],
            'test_ev_no_top': test['ev_no_top'],
            'test_wr': test['wr'],
        })

    profitable = sum(1 for r in results if r['test_pnl'] > 0)
    avg_test = sum(r['test_pnl'] for r in results) / len(results)

    return {
        'folds': results,
        'profitable_folds': profitable,
        'total_folds': n_folds,
        'avg_test_pnl': avg_test,
        'verdict': ('STERK' if profitable >= 2 else
                    'ZWAK' if profitable >= 1 else 'GEFAALD'),
    }


# ============================================================
# SWEEP CONFIG GENERATOR
# ============================================================

def generate_configs(quick=False):
    """Genereer alle V8 configuraties voor de sweep."""
    configs = []

    if quick:
        # Snelle sweep: kernparameters
        stop_pcts = [5.0, 8.0, 10.0, 15.0]
        time_maxes = [10]
        rsi_targets = [45]
        quality_gates = [False]
        combo_exits = [False]
        pos_sizes = [2000]
    else:
        # Volledige sweep
        stop_pcts = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.0, 15.0]
        time_maxes = [8, 10, 12]
        rsi_targets = [43, 45, 47]
        quality_gates = [False, 0.4, 0.5]
        combo_exits = [False, True]
        pos_sizes = [1000, 2000]

    # Also add NO stop (pure time-based)
    stop_pcts_full = [0] + list(stop_pcts)  # 0 = no fixed stop

    for stop_pct in stop_pcts_full:
        for tm in time_maxes:
            for rsi_t in rsi_targets:
                for qg in quality_gates:
                    for combo in combo_exits:
                        for ps in pos_sizes:
                            # Skip incompatible combos
                            if combo and rsi_t != 45:
                                continue  # Combo has own RSI target

                            cfg = {
                                'rsi_max': 40,
                                'vol_spike': True, 'vol_spike_mult': 2.0,
                                'vol_confirm': True, 'vol_confirm_mult': 1.0,
                                'time_max': True, 'time_max_bars': tm,
                            }

                            if stop_pct > 0:
                                cfg['fixed_stop_pct'] = stop_pct
                            else:
                                cfg['fixed_stop_pct'] = 99.0  # effectively disabled

                            if combo:
                                cfg['combo_exit'] = True
                                cfg['combo_rsi_target'] = 45
                                cfg['combo_rsi_min_bars'] = 2
                                cfg['combo_fallback_pct'] = 2.0
                                cfg['combo_fallback_bars'] = 5
                            else:
                                cfg['rsi_recovery'] = True
                                cfg['rsi_rec_target'] = rsi_t
                                cfg['rsi_rec_min_bars'] = 2

                            if qg is not False:
                                cfg['quality_gate'] = True
                                cfg['min_quality'] = qg

                            name_parts = []
                            if stop_pct == 0:
                                name_parts.append("NoStop")
                            else:
                                name_parts.append(f"FS{stop_pct:.0f}%")
                            name_parts.append(f"TM{tm}")
                            if combo:
                                name_parts.append("Combo")
                            else:
                                name_parts.append(f"RSI{rsi_t}")
                            if qg is not False:
                                name_parts.append(f"QG{qg}")
                            if ps != 2000:
                                name_parts.append(f"${ps}")

                            name = " ".join(name_parts)

                            configs.append({
                                'name': name,
                                'cfg': cfg,
                                'pos_size': ps,
                            })

    return configs


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='V8 Mega Sweep — Fixed Stop Optimalisatie')
    parser.add_argument('--quick', action='store_true',
                        help='Snelle sweep met minder combinaties')
    parser.add_argument('--top', type=int, default=20,
                        help='Toon top N resultaten')
    parser.add_argument('--validate-top', type=int, default=5,
                        help='Walk-forward valideer top N')
    parser.add_argument('--save', action='store_true',
                        help='Sla resultaten op als JSON')
    args = parser.parse_args()

    logger.info("V8 MEGA SWEEP — Fixed Stop Parameter Optimalisatie")
    logger.info("=" * 80)

    # Load data
    if not CACHE_FILE.exists():
        logger.error(f"Cache niet gevonden: {CACHE_FILE}")
        sys.exit(1)
    with open(CACHE_FILE) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith('_')])
    logger.info(f"Geladen: {len(coins)} coins")

    # Generate configs
    configs = generate_configs(quick=args.quick)
    logger.info(f"Configs te testen: {len(configs)}")
    logger.info("")

    # === PHASE 1: Full Backtest Sweep ===
    logger.info("FASE 1: VOLLEDIGE BACKTEST SWEEP")
    logger.info("=" * 80)

    results = []
    for i, config in enumerate(configs):
        if (i + 1) % 25 == 0 or i == 0:
            logger.info(f"  Testing {i+1}/{len(configs)}...")

        r = run_backtest(data, coins, config['cfg'],
                         pos_size=config['pos_size'],
                         label=config['name'])
        r['config'] = config
        results.append(r)

    # Sort by EV no top (primary), then by PF (secondary)
    results.sort(key=lambda x: (x['ev_no_top'], x['pf']), reverse=True)

    # === PHASE 2: Results ===
    logger.info(f"\n{'='*140}")
    logger.info(f"TOP {args.top} CONFIGS — Gesorteerd op EV zonder top trade")
    logger.info(f"{'='*140}")
    logger.info(
        f"{'#':>3} | {'Config':<30} | {'Tr':>3} | {'WR%':>5} | "
        f"{'P&L':>8} | {'PF':>5} | {'DD%':>5} | {'AvgW':>7} | {'AvgL':>7} | "
        f"{'NoTop$':>8} | {'EV/t':>6} | {'FS#':>3} | {'Herf':>5}"
    )
    logger.info(f"{'-'*140}")

    for i, r in enumerate(results[:args.top]):
        pf_str = f"{r['pf']:5.2f}" if r['pf'] < 100 else "  INF"
        logger.info(
            f"{i+1:3d} | {r['label']:<30} | {r['trades']:3d} | {r['wr']:5.1f} | "
            f"${r['pnl']:+7.0f} | {pf_str} | {r['dd']:5.1f} | "
            f"${r['avg_w']:+6.0f} | ${r['avg_l']:+6.0f} | "
            f"${r['pnl_no_top']:+7.0f} | ${r['ev_no_top']:+5.0f} | "
            f"{r['fixed_stops']:3d} | {r['herf']:5.3f}"
        )

    # Show the worst too
    logger.info(f"\n--- BOTTOM 5 (slechtste configs) ---")
    for r in results[-5:]:
        pf_str = f"{r['pf']:5.2f}" if r['pf'] < 100 else "  INF"
        logger.info(
            f"    | {r['label']:<30} | {r['trades']:3d} | {r['wr']:5.1f} | "
            f"${r['pnl']:+7.0f} | {pf_str} | {r['dd']:5.1f} | "
            f"${r['pnl_no_top']:+7.0f} | ${r['ev_no_top']:+5.0f}"
        )

    # === PHASE 3: Walk-Forward Validation ===
    n_validate = min(args.validate_top, len(results))
    logger.info(f"\n{'='*80}")
    logger.info(f"FASE 2: WALK-FORWARD VALIDATIE (top {n_validate})")
    logger.info(f"{'='*80}")

    wf_results = []
    for i, r in enumerate(results[:n_validate]):
        config = r['config']
        logger.info(f"\n--- WF #{i+1}: {config['name']} ---")

        wf = walk_forward(data, coins, config['cfg'],
                          pos_size=config['pos_size'])

        logger.info(f"  Verdict: {wf['verdict']}")
        logger.info(f"  Profitable Folds: {wf['profitable_folds']}/{wf['total_folds']}")
        logger.info(f"  Avg Test P&L: ${wf['avg_test_pnl']:+.0f}")
        for fold in wf['folds']:
            logger.info(
                f"  Fold {fold['fold']}: "
                f"Train ${fold['train_pnl']:+.0f} ({fold['train_trades']}tr) | "
                f"Test ${fold['test_pnl']:+.0f} ({fold['test_trades']}tr) | "
                f"WR {fold['test_wr']:.0f}% | "
                f"EV/t ${fold['test_ev_no_top']:+.1f}"
            )

        wf_results.append({
            'config': config,
            'backtest': {k: v for k, v in r.items()
                        if k not in ('trade_list', 'config')},
            'walk_forward': wf,
        })

    # === PHASE 4: Final Ranking ===
    logger.info(f"\n{'='*80}")
    logger.info(f"FINALE RANKING — Walk-Forward Validated")
    logger.info(f"{'='*80}")

    # Score: WF folds * 30 + EV_no_top * 5 + WR * 0.5 - DD * 0.3
    for wfr in wf_results:
        wf = wfr['walk_forward']
        bt = wfr['backtest']
        score = (wf['profitable_folds'] * 30
                + bt['ev_no_top'] * 5
                + bt['wr'] * 0.5
                - bt['dd'] * 0.3
                + (1 if bt['pnl_no_top'] > 0 else -10))
        wfr['final_score'] = score

    wf_results.sort(key=lambda x: x['final_score'], reverse=True)

    for i, wfr in enumerate(wf_results):
        wf = wfr['walk_forward']
        bt = wfr['backtest']
        status = "✅" if wf['verdict'] == 'STERK' else ("⚠️" if wf['verdict'] == 'ZWAK' else "❌")
        pos_ev = "✅" if bt['ev_no_top'] > 0 else "❌"

        logger.info(
            f"  #{i+1} {status} {wfr['config']['name']:<30} | "
            f"WF: {wf['profitable_folds']}/{wf['total_folds']} | "
            f"EV/t: ${bt['ev_no_top']:+.1f} {pos_ev} | "
            f"P&L: ${bt['pnl']:+.0f} | NoTop: ${bt['pnl_no_top']:+.0f} | "
            f"Score: {wfr['final_score']:.1f}"
        )

    # === Best candidate ===
    if wf_results:
        best = wf_results[0]
        logger.info(f"\n{'='*80}")
        logger.info(f"🏆 BESTE KANDIDAAT: {best['config']['name']}")
        logger.info(f"{'='*80}")
        bt = best['backtest']
        wf = best['walk_forward']
        logger.info(f"  Walk-Forward: {wf['verdict']} ({wf['profitable_folds']}/{wf['total_folds']} folds)")
        logger.info(f"  P&L: ${bt['pnl']:+.0f} | Zonder Top: ${bt['pnl_no_top']:+.0f}")
        logger.info(f"  EV/trade (geen top): ${bt['ev_no_top']:+.1f}")
        logger.info(f"  WR: {bt['wr']:.1f}% | PF: {bt['pf']:.2f} | DD: {bt['dd']:.1f}%")
        logger.info(f"  Fixed Stops: {bt['fixed_stops']} | Herf: {bt['herf']:.3f}")
        logger.info(f"  Config: {json.dumps(best['config']['cfg'], indent=4)}")

    # Save
    if args.save:
        report = {
            'timestamp': datetime.now().isoformat(),
            'coins': len(coins),
            'configs_tested': len(configs),
            'top_results': [],
        }
        for wfr in wf_results:
            entry = {
                'config': wfr['config'],
                'backtest': wfr['backtest'],
                'walk_forward': wfr['walk_forward'],
                'final_score': wfr['final_score'],
            }
            report['top_results'].append(entry)

        # Add all results summary (without trade lists)
        report['all_results_summary'] = [
            {
                'name': r['label'],
                'trades': r['trades'], 'wr': r['wr'],
                'pnl': r['pnl'], 'pf': r['pf'] if r['pf'] < 1000 else 999,
                'dd': r['dd'],
                'pnl_no_top': r['pnl_no_top'],
                'ev_no_top': r['ev_no_top'],
                'fixed_stops': r['fixed_stops'],
            }
            for r in results[:50]
        ]

        report_file = BASE_DIR / 'v8_sweep_report.json'

        def clean(obj):
            if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
                return str(obj)
            if isinstance(obj, dict):
                return {k: clean(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [clean(v) for v in obj]
            return obj

        with open(report_file, 'w') as f:
            json.dump(clean(report), f, indent=2)
        logger.info(f"\nRapport opgeslagen: {report_file}")

    logger.info(f"\nKlaar! {len(configs)} configs getest, top {n_validate} gevalideerd.")


if __name__ == '__main__':
    main()

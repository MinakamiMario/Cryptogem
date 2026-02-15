#!/usr/bin/env python3
"""
AGENT TEAM V3 — Wetenschappelijk Multi-Agent Optimizer (Gestroomlijnd)
=====================================================================
Architectuur:
  Blackboard    — gedeeld geheugen + event bus
  Pipeline      — Audit → Scout → MetaLearn → Validate → Promote

4 Agents:
  Auditor       — sanity, deterministic replay, outlier dependency, causal check
  Scout         — 2/3-param grids + exit families (merged Combiner+ExitArchitect)
  Validator     — walk-forward (leakage-safe) + friction stress + coin MC + window dist
  Orchestrator  — budget allocatie, breakthrough shifting, promotion gates

Verbeteringen vs v2:
  ✅ Runtime-based budget (seconds, niet config-count)
  ✅ Adaptive Scout (start klein, expand in belovende regio's)
  ✅ Friction stress test (fee × [1.0, 1.5, 2.0])
  ✅ Window distribution (bars-based, niet datum-based)
  ✅ Deterministic replay check
  ✅ Multi-point causal check (20/40/60/80%)
  ✅ Outlier dependency met edge cases + coin concentratie
  ✅ 7-gate promotion pipeline
  ✅ Budget reallocation bij EXIT_TYPE_BREAKTHROUGH

v3.1 Verbeteringen:
  ✅ Champion persistentie (champion.json) tussen runs
  ✅ Scout Ablation Mode (Phase 0: 1-knob sensitivity analyse)
  ✅ Multi-Run support (--runs N met coin subsampling)

Gebruik:
    python agent_team_v3.py                 # Volledige run (~4 uur)
    python agent_team_v3.py --quick         # Snelle test (~5-10 min)
    python agent_team_v3.py --hours 8       # Max runtime
    python agent_team_v3.py --quick --runs 3  # 3 runs met 90% coin subsampling
"""
import sys
import json
import time
import random
import math
import hashlib
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from copy import deepcopy
from datetime import datetime
from typing import Optional

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger
from telegram_notifier import TelegramNotifier

# Globale Telegram notifier (lazy init in orchestrator)
TG = None


# ============================================================
# SECTION 1: CONSTANTS + CONFIG
# ============================================================
CACHE_FILE = BASE_DIR / 'candle_cache_532.json'
BLACKBOARD_FILE = BASE_DIR / 'agent_team_v3_blackboard.json'
RESULTS_FILE = BASE_DIR / 'agent_team_v3_results.json'
CHAMPION_FILE = BASE_DIR / 'champion.json'
KRAKEN_FEE = 0.0026
DC_PERIOD = 20
BB_PERIOD = 20
BB_DEV = 2.0
RSI_PERIOD = 14
ATR_PERIOD = 14
START_BAR = 50
VOL_MIN_PCT = 0.5
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8
INITIAL_CAPITAL = 2000

# --- Score gates (harde drempels) ---
GATE_MIN_TRADES = 20
GATE_MAX_DD = 50.0
GATE_MIN_WF_RATIO = 0.5       # minstens helft van folds winstgevend
GATE_NOTOP_PNL_MIN = -200     # zonder beste trade niet meer dan $200 verlies

# --- Promotion gates ---
PROMO_WF_MIN = 0.6             # WF ≥ 3/5
PROMO_FRICTION_2X_MIN = 0      # P&L bij 2x fees > 0
PROMO_OUTLIER_MAX = 0.8        # top1 trade < 80% van totaal
PROMO_COIN_CONC_MAX = 0.8     # max coin < 80% van totaal
PROMO_MC_P5_MIN = INITIAL_CAPITAL * 0.5  # MC P5 > 50% startkapitaal
PROMO_CLASS_A_MIN = 0.5        # minstens 50% P&L uit klasse A exits
PROMO_WORST_WINDOW_MIN = -300  # worst window niet slechter dan -$300

# --- Bekende baselines ---
BASELINE_CFG = {
    'exit_type': 'trail', 'rsi_max': 40, 'atr_mult': 2.0,
    'vol_spike_mult': 3.0, 'vol_confirm': True,
    'breakeven': True, 'be_trigger': 3.0,
    'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
    'max_stop_pct': 15.0, 'max_pos': 1,
}
BASELINE_EXPECTED_TRADES = 39
BASELINE_EXPECTED_PNL_MIN = 3500

BEST_KNOWN = {
    'exit_type': 'trail', 'rsi_max': 42, 'atr_mult': 2.0,
    'vol_spike_mult': 3.0, 'vol_confirm': True,
    'breakeven': True, 'be_trigger': 2.0,
    'time_max_bars': 6, 'rsi_recovery': True, 'rsi_rec_target': 45,
    'max_stop_pct': 12.0, 'max_pos': 1,
}


# --- Champion persistentie ---
def save_champion(entry, run_id=None):
    """Bewaar champion config + metrics. Overschrijft alleen als score hoger."""
    champion = {
        'cfg': normalize_cfg(dict(entry['cfg'])),
        'score': entry['score'],
        'label': entry.get('label', 'unknown'),
        'backtest': entry.get('backtest', {}),
        'mc_block': entry.get('mc_block', {}),
        'notop_pnl': entry.get('notop_pnl', 0),
        'class_a_ratio': entry.get('class_a_ratio', 0),
        'hash': entry.get('hash', ''),
        'promoted': False,
        'run_id': run_id or datetime.now().strftime('%Y%m%d_%H%M%S'),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    existing = load_champion()
    if existing and existing.get('score', 0) >= champion['score']:
        return False
    with open(CHAMPION_FILE, 'w') as f:
        json.dump(champion, f, indent=2, default=str)
    return True


def normalize_cfg(cfg):
    """Unify legacy key aliases → canonical keys.

    tm_bars → time_max_bars (canonical). Oude configs blijven werken.
    """
    if 'tm_bars' in cfg and 'time_max_bars' not in cfg:
        cfg['time_max_bars'] = cfg.pop('tm_bars')
    elif 'tm_bars' in cfg and 'time_max_bars' in cfg:
        cfg.pop('tm_bars')  # canonical wint
    return cfg


def load_champion():
    """Laad champion uit champion.json. Retourneert None als niet gevonden."""
    try:
        with open(CHAMPION_FILE) as f:
            champ = json.load(f)
        if champ and 'cfg' in champ:
            champ['cfg'] = normalize_cfg(champ['cfg'])
        return champ
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# --- Exit-type parameter mapping (authoritative source) ---
# Keys that each exit_type actually reads during backtest.
# Entry params are shared across all exit types.
PARAMS_BY_EXIT = {
    'tp_sl': {
        'entry': ['rsi_max', 'vol_spike_mult'],
        'exit':  ['tp_pct', 'sl_pct', 'time_max_bars'],
    },
    'trail': {
        'entry': ['rsi_max', 'vol_spike_mult'],
        'exit':  ['atr_mult', 'be_trigger', 'max_stop_pct', 'time_max_bars',
                   'rsi_rec_target'],
    },
    'hybrid_notrl': {
        'entry': ['rsi_max', 'vol_spike_mult'],
        'exit':  ['max_stop_pct', 'time_max_bars', 'rsi_rec_target'],
    },
}
# Structural params (niet varieerbaar in grid, maar wel gelezen)
STRUCTURAL_KEYS = {'exit_type', 'max_pos', 'vol_confirm', 'rsi_recovery', 'breakeven'}


def used_keys_for(exit_type):
    """Return set of cfg keys that this exit_type actually reads."""
    spec = PARAMS_BY_EXIT.get(exit_type, PARAMS_BY_EXIT['trail'])
    return set(spec['entry'] + spec['exit']) | STRUCTURAL_KEYS


def warn_unused_params(cfg, context=''):
    """Log warning als cfg keys bevat die niet gelezen worden door exit_type.

    Returns list of unused keys (empty = OK).
    """
    exit_type = cfg.get('exit_type', 'trail')
    used = used_keys_for(exit_type)
    unused = [k for k in cfg if k not in used]
    if unused:
        print(f"  ⚠️  GUARDRAIL{' ('+context+')' if context else ''}: "
              f"exit_type={exit_type} ignores cfg keys: {sorted(unused)}")
    return unused


# ============================================================
# SECTION 2: CONFIG HASHING + PRECOMPUTE + ENTRY
# ============================================================
def cfg_hash(cfg):
    """Deterministic hash van een config dict."""
    s = json.dumps(cfg, sort_keys=True)
    return hashlib.md5(s.encode()).hexdigest()[:12]


def precompute_all(data, coins, end_bar=None):
    """Precompute indicators. end_bar = exclusive upper bound (causal)."""
    indicators = {}
    for pair in coins:
        if pair not in data:
            continue
        candles = data[pair]
        n = len(candles)
        if end_bar is not None:
            n = min(n, end_bar)
        closes = [c['close'] for c in candles[:n]]
        highs = [c['high'] for c in candles[:n]]
        lows = [c['low'] for c in candles[:n]]
        volumes = [c.get('volume', 0) for c in candles[:n]]
        ind = {
            'closes': closes, 'highs': highs, 'lows': lows,
            'volumes': volumes, 'n': n,
            'rsi': [None]*n, 'atr': [None]*n,
            'dc_prev_low': [None]*n, 'dc_mid': [None]*n,
            'bb_mid': [None]*n, 'bb_lower': [None]*n,
            'vol_avg': [None]*n,
        }
        min_bars = max(DC_PERIOD, BB_PERIOD, RSI_PERIOD, ATR_PERIOD) + 5
        for bar in range(min_bars, n):
            wc = closes[:bar+1]
            wh = highs[:bar+1]
            wl = lows[:bar+1]
            wv = volumes[:bar+1]
            rsi = calc_rsi(wc, RSI_PERIOD)
            atr = calc_atr(wh, wl, wc, ATR_PERIOD)
            _, prev_low, _ = calc_donchian(wh[:-1], wl[:-1], DC_PERIOD)
            _, _, mid_ch = calc_donchian(wh, wl, DC_PERIOD)
            bb_m, _, bb_l = calc_bollinger(wc, BB_PERIOD, BB_DEV)
            if any(v is None for v in [rsi, atr, prev_low, mid_ch, bb_m, bb_l]):
                continue
            ind['rsi'][bar] = rsi
            ind['atr'][bar] = atr
            ind['dc_prev_low'][bar] = prev_low
            ind['dc_mid'][bar] = mid_ch
            ind['bb_mid'][bar] = bb_m
            ind['bb_lower'][bar] = bb_l
            vol_slice = wv[-20:]
            ind['vol_avg'][bar] = sum(vol_slice)/len(vol_slice) if vol_slice else 0
        indicators[pair] = ind
    return indicators


def check_entry_at_bar(ind, bar, cfg):
    if ind['rsi'][bar] is None:
        return False, 0
    rsi = ind['rsi'][bar]
    rsi_max = cfg.get('rsi_max', 40)
    close = ind['closes'][bar]
    low = ind['lows'][bar]
    prev_close = ind['closes'][bar-1] if bar > 0 else close
    cur_vol = ind['volumes'][bar]
    prev_vol = ind['volumes'][bar-1] if bar > 0 else 0
    vol_avg = ind['vol_avg'][bar]
    vol_spike_mult = cfg.get('vol_spike_mult', 2.0)
    use_vol_confirm = cfg.get('vol_confirm', True)
    if vol_avg and vol_avg > 0 and cur_vol < vol_avg * VOL_MIN_PCT:
        return False, 0
    dc_sig = (low <= ind['dc_prev_low'][bar] and rsi < rsi_max and close > prev_close)
    bb_sig = (close <= ind['bb_lower'][bar] and rsi < rsi_max and close > prev_close)
    if not (dc_sig and bb_sig):
        return False, 0
    if vol_avg and vol_avg > 0 and cur_vol < vol_avg * vol_spike_mult:
        return False, 0
    if use_vol_confirm and prev_vol > 0:
        if cur_vol / prev_vol < 1.0:
            return False, 0
    vol_ratio = cur_vol / vol_avg if vol_avg and vol_avg > 0 else 0
    return True, vol_ratio


# ============================================================
# SECTION 3: BACKTEST ENGINE (v2 + fee_override)
# ============================================================
@dataclass
class Pos:
    pair: str
    entry_price: float
    entry_bar: int
    size_usd: float
    stop_price: float = 0.0
    highest_price: float = 0.0


def run_backtest(indicators, coins, cfg, start_bar=START_BAR, end_bar=None,
                 early_stop_dd=None, early_stop_min_trades=None,
                 fee_override=None):
    """
    Realistic equity backtest met optionele early stopping.
    fee_override: overschrijf KRAKEN_FEE (voor friction stress test).
    """
    cfg = normalize_cfg(dict(cfg))  # normalize + copy (geen mutatie van caller)
    fee = fee_override if fee_override is not None else KRAKEN_FEE
    exit_type = cfg['exit_type']
    max_pos = cfg.get('max_pos', 1)
    coin_list = [c for c in coins if c in indicators]
    max_bars = max(indicators[p]['n'] for p in coin_list) if coin_list else 0
    if end_bar is not None:
        max_bars = min(max_bars, end_bar)

    positions = {}
    trades = []
    equity = float(INITIAL_CAPITAL)
    peak_eq = equity
    max_dd = 0
    broke = False
    early_stopped = False
    last_exit_bar = {p: -999 for p in coin_list}
    last_exit_was_stop = {p: False for p in coin_list}

    for bar in range(start_bar, max_bars):
        if equity < 0:
            broke = True
            break

        # --- Early stopping checks ---
        if early_stop_dd and max_dd > early_stop_dd:
            early_stopped = True
            break
        if early_stop_min_trades and len(trades) >= early_stop_min_trades:
            wins_so_far = sum(1 for t in trades if t['pnl'] > 0)
            losses_so_far = len(trades) - wins_so_far
            if losses_so_far > 0:
                tw = sum(t['pnl'] for t in trades if t['pnl'] > 0)
                tl = abs(sum(t['pnl'] for t in trades if t['pnl'] <= 0))
                if tl > 0 and tw / tl < 0.8:
                    early_stopped = True
                    break

        sells = []
        for pair in list(positions.keys()):
            pos = positions[pair]
            ind = indicators[pair]
            if bar >= ind['n'] or ind['rsi'][bar] is None:
                continue
            entry_price = pos.entry_price
            bars_in = bar - pos.entry_bar
            close = ind['closes'][bar]
            low = ind['lows'][bar]
            high = ind['highs'][bar]
            rsi = ind['rsi'][bar]
            atr = ind['atr'][bar]
            exit_price = None
            reason = None

            if exit_type == 'tp_sl':
                tp_pct = cfg.get('tp_pct', 7.0)
                sl_pct = cfg.get('sl_pct', 15.0)
                tm_bars = cfg.get('time_max_bars', 15)
                sl_p = entry_price * (1 - sl_pct/100)
                tp_p = entry_price * (1 + tp_pct/100)
                if low <= sl_p:
                    exit_price, reason = sl_p, 'FIXED STOP'
                elif high >= tp_p:
                    exit_price, reason = tp_p, 'PROFIT TARGET'
                elif bars_in >= tm_bars:
                    exit_price, reason = close, 'TIME MAX'

            elif exit_type == 'trail':
                atr_mult = cfg.get('atr_mult', 2.0)
                max_stop_pct = cfg.get('max_stop_pct', 15.0)
                tm_bars = cfg.get('time_max_bars', 10)
                if close > pos.highest_price:
                    pos.highest_price = close
                new_stop = pos.highest_price - atr * atr_mult
                hard_stop = entry_price * (1 - max_stop_pct/100)
                if new_stop < hard_stop:
                    new_stop = hard_stop
                if cfg.get('breakeven', False):
                    pnl_pct = (close - entry_price) / entry_price * 100
                    if pnl_pct >= cfg.get('be_trigger', 3.0):
                        be_level = entry_price * (1 + fee * 2)
                        if new_stop < be_level:
                            new_stop = be_level
                if new_stop > pos.stop_price:
                    pos.stop_price = new_stop
                if close < hard_stop:
                    exit_price, reason = close, 'HARD STOP'
                elif tm_bars < 999 and bars_in >= tm_bars:
                    exit_price, reason = close, 'TIME MAX'
                elif (cfg.get('rsi_recovery', False)
                      and bars_in >= 2
                      and rsi >= cfg.get('rsi_rec_target', 45)):
                    exit_price, reason = close, 'RSI RECOVERY'
                elif close >= ind['dc_mid'][bar]:
                    exit_price, reason = close, 'DC TARGET'
                elif close >= ind['bb_mid'][bar]:
                    exit_price, reason = close, 'BB TARGET'
                elif close < pos.stop_price:
                    exit_price, reason = close, 'TRAIL STOP'

            elif exit_type == 'hybrid_notrl':
                max_stop_pct = cfg.get('max_stop_pct', 20.0)
                hard_stop = entry_price * (1 - max_stop_pct/100)
                tm_bars = cfg.get('time_max_bars', 15)
                if low <= hard_stop:
                    exit_price, reason = hard_stop, 'FIXED STOP'
                elif bars_in >= tm_bars:
                    exit_price, reason = close, 'TIME MAX'
                elif (cfg.get('rsi_recovery', False)
                      and bars_in >= 2
                      and rsi >= cfg.get('rsi_rec_target', 45)):
                    exit_price, reason = close, 'RSI RECOVERY'
                elif close >= ind['dc_mid'][bar]:
                    exit_price, reason = close, 'DC TARGET'
                elif close >= ind['bb_mid'][bar]:
                    exit_price, reason = close, 'BB TARGET'

            if exit_price is not None:
                sells.append((pair, exit_price, reason, pos))

        for pair, exit_price, reason, pos in sells:
            gross = (exit_price - pos.entry_price) / pos.entry_price * pos.size_usd
            fees = pos.size_usd * fee + (pos.size_usd + gross) * fee
            net = gross - fees
            equity += pos.size_usd + net
            last_exit_bar[pair] = bar
            last_exit_was_stop[pair] = 'STOP' in reason
            trades.append({
                'pair': pair, 'entry': pos.entry_price, 'exit': exit_price,
                'pnl': net, 'pnl_pct': net / pos.size_usd * 100,
                'reason': reason, 'bars': bar - pos.entry_bar,
                'entry_bar': pos.entry_bar, 'exit_bar': bar,
                'size': pos.size_usd, 'equity_after': equity,
            })
            del positions[pair]

        buys = []
        for pair in coin_list:
            if pair in positions:
                continue
            ind = indicators[pair]
            if bar >= ind['n']:
                continue
            cd = COOLDOWN_AFTER_STOP if last_exit_was_stop.get(pair, False) else COOLDOWN_BARS
            if (bar - last_exit_bar.get(pair, -999)) < cd:
                continue
            ok, vol_ratio = check_entry_at_bar(ind, bar, cfg)
            if ok:
                buys.append((pair, vol_ratio))

        invested = sum(p.size_usd for p in positions.values())
        available = equity - invested
        if len(positions) < max_pos and buys and available > 10:
            buys.sort(key=lambda x: x[1], reverse=True)
            slots = max_pos - len(positions)
            size_per_pos = available / slots
            for pair, vol_ratio in buys:
                if len(positions) >= max_pos:
                    break
                if size_per_pos < 10:
                    break
                ind = indicators[pair]
                ep = ind['closes'][bar]
                atr_val = ind['atr'][bar] or 0
                if exit_type in ('trail',):
                    stop = ep - atr_val * cfg.get('atr_mult', 2.0)
                    hard = ep * (1 - cfg.get('max_stop_pct', 15.0)/100)
                    if stop < hard:
                        stop = hard
                else:
                    stop = ep * (1 - cfg.get('sl_pct', cfg.get('max_stop_pct', 15.0))/100)
                equity -= size_per_pos
                positions[pair] = Pos(pair=pair, entry_price=ep, entry_bar=bar,
                                      size_usd=size_per_pos, stop_price=stop, highest_price=ep)

        total_value = equity
        for pair, pos in positions.items():
            ind = indicators[pair]
            if bar < ind['n']:
                cur_price = ind['closes'][bar]
                unrealized = (cur_price - pos.entry_price) / pos.entry_price * pos.size_usd
                total_value += pos.size_usd + unrealized
            else:
                total_value += pos.size_usd
        if total_value > peak_eq:
            peak_eq = total_value
        dd = (peak_eq - total_value) / peak_eq * 100 if peak_eq > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Close remaining positions
    for pair, pos in list(positions.items()):
        ind = indicators[pair]
        last_idx = min(ind['n']-1, max_bars-1)
        lp = ind['closes'][last_idx]
        gross = (lp - pos.entry_price) / pos.entry_price * pos.size_usd
        fees = pos.size_usd * fee + (pos.size_usd + gross) * fee
        net = gross - fees
        equity += pos.size_usd + net
        trades.append({
            'pair': pair, 'entry': pos.entry_price, 'exit': lp,
            'pnl': net, 'pnl_pct': net / pos.size_usd * 100,
            'reason': 'END', 'bars': max_bars - pos.entry_bar,
            'entry_bar': pos.entry_bar, 'exit_bar': max_bars,
            'size': pos.size_usd, 'equity_after': equity,
        })

    final_equity = equity
    total_pnl = final_equity - INITIAL_CAPITAL
    n = len(trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins)/n*100 if n else 0
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else float('inf')

    # Exit class analysis
    exit_classes = {'A': {}, 'B': {}}
    class_a_reasons = {'RSI RECOVERY', 'DC TARGET', 'BB TARGET', 'PROFIT TARGET'}
    for t in trades:
        cls = 'A' if t['reason'] in class_a_reasons else 'B'
        r = t['reason']
        if r not in exit_classes[cls]:
            exit_classes[cls][r] = {'count': 0, 'pnl': 0, 'wins': 0}
        exit_classes[cls][r]['count'] += 1
        exit_classes[cls][r]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            exit_classes[cls][r]['wins'] += 1

    return {
        'trades': n, 'wr': wr, 'pnl': total_pnl,
        'final_equity': final_equity,
        'pf': pf, 'dd': max_dd, 'broke': broke,
        'early_stopped': early_stopped,
        'trade_list': trades,
        'exit_classes': exit_classes,
    }


# ============================================================
# SECTION 4: MONTE CARLO — Block Bootstrap + Coin Subsampling
# ============================================================

def monte_carlo_block(trade_pnl_pcts, n_sims=3000, block_size=5, seed=42):
    """Block bootstrap MC: sample blokken van trades."""
    rng = random.Random(seed)
    n_trades = len(trade_pnl_pcts)
    if n_trades < 5:
        return _empty_mc(n_trades)

    blocks = []
    for i in range(0, n_trades, block_size):
        blocks.append(trade_pnl_pcts[i:i+block_size])
    n_blocks = len(blocks)
    target_trades = n_trades

    final_equities = []
    broke_count = 0

    for _ in range(n_sims):
        sampled = []
        while len(sampled) < target_trades:
            block = rng.choice(blocks)
            sampled.extend(block)
        sampled = sampled[:target_trades]

        eq = float(INITIAL_CAPITAL)
        for pnl_pct in sampled:
            if eq <= 0:
                broke_count += 1
                eq = 0
                break
            eq += eq * (pnl_pct / 100)
        final_equities.append(eq)

    return _calc_mc_stats(final_equities, n_sims, n_trades, broke_count)


def monte_carlo_coin_subsample(indicators, coins, cfg, n_sims=500, sample_pct=0.7, seed=42):
    """MC op coin-subsets: random 70% van coins."""
    rng = random.Random(seed)
    n_coins = len(coins)
    sample_size = int(n_coins * sample_pct)
    final_equities = []
    broke_count = 0

    for i in range(n_sims):
        subset = rng.sample(coins, sample_size)
        bt = run_backtest(indicators, subset, cfg)
        final_equities.append(bt['final_equity'])
        if bt['broke']:
            broke_count += 1

    return _calc_mc_stats(final_equities, n_sims, sample_size, broke_count)


def _empty_mc(n_trades):
    return {'win_pct': 0, 'median_equity': INITIAL_CAPITAL,
            'mean_equity': INITIAL_CAPITAL, 'p5': INITIAL_CAPITAL,
            'p95': INITIAL_CAPITAL, 'cvar95': INITIAL_CAPITAL,
            'broke_pct': 0, 'n_sims': 0, 'n_trades': n_trades}


def _calc_mc_stats(final_equities, n_sims, n_trades, broke_count):
    final_equities.sort()
    n = len(final_equities)
    winners = sum(1 for e in final_equities if e > INITIAL_CAPITAL)
    worst_5pct = final_equities[:max(1, int(n * 0.05))]
    cvar95 = sum(worst_5pct) / len(worst_5pct)
    return {
        'win_pct': winners / n * 100,
        'median_equity': final_equities[n // 2],
        'mean_equity': sum(final_equities) / n,
        'p5': final_equities[int(n * 0.05)],
        'p10': final_equities[int(n * 0.10)],
        'p95': final_equities[int(n * 0.95)],
        'cvar95': cvar95,
        'broke_pct': broke_count / n * 100,
        'n_sims': n_sims, 'n_trades': n_trades,
    }


# ============================================================
# SECTION 5: SCORING + GATES
# ============================================================

def evaluate(indicators, coins, cfg, label, bb, n_sims=3000):
    """Volledige evaluatie met gates + Pareto scoring."""
    bt = run_backtest(indicators, coins, cfg)

    # --- Hard gates ---
    if bt['trades'] < GATE_MIN_TRADES:
        return None
    if bt['dd'] > GATE_MAX_DD:
        return None

    pnl_pcts = [t['pnl_pct'] for t in bt['trade_list']]

    # NoTop check
    if len(pnl_pcts) > 1:
        sorted_trades = sorted(bt['trade_list'], key=lambda t: t['pnl'], reverse=True)
        notop_dollar = bt['pnl'] - sorted_trades[0]['pnl']
    else:
        notop_dollar = 0

    if notop_dollar < GATE_NOTOP_PNL_MIN:
        return None

    # --- Block bootstrap MC ---
    mc_block = monte_carlo_block(pnl_pcts, n_sims=n_sims, block_size=5)

    # --- Pareto score (multi-objective) ---
    median_s = min(100, max(0, (mc_block['median_equity'] - 1000) / 80))
    p5_s = min(100, max(0, (mc_block['p5'] - 500) / 40))
    cvar_s = min(100, max(0, (mc_block['cvar95'] - 500) / 30))
    notop_s = min(100, max(0, (notop_dollar + 500) / 30))
    trade_s = min(100, bt['trades'] / 0.6)
    dd_s = max(0, 100 - bt['dd'] * 2.5)

    # Klasse A dominantie bonus (positive profit attribution)
    class_a_profit = sum(max(0, v['pnl']) for v in bt['exit_classes'].get('A', {}).values())
    total_profit_all = sum(max(0, t['pnl']) for t in bt['trade_list'])
    class_a_ratio = min(1.0, class_a_profit / max(1e-9, total_profit_all))
    class_a_bonus = min(10, max(0, (class_a_ratio - 0.5) * 20))

    score = (
        median_s  * 0.20 +
        p5_s      * 0.15 +
        cvar_s    * 0.10 +
        notop_s   * 0.20 +
        trade_s   * 0.10 +
        dd_s      * 0.15 +
        class_a_bonus * 0.10
    )

    h = cfg_hash(cfg)
    entry = {
        'hash': h,
        'label': label,
        'cfg': cfg,
        'score': round(score, 3),
        'backtest': {
            'trades': bt['trades'], 'wr': round(bt['wr'], 1),
            'pnl': round(bt['pnl'], 2), 'final_equity': round(bt['final_equity'], 2),
            'pf': round(bt['pf'], 2) if bt['pf'] < 999 else 'INF',
            'dd': round(bt['dd'], 1),
        },
        'mc_block': {
            'win_pct': round(mc_block['win_pct'], 1),
            'median_eq': round(mc_block['median_equity'], 0),
            'p5': round(mc_block['p5'], 0),
            'p10': round(mc_block.get('p10', mc_block['p5']), 0),
            'p95': round(mc_block['p95'], 0),
            'cvar95': round(mc_block['cvar95'], 0),
        },
        'notop_pnl': round(notop_dollar, 0),
        'exit_classes': bt['exit_classes'],
        'class_a_ratio': round(class_a_ratio, 2),
    }
    return entry


def fmt(entry):
    bt = entry['backtest']
    mc = entry['mc_block']
    return (f"SC:{entry['score']:5.1f} | Med:${mc['median_eq']:,.0f} P5:${mc['p5']:,.0f} "
            f"CVaR:${mc['cvar95']:,.0f} | NT:${entry['notop_pnl']:+,.0f} | "
            f"Tr:{bt['trades']:3d} WR:{bt['wr']:.0f}% P&L:${bt['pnl']:+,.0f} "
            f"DD:{bt['dd']:.0f}% A:{entry['class_a_ratio']:.0%}")


# ============================================================
# SECTION 6: BLACKBOARD — gedeeld geheugen + event bus
# ============================================================

class Blackboard:
    """Centraal geheugen voor alle agents. Persist naar JSON."""

    def __init__(self, filepath=BLACKBOARD_FILE):
        self.filepath = filepath
        self.data = {
            'started': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'best_configs': [],
            'failed_regions': [],
            'events': [],
            'anomalies': [],
            'promotion_queue': [],
            'agent_status': {},
            'configs_evaluated': 0,
            'configs_triaged': 0,
            'configs_killed': 0,
            'meta_insights': [],
            # v3 nieuw:
            'scout_used_s': 0,
            'validator_used_s': 0,
            'friction_results': {},
            'outlier_map': {},
            'window_dist': {},
            'causal_verified': [],
            'ablation_results': {},
        }
        self._save()

    def _save(self):
        with open(self.filepath, 'w') as f:
            json.dump(self.data, f, indent=2, default=str)

    def _load(self):
        try:
            with open(self.filepath) as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    # --- Events ---
    def emit(self, event_type, agent, data_dict=None):
        self._load()
        event = {
            'type': event_type, 'agent': agent,
            'time': datetime.now().strftime('%H:%M:%S'),
            'data': data_dict or {},
        }
        self.data.setdefault('events', []).append(event)
        self._save()

    def get_events(self, event_type=None, since_idx=0):
        self._load()
        events = self.data.get('events', [])[since_idx:]
        if event_type:
            events = [e for e in events if e['type'] == event_type]
        return events

    # --- Best configs ---
    def post_config(self, entry):
        self._load()
        self.data['configs_evaluated'] = self.data.get('configs_evaluated', 0) + 1
        h = entry.get('hash', cfg_hash(entry['cfg']))
        existing = [i for i, e in enumerate(self.data['best_configs'])
                     if e.get('hash') == h]
        if existing:
            idx = existing[0]
            if entry['score'] > self.data['best_configs'][idx]['score']:
                self.data['best_configs'][idx] = entry
        else:
            self.data['best_configs'].append(entry)
        self.data['best_configs'].sort(key=lambda x: x['score'], reverse=True)
        self.data['best_configs'] = self.data['best_configs'][:50]
        self._save()
        return entry['score'] >= self.data['best_configs'][0]['score']

    def get_best(self, n=1):
        self._load()
        top = self.data.get('best_configs', [])
        return top[:n] if n > 1 else (top[0] if top else None)

    def get_best_cfg(self):
        best = self.get_best(1)
        return deepcopy(best['cfg']) if best else deepcopy(BEST_KNOWN)

    # --- Failed regions ---
    def mark_failed(self, region_desc, agent):
        self._load()
        self.data.setdefault('failed_regions', []).append({
            'region': region_desc, 'agent': agent,
            'time': datetime.now().strftime('%H:%M:%S'),
        })
        if len(self.data['failed_regions']) > 200:
            self.data['failed_regions'] = self.data['failed_regions'][-200:]
        self._save()

    def is_region_failed(self, region_desc):
        self._load()
        return any(f['region'] == region_desc for f in self.data.get('failed_regions', []))

    # --- Anomalies ---
    def flag_anomaly(self, desc, agent):
        self._load()
        self.data.setdefault('anomalies', []).append({
            'desc': desc, 'agent': agent,
            'time': datetime.now().strftime('%H:%M:%S'),
        })
        self._save()

    # --- Triage stats ---
    def inc_triaged(self):
        self._load()
        self.data['configs_triaged'] = self.data.get('configs_triaged', 0) + 1
        self._save()

    def inc_killed(self):
        self._load()
        self.data['configs_killed'] = self.data.get('configs_killed', 0) + 1
        self._save()

    # --- Agent status ---
    def update_agent(self, agent, status):
        self._load()
        self.data.setdefault('agent_status', {})[agent] = {
            'status': status, 'time': datetime.now().strftime('%H:%M:%S'),
        }
        self._save()

    # --- Promotion ---
    def promote(self, entry):
        self._load()
        self.data.setdefault('promotion_queue', []).append(entry)
        self._save()

    # --- Meta insights ---
    def post_insight(self, insight, agent):
        self._load()
        self.data.setdefault('meta_insights', []).append({
            'insight': insight, 'agent': agent,
            'time': datetime.now().strftime('%H:%M:%S'),
        })
        self._save()

    # --- v3: Budget tracking ---
    def add_scout_time(self, seconds):
        self._load()
        self.data['scout_used_s'] = self.data.get('scout_used_s', 0) + seconds
        self._save()

    def add_validator_time(self, seconds):
        self._load()
        self.data['validator_used_s'] = self.data.get('validator_used_s', 0) + seconds
        self._save()

    # --- v3: Friction results ---
    def post_friction(self, cfg_hash, results):
        self._load()
        self.data.setdefault('friction_results', {})[cfg_hash] = results
        self._save()

    # --- v3: Outlier map ---
    def post_outlier(self, cfg_hash, outlier_data):
        self._load()
        self.data.setdefault('outlier_map', {})[cfg_hash] = outlier_data
        self._save()

    # --- v3: Window distribution ---
    def post_window_dist(self, cfg_hash, dist_data):
        self._load()
        self.data.setdefault('window_dist', {})[cfg_hash] = dist_data
        self._save()

    # --- v3: Causal verified ---
    def mark_causal_verified(self, cfg_hash):
        self._load()
        verified = self.data.setdefault('causal_verified', [])
        if cfg_hash not in verified:
            verified.append(cfg_hash)
        self._save()

    # --- v3.1: Ablation results ---
    def post_ablation(self, results):
        self._load()
        self.data['ablation_results'] = results
        self._save()


# ============================================================
# SECTION 7: TRIAGE — goedkope pre-screening
# ============================================================

def triage(indicators, coins, cfg, bb):
    """Snelle triage met early stopping. Returns None als killed."""
    bt = run_backtest(indicators, coins, cfg,
                      early_stop_dd=60.0, early_stop_min_trades=15)
    bb.inc_triaged()

    if bt['early_stopped'] or bt['trades'] < 5 or bt['broke']:
        bb.inc_killed()
        return None

    if bt['trades'] < GATE_MIN_TRADES // 2:
        bb.inc_killed()
        return None

    if bt['dd'] > GATE_MAX_DD + 10:
        bb.inc_killed()
        return None

    return bt


# ============================================================
# SECTION 8: AGENT — Auditor
# ============================================================

def outlier_dependency(bt_result):
    """Analyseer outlier-afhankelijkheid met edge case handling."""
    trades = sorted(bt_result['trade_list'], key=lambda t: t['pnl'], reverse=True)
    if not trades:
        return {'top1_share': 0, 'top3_share': 0, 'worst1_loss_share': 0,
                'max_coin_share': 0, 'outlier_dependent': False, 'coin_concentrated': False}

    eps = 1e-9
    # Profit-only shares (upside concentration)
    total_profit = sum(max(0, t['pnl']) for t in trades)
    top1_share = min(1.0, max(0, trades[0]['pnl']) / max(eps, total_profit))
    top3_share = min(1.0, sum(max(0, t['pnl']) for t in trades[:3]) / max(eps, total_profit))

    # Downside: worst loss als share van totale verliezen
    total_loss = sum(abs(min(0, t['pnl'])) for t in trades)
    worst_trade_pnl = min(t['pnl'] for t in trades)
    worst1_loss_share = min(1.0, abs(min(0, worst_trade_pnl)) / max(eps, total_loss))

    # Coin concentratie (profit-only)
    coin_profit = {}
    for t in bt_result['trade_list']:
        coin_profit[t['pair']] = coin_profit.get(t['pair'], 0) + max(0, t['pnl'])
    max_coin_share = min(1.0, max(coin_profit.values()) / max(eps, total_profit)) if coin_profit else 0

    return {
        'top1_share': round(top1_share, 3),
        'top3_share': round(top3_share, 3),
        'worst1_loss_share': round(worst1_loss_share, 3),
        'max_coin_share': round(max_coin_share, 3),
        'outlier_dependent': top1_share > 0.8,
        'coin_concentrated': max_coin_share > 0.8,
    }


def deterministic_replay(indicators, coins, cfg):
    """Verifieer dat 2x dezelfde backtest identieke trades geeft."""
    bt1 = run_backtest(indicators, coins, cfg)
    bt2 = run_backtest(indicators, coins, cfg)
    if len(bt1['trade_list']) != len(bt2['trade_list']):
        return False
    for t1, t2 in zip(bt1['trade_list'], bt2['trade_list']):
        if t1['pair'] != t2['pair'] or abs(t1['pnl'] - t2['pnl']) > 0.01:
            return False
    return True


def causal_check(indicators, coins, cfg, data):
    """Multi-point causal check: trades vóór N moeten identiek blijven."""
    coin_list = [c for c in coins if c in indicators]
    max_bars = max(indicators[p]['n'] for p in coin_list) if coin_list else 0

    checkpoints = [int(max_bars * pct) for pct in [0.2, 0.4, 0.6, 0.8]]
    all_pass = True

    for n_bar in checkpoints:
        # Run met end_bar=N
        ind_short = precompute_all(data, coins, end_bar=n_bar)
        bt_short = run_backtest(ind_short, coins, cfg, end_bar=n_bar)

        # Run met end_bar=N+50
        ind_long = precompute_all(data, coins, end_bar=min(n_bar + 50, max_bars))
        bt_long = run_backtest(ind_long, coins, cfg, end_bar=min(n_bar + 50, max_bars))

        # Trades in [0, N] moeten identiek zijn
        short_trades = bt_short['trade_list']
        long_trades_before_n = [t for t in bt_long['trade_list'] if t['exit_bar'] <= n_bar]

        if len(short_trades) != len(long_trades_before_n):
            all_pass = False
            break

        for t1, t2 in zip(short_trades, long_trades_before_n):
            if t1['pair'] != t2['pair'] or abs(t1['pnl'] - t2['pnl']) > 0.01:
                all_pass = False
                break

        if not all_pass:
            break

    return all_pass


def agent_auditor(indicators, coins, data, bb, is_subsample=False):
    """Sanity check + deterministic replay + outlier + causal check.

    Hard-fail (altijd abort):
      - equity invariant fail
      - deterministic replay fail
      - causal check fail
      - trade count extreem (0 trades = engine broken)

    Soft (WARNING, nooit abort):
      - baseline P&L laag/negatief (coin subset kan outliers missen)
      - trade count afwijking (mild, verwacht bij subsampling)
    """
    name = 'Auditor'
    bb.update_agent(name, 'RUNNING')
    sub_tag = " [SUBSAMPLE]" if is_subsample else ""
    print(f"\n{'='*80}\n  AUDITOR: Sanity + Replay + Outlier + Causal{sub_tag}\n{'='*80}")

    hard_ok = True   # hard fails → abort
    soft_ok = True   # soft warnings → log but continue
    status = 'OK'

    # 1. Baseline backtest
    bt = run_backtest(indicators, coins, BASELINE_CFG)

    # 1a. HARD: trade count = 0 (engine broken)
    if bt['trades'] == 0:
        bb.flag_anomaly(f"HARD FAIL: 0 trades on {len(coins)} coins", name)
        bb.emit('SANITY_FAIL', name, {'reason': 'zero_trades'})
        print(f"  [1] Baseline: 0 trades — HARD FAIL (engine broken)")
        bb.update_agent(name, 'FAILED: zero trades')
        return False

    # 1b. SOFT: trade count afwijking
    trade_diff = abs(bt['trades'] - BASELINE_EXPECTED_TRADES)
    if trade_diff > 10:
        print(f"  [1a] Trade count: {bt['trades']} (verwacht ~{BASELINE_EXPECTED_TRADES}, "
              f"diff={trade_diff}) — WARNING")
        bb.flag_anomaly(f"Trade count deviation: {bt['trades']} (expected ~{BASELINE_EXPECTED_TRADES})", name)
        soft_ok = False
    elif trade_diff > 5:
        print(f"  [1a] Trade count: {bt['trades']} (verwacht ~{BASELINE_EXPECTED_TRADES}, "
              f"diff={trade_diff}) — MINOR WARNING")
        soft_ok = False
    else:
        print(f"  [1a] Trade count: {bt['trades']} (verwacht ~{BASELINE_EXPECTED_TRADES}) — OK")

    # 1c. SOFT: P&L check (NOOIT abort, zelfs bij full universe)
    if bt['pnl'] >= BASELINE_EXPECTED_PNL_MIN:
        print(f"  [1b] Baseline P&L: ${bt['pnl']:+,.0f} (>= ${BASELINE_EXPECTED_PNL_MIN}) — OK")
    else:
        print(f"  [1b] Baseline P&L: ${bt['pnl']:+,.0f} (< ${BASELINE_EXPECTED_PNL_MIN}) — "
              f"WARNING (performance variatie{'  — coin subset effect' if is_subsample else ''})")
        bb.flag_anomaly(f"Baseline PNL low: ${bt['pnl']:+,.0f} on {len(coins)} coins", name)
        status = 'WARN_BASELINE_PNL'
        soft_ok = False

    # 2. HARD: Equity invariant
    sum_pnl = sum(t['pnl'] for t in bt['trade_list'])
    eq_diff = abs(bt['final_equity'] - (INITIAL_CAPITAL + sum_pnl))
    if eq_diff > 1.0:
        bb.flag_anomaly(f"HARD FAIL: Equity mismatch diff=${eq_diff:.2f}", name)
        print(f"  [2] Equity invariant: diff=${eq_diff:.2f} — HARD FAIL")
        hard_ok = False
    else:
        print(f"  [2] Equity invariant: OK (diff=${eq_diff:.4f})")

    # 3. HARD: Deterministic replay
    replay_ok = deterministic_replay(indicators, coins, BASELINE_CFG)
    if not replay_ok:
        bb.flag_anomaly("HARD FAIL: Deterministic replay FAILED", name)
        print(f"  [3] Deterministic replay: HARD FAIL")
        hard_ok = False
    else:
        print(f"  [3] Deterministic replay: OK")

    # 4. SOFT: Outlier dependency (informatief, niet blocking)
    od = outlier_dependency(bt)
    bb.post_outlier(cfg_hash(BASELINE_CFG), od)
    print(f"  [4] Outlier dependency: top1={od['top1_share']:.1%} top3={od['top3_share']:.1%} "
          f"max_coin={od['max_coin_share']:.1%}")
    if od['outlier_dependent']:
        print(f"      OUTLIER DEPENDENT")
    if od['coin_concentrated']:
        print(f"      COIN CONCENTRATED")

    # 5. HARD: Multi-point causal check
    print(f"  [5] Causal check (20/40/60/80%)...", end=' ', flush=True)
    causal_ok = causal_check(indicators, coins, BASELINE_CFG, data)
    if not causal_ok:
        bb.flag_anomaly("HARD FAIL: Causal check FAILED", name)
        print(f"HARD FAIL")
        hard_ok = False
    else:
        bb.mark_causal_verified(cfg_hash(BASELINE_CFG))
        print(f"OK")

    # === VERDICT ===
    if not hard_ok:
        print(f"  HARD FAIL — ABORT (engineering invariant broken)")
        bb.emit('SANITY_FAIL', name, {'reason': 'hard_invariant'})
        bb.update_agent(name, 'FAILED: hard invariant')
        return False

    if soft_ok:
        print(f"  ALL CHECKS PASSED")
        bb.emit('SANITY_PASS', name, {'status': 'OK'})
        bb.update_agent(name, 'DONE: all checks passed')
    else:
        print(f"  HARD CHECKS PASSED, soft warnings logged — CONTINUING")
        bb.emit('SANITY_PASS', name, {'status': status, 'warnings': True})
        bb.update_agent(name, f'DONE: passed with warnings ({status})')

    return True  # hard checks OK → doorgaan


# ============================================================
# SECTION 9: AGENT — Scout (merged Combiner + ExitArchitect)
# ============================================================

def agent_scout(indicators, coins, bb, budget_s=600, quick=False):
    """
    Adaptive config generatie:
    1) 2-param grid (start klein, expand in hits)
    2) 3-param extensies op top-5
    3) Exit families (hybrid_notrl + tp_sl)
    4) max_pos variaties

    budget_s: max runtime in seconds.
    """
    name = 'Scout'
    bb.update_agent(name, 'RUNNING')
    print(f"\n{'='*80}\n  SCOUT: Adaptive Config Generatie (budget: {budget_s}s)\n{'='*80}")

    best = bb.get_best_cfg()
    evaluated = 0
    improved = 0
    t0 = time.time()
    deadline = t0 + budget_s

    # =========== PHASE 0: Ablation (champion sensitivity) ===========
    ablation_budget = min(120, budget_s * 0.10)
    ablation_deadline = t0 + ablation_budget
    ablation_results = {}
    champion_entry = bb.get_best(1)

    if champion_entry and isinstance(champion_entry, dict) and 'cfg' in champion_entry:
        print(f"  Phase 0: Ablation Analysis (budget: {ablation_budget:.0f}s)")
        champion_cfg = deepcopy(champion_entry['cfg'])
        champion_score = champion_entry['score']

        ABLATION_GRID_ALL = {
            'vol_spike_mult': [2.0, 2.5, 3.0, 3.5, 4.0, 5.0],
            'rsi_max':         [30, 35, 38, 40, 42, 45, 48],
            'tp_pct':          [3, 5, 7, 10, 12, 15, 20],
            'sl_pct':          [5, 8, 10, 15, 20, 25],
            'rsi_rec_target':  [40, 42, 44, 45, 46, 47, 48],
            'time_max_bars':   [4, 6, 8, 10, 12, 15],
            'atr_mult':        [1.5, 1.75, 2.0, 2.5, 3.0],
            'be_trigger':      [1.5, 2.0, 2.5, 3.0, 4.0],
            'max_stop_pct':    [8.0, 10.0, 12.0, 15.0, 20.0],
        }
        # Filter ablation grid op exit_type van champion
        champ_exit = champion_cfg.get('exit_type', 'trail')
        champ_allowed = PARAMS_BY_EXIT.get(champ_exit, PARAMS_BY_EXIT['trail'])
        champ_keys = set(champ_allowed['entry'] + champ_allowed['exit'])
        ABLATION_GRID = {k: v for k, v in ABLATION_GRID_ALL.items() if k in champ_keys}
        print(f"    Ablation grid for {champ_exit}: {sorted(ABLATION_GRID.keys())}")

        for param, values in ABLATION_GRID.items():
            if time.time() >= ablation_deadline:
                break
            param_results = []
            base_val = champion_cfg.get(param)
            for val in values:
                if time.time() >= ablation_deadline:
                    break
                if val == base_val:
                    param_results.append({'value': val, 'delta_score': 0.0, 'is_champion': True})
                    continue
                cfg = deepcopy(champion_cfg)
                cfg[param] = val
                bt = triage(indicators, coins, cfg, bb)
                evaluated += 1
                if bt is None:
                    param_results.append({'value': val, 'delta_score': None, 'killed': True})
                    continue
                abl_entry = evaluate(indicators, coins, cfg, f"abl-{param}={val}", bb)
                if abl_entry is None:
                    param_results.append({'value': val, 'delta_score': None, 'killed': True})
                    continue
                delta = abl_entry['score'] - champion_score
                param_results.append({'value': val, 'delta_score': round(delta, 2),
                                      'score': abl_entry['score']})
                if abl_entry['score'] >= champion_score - 5:
                    bb.post_config(abl_entry)

            deltas = [abs(r['delta_score']) for r in param_results
                      if r.get('delta_score') is not None]
            n_killed = sum(1 for r in param_results if r.get('killed'))
            n_tested = len(param_results) - 1  # minus champion zelf
            n_scored = len(deltas)
            sensitivity = max(deltas) if deltas else 0
            ablation_results[param] = {
                'champion_value': base_val,
                'variations': param_results,
                'sensitivity': round(sensitivity, 2),
                'n_killed': n_killed,
                'n_scored': n_scored,
                'n_tested': n_tested,
            }
            best_delta = max((r.get('delta_score', 0) or 0) for r in param_results)
            print(f"    {param}: sens={sensitivity:.2f} "
                  f"(champ={base_val}, best_delta={best_delta:+.1f}, "
                  f"scored={n_scored}/{n_tested}, killed={n_killed})")

        ablation_ranked = sorted(
            [(p, d) for p, d in ablation_results.items()],
            key=lambda x: x[1]['sensitivity'], reverse=True)
        ablation_results['_ranking'] = [p for p, _ in ablation_ranked]
        bb.post_ablation(ablation_results)
        print(f"    Ranking: {' > '.join(p for p, _ in ablation_ranked[:5])}")
        print(f"    Ablation klaar: {time.time() - t0:.0f}s")
    else:
        print(f"  Phase 0: Ablation overgeslagen (geen champion)")

    # Herbereken deadline voor resterende phases
    remaining_budget = budget_s - (time.time() - t0)
    deadline = time.time() + remaining_budget

    # --- Exit-type-aware parameter grids ---
    # PARAMS_BY_EXIT is module-level constante (source of truth)
    ALL_PARAM_VALUES_QUICK = {
        'vol_spike_mult': [2.5, 3.0, 4.0],
        'rsi_max':         [35, 40, 42, 45],
        'tp_pct':          [5, 7, 10, 15],
        'sl_pct':          [8, 10, 15, 20],
        'rsi_rec_target':  [42, 45, 47],
        'time_max_bars':   [5, 6, 8, 10, 15],
        'atr_mult':        [1.5, 2.0, 2.5],
        'be_trigger':      [1.5, 2.0, 3.0],
        'max_stop_pct':    [8.0, 12.0, 15.0],
    }
    ALL_PARAM_VALUES_EXPANDED = {
        'vol_spike_mult': [2.0, 2.5, 3.0, 3.5, 4.0, 5.0],
        'rsi_max':         [30, 35, 38, 40, 42, 45, 48],
        'tp_pct':          [3, 5, 7, 8, 10, 12, 15, 20],
        'sl_pct':          [5, 8, 10, 12, 15, 20, 25],
        'rsi_rec_target':  [40, 42, 44, 45, 46, 47, 48],
        'time_max_bars':   [4, 6, 8, 10, 12, 15, 20],
        'atr_mult':        [1.5, 1.75, 2.0, 2.5, 3.0],
        'be_trigger':      [1.5, 2.0, 2.5, 3.0, 4.0],
        'max_stop_pct':    [8.0, 10.0, 12.0, 15.0, 20.0],
    }

    # Filter grid op exit_type van huidige best config
    best_exit = best.get('exit_type', 'trail')
    allowed_params = PARAMS_BY_EXIT.get(best_exit, PARAMS_BY_EXIT['trail'])
    allowed_keys = set(allowed_params['entry'] + allowed_params['exit'])
    PARAMS = {k: v for k, v in ALL_PARAM_VALUES_QUICK.items() if k in allowed_keys}
    PARAMS_EXPANDED = {k: v for k, v in ALL_PARAM_VALUES_EXPANDED.items() if k in allowed_keys}
    param_names = list(PARAMS.keys())
    promising_regions = set()  # Regio's met score > 80 → expand

    skipped = set(ALL_PARAM_VALUES_QUICK.keys()) - allowed_keys
    print(f"  Exit-type={best_exit}: grid params={sorted(allowed_keys)}")
    if skipped:
        print(f"  ⚠️  Skipped (not used by {best_exit}): {sorted(skipped)}")

    # =========== PHASE 1: 2-param grid ===========
    print(f"  Phase 1: 2-param grid (adaptive)")
    for i in range(len(param_names)):
        if time.time() >= deadline:
            break
        for j in range(i+1, len(param_names)):
            if time.time() >= deadline:
                break
            p1, p2 = param_names[i], param_names[j]
            region = f"{p1}x{p2}"
            if bb.is_region_failed(region):
                continue

            # Determine grid: expanded als regio belovend
            grid_p1 = PARAMS_EXPANDED.get(p1, PARAMS[p1]) if region in promising_regions else PARAMS[p1]
            grid_p2 = PARAMS_EXPANDED.get(p2, PARAMS[p2]) if region in promising_regions else PARAMS[p2]

            region_hits = 0
            region_evals = 0
            for v1 in grid_p1:
                if time.time() >= deadline:
                    break
                for v2 in grid_p2:
                    if time.time() >= deadline:
                        break
                    if v1 == best.get(p1) and v2 == best.get(p2):
                        continue
                    cfg = deepcopy(best)
                    cfg[p1] = v1
                    cfg[p2] = v2
                    bt = triage(indicators, coins, cfg, bb)
                    evaluated += 1
                    region_evals += 1
                    if bt is None:
                        continue
                    if bt['trades'] < 15 and bt['pnl'] < 200:
                        continue
                    label = f"s2-{p1}={v1}-{p2}={v2}"
                    entry = evaluate(indicators, coins, cfg, label, bb)
                    if entry is None:
                        continue
                    is_best = bb.post_config(entry)
                    if is_best:
                        improved += 1
                        bb.emit('NEW_BEST_FOUND', name, {'label': label, 'score': entry['score']})
                        print(f"    NEW BEST: {label}")
                        print(f"     {fmt(entry)}")
                    if entry['score'] >= 80:
                        region_hits += 1

            # Adaptive: als regio hits heeft, expand
            if region_hits > 0 and region not in promising_regions:
                promising_regions.add(region)
                print(f"    Promising region: {region} ({region_hits} hits) → expand")

            # Mark als failed als geen hits na voldoende evaluaties
            if region_hits == 0 and region_evals > 8:
                bb.mark_failed(region, name)

            if evaluated % 50 == 0 and evaluated > 0:
                elapsed = time.time() - t0
                print(f"    ... {evaluated} eval | {improved} improved | {elapsed:.0f}s / {budget_s}s")

    # =========== PHASE 2: 3-param extensies op top-5 ===========
    if time.time() < deadline:
        print(f"\n  Phase 2: 3-param extensies op top-5")
        top5 = bb.get_best(5)
        if isinstance(top5, dict):
            top5 = [top5]
        for entry in (top5 or []):
            if time.time() >= deadline:
                break
            base = deepcopy(entry['cfg'])
            for param in param_names:
                if time.time() >= deadline:
                    break
                for val in PARAMS[param]:
                    if time.time() >= deadline:
                        break
                    if val == base.get(param):
                        continue
                    cfg = deepcopy(base)
                    cfg[param] = val
                    bt = triage(indicators, coins, cfg, bb)
                    evaluated += 1
                    if bt is None:
                        continue
                    if bt['trades'] < 15 and bt['pnl'] < 200:
                        continue
                    label = f"s3-{entry.get('label','top')[:20]}-{param}={val}"
                    result = evaluate(indicators, coins, cfg, label, bb)
                    if result is None:
                        continue
                    is_best = bb.post_config(result)
                    if is_best:
                        improved += 1
                        bb.emit('NEW_BEST_FOUND', name, {'label': label, 'score': result['score']})
                        print(f"    3P NEW BEST: {label}")
                        print(f"     {fmt(result)}")

    # =========== PHASE 3: Exit families ===========
    if time.time() < deadline:
        print(f"\n  Phase 3: Exit families")

        # Basis entry params (bewezen)
        base_entry = {k: best[k] for k in ['rsi_max', 'vol_spike_mult', 'vol_confirm']
                      if k in best}

        # --- hybrid_notrl ---
        print(f"    Phase 3A: hybrid_notrl")
        tm_vals = [6, 8, 10, 12, 15, 20, 25] if not quick else [8, 12, 20]
        ms_vals = [10, 12, 15, 20, 25] if not quick else [12, 15, 20]
        rr_vals = [False, 42, 45, 47] if not quick else [45, False]

        for tm in tm_vals:
            if time.time() >= deadline:
                break
            for ms in ms_vals:
                if time.time() >= deadline:
                    break
                for rr in rr_vals:
                    if time.time() >= deadline:
                        break
                    cfg = {**base_entry, 'exit_type': 'hybrid_notrl',
                           'max_stop_pct': ms, 'time_max_bars': tm,
                           'max_pos': 1, 'breakeven': False}
                    if rr is not False:
                        cfg['rsi_recovery'] = True
                        cfg['rsi_rec_target'] = rr
                    else:
                        cfg['rsi_recovery'] = False
                    label = f"notrl-tm{tm}-ms{ms}-rr{rr}"
                    bt = triage(indicators, coins, cfg, bb)
                    evaluated += 1
                    if bt is None:
                        continue
                    entry = evaluate(indicators, coins, cfg, label, bb)
                    if entry is None:
                        continue
                    is_best = bb.post_config(entry)
                    if is_best:
                        improved += 1
                        bb.emit('EXIT_TYPE_BREAKTHROUGH', name,
                                {'type': 'hybrid_notrl', 'label': label, 'score': entry['score']})
                        print(f"    BREAKTHROUGH: {label}")
                        print(f"     {fmt(entry)}")
                    elif entry['score'] >= 75:
                        print(f"      {label}: SC:{entry['score']:.1f}")

        # --- tp_sl ---
        if time.time() < deadline:
            print(f"    Phase 3B: tp_sl")
            tp_vals = [5, 7, 8, 10, 12, 15] if not quick else [7, 10]
            sl_vals = [8, 10, 15, 20] if not quick else [10, 15]
            tmb_vals = [8, 10, 15, 20, 999] if not quick else [10, 15]

            for tp in tp_vals:
                if time.time() >= deadline:
                    break
                for sl in sl_vals:
                    if time.time() >= deadline:
                        break
                    for tmb in tmb_vals:
                        if time.time() >= deadline:
                            break
                        cfg = {**base_entry, 'exit_type': 'tp_sl',
                               'tp_pct': tp, 'sl_pct': sl, 'time_max_bars': tmb,
                               'max_pos': 1}
                        label = f"tpsl-tp{tp}-sl{sl}-tm{tmb}"
                        bt = triage(indicators, coins, cfg, bb)
                        evaluated += 1
                        if bt is None:
                            continue
                        entry = evaluate(indicators, coins, cfg, label, bb)
                        if entry is None:
                            continue
                        is_best = bb.post_config(entry)
                        if is_best:
                            improved += 1
                            bb.emit('EXIT_TYPE_BREAKTHROUGH', name,
                                    {'type': 'tp_sl', 'label': label, 'score': entry['score']})
                            print(f"    BREAKTHROUGH: {label}")
                            print(f"     {fmt(entry)}")
                        elif entry['score'] >= 75:
                            print(f"      {label}: SC:{entry['score']:.1f}")

    # =========== PHASE 4: max_pos variaties ===========
    if time.time() < deadline:
        print(f"\n  Phase 4: max_pos variaties")
        top_entries = bb.get_best(5)
        if isinstance(top_entries, dict):
            top_entries = [top_entries]
        for entry in (top_entries or []):
            if time.time() >= deadline:
                break
            if isinstance(entry, dict) and 'cfg' in entry:
                for mp in [1, 2, 3]:
                    if time.time() >= deadline:
                        break
                    cfg = deepcopy(entry['cfg'])
                    cfg['max_pos'] = mp
                    label = f"mp{mp}-{entry.get('label','top')[:25]}"
                    bt = triage(indicators, coins, cfg, bb)
                    evaluated += 1
                    if bt is not None:
                        result = evaluate(indicators, coins, cfg, label, bb)
                        if result:
                            bb.post_config(result)

    elapsed = time.time() - t0
    bb.add_scout_time(elapsed)
    print(f"\n  Scout klaar: {evaluated} eval, {improved} improved, {elapsed:.0f}s")
    bb.update_agent(name, f'DONE: {evaluated} eval, {improved} improved, {elapsed:.0f}s')
    return evaluated


# ============================================================
# SECTION 10: AGENT — Validator (WF + friction + coin MC + window)
# ============================================================

def friction_stress(indicators, coins, cfg):
    """Test fee-gevoeligheid met fee × [1.0, 1.5, 2.0]."""
    results = {}
    for fee_mult in [1.0, 1.5, 2.0]:
        fee_val = KRAKEN_FEE * fee_mult
        bt = run_backtest(indicators, coins, cfg, fee_override=fee_val)
        results[f'{fee_mult}x'] = {
            'pnl': round(bt['pnl'], 2),
            'trades': bt['trades'],
            'wr': round(bt['wr'], 1),
            'dd': round(bt['dd'], 1),
        }
    passed = results['2.0x']['pnl'] > PROMO_FRICTION_2X_MIN
    return results, passed


def window_distribution(trade_list, window_bars=180):
    """
    Groepeer trades per window van N bars (180 bars ≈ 30 dagen bij 4H).
    Puur bar-based, geen datum-mapping nodig.
    """
    if not trade_list:
        return {'n_windows': 0, 'worst_window': 0, 'max_window_share': 0, 'concentrated': False}

    windows = {}
    for t in trade_list:
        w = t['entry_bar'] // window_bars
        windows.setdefault(w, []).append(t['pnl'])

    pnl_per_window = {w: sum(pnls) for w, pnls in windows.items()}
    worst_window = min(pnl_per_window.values()) if pnl_per_window else 0
    best_window = max(pnl_per_window.values()) if pnl_per_window else 0
    # Profit-only window concentration
    window_profit = {w: sum(max(0, p) for p in pnls) for w, pnls in windows.items()}
    total_profit = sum(window_profit.values())
    max_window_share = min(1.0, max(window_profit.values()) / max(1e-9, total_profit)) if window_profit else 0

    return {
        'n_windows': len(windows),
        'pnl_per_window': {str(k): round(v, 2) for k, v in sorted(pnl_per_window.items())},
        'worst_window': round(worst_window, 2),
        'best_window': round(best_window, 2),
        'max_window_share': round(max_window_share, 3),
        'concentrated': max_window_share > 0.6,
    }


def agent_validator(indicators, coins, data, bb, budget_s=600, quick=False):
    """Walk-forward + friction stress + coin MC + window distribution."""
    name = 'Validator'
    bb.update_agent(name, 'RUNNING')
    print(f"\n{'='*80}\n  VALIDATOR: WF + Friction + Coin MC + Window (budget: {budget_s}s)\n{'='*80}")

    n_folds = 5 if not quick else 3
    t0 = time.time()
    deadline = t0 + budget_s

    # Collect configs to validate
    configs_to_test = []
    seen = set()

    top = bb.get_best(10 if not quick else 5) or []
    if isinstance(top, dict):
        top = [top]
    for e in top:
        h = cfg_hash(e['cfg'])
        if h not in seen:
            seen.add(h)
            configs_to_test.append((e.get('label', 'top'), e['cfg']))

    for lbl, cfg in [('BASELINE', BASELINE_CFG), ('BEST_KNOWN', BEST_KNOWN)]:
        h = cfg_hash(cfg)
        if h not in seen:
            seen.add(h)
            configs_to_test.append((lbl, cfg))

    print(f"  Configs: {len(configs_to_test)}, Folds: {n_folds}")

    coin_list = [c for c in coins if c in indicators]
    max_bars = max(indicators[p]['n'] for p in coin_list)
    usable = max_bars - START_BAR
    fold_size = usable // n_folds

    results = []

    for cfg_label, cfg in configs_to_test:
        if time.time() >= deadline:
            print(f"  Budget op — stoppen")
            break

        # ====== Walk-Forward ======
        folds_profitable = 0
        fold_details = []

        for fold in range(n_folds):
            fold_start = START_BAR + fold * fold_size
            fold_end = fold_start + fold_size
            if fold == n_folds - 1:
                fold_end = max_bars

            train_end = fold_start + int(fold_size * 0.7)
            test_start = train_end
            test_end = fold_end

            # LEAKAGE-SAFE: herbereken indicators per fold
            fold_ind = precompute_all(data, coins, end_bar=fold_end)

            bt_train = run_backtest(fold_ind, coins, cfg,
                                    start_bar=fold_start, end_bar=train_end)
            bt_test = run_backtest(fold_ind, coins, cfg,
                                   start_bar=test_start, end_bar=test_end)

            profitable = bt_test['pnl'] > 0
            if profitable:
                folds_profitable += 1

            fold_details.append({
                'fold': fold+1,
                'train': f"{fold_start}-{train_end}",
                'test': f"{test_start}-{test_end}",
                'train_tr': bt_train['trades'],
                'train_pnl': round(bt_train['pnl'], 0),
                'test_tr': bt_test['trades'],
                'test_pnl': round(bt_test['pnl'], 0),
                'pass': profitable,
            })

        wf_ratio = folds_profitable / n_folds
        wf_passed = wf_ratio >= GATE_MIN_WF_RATIO

        # ====== Friction Stress ======
        friction_res, friction_passed = friction_stress(indicators, coins, cfg)
        h = cfg_hash(cfg)
        bb.post_friction(h, friction_res)

        # ====== Outlier Dependency ======
        bt_full = run_backtest(indicators, coins, cfg)
        od = outlier_dependency(bt_full)
        bb.post_outlier(h, od)

        # ====== Window Distribution ======
        wd = window_distribution(bt_full['trade_list'])
        bb.post_window_dist(h, wd)

        result = {
            'label': cfg_label, 'cfg': cfg,
            'wf': f"{folds_profitable}/{n_folds}",
            'wf_ratio': wf_ratio, 'wf_passed': wf_passed,
            'folds': fold_details,
            'friction': friction_res, 'friction_passed': friction_passed,
            'outlier': od,
            'window': wd,
        }
        results.append(result)

        # Emit events
        if wf_passed:
            bb.emit('WF_PASSED', name, {'label': cfg_label, 'wf': f"{folds_profitable}/{n_folds}"})
        else:
            bb.emit('WF_FAILED', name, {'label': cfg_label, 'wf': f"{folds_profitable}/{n_folds}"})

        if friction_passed:
            bb.emit('FRICTION_PASSED', name, {'label': cfg_label})
        else:
            bb.emit('FRICTION_FAILED', name, {'label': cfg_label})

        # Print summary
        wf_icon = "OK" if wf_passed else "FAIL"
        fr_icon = "OK" if friction_passed else "FAIL"
        test_pnls = [f['test_pnl'] for f in fold_details]
        print(f"  [{wf_icon}] {cfg_label}: WF {folds_profitable}/{n_folds} | "
              f"Friction [{fr_icon}] 2x=${friction_res['2.0x']['pnl']:+,.0f} | "
              f"Outlier top1={od['top1_share']:.1%} coin={od['max_coin_share']:.1%} | "
              f"Window worst=${wd['worst_window']:+,.0f} conc={wd['max_window_share']:.0%}")

    # ====== Coin subsample MC op WF-passers ======
    passed_cfgs = [r for r in results if r.get('wf_passed', False)]
    if passed_cfgs and time.time() < deadline:
        print(f"\n  Coin-subsample MC op {min(3, len(passed_cfgs))} WF-passers...")
        for r in passed_cfgs[:3]:
            if time.time() >= deadline:
                break
            mc_coin = monte_carlo_coin_subsample(indicators, coins, r['cfg'],
                                                  n_sims=200 if not quick else 50)
            print(f"    {r['label']}: Coin-MC win={mc_coin['win_pct']:.0f}% "
                  f"med=${mc_coin['median_equity']:,.0f} p5=${mc_coin['p5']:,.0f}")
            r['coin_mc'] = {
                'win_pct': round(mc_coin['win_pct'], 1),
                'median': round(mc_coin['median_equity'], 0),
                'p5': round(mc_coin['p5'], 0),
            }

    elapsed = time.time() - t0
    bb.add_validator_time(elapsed)
    print(f"\n  Validator klaar: {len(configs_to_test)} configs, {elapsed:.0f}s")
    bb.update_agent(name, f'DONE: {len(configs_to_test)} configs, {elapsed:.0f}s')
    return results


# ============================================================
# SECTION 11: AGENT — MetaLearner (compact helper)
# ============================================================

def agent_meta_learner(bb):
    """Analyseer leaderboard, detecteer patronen."""
    name = 'MetaLearner'
    bb.update_agent(name, 'RUNNING')
    print(f"\n{'='*80}\n  META-LEARNER: Leaderboard Analyse\n{'='*80}")

    top = bb.get_best(20) or []
    if isinstance(top, dict):
        top = [top]
    if len(top) < 3:
        print("  Te weinig data voor meta-analyse")
        bb.update_agent(name, 'DONE: insufficient data')
        return

    # 1. Score plateau detectie
    scores = [e['score'] for e in top]
    if len(scores) >= 5:
        top5_spread = max(scores[:5]) - min(scores[:5])
        if top5_spread < 0.5:
            insight = f"PLATEAU: top-5 spread = {top5_spread:.3f} (< 0.5). Zoekruimte uitgeput rond optimum."
            bb.post_insight(insight, name)
            print(f"    {insight}")

    # 2. Stabiele params (>70% top-10)
    param_freq = {}
    for e in top[:10]:
        cfg = e['cfg']
        for k, v in cfg.items():
            key = f"{k}={v}"
            param_freq[key] = param_freq.get(key, 0) + 1

    stable = [(k, v) for k, v in param_freq.items() if v >= 7]
    if stable:
        insight = f"STABLE PARAMS (>70% top-10): {', '.join(k for k,v in stable)}"
        bb.post_insight(insight, name)
        print(f"    {insight}")

    # 3. Exit class dominantie
    for e in top[:5]:
        ec = e.get('exit_classes', {})
        a_profit = sum(max(0, v['pnl']) for v in ec.get('A', {}).values())
        b_profit = sum(max(0, v['pnl']) for v in ec.get('B', {}).values())
        total_profit = a_profit + b_profit
        a_share = min(1.0, a_profit / max(1e-9, total_profit))
        if a_share > 0.8:
            insight = f"KLASSE A DOMINANT ({e.get('label','')}): {a_share:.0%} P&L uit winst-exits"
            bb.post_insight(insight, name)
            print(f"    {insight}")

    # 4. Exit type breakdown
    exit_types = {}
    for e in top[:10]:
        et = e['cfg'].get('exit_type', 'unknown')
        exit_types[et] = exit_types.get(et, 0) + 1
    if exit_types:
        insight = f"EXIT TYPES in top-10: {', '.join(f'{k}:{v}' for k,v in sorted(exit_types.items(), key=lambda x: -x[1]))}"
        bb.post_insight(insight, name)
        print(f"    {insight}")

    # 5. Ablation samenvatting
    bb._load()
    ablation = bb.data.get('ablation_results', {})
    ranking = ablation.get('_ranking', [])
    if ranking:
        top3 = ranking[:3]
        sensitivity_str = ', '.join(
            f"{p}={ablation[p]['sensitivity']:.1f}" for p in top3 if p in ablation)
        insight = f"ABLATION: Meest gevoelige params: {sensitivity_str}"
        bb.post_insight(insight, name)
        print(f"    {insight}")
        improvements = []
        for p in ranking:
            if p not in ablation or p.startswith('_'):
                continue
            for v in ablation[p].get('variations', []):
                ds = v.get('delta_score')
                if ds is not None and ds > 0:
                    improvements.append(f"{p}={v['value']}(+{ds:.1f})")
        if improvements:
            insight2 = f"ABLATION VERBETERINGEN: {', '.join(improvements[:5])}"
            bb.post_insight(insight2, name)
            print(f"    {insight2}")

    # 6. Efficiency stats
    bb._load()
    total_eval = bb.data.get('configs_evaluated', 0)
    total_triage = bb.data.get('configs_triaged', 0)
    total_killed = bb.data.get('configs_killed', 0)
    if total_triage > 0:
        kill_rate = total_killed / total_triage * 100
        print(f"    Triage efficiency: {total_killed}/{total_triage} killed ({kill_rate:.0f}%) "
              f"— {total_eval} full evaluations")

    bb.update_agent(name, 'DONE')


# ============================================================
# SECTION 12: ORCHESTRATOR + PROMOTION
# ============================================================

def apply_promotion_gates(entry, wf_result, bb):
    """
    7-gate promotion pipeline.
    Returns (passed: bool, details: dict)
    """
    h = cfg_hash(entry['cfg']) if isinstance(entry, dict) and 'cfg' in entry else ''
    details = {}

    # Gate 1: Walk-Forward
    wf_ratio = wf_result.get('wf_ratio', 0) if wf_result else 0
    details['g1_wf'] = wf_ratio >= PROMO_WF_MIN
    details['g1_val'] = wf_result.get('wf', '0/0') if wf_result else '0/0'

    # Gate 2: Friction 2x fees
    friction_passed = wf_result.get('friction_passed', False) if wf_result else False
    details['g2_friction'] = friction_passed
    friction_res = wf_result.get('friction', {}) if wf_result else {}
    details['g2_val'] = friction_res.get('2.0x', {}).get('pnl', 0)

    # Gate 3: NoTop
    notop = entry.get('notop_pnl', -999) if isinstance(entry, dict) else -999
    details['g3_notop'] = notop > GATE_NOTOP_PNL_MIN
    details['g3_val'] = notop

    # Gate 4: Outlier + coin concentration
    od = wf_result.get('outlier', {}) if wf_result else {}
    details['g4_outlier'] = not od.get('outlier_dependent', True)
    details['g4_coin'] = not od.get('coin_concentrated', True)
    details['g4_val'] = f"top1={od.get('top1_share',1):.1%} coin={od.get('max_coin_share',1):.1%}"

    # Gate 5: MC P5
    mc = entry.get('mc_block', {}) if isinstance(entry, dict) else {}
    mc_p5 = mc.get('p5', 0)
    details['g5_mc_p5'] = mc_p5 > PROMO_MC_P5_MIN
    details['g5_val'] = mc_p5

    # Gate 6: Class A ratio
    class_a = entry.get('class_a_ratio', 0) if isinstance(entry, dict) else 0
    details['g6_class_a'] = class_a > PROMO_CLASS_A_MIN
    details['g6_val'] = class_a

    # Gate 7: Window worst-case
    wd = wf_result.get('window', {}) if wf_result else {}
    worst_w = wd.get('worst_window', -9999)
    details['g7_window'] = worst_w > PROMO_WORST_WINDOW_MIN
    details['g7_val'] = worst_w

    passed = all([
        details['g1_wf'],
        details['g2_friction'],
        details['g3_notop'],
        details['g4_outlier'],
        details['g4_coin'],
        details['g5_mc_p5'],
        details['g6_class_a'],
        details['g7_window'],
    ])

    return passed, details


def orchestrator(args, coin_seed=None, run_idx=0):
    """Main orchestrator: budget, breakthrough shifting, promotion."""
    global TG
    if TG is None:
        TG = TelegramNotifier()

    n_runs = getattr(args, 'runs', 1)
    run_label = f" (run {run_idx+1})" if coin_seed is not None else ""
    print(f"{'='*80}")
    print(f"AGENT TEAM V3 — Wetenschappelijk Multi-Agent Optimizer{run_label}")
    print(f"{'='*80}")
    print(f"  Mode: {'QUICK' if args.quick else 'FULL'}")
    print(f"  Max runtime: {args.hours}h")
    print(f"  Start: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # 1. Load data
    print(f"\n  Laden data...")
    with open(CACHE_FILE) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith('_')])
    all_coins = coins
    print(f"  {len(coins)} coins geladen")

    # Coin subsampling voor multi-run
    if coin_seed is not None:
        rng = random.Random(coin_seed)
        n_sample = int(len(coins) * 0.9)
        coins = sorted(rng.sample(coins, n_sample))
        print(f"  Coin subsample: {len(coins)}/{len(all_coins)} coins (seed={coin_seed})")

    TG.run_start(run_idx, n_runs, len(coins), seed=coin_seed)

    # 2. Precompute (full dataset)
    print(f"  Precomputing indicators...")
    t0_global = time.time()
    indicators = precompute_all(data, coins)
    print(f"  Precompute: {time.time()-t0_global:.1f}s")

    # 3. Init Blackboard + budgets
    bb = Blackboard()
    total_runtime = args.hours * 3600
    budgets = {
        'auditor':   int(total_runtime * 0.10),
        'scout':     int(total_runtime * 0.60),
        'validator': int(total_runtime * 0.30),
    }
    print(f"  Budgets: Auditor={budgets['auditor']}s Scout={budgets['scout']}s "
          f"Validator={budgets['validator']}s")

    # ====== PHASE 1: Auditor ======
    t_audit = time.time()
    is_sub = coin_seed is not None  # multi-run coin subsample
    if not agent_auditor(indicators, coins, data, bb, is_subsample=is_sub):
        # Hard invariant fail (equity, replay, causal, zero trades)
        print(f"\n  ABORT: Auditor HARD FAIL (engineering invariant broken)")
        if is_sub:
            # Multi-run: return met HARD_FAIL status, laat andere runs door
            print(f"  (Subsample run — returning HARD_FAIL, andere runs gaan door)")
            return {'run_idx': run_idx, 'coin_seed': coin_seed, 'n_coins': len(coins),
                    'promoted': [], 'top5': [], 'best_config': None,
                    'total_time': 0, 'status': 'HARD_FAIL'}
        sys.exit(1)
    audit_time = time.time() - t_audit
    print(f"  Auditor: {audit_time:.0f}s")

    # Auditor status naar Telegram (1 bericht per run)
    bb._load()
    audit_status = bb.data.get('events', [])
    audit_st = 'OK'
    for ev in audit_status:
        if ev.get('type') == 'SANITY_PASS':
            audit_st = ev.get('data', {}).get('status', 'OK')
            break
    TG.auditor_status(run_idx, n_runs, audit_st, len(coins), audit_time)

    # 4. Seed blackboard
    print(f"\n  Seeding blackboard met BEST_KNOWN + BASELINE + CHAMPION...")
    entry = evaluate(indicators, coins, BEST_KNOWN, 'BEST_KNOWN', bb)
    if entry:
        bb.post_config(entry)
        print(f"  Startpunt: {fmt(entry)}")
    entry2 = evaluate(indicators, coins, BASELINE_CFG, 'BASELINE_V5+VolSpk3', bb)
    if entry2:
        bb.post_config(entry2)

    # Seed champion uit vorige run
    champion = load_champion()
    if champion and 'cfg' in champion:
        champ_entry = evaluate(indicators, coins, champion['cfg'],
                               f"CHAMP({champion.get('label','?')[:20]})", bb)
        if champ_entry:
            bb.post_config(champ_entry)
            print(f"  Champion geladen: {fmt(champ_entry)} (van {champion.get('timestamp','?')})")
        else:
            print(f"  Champion geladen maar faalt gates — overgeslagen")
    else:
        print(f"  Geen vorige champion gevonden")

    # ====== PHASE 2: Scout ======
    scout_budget = budgets['scout']
    if time.time() - t0_global < total_runtime:
        agent_scout(indicators, coins, bb, budget_s=scout_budget, quick=args.quick)

    # 5. Check EXIT_TYPE_BREAKTHROUGH → reallocate
    breakthroughs = bb.get_events('EXIT_TYPE_BREAKTHROUGH')
    extra_validator_s = 0
    if breakthroughs:
        bb._load()
        scout_used = bb.data.get('scout_used_s', 0)
        remaining_scout = max(0, scout_budget - scout_used)
        extra_validator_s = int(remaining_scout * 0.5)
        if extra_validator_s > 30:
            print(f"\n  BREAKTHROUGH detected ({len(breakthroughs)}x) → "
                  f"+{extra_validator_s}s naar Validator")

    # ====== PHASE 3: MetaLearner ======
    agent_meta_learner(bb)

    # ====== PHASE 4: Validator ======
    validator_budget = budgets['validator'] + extra_validator_s
    wf_results = []
    remaining = total_runtime - (time.time() - t0_global)
    if remaining > 60:
        actual_budget = min(validator_budget, int(remaining))
        wf_results = agent_validator(indicators, coins, data, bb,
                                      budget_s=actual_budget, quick=args.quick)

    # ====== PHASE 5: Promotion gates ======
    print(f"\n{'='*80}\n  PROMOTION PIPELINE (7 gates)\n{'='*80}")

    # Match WF results met best_configs voor promotion
    promoted = []
    bb._load()
    best_configs = bb.data.get('best_configs', [])

    for wf_r in wf_results:
        if not wf_r.get('wf_passed', False):
            continue

        # Vind matching entry in best_configs
        h = cfg_hash(wf_r['cfg'])
        matching = [e for e in best_configs if e.get('hash') == h]
        if not matching:
            continue

        entry = matching[0]
        passed, details = apply_promotion_gates(entry, wf_r, bb)

        gate_str = ' '.join([
            f"WF:{'OK' if details['g1_wf'] else 'X'}",
            f"FR:{'OK' if details['g2_friction'] else 'X'}",
            f"NT:{'OK' if details['g3_notop'] else 'X'}",
            f"OL:{'OK' if details['g4_outlier'] else 'X'}",
            f"CC:{'OK' if details['g4_coin'] else 'X'}",
            f"MC:{'OK' if details['g5_mc_p5'] else 'X'}",
            f"CA:{'OK' if details['g6_class_a'] else 'X'}",
            f"WN:{'OK' if details['g7_window'] else 'X'}",
        ])

        if passed:
            promo_entry = {
                'label': wf_r['label'],
                'cfg': wf_r['cfg'],
                'hash': h,
                'wf': wf_r['wf'],
                'score': entry['score'],
                'gates': details,
                'status': 'paper_candidate',
            }
            bb.promote(promo_entry)
            bb.emit('PROMOTED', 'Orchestrator', {'label': wf_r['label'], 'score': entry['score']})
            promoted.append(promo_entry)
            print(f"  PROMOTED: {wf_r['label']} | {gate_str}")
        else:
            print(f"  REJECTED: {wf_r['label']} | {gate_str}")

    print(f"\n  Promoted: {len(promoted)} configs")

    # Champion opslaan (beste config uit deze run)
    run_best = bb.get_best(1)
    if run_best:
        run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        old_champ = load_champion()
        old_score = old_champ.get('score') if old_champ else None
        saved = save_champion(run_best, run_id=run_id)
        if saved:
            print(f"  Champion opgeslagen: {run_best['label']} (score {run_best['score']:.1f})")
            TG.champion_update(
                {'label': run_best['label'], 'score': run_best['score'],
                 'cfg': run_best['cfg'], 'backtest': run_best['backtest'],
                 'mc_block': run_best['mc_block']},
                old_score=old_score)
        else:
            print(f"  Champion NIET opgeslagen (bestaande champion heeft hogere score)")
        # Update promoted status in champion.json
        if promoted and saved:
            for p in promoted:
                if p.get('hash') == run_best.get('hash'):
                    champ = load_champion()
                    if champ:
                        champ['promoted'] = True
                        with open(CHAMPION_FILE, 'w') as f:
                            json.dump(champ, f, indent=2, default=str)
                    break

    # ====== PHASE 6: Final report ======
    generate_report(bb, wf_results, promoted)

    total_time = time.time() - t0_global
    print(f"\n  Totale runtime: {total_time/60:.1f} minuten")
    print(f"  KLAAR!")

    best_label = run_best['label'] if run_best else '?'
    best_score = run_best['score'] if run_best else 0
    TG.run_done(run_idx, n_runs, best_label, best_score,
                len(promoted), total_time / 60)

    # Return voor multi-run aggregatie
    bb._load()
    return {
        'run_idx': run_idx,
        'coin_seed': coin_seed,
        'n_coins': len(coins),
        'status': audit_st,
        'top5': bb.data.get('best_configs', [])[:5],
        'promoted': promoted,
        'total_time': total_time,
        'best_config': bb.get_best(1),
    }


# ============================================================
# SECTION 13: REPORT + MAIN
# ============================================================

def generate_report(bb, wf_results, promoted):
    bb._load()
    print(f"\n{'='*80}")
    print(f"EINDRAPPORT AGENT TEAM V3")
    print(f"{'='*80}")

    print(f"\n  Started: {bb.data.get('started', '?')}")
    print(f"  Configs triaged: {bb.data.get('configs_triaged', 0)}")
    print(f"  Configs killed (early stop): {bb.data.get('configs_killed', 0)}")
    print(f"  Configs fully evaluated: {bb.data.get('configs_evaluated', 0)}")
    print(f"  Failed regions: {len(bb.data.get('failed_regions', []))}")
    print(f"  Scout runtime: {bb.data.get('scout_used_s', 0):.0f}s")
    print(f"  Validator runtime: {bb.data.get('validator_used_s', 0):.0f}s")

    # Agent status
    print(f"\n  Agent Status:")
    for agent, info in bb.data.get('agent_status', {}).items():
        print(f"    {agent}: {info.get('status', '?')}")

    # Top 10
    top = bb.data.get('best_configs', [])[:10]
    if top:
        print(f"\n  TOP 10:")
        print(f"  {'#':>3} {'SC':>5} {'Label':<40} {'Tr':>4} {'P&L':>8} {'WR':>5} "
              f"{'DD':>5} {'Med$':>7} {'P5$':>7} {'CVaR':>7} {'NT$':>7} {'A%':>4}")
        print(f"  {'-'*115}")
        for i, e in enumerate(top):
            bt, mc = e['backtest'], e['mc_block']
            print(f"  {i+1:>3} {e['score']:>5.1f} {e['label']:<40} "
                  f"{bt['trades']:>4} ${bt['pnl']:>+7,.0f} {bt['wr']:>4.0f}% "
                  f"{bt['dd']:>4.0f}% ${mc['median_eq']:>6,.0f} ${mc['p5']:>6,.0f} "
                  f"${mc['cvar95']:>6,.0f} ${e['notop_pnl']:>+6,.0f} "
                  f"{e.get('class_a_ratio',0):>3.0%}")

    # Walk-forward
    if wf_results:
        print(f"\n  WALK-FORWARD + VALIDATION:")
        for r in wf_results:
            wf_s = "OK" if r.get('wf_passed') else "FAIL"
            fr_s = "OK" if r.get('friction_passed') else "FAIL"
            od = r.get('outlier', {})
            wd = r.get('window', {})
            coin_mc = r.get('coin_mc', {})
            coin_str = f" Coin-MC:{coin_mc.get('win_pct',0):.0f}%" if coin_mc else ""
            print(f"    [{wf_s}] {r['label']}: WF {r['wf']} | "
                  f"Friction [{fr_s}] | "
                  f"Outlier top1={od.get('top1_share',0):.1%} | "
                  f"Window worst=${wd.get('worst_window',0):+,.0f}{coin_str}")

    # Promotion queue
    promo = bb.data.get('promotion_queue', [])
    if promo:
        print(f"\n  PROMOTION QUEUE ({len(promo)} paper_candidates):")
        for p in promo:
            print(f"    {p['label']}: WF {p.get('wf','?')} | Score {p.get('score','?')}")

    # Meta insights
    insights = bb.data.get('meta_insights', [])
    if insights:
        print(f"\n  META-INSIGHTS:")
        for ins in insights:
            print(f"    {ins['insight']}")

    # Anomalies
    anomalies = bb.data.get('anomalies', [])
    if anomalies:
        print(f"\n  ANOMALIES:")
        for a in anomalies:
            print(f"    {a['desc']}")

    # Best config detail
    best = bb.get_best(1)
    if best:
        print(f"\n  BESTE CONFIG:")
        print(f"    Label: {best['label']}")
        print(f"    Score: {best['score']}")
        for k, v in sorted(best['cfg'].items()):
            print(f"    {k}: {v}")

    # Friction detail voor top
    friction_results = bb.data.get('friction_results', {})
    if friction_results:
        print(f"\n  FRICTION STRESS (top configs):")
        for h, fr in list(friction_results.items())[:5]:
            matching = [e for e in bb.data.get('best_configs', []) if e.get('hash') == h]
            label = matching[0]['label'] if matching else h
            print(f"    {label}: 1x=${fr.get('1.0x',{}).get('pnl',0):+,.0f} "
                  f"1.5x=${fr.get('1.5x',{}).get('pnl',0):+,.0f} "
                  f"2x=${fr.get('2.0x',{}).get('pnl',0):+,.0f}")

    # Ablation sensitivity ranking
    ablation = bb.data.get('ablation_results', {})
    ranking = ablation.get('_ranking', [])
    if ranking:
        print(f"\n  ABLATION SENSITIVITY RANKING:")
        for i, param in enumerate(ranking):
            if param.startswith('_') or param not in ablation:
                continue
            info = ablation[param]
            print(f"    {i+1}. {param}: sensitivity={info['sensitivity']:.2f} "
                  f"(champion={info['champion_value']})")

    # Save report
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'stats': {
            'triaged': bb.data.get('configs_triaged', 0),
            'killed': bb.data.get('configs_killed', 0),
            'evaluated': bb.data.get('configs_evaluated', 0),
            'failed_regions': len(bb.data.get('failed_regions', [])),
            'scout_s': round(bb.data.get('scout_used_s', 0), 1),
            'validator_s': round(bb.data.get('validator_used_s', 0), 1),
        },
        'top10': top,
        'walk_forward': wf_results,
        'promoted': promoted,
        'promotion_queue': promo,
        'meta_insights': insights,
        'anomalies': anomalies,
        'best_config': best,
        'friction_results': friction_results,
        'outlier_map': bb.data.get('outlier_map', {}),
        'window_dist': bb.data.get('window_dist', {}),
        'ablation_results': ablation,
    }
    with open(RESULTS_FILE, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Resultaten opgeslagen: {RESULTS_FILE}")


def multi_run(args):
    """Draai orchestrator N keer met coin subsampling + cross-run analyse."""
    global TG
    if TG is None:
        TG = TelegramNotifier()

    n_runs = args.runs
    if n_runs <= 1:
        return orchestrator(args)

    print(f"\n{'='*80}")
    print(f"MULTI-RUN MODE: {n_runs} runs met 90% coin subsampling")
    print(f"{'='*80}")
    TG.status(f"MULTI-RUN gestart: {n_runs} runs × {args.hours}h")

    all_run_results = []
    for i in range(n_runs):
        seed = 42 + i
        print(f"\n{'#'*80}")
        print(f"  RUN {i+1}/{n_runs} (seed={seed})")
        print(f"{'#'*80}")
        result = orchestrator(args, coin_seed=seed, run_idx=i)
        all_run_results.append(result)

    # Cross-run consistency analyse
    print(f"\n{'='*80}")
    print(f"CROSS-RUN CONSISTENCY ANALYSE ({n_runs} runs)")
    print(f"{'='*80}")

    config_appearances = {}
    champion_hashes = []

    # Per-run status rapport
    print(f"\n  Per-run status:")
    for r in all_run_results:
        if r is None:
            print(f"    Run ?: None (crash)")
            continue
        st = r.get('status', 'OK')
        seed = r.get('coin_seed', '?')
        n_pr = len(r.get('promoted', []))
        n_t5 = len(r.get('top5', []))
        bc = r.get('best_config')
        best_lbl = bc.get('label', '?')[:30] if bc else '-'
        best_sc = bc.get('score', 0) if bc else 0
        icon = '✅' if st == 'OK' else '⚠️' if st.startswith('WARN') else '❌'
        print(f"    {icon} Run {r['run_idx']+1} (seed={seed}): {st} | "
              f"{n_pr} promoted | top5={n_t5} | best: {best_lbl} ({best_sc:.1f})")

    n_completed = sum(1 for r in all_run_results
                      if r and r.get('status', 'OK') not in ('HARD_FAIL',))
    n_failed = sum(1 for r in all_run_results
                   if r and r.get('status') == 'HARD_FAIL')
    if n_failed:
        print(f"\n  ⚠️  {n_failed}/{n_runs} runs HARD_FAIL, "
              f"{n_completed}/{n_runs} completed")

    for r in all_run_results:
        if r is None or r.get('status') == 'HARD_FAIL':
            continue
        best = r.get('best_config')
        if best:
            champion_hashes.append(best.get('hash', ''))
        for entry in r.get('top5', []):
            h = entry.get('hash', cfg_hash(entry['cfg']))
            if h not in config_appearances:
                config_appearances[h] = {
                    'cfg': entry['cfg'],
                    'labels': [],
                    'scores': [],
                    'run_indices': [],
                }
            config_appearances[h]['labels'].append(entry.get('label', ''))
            config_appearances[h]['scores'].append(entry.get('score', 0))
            config_appearances[h]['run_indices'].append(r['run_idx'])

    consistent_configs = sorted(
        config_appearances.items(),
        key=lambda x: (len(x[1]['run_indices']), max(x[1]['scores'])),
        reverse=True)

    print(f"\n  Configs in top-5 over runs:")
    for h, info in consistent_configs[:10]:
        n_app = len(info['run_indices'])
        avg_sc = sum(info['scores']) / len(info['scores'])
        runs_str = ','.join(str(r+1) for r in info['run_indices'])
        print(f"    [{n_app}/{n_runs}] runs=[{runs_str}] "
              f"avg_score={avg_sc:.1f} {info['labels'][0][:40]}")

    unique_champs = len(set(champion_hashes))
    stability = (1 - (unique_champs - 1) / max(1, n_runs - 1)) * 100 if n_runs > 1 else 100
    print(f"\n  Champion stabiliteit: {unique_champs} unieke champions "
          f"over {n_runs} runs ({stability:.0f}% stabiel)")

    universal = [h for h, info in consistent_configs
                 if len(info['run_indices']) == n_runs]
    if universal:
        print(f"\n  Universele configs (in ALLE {n_runs} runs top-5):")
        for h in universal:
            info = config_appearances[h]
            avg_sc = sum(info['scores']) / len(info['scores'])
            print(f"    {info['labels'][0][:40]}: avg_score={avg_sc:.1f}")
    else:
        print(f"\n  Geen config in ALLE runs top-5")

    # ====== UNIVERSE HOLDOUT CHECK ======
    # Test kandidaten op full universe + complement sets
    candidates_for_holdout = [
        (h, info) for h, info in consistent_configs
        if len(info['run_indices']) >= max(2, n_runs // 2)
    ][:10]

    holdout_results = {}
    if candidates_for_holdout:
        print(f"\n{'='*80}")
        print(f"UNIVERSE HOLDOUT CHECK ({len(candidates_for_holdout)} kandidaten)")
        print(f"{'='*80}")

        # Load full universe data + precompute
        print(f"  Laden full universe...")
        with open(CACHE_FILE) as f:
            full_data = json.load(f)
        full_coins = sorted([k for k in full_data if not k.startswith('_')])
        full_indicators = precompute_all(full_data, full_coins)
        print(f"  Full universe: {len(full_coins)} coins")

        print(f"\n  {'Label':<45} {'Full':>8} {'Full':>5} {'Full':>5} | "
              f"{'Compl':>7} {'Compl':>5}")
        print(f"  {'':<45} {'P&L':>8} {'Tr':>5} {'WR':>5} | "
              f"{'P&L':>7} {'Tr':>5}")
        print(f"  {'-'*95}")

        for h, info in candidates_for_holdout:
            cfg = info['cfg']
            label = info['labels'][0][:45]

            # Full universe backtest
            full_bt = run_backtest(full_indicators, full_coins, cfg,
                                   START_BAR, max(full_indicators[c]['n']
                                   for c in full_coins))
            full_pnl = full_bt['pnl']
            full_tr = full_bt['trades']
            full_wr = full_bt['wr']

            # Per-seed complement backtests
            complement_results = []
            for i in range(n_runs):
                seed = 42 + i
                rng = random.Random(seed)
                n_sample = int(len(full_coins) * 0.9)
                subset = set(rng.sample(full_coins, n_sample))
                complement = sorted(set(full_coins) - subset)
                if len(complement) < 5:
                    continue
                comp_ind = precompute_all(full_data, complement)
                comp_bt = run_backtest(comp_ind, complement, cfg,
                                        START_BAR, max(comp_ind[c]['n']
                                        for c in complement))
                complement_results.append({
                    'seed': seed,
                    'n_coins': len(complement),
                    'pnl': comp_bt['pnl'],
                    'trades': comp_bt['trades'],
                    'wr': comp_bt['wr'],
                })

            avg_comp_pnl = (sum(r['pnl'] for r in complement_results)
                            / max(1, len(complement_results)))
            avg_comp_tr = (sum(r['trades'] for r in complement_results)
                           / max(1, len(complement_results)))

            holdout_results[h] = {
                'label': info['labels'][0],
                'cfg': cfg,
                'n_appearances': len(info['run_indices']),
                'full': {'pnl': full_pnl, 'trades': full_tr, 'wr': full_wr},
                'complement': complement_results,
                'avg_complement_pnl': avg_comp_pnl,
            }

            print(f"  {label:<45} ${full_pnl:>+7,.0f} {full_tr:>5} "
                  f"{full_wr:>4.0f}% | ${avg_comp_pnl:>+6,.0f} "
                  f"{avg_comp_tr:>4.0f}")

        # Overfit flag
        print(f"\n  OVERFIT CHECK:")
        tg_holdout_batch = []
        for h, hr in holdout_results.items():
            full_pnl = hr['full']['pnl']
            comp_pnl = hr['avg_complement_pnl']
            if full_pnl > 0 and comp_pnl < 0:
                flag = "⚠️  MOGELIJK OVERFIT"
                icon = "⚠️"
            elif full_pnl > 0 and comp_pnl > 0:
                flag = "✅ ROBUUST"
                icon = "✅"
            elif full_pnl <= 0:
                flag = "❌ VERLIESGEVEND"
                icon = "❌"
            else:
                flag = "⚠️  GEMENGD"
                icon = "⚠️"
            print(f"    {hr['label'][:40]}: full=${full_pnl:+,.0f} "
                  f"complement=${comp_pnl:+,.0f} → {flag}")
            tg_holdout_batch.append({
                'label': hr['label'], 'full_pnl': full_pnl,
                'complement_pnl': comp_pnl, 'verdict_icon': icon,
            })
        # 1 gebatcht TG bericht ipv per-candidate spam
        TG.holdout_batch(tg_holdout_batch)
    else:
        print(f"\n  Geen kandidaten voor holdout check "
              f"(niemand in ≥{max(2, n_runs//2)} runs top-5)")

    # ====== ACCEPTANCE CRITERIA CHECK ======
    print(f"\n{'='*80}")
    print(f"ACCEPTANCE CRITERIA CHECK")
    print(f"{'='*80}")

    accepted = []
    for r in all_run_results:
        if r is None or r.get('status') == 'HARD_FAIL':
            continue
        for p in r.get('promoted', []):
            h = p.get('hash', '')
            if h not in config_appearances:
                continue
            info = config_appearances[h]
            if h not in [a['hash'] for a in accepted]:
                # Check: in ≥4/5 runs top-5 (of proportioneel)
                threshold = max(2, int(n_runs * 0.8))
                if len(info['run_indices']) >= threshold:
                    accepted.append({
                        'hash': h,
                        'label': info['labels'][0],
                        'cfg': info['cfg'],
                        'n_top5': len(info['run_indices']),
                        'avg_score': sum(info['scores']) / len(info['scores']),
                        'holdout': holdout_results.get(h, {}),
                    })

    if accepted:
        print(f"\n  GEACCEPTEERDE CONFIGS ({len(accepted)}):")
        for a in accepted:
            hr = a.get('holdout', {})
            full_pnl = hr.get('full', {}).get('pnl', '?')
            comp_pnl = hr.get('avg_complement_pnl', '?')
            print(f"    {a['label'][:40]}: top5 in {a['n_top5']}/{n_runs} runs, "
                  f"avg_score={a['avg_score']:.1f}, "
                  f"full=${full_pnl:+,.0f}, complement=${comp_pnl:+,.0f}"
                  if isinstance(full_pnl, (int, float)) else
                  f"    {a['label'][:40]}: top5 in {a['n_top5']}/{n_runs} runs, "
                  f"avg_score={a['avg_score']:.1f}")
    else:
        print(f"\n  Geen config voldoet aan acceptance criteria "
              f"(≥{max(2, int(n_runs * 0.8))}/{n_runs} runs top-5 + promoted)")

    # Save cross-run summary
    cross_run = {
        'n_runs': n_runs,
        'champion_stability_pct': round(stability, 1),
        'per_run': [],
        'consistent_configs': [],
        'universal_configs': universal,
        'holdout_results': {h: {k: v for k, v in hr.items() if k != 'cfg'}
                           for h, hr in holdout_results.items()},
        'accepted': accepted,
    }
    for r in all_run_results:
        if r is None:
            continue
        cross_run['per_run'].append({
            'run_idx': r['run_idx'],
            'coin_seed': r.get('coin_seed'),
            'n_coins': r['n_coins'],
            'status': r.get('status', 'OK'),
            'total_time': round(r.get('total_time', 0), 1),
            'best_label': r.get('best_config', {}).get('label', '?') if r.get('best_config') else '?',
            'best_score': r.get('best_config', {}).get('score', 0) if r.get('best_config') else 0,
            'n_promoted': len(r.get('promoted', [])),
        })
    for h, info in consistent_configs[:20]:
        cross_run['consistent_configs'].append({
            'hash': h,
            'label': info['labels'][0],
            'cfg': info['cfg'],
            'n_appearances': len(info['run_indices']),
            'runs': info['run_indices'],
            'avg_score': round(sum(info['scores']) / len(info['scores']), 1),
            'min_score': round(min(info['scores']), 1),
            'max_score': round(max(info['scores']), 1),
        })
    with open(RESULTS_FILE, 'w') as f:
        json.dump(cross_run, f, indent=2, default=str)
    print(f"\n  Cross-run resultaten opgeslagen: {RESULTS_FILE}")

    # Telegram samenvatting
    top_cfg_str = None
    if consistent_configs:
        top_h, top_info = consistent_configs[0]
        top_cfg_str = (f"{top_info['labels'][0][:30]} "
                       f"[{len(top_info['run_indices'])}/{n_runs}]")
    TG.cross_run_summary(n_runs, stability, len(universal),
                         len(accepted), top_config=top_cfg_str)

    return cross_run


def main():
    parser = argparse.ArgumentParser(description='Agent Team V3 — Wetenschappelijk Optimizer')
    parser.add_argument('--quick', action='store_true', help='Snelle test (~5-10 min)')
    parser.add_argument('--hours', type=float, default=4.0, help='Max runtime in uren')
    parser.add_argument('--runs', type=int, default=1, help='Multi-run met coin subsampling (90%%)')
    args = parser.parse_args()
    multi_run(args)


if __name__ == '__main__':
    main()

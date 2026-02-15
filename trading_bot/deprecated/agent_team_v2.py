#!/usr/bin/env python3
"""
AGENT TEAM V2 — Wetenschappelijk Multi-Agent Zoeksysteem
=========================================================
Architectuur:
  Blackboard    — gedeeld geheugen: best_configs, failed_regions, events, anomalies
  Event Bus     — agents publiceren events (NEW_BEST, WF_FAIL, SANITY_FAIL, etc.)
  Pipeline      — Generate → Triage → Validate → Stress-test → Promote

Agents:
  Orchestrator  — verdeelt budget, bewaakt gates, beslist vervolg
  Combiner      — 2/3-param interactie-jacht
  ExitArchitect — exit families (trail/hybrid/tpsl) met bewezen entry
  Validator     — walk-forward (leakage-safe, indicators herberekend per fold)
  Auditor       — sanity checks, equity invariants, leakage detectie
  MetaLearner   — analyseert leaderboard, detecteert plateaus/cliffs

Verbeteringen vs v1:
  ✅ Blackboard + event bus (echte inter-agent communicatie)
  ✅ Leakage-safe WF (causal indicator pipeline per fold)
  ✅ Early stopping (DD cap, PF gate, trade count minimum)
  ✅ Triage runner (quick subset → alleen survivors naar full)
  ✅ Score gates + Pareto (harde drempels + multi-objective)
  ✅ Block bootstrap MC + coin subsampling (differentieert wél)
  ✅ Exit class analyse (klasse A/B bewust in scoring)
  ✅ Promotion pipeline (research → paper → live)

Gebruik:
    python agent_team_v2.py                 # Volledige run (~2-4 uur)
    python agent_team_v2.py --quick         # Snelle test (~15 min)
    python agent_team_v2.py --hours 8       # Max runtime
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

# ============================================================
# CONSTANTS
# ============================================================
CACHE_FILE = BASE_DIR / 'candle_cache_532.json'
BLACKBOARD_FILE = BASE_DIR / 'agent_team_v2_blackboard.json'
RESULTS_FILE = BASE_DIR / 'agent_team_v2_results.json'
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
GATE_MIN_WF_RATIO = 0.5      # minstens helft van folds winstgevend
GATE_NOTOP_PNL_MIN = -200    # zonder beste trade niet meer dan $200 verlies

# --- Bekende baseline ---
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


# ============================================================
# CONFIG HASHING
# ============================================================
def cfg_hash(cfg):
    """Deterministic hash van een config dict."""
    s = json.dumps(cfg, sort_keys=True)
    return hashlib.md5(s.encode()).hexdigest()[:12]


# ============================================================
# PRECOMPUTE (causal — nooit toekomst zien)
# ============================================================
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


# ============================================================
# ENTRY CHECK
# ============================================================
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
# REALISTIC EQUITY BACKTEST + EARLY STOPPING
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
                 early_stop_dd=None, early_stop_min_trades=None):
    """
    Realistic equity backtest met optionele early stopping.
    early_stop_dd: abort als DD > dit percentage
    early_stop_min_trades: na dit aantal trades checken of PF < 1
    """
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
                if tl > 0 and tw / tl < 0.8:  # PF < 0.8 na N trades = kill
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
                tm_bars = cfg.get('tm_bars', 15)
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
                        be_level = entry_price * (1 + KRAKEN_FEE * 2)
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
            fees = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
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

    # Close remaining
    for pair, pos in list(positions.items()):
        ind = indicators[pair]
        last_idx = min(ind['n']-1, max_bars-1)
        lp = ind['closes'][last_idx]
        gross = (lp - pos.entry_price) / pos.entry_price * pos.size_usd
        fees = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
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
    exit_classes = {'A': {}, 'B': {}}  # A=winst-exits, B=schadebeperkers
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
# MONTE CARLO — Block Bootstrap + Coin Subsampling
# ============================================================

def monte_carlo_block(trade_pnl_pcts, n_sims=3000, block_size=5, seed=42):
    """
    Block bootstrap MC: sample blokken van trades (niet individueel).
    Vangt regime-dependence op.
    """
    rng = random.Random(seed)
    n_trades = len(trade_pnl_pcts)
    if n_trades < 5:
        return _empty_mc(n_trades)

    # Maak blokken
    blocks = []
    for i in range(0, n_trades, block_size):
        blocks.append(trade_pnl_pcts[i:i+block_size])
    n_blocks = len(blocks)
    target_trades = n_trades  # Houd zelfde aantal trades

    final_equities = []
    broke_count = 0

    for _ in range(n_sims):
        # Sample random blokken tot we genoeg trades hebben
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
    """
    MC op coin-subsets: random 70% van coins → meet stabiliteit over universum.
    Duurder maar onthult of winst van paar coins afhangt.
    """
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
    # CVaR(95): gemiddelde van de slechtste 5%
    worst_5pct = final_equities[:max(1, int(n * 0.05))]
    cvar95 = sum(worst_5pct) / len(worst_5pct)
    return {
        'win_pct': winners / n * 100,
        'median_equity': final_equities[n // 2],
        'mean_equity': sum(final_equities) / n,
        'p5': final_equities[int(n * 0.05)],
        'p95': final_equities[int(n * 0.95)],
        'cvar95': cvar95,
        'broke_pct': broke_count / n * 100,
        'n_sims': n_sims, 'n_trades': n_trades,
    }


# ============================================================
# BLACKBOARD — gedeeld geheugen
# ============================================================

class Blackboard:
    """Centraal geheugen voor alle agents. Persist naar JSON."""

    def __init__(self, filepath=BLACKBOARD_FILE):
        self.filepath = filepath
        self.data = {
            'started': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'best_configs': [],         # Top-N configs met volledige metrics
            'failed_regions': [],       # Parameter-regio's die bewezen slecht zijn
            'events': [],               # Event log
            'anomalies': [],            # Sanity flags
            'promotion_queue': [],      # Configs die gates gepasseerd zijn
            'agent_status': {},
            'configs_evaluated': 0,
            'configs_triaged': 0,
            'configs_killed': 0,
            'meta_insights': [],        # MetaLearner findings
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
        """Publiceer event op de bus."""
        self._load()
        event = {
            'type': event_type,
            'agent': agent,
            'time': datetime.now().strftime('%H:%M:%S'),
            'data': data_dict or {},
        }
        self.data.setdefault('events', []).append(event)
        self._save()

    def get_events(self, event_type=None, since_idx=0):
        """Lees events (optioneel gefilterd)."""
        self._load()
        events = self.data.get('events', [])[since_idx:]
        if event_type:
            events = [e for e in events if e['type'] == event_type]
        return events

    # --- Best configs ---
    def post_config(self, entry):
        """Post een geëvalueerde config. Dedupliceer op hash."""
        self._load()
        self.data['configs_evaluated'] = self.data.get('configs_evaluated', 0) + 1
        h = entry.get('hash', cfg_hash(entry['cfg']))

        # Dedup
        existing = [i for i, e in enumerate(self.data['best_configs'])
                     if e.get('hash') == h]
        if existing:
            idx = existing[0]
            if entry['score'] > self.data['best_configs'][idx]['score']:
                self.data['best_configs'][idx] = entry
        else:
            self.data['best_configs'].append(entry)

        # Sort + cap
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
        """Markeer een parameter-regio als niet-belovend."""
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


# ============================================================
# TRIAGE — goedkope pre-screening
# ============================================================

def triage(indicators, coins, cfg, bb):
    """
    Snelle triage: backtest met early stopping.
    Returns None als config killed, anders backtest result.
    """
    bt = run_backtest(indicators, coins, cfg,
                      early_stop_dd=60.0, early_stop_min_trades=15)
    bb.inc_triaged()

    if bt['early_stopped'] or bt['trades'] < 5 or bt['broke']:
        bb.inc_killed()
        return None

    # Gate: minimum trades
    if bt['trades'] < GATE_MIN_TRADES // 2:  # Halve gate voor triage
        bb.inc_killed()
        return None

    # Gate: max DD
    if bt['dd'] > GATE_MAX_DD + 10:  # Iets ruimer voor triage
        bb.inc_killed()
        return None

    return bt


# ============================================================
# FULL EVALUATION — backtest + block MC + scoring + gates
# ============================================================

def evaluate(indicators, coins, cfg, label, bb, n_sims=3000):
    """
    Volledige evaluatie met gates + Pareto scoring.
    Returns None als gates niet gepasseerd.
    """
    bt = run_backtest(indicators, coins, cfg)

    # --- Hard gates ---
    if bt['trades'] < GATE_MIN_TRADES:
        return None
    if bt['dd'] > GATE_MAX_DD:
        return None

    pnl_pcts = [t['pnl_pct'] for t in bt['trade_list']]

    # NoTop check
    if len(pnl_pcts) > 1:
        sorted_pcts = sorted(pnl_pcts, reverse=True)
        notop_pnl = sum(sorted_pcts[1:])  # Som zonder beste (in %)
        # Bereken notop in dollars (realistic): verwijder beste trade pnl
        sorted_trades = sorted(bt['trade_list'], key=lambda t: t['pnl'], reverse=True)
        notop_dollar = bt['pnl'] - sorted_trades[0]['pnl']
    else:
        notop_pnl = 0
        notop_dollar = 0

    if notop_dollar < GATE_NOTOP_PNL_MIN:
        return None

    # --- Block bootstrap MC ---
    mc_block = monte_carlo_block(pnl_pcts, n_sims=n_sims, block_size=5)

    # --- Pareto score (multi-objective) ---
    # Beloon: median equity, p5 (downside), notop, trade count
    # Bestraf: DD, ZEUS-afhankelijkheid
    median_s = min(100, max(0, (mc_block['median_equity'] - 1000) / 80))  # $1K-$9K
    p5_s = min(100, max(0, (mc_block['p5'] - 500) / 40))                 # Downside
    cvar_s = min(100, max(0, (mc_block['cvar95'] - 500) / 30))            # Worst case
    notop_s = min(100, max(0, (notop_dollar + 500) / 30))                 # Anti-fragility
    trade_s = min(100, bt['trades'] / 0.6)                                 # Significantie
    dd_s = max(0, 100 - bt['dd'] * 2.5)                                    # DD penalty

    # Klasse A dominantie bonus: als >60% P&L uit klasse A exits → bonus
    class_a_pnl = sum(v['pnl'] for v in bt['exit_classes'].get('A', {}).values())
    total_abs_pnl = abs(bt['pnl']) if bt['pnl'] != 0 else 1
    class_a_ratio = class_a_pnl / total_abs_pnl if total_abs_pnl > 0 else 0
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
        'score': round(score, 1),
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
# AGENT: Auditor — sanity + invariants
# ============================================================

def agent_auditor(indicators, coins, bb):
    """Sanity check + equity invariants."""
    name = 'Auditor'
    bb.update_agent(name, 'RUNNING')
    print(f"\n{'='*80}\n🔍 AUDITOR: Sanity Check + Invariants\n{'='*80}")

    # 1. Baseline check
    bt = run_backtest(indicators, coins, BASELINE_CFG)
    trade_ok = abs(bt['trades'] - BASELINE_EXPECTED_TRADES) <= 5
    pnl_ok = bt['pnl'] >= BASELINE_EXPECTED_PNL_MIN

    print(f"  Baseline: {bt['trades']} trades (verwacht ~{BASELINE_EXPECTED_TRADES}), "
          f"${bt['pnl']:+,.0f} (verwacht >= ${BASELINE_EXPECTED_PNL_MIN})")

    if not (trade_ok and pnl_ok):
        bb.flag_anomaly(f"Baseline mismatch: {bt['trades']}tr, ${bt['pnl']:+,.0f}", name)
        bb.emit('SANITY_FAIL', name, {'trades': bt['trades'], 'pnl': bt['pnl']})
        print(f"  ❌ SANITY FAIL")
        bb.update_agent(name, 'FAILED: sanity check')
        return False

    # 2. Equity invariant: final_equity moet consistent zijn met trade P&L
    sum_pnl = sum(t['pnl'] for t in bt['trade_list'])
    eq_diff = abs(bt['final_equity'] - (INITIAL_CAPITAL + sum_pnl))
    if eq_diff > 1.0:
        bb.flag_anomaly(f"Equity mismatch: diff=${eq_diff:.2f}", name)
        print(f"  ⚠️ Equity invariant: diff=${eq_diff:.2f}")

    # 3. No future leakage check: run op eerste helft, moet niet weten van tweede helft
    max_bars = max(indicators[p]['n'] for p in coins if p in indicators)
    mid = max_bars // 2
    bt_first = run_backtest(indicators, coins, BASELINE_CFG, end_bar=mid)
    bt_full = run_backtest(indicators, coins, BASELINE_CFG)
    # Trades in eerste helft moeten identiek zijn
    first_half_trades_full = [t for t in bt_full['trade_list'] if t['exit_bar'] <= mid]
    if len(first_half_trades_full) != bt_first['trades']:
        bb.flag_anomaly(f"Possible leakage: first_half={bt_first['trades']} vs full_first={len(first_half_trades_full)}", name)
        print(f"  ⚠️ Leakage hint: {bt_first['trades']} vs {len(first_half_trades_full)}")

    print(f"  ✅ SANITY CHECK PASSED")
    bb.emit('SANITY_PASS', name)
    bb.update_agent(name, 'DONE: all checks passed')
    return True


# ============================================================
# AGENT: Combiner — 2/3-param interactie-jacht
# ============================================================

def agent_combiner(indicators, coins, bb, quick=False):
    """Systematisch 2-param combinaties + selectieve 3-param."""
    name = 'Combiner'
    bb.update_agent(name, 'RUNNING')
    print(f"\n{'='*80}\n🔗 COMBINER: Param-interactie zoeker\n{'='*80}")

    best = bb.get_best_cfg()
    evaluated = 0
    improved = 0
    t0 = time.time()

    PARAMS = {
        'vol_spike_mult': [2.0, 2.5, 3.0, 3.5, 4.0, 5.0] if not quick else [2.5, 3.0, 4.0],
        'rsi_max':         [30, 35, 38, 40, 42, 45, 48] if not quick else [35, 40, 42, 45],
        'rsi_rec_target':  [40, 42, 44, 45, 46, 47, 48] if not quick else [42, 45, 47],
        'time_max_bars':   [4, 6, 8, 10, 12, 15] if not quick else [5, 6, 8, 10],
        'atr_mult':        [1.5, 1.75, 2.0, 2.5, 3.0] if not quick else [1.5, 2.0, 2.5],
        'be_trigger':      [1.5, 2.0, 2.5, 3.0, 4.0] if not quick else [1.5, 2.0, 3.0],
        'max_stop_pct':    [8.0, 10.0, 12.0, 15.0, 20.0] if not quick else [8.0, 12.0, 15.0],
    }
    param_names = list(PARAMS.keys())

    # --- Phase 1: 2-param grid ---
    print(f"  Phase 1: 2-param grid")
    for i in range(len(param_names)):
        for j in range(i+1, len(param_names)):
            p1, p2 = param_names[i], param_names[j]
            region = f"{p1}x{p2}"
            if bb.is_region_failed(region):
                continue
            region_hits = 0
            for v1 in PARAMS[p1]:
                for v2 in PARAMS[p2]:
                    if v1 == best.get(p1) and v2 == best.get(p2):
                        continue
                    cfg = deepcopy(best)
                    cfg[p1] = v1
                    cfg[p2] = v2
                    bt = triage(indicators, coins, cfg, bb)
                    evaluated += 1
                    if bt is None:
                        continue
                    if bt['trades'] < 15 and bt['pnl'] < 200:
                        continue
                    label = f"comb-{p1}={v1}-{p2}={v2}"
                    entry = evaluate(indicators, coins, cfg, label, bb)
                    if entry is None:
                        continue
                    is_best = bb.post_config(entry)
                    if is_best:
                        improved += 1
                        bb.emit('NEW_BEST_FOUND', name, {'label': label, 'score': entry['score']})
                        print(f"  🏆 NEW BEST: {label}")
                        print(f"     {fmt(entry)}")
                    elif entry['score'] >= 80:
                        region_hits += 1

            if region_hits == 0 and evaluated > 10:
                bb.mark_failed(region, name)

            if evaluated % 100 == 0:
                elapsed = time.time() - t0
                print(f"  ... {evaluated} eval | {improved} improved | {elapsed:.0f}s")

    # --- Phase 2: 3-param rond belovende 2-param combos ---
    print(f"\n  Phase 2: 3-param extensies op top-5")
    top5 = bb.get_best(5)
    if isinstance(top5, dict):
        top5 = [top5]
    for entry in (top5 or []):
        base = deepcopy(entry['cfg'])
        for param in param_names:
            for val in PARAMS[param]:
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
                label = f"3p-{entry.get('label','top')}-{param}={val}"
                result = evaluate(indicators, coins, cfg, label, bb)
                if result is None:
                    continue
                is_best = bb.post_config(result)
                if is_best:
                    improved += 1
                    bb.emit('NEW_BEST_FOUND', name, {'label': label, 'score': result['score']})
                    print(f"  🏆 3P NEW BEST: {label}")
                    print(f"     {fmt(result)}")

    elapsed = time.time() - t0
    print(f"\n  Combiner klaar: {evaluated} eval, {improved} improved, {elapsed:.0f}s")
    bb.update_agent(name, f'DONE: {evaluated} eval, {improved} improved')


# ============================================================
# AGENT: ExitArchitect — exit families
# ============================================================

def agent_exit_architect(indicators, coins, bb, quick=False):
    """Test exit families met bewezen entry-basis."""
    name = 'ExitArchitect'
    bb.update_agent(name, 'RUNNING')
    print(f"\n{'='*80}\n🏗️ EXIT ARCHITECT: Exit type verkenning\n{'='*80}")

    best = bb.get_best_cfg()
    evaluated = 0
    improved = 0
    t0 = time.time()

    # Basis entry params (bewezen)
    base_entry = {k: best[k] for k in ['rsi_max', 'vol_spike_mult', 'vol_confirm']
                  if k in best}

    # --- hybrid_notrl ---
    print(f"  Phase A: hybrid_notrl")
    for tm in ([6, 8, 10, 12, 15, 20, 25] if not quick else [8, 12, 20]):
        for ms in ([10, 12, 15, 20, 25] if not quick else [12, 15, 20]):
            for rr in ([False, 42, 45, 47] if not quick else [45, False]):
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
                    bb.emit('EXIT_TYPE_BREAKTHROUGH', name, {'type': 'hybrid_notrl', 'score': entry['score']})
                    print(f"  🏆 {label}: {fmt(entry)}")
                elif entry['score'] >= 75:
                    print(f"  ✅ {label}: SC:{entry['score']:.1f}")

    # --- tp_sl ---
    print(f"\n  Phase B: tp_sl")
    for tp in ([5, 7, 8, 10, 12, 15] if not quick else [7, 10]):
        for sl in ([8, 10, 15, 20] if not quick else [10, 15]):
            for tm in ([8, 10, 15, 20, 999] if not quick else [10, 15]):
                cfg = {**base_entry, 'exit_type': 'tp_sl',
                       'tp_pct': tp, 'sl_pct': sl, 'tm_bars': tm,
                       'max_pos': 1}
                label = f"tpsl-tp{tp}-sl{sl}-tm{tm}"
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
                    bb.emit('EXIT_TYPE_BREAKTHROUGH', name, {'type': 'tp_sl', 'score': entry['score']})
                    print(f"  🏆 {label}: {fmt(entry)}")
                elif entry['score'] >= 75:
                    print(f"  ✅ {label}: SC:{entry['score']:.1f}")

    # --- max_pos variaties ---
    print(f"\n  Phase C: max_pos variaties")
    for entry in (bb.get_best(5) or []):
        if isinstance(entry, dict) and 'cfg' in entry:
            for mp in [1, 2, 3]:
                cfg = deepcopy(entry['cfg'])
                cfg['max_pos'] = mp
                label = f"mp{mp}-{entry.get('label','top')[:30]}"
                bt = triage(indicators, coins, cfg, bb)
                evaluated += 1
                if bt is not None:
                    result = evaluate(indicators, coins, cfg, label, bb)
                    if result:
                        bb.post_config(result)

    elapsed = time.time() - t0
    print(f"\n  ExitArchitect klaar: {evaluated} eval, {improved} improved, {elapsed:.0f}s")
    bb.update_agent(name, f'DONE: {evaluated} eval, {improved} improved')


# ============================================================
# AGENT: Validator — walk-forward (leakage-safe)
# ============================================================

def agent_validator(indicators, coins, data, bb, quick=False):
    """Walk-forward met leakage-safe indicator herberekening per fold."""
    name = 'Validator'
    bb.update_agent(name, 'RUNNING')
    print(f"\n{'='*80}\n✅ VALIDATOR: Walk-Forward (leakage-safe)\n{'='*80}")

    n_folds = 5 if not quick else 3
    t0 = time.time()

    # Top configs + baselines
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

            # LEAKAGE-SAFE: herbereken indicators tot fold_end (causal)
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
        passed = wf_ratio >= GATE_MIN_WF_RATIO

        result = {
            'label': cfg_label, 'cfg': cfg,
            'wf': f"{folds_profitable}/{n_folds}",
            'wf_ratio': wf_ratio, 'passed': passed,
            'folds': fold_details,
        }
        results.append(result)

        # Emit event
        if not passed:
            bb.emit('WF_FAILED', name, {'label': cfg_label, 'wf': f"{folds_profitable}/{n_folds}"})
        else:
            bb.emit('WF_PASSED', name, {'label': cfg_label, 'wf': f"{folds_profitable}/{n_folds}"})
            # Promote
            bb.promote({'label': cfg_label, 'cfg': cfg, 'wf': f"{folds_profitable}/{n_folds}"})

        status = "✅" if passed else "❌"
        test_pnls = [f['test_pnl'] for f in fold_details]
        print(f"  {status} {cfg_label}: WF {folds_profitable}/{n_folds} | "
              f"Test P&L: {test_pnls}")

    # Coin subsampling MC op top-3 die WF passeerden
    passed_cfgs = [r for r in results if r['passed']]
    if passed_cfgs:
        print(f"\n  Coin-subsample MC op {min(3, len(passed_cfgs))} WF-passers...")
        for r in passed_cfgs[:3]:
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
    print(f"\n  Validator klaar: {len(configs_to_test)} configs × {n_folds} folds, {elapsed:.0f}s")
    bb.update_agent(name, f'DONE: {len(configs_to_test)} configs')
    return results


# ============================================================
# AGENT: MetaLearner — analyse + plateau detectie
# ============================================================

def agent_meta_learner(bb):
    """Analyseert leaderboard, detecteert patronen."""
    name = 'MetaLearner'
    bb.update_agent(name, 'RUNNING')
    print(f"\n{'='*80}\n🧠 META-LEARNER: Leaderboard analyse\n{'='*80}")

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
        if top5_spread < 2.0:
            insight = f"PLATEAU: top-5 spread = {top5_spread:.1f} (< 2.0). Zoekruimte is uitgeput rond huidig optimum."
            bb.post_insight(insight, name)
            print(f"  📊 {insight}")

    # 2. Param analyse: welke params komen het vaakst voor in top-10?
    param_freq = {}
    for e in top[:10]:
        cfg = e['cfg']
        for k, v in cfg.items():
            key = f"{k}={v}"
            param_freq[key] = param_freq.get(key, 0) + 1

    # Params die in >70% van top-10 zitten = "stabiel"
    stable = [(k, v) for k, v in param_freq.items() if v >= 7]
    if stable:
        insight = f"STABLE PARAMS (>70% top-10): {', '.join(k for k,v in stable)}"
        bb.post_insight(insight, name)
        print(f"  📊 {insight}")

    # 3. Exit class analyse: domineert klasse A?
    for e in top[:5]:
        ec = e.get('exit_classes', {})
        a_pnl = sum(v['pnl'] for v in ec.get('A', {}).values())
        b_pnl = sum(v['pnl'] for v in ec.get('B', {}).values())
        total = a_pnl + abs(b_pnl) if (a_pnl + abs(b_pnl)) > 0 else 1
        a_share = a_pnl / total
        if a_share > 0.8:
            insight = f"KLASSE A DOMINANT ({e.get('label','')}): {a_share:.0%} van P&L uit winst-exits"
            bb.post_insight(insight, name)
            print(f"  📊 {insight}")

    # 4. Failed regions summary
    bb._load()
    failed = bb.data.get('failed_regions', [])
    if failed:
        print(f"  📊 Failed regions: {len(failed)} regio's gemarkeerd als niet-belovend")

    # 5. Efficiency stats
    total_eval = bb.data.get('configs_evaluated', 0)
    total_triage = bb.data.get('configs_triaged', 0)
    total_killed = bb.data.get('configs_killed', 0)
    if total_triage > 0:
        kill_rate = total_killed / total_triage * 100
        print(f"  📊 Triage efficiency: {total_killed}/{total_triage} killed ({kill_rate:.0f}%) "
              f"— {total_eval} full evaluations")

    bb.update_agent(name, 'DONE')


# ============================================================
# ORCHESTRATOR — verdeelt werk
# ============================================================

def run_all(args):
    print(f"{'='*80}")
    print(f"AGENT TEAM V2 — Wetenschappelijk Multi-Agent Optimizer")
    print(f"{'='*80}")
    print(f"  Mode: {'QUICK' if args.quick else 'FULL'}")
    print(f"  Max runtime: {args.hours}h")
    print(f"  Start: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Load data
    print(f"\n  Laden data...")
    with open(CACHE_FILE) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith('_')])
    print(f"  {len(coins)} coins geladen")

    # Precompute (full dataset voor search agents)
    print(f"  Precomputing indicators...")
    t0 = time.time()
    indicators = precompute_all(data, coins)
    print(f"  Precompute: {time.time()-t0:.1f}s")

    # Blackboard
    bb = Blackboard()
    deadline = time.time() + args.hours * 3600

    # === PHASE 1: Auditor ===
    if not agent_auditor(indicators, coins, bb):
        print(f"\n  ❌ ABORT: Auditor sanity check failed")
        sys.exit(1)

    # Seed blackboard met BEST_KNOWN
    print(f"\n  Seeding blackboard met BEST_KNOWN...")
    entry = evaluate(indicators, coins, BEST_KNOWN, 'BEST_KNOWN_sweep', bb)
    if entry:
        bb.post_config(entry)
        print(f"  Startpunt: {fmt(entry)}")
    entry2 = evaluate(indicators, coins, BASELINE_CFG, 'BASELINE_V5+VolSpk3', bb)
    if entry2:
        bb.post_config(entry2)

    # === PHASE 2: Generate (Combiner + ExitArchitect) ===
    if time.time() < deadline:
        agent_combiner(indicators, coins, bb, quick=args.quick)

    if time.time() < deadline:
        agent_exit_architect(indicators, coins, bb, quick=args.quick)

    # === PHASE 3: Meta-analyse ===
    agent_meta_learner(bb)

    # === PHASE 4: Validate (walk-forward) ===
    wf_results = []
    if time.time() < deadline:
        wf_results = agent_validator(indicators, coins, data, bb, quick=args.quick)

    # === PHASE 5: Final report ===
    generate_report(bb, wf_results)

    total = time.time() - t0
    print(f"\n  Totale runtime: {total/60:.1f} minuten")
    print(f"  KLAAR!")


# ============================================================
# REPORT
# ============================================================

def generate_report(bb, wf_results):
    bb._load()
    print(f"\n{'='*80}")
    print(f"EINDRAPPORT AGENT TEAM V2")
    print(f"{'='*80}")

    print(f"\n  Started: {bb.data.get('started', '?')}")
    print(f"  Configs triaged: {bb.data.get('configs_triaged', 0)}")
    print(f"  Configs killed (early stop): {bb.data.get('configs_killed', 0)}")
    print(f"  Configs fully evaluated: {bb.data.get('configs_evaluated', 0)}")
    print(f"  Failed regions: {len(bb.data.get('failed_regions', []))}")

    # Agent status
    print(f"\n  Agent Status:")
    for agent, info in bb.data.get('agent_status', {}).items():
        print(f"    {agent}: {info.get('status', '?')}")

    # Top 10
    top = bb.data.get('best_configs', [])[:10]
    if top:
        print(f"\n  TOP 10 (gate-passing configs):")
        print(f"  {'#':>3} {'SC':>5} {'Label':<40} {'Tr':>4} {'P&L':>8} {'WR':>5} "
              f"{'DD':>5} {'Med$':>7} {'P5$':>7} {'CVaR':>7} {'NT$':>7} {'A%':>4}")
        print(f"  {'-'*110}")
        for i, e in enumerate(top):
            bt, mc = e['backtest'], e['mc_block']
            print(f"  {i+1:>3} {e['score']:>5.1f} {e['label']:<40} "
                  f"{bt['trades']:>4} ${bt['pnl']:>+7,.0f} {bt['wr']:>4.0f}% "
                  f"{bt['dd']:>4.0f}% ${mc['median_eq']:>6,.0f} ${mc['p5']:>6,.0f} "
                  f"${mc['cvar95']:>6,.0f} ${e['notop_pnl']:>+6,.0f} "
                  f"{e.get('class_a_ratio',0):>3.0%}")

    # Walk-forward
    if wf_results:
        print(f"\n  WALK-FORWARD RESULTATEN:")
        for r in wf_results:
            status = "✅" if r['passed'] else "❌"
            coin_mc = r.get('coin_mc', {})
            coin_str = f" | Coin-MC: {coin_mc.get('win_pct',0):.0f}%" if coin_mc else ""
            print(f"    {status} {r['label']}: {r['wf']}{coin_str}")

    # Promotion queue
    promo = bb.data.get('promotion_queue', [])
    if promo:
        print(f"\n  PROMOTION QUEUE ({len(promo)} configs ready for paper trading):")
        for p in promo:
            print(f"    → {p['label']}: WF {p['wf']}")

    # Meta insights
    insights = bb.data.get('meta_insights', [])
    if insights:
        print(f"\n  META-INSIGHTS:")
        for ins in insights:
            print(f"    💡 {ins['insight']}")

    # Anomalies
    anomalies = bb.data.get('anomalies', [])
    if anomalies:
        print(f"\n  ⚠️ ANOMALIES:")
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

    # Save
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'stats': {
            'triaged': bb.data.get('configs_triaged', 0),
            'killed': bb.data.get('configs_killed', 0),
            'evaluated': bb.data.get('configs_evaluated', 0),
            'failed_regions': len(bb.data.get('failed_regions', [])),
        },
        'top10': top,
        'walk_forward': wf_results,
        'promotion_queue': promo,
        'meta_insights': insights,
        'anomalies': anomalies,
        'best_config': best,
    }
    with open(RESULTS_FILE, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Resultaten opgeslagen: {RESULTS_FILE}")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Agent Team V2')
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--hours', type=float, default=4.0)
    args = parser.parse_args()
    run_all(args)


if __name__ == '__main__':
    main()

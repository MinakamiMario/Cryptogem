#!/usr/bin/env python3
"""
AGENT TEAM — Geoptimaliseerd Multi-Agent Zoeksysteem
=====================================================
4 agents die SAMENWERKEN met een gedeeld scoreboard:

  Agent 1: GRID SEARCH      — 2-param combinaties (vindt interacties)
  Agent 2: WIDE EXPLORER     — andere exit types + extreme params
  Agent 3: FINE TUNER        — fijne stappen rondom beste gevonden config
  Agent 4: WALK-FORWARD      — valideert top ontdekkingen van andere agents

VERBETERINGEN vs agent_search.py:
  ✅ Inter-agent communicatie via gedeeld scoreboard
  ✅ Agent 4 valideert ontdekkingen van Agent 1/2/3 (niet hardcoded)
  ✅ Sanity check bij start (vergelijk met bekende baseline)
  ✅ Early stopping bij slechte configs (< 10 trades = skip MC)
  ✅ Adaptive MC sims (500 voor screening, 5000 voor top configs)
  ✅ Walk-forward herberekent indicators per fold (geen data leakage)
  ✅ Betere scoring: median equity ipv win% als primaire metric
  ✅ Gedeeld JSON scoreboard dat real-time bijgewerkt wordt

Gebruik:
    python agent_team.py                    # Volledige run (~2-4 uur)
    python agent_team.py --quick            # Snelle test (~15 min)
    python agent_team.py --agent 1          # Alleen agent 1 draaien
    python agent_team.py --agent 4          # Alleen validatie
    python agent_team.py --hours 8          # Max runtime in uren
"""
import sys
import json
import time
import random
import math
import argparse
from pathlib import Path
from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

# ============================================================
# CONSTANTS
# ============================================================
CACHE_FILE = BASE_DIR / 'candle_cache_532.json'
SCOREBOARD_FILE = BASE_DIR / 'agent_team_scoreboard.json'
RESULTS_FILE = BASE_DIR / 'agent_team_results.json'
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

# Bekende baseline voor sanity check
BASELINE_V5_VOLSPK3 = {
    'exit_type': 'trail', 'rsi_max': 40, 'atr_mult': 2.0,
    'vol_spike_mult': 3.0, 'vol_confirm': True,
    'breakeven': True, 'be_trigger': 3.0,
    'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
    'max_stop_pct': 15.0, 'max_pos': 1,
}
BASELINE_EXPECTED_TRADES = 39
BASELINE_EXPECTED_PNL_MIN = 3500  # Minstens $3500 P&L verwacht

# Geoptimaliseerde config (sweep winnaar)
BEST_KNOWN = {
    'exit_type': 'trail', 'rsi_max': 42, 'atr_mult': 2.0,
    'vol_spike_mult': 3.0, 'vol_confirm': True,
    'breakeven': True, 'be_trigger': 2.0,
    'time_max_bars': 6, 'rsi_recovery': True, 'rsi_rec_target': 45,
    'max_stop_pct': 12.0, 'max_pos': 1,
}

# ============================================================
# PRECOMPUTE (identiek aan overnight_optimizer)
# ============================================================

def precompute_all(data, coins, start_bar=None, end_bar=None):
    """Precompute indicators. Optioneel beperkt tot bar range (voor walk-forward)."""
    sb = start_bar or 0
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
            'rsi': [None] * n, 'atr': [None] * n,
            'dc_prev_low': [None] * n, 'dc_mid': [None] * n,
            'bb_mid': [None] * n, 'bb_lower': [None] * n,
            'vol_avg': [None] * n,
        }
        min_bars = max(DC_PERIOD, BB_PERIOD, RSI_PERIOD, ATR_PERIOD) + 5
        for bar in range(min_bars, n):
            wc = closes[:bar + 1]
            wh = highs[:bar + 1]
            wl = lows[:bar + 1]
            wv = volumes[:bar + 1]
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
            ind['vol_avg'][bar] = sum(vol_slice) / len(vol_slice) if vol_slice else 0
        indicators[pair] = ind
    return indicators


# ============================================================
# ENTRY CHECK (identiek aan overnight_optimizer)
# ============================================================

def check_entry_at_bar(ind, bar, cfg):
    if ind['rsi'][bar] is None:
        return False, 0
    rsi = ind['rsi'][bar]
    rsi_max = cfg.get('rsi_max', 40)
    close = ind['closes'][bar]
    low = ind['lows'][bar]
    prev_close = ind['closes'][bar - 1] if bar > 0 else close
    cur_vol = ind['volumes'][bar]
    prev_vol = ind['volumes'][bar - 1] if bar > 0 else 0
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
# REALISTIC EQUITY BACKTEST (identiek aan overnight_optimizer)
# ============================================================

@dataclass
class Pos:
    pair: str
    entry_price: float
    entry_bar: int
    size_usd: float
    stop_price: float = 0.0
    highest_price: float = 0.0


def run_backtest_realistic(indicators, coins, cfg, start_bar=START_BAR, end_bar=None):
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
    last_exit_bar = {p: -999 for p in coin_list}
    last_exit_was_stop = {p: False for p in coin_list}

    for bar in range(start_bar, max_bars):
        if equity < 0:
            broke = True
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
                sl_p = entry_price * (1 - sl_pct / 100)
                tp_p = entry_price * (1 + tp_pct / 100)
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
                hard_stop = entry_price * (1 - max_stop_pct / 100)
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
                hard_stop = entry_price * (1 - max_stop_pct / 100)
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
            is_stop = 'STOP' in reason
            last_exit_bar[pair] = bar
            last_exit_was_stop[pair] = is_stop
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
                    hard = ep * (1 - cfg.get('max_stop_pct', 15.0) / 100)
                    if stop < hard:
                        stop = hard
                else:
                    stop = ep * (1 - cfg.get('sl_pct', cfg.get('max_stop_pct', 15.0)) / 100)
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

    for pair, pos in list(positions.items()):
        ind = indicators[pair]
        last_idx = min(ind['n'] - 1, max_bars - 1)
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
    wr = len(wins) / n * 100 if n else 0
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else float('inf')

    return {
        'trades': n, 'wr': wr, 'pnl': total_pnl,
        'final_equity': final_equity,
        'pf': pf, 'dd': max_dd, 'broke': broke,
        'trade_list': trades,
    }


# ============================================================
# MONTE CARLO
# ============================================================

def monte_carlo(trade_pnl_pcts, n_sims=5000, seed=42):
    rng = random.Random(seed)
    n_trades = len(trade_pnl_pcts)
    if n_trades < 3:
        return {'win_pct': 0, 'median_equity': INITIAL_CAPITAL,
                'mean_equity': INITIAL_CAPITAL, 'p5': INITIAL_CAPITAL,
                'p95': INITIAL_CAPITAL, 'broke_pct': 0,
                'n_sims': 0, 'n_trades': n_trades}
    final_equities = []
    broke_count = 0
    for _ in range(n_sims):
        shuffled = trade_pnl_pcts.copy()
        rng.shuffle(shuffled)
        eq = float(INITIAL_CAPITAL)
        for pnl_pct in shuffled:
            if eq <= 0:
                broke_count += 1
                eq = 0
                break
            eq += eq * (pnl_pct / 100)
        final_equities.append(eq)
    final_equities.sort()
    n = len(final_equities)
    winners = sum(1 for e in final_equities if e > INITIAL_CAPITAL)
    return {
        'win_pct': winners / n * 100,
        'median_equity': final_equities[n // 2],
        'mean_equity': sum(final_equities) / n,
        'p5': final_equities[int(n * 0.05)],
        'p95': final_equities[int(n * 0.95)],
        'broke_pct': broke_count / n * 100,
        'n_sims': n_sims, 'n_trades': n_trades,
    }


# ============================================================
# ADAPTIVE EVALUATION: screen snel, evalueer diep als goed
# ============================================================

def evaluate_quick(indicators, coins, cfg, label=""):
    """Snelle screening: alleen backtest, geen MC. Return None als <10 trades."""
    bt = run_backtest_realistic(indicators, coins, cfg)
    if bt['trades'] < 5:
        return None  # Te weinig trades, skip
    return {
        'label': label, 'cfg': cfg,
        'trades': bt['trades'], 'wr': bt['wr'],
        'pnl': bt['pnl'], 'dd': bt['dd'],
        'pnl_pcts': [t['pnl_pct'] for t in bt['trade_list']],
    }


def evaluate_full(indicators, coins, cfg, label="", n_sims=5000):
    """Volledige evaluatie: backtest + MC + NoTop + score."""
    bt = run_backtest_realistic(indicators, coins, cfg)
    pnl_pcts = [t['pnl_pct'] for t in bt['trade_list']]
    mc = monte_carlo(pnl_pcts, n_sims=n_sims)

    # NoTop: verwijder beste trade
    if len(pnl_pcts) > 1:
        sorted_pcts = sorted(pnl_pcts, reverse=True)
        notop_pcts = sorted_pcts[1:]
        mc_notop = monte_carlo(notop_pcts, n_sims=min(2000, n_sims), seed=123)
        notop_win = mc_notop['win_pct']
    else:
        notop_win = 0

    # VERBETERDE SCORE: median equity is primair (niet win%)
    # Win% is bijna altijd 100% en differentieert niet
    median_score = min(100, max(0, (mc['median_equity'] - 1000) / 60))  # $1K-$7K → 0-100
    notop_score = notop_win
    trade_score = min(100, bt['trades'] / 0.5)  # 50 trades = 100
    dd_score = max(0, 100 - bt['dd'] * 2.0)  # Strenger: 50% DD = 0
    pnl_score = min(100, max(0, (bt['pnl'] + 500) / 60))  # -$500 tot $5500 → 0-100

    total_score = (
        median_score * 0.25 +   # Hoeveel verdien je typisch?
        notop_score  * 0.25 +   # Robuust zonder outlier?
        pnl_score    * 0.20 +   # Absolute P&L
        dd_score     * 0.15 +   # Drawdown
        trade_score  * 0.15     # Statistische significantie
    )

    return {
        'label': label,
        'cfg': cfg,
        'backtest': {
            'trades': bt['trades'], 'wr': round(bt['wr'], 1),
            'pnl': round(bt['pnl'], 2), 'final_equity': round(bt['final_equity'], 2),
            'pf': round(bt['pf'], 2) if bt['pf'] < 999 else 'INF',
            'dd': round(bt['dd'], 1), 'broke': bt['broke'],
        },
        'monte_carlo': {
            'win_pct': round(mc['win_pct'], 1),
            'median_eq': round(mc['median_equity'], 0),
            'p5': round(mc['p5'], 0),
            'p95': round(mc['p95'], 0),
        },
        'notop_win_pct': round(notop_win, 1),
        'score': round(total_score, 1),
    }


# ============================================================
# SCOREBOARD: gedeeld tussen agents
# ============================================================

class Scoreboard:
    """Gedeeld scoreboard — agents posten hun ontdekkingen hier."""

    def __init__(self, filepath=SCOREBOARD_FILE):
        self.filepath = filepath
        self.data = {
            'started': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'baseline_ok': False,
            'best_score': 0,
            'best_config': None,
            'best_label': '',
            'top20': [],
            'agent_status': {},
            'configs_evaluated': 0,
            'walk_forward_results': [],
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

    def post_result(self, result, agent_id):
        """Agent post een resultaat. Update top20 + best als verbeterd."""
        self._load()
        self.data['configs_evaluated'] = self.data.get('configs_evaluated', 0) + 1

        entry = {
            'score': result['score'],
            'label': result['label'],
            'agent': agent_id,
            'cfg': result['cfg'],
            'trades': result['backtest']['trades'],
            'pnl': result['backtest']['pnl'],
            'wr': result['backtest']['wr'],
            'dd': result['backtest']['dd'],
            'mc_win': result['monte_carlo']['win_pct'],
            'mc_median': result['monte_carlo']['median_eq'],
            'notop': result['notop_win_pct'],
        }

        # Update top20
        top = self.data.get('top20', [])
        top.append(entry)
        top.sort(key=lambda x: x['score'], reverse=True)
        self.data['top20'] = top[:20]

        # Update best
        if result['score'] > self.data.get('best_score', 0):
            self.data['best_score'] = result['score']
            self.data['best_config'] = result['cfg']
            self.data['best_label'] = result['label']

        self._save()
        return result['score'] > self.data.get('best_score', 0)

    def get_best_config(self):
        """Haal huidige beste config op (voor andere agents)."""
        self._load()
        return self.data.get('best_config', BEST_KNOWN)

    def get_top_configs(self, n=10):
        """Haal top N configs op voor walk-forward validatie."""
        self._load()
        top = self.data.get('top20', [])
        # Deduplicate by config (different labels may have same config)
        seen = set()
        unique = []
        for entry in top:
            cfg_key = json.dumps(entry['cfg'], sort_keys=True)
            if cfg_key not in seen:
                seen.add(cfg_key)
                unique.append(entry)
            if len(unique) >= n:
                break
        return unique

    def update_agent_status(self, agent_id, status):
        self._load()
        self.data.setdefault('agent_status', {})[str(agent_id)] = {
            'status': status,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
        }
        self._save()

    def post_walk_forward(self, result):
        self._load()
        self.data.setdefault('walk_forward_results', []).append(result)
        self._save()

    def set_baseline_ok(self, ok):
        self._load()
        self.data['baseline_ok'] = ok
        self._save()


# ============================================================
# PRINT HELPERS
# ============================================================

def fmt_result(r):
    bt = r['backtest']
    mc = r['monte_carlo']
    pf = bt['pf'] if bt['pf'] != 'INF' else '∞'
    return (f"SC:{r['score']:5.1f} | MC:{mc['win_pct']:5.1f}% Med:${mc['median_eq']:,.0f} | "
            f"NT:{r['notop_win_pct']:5.1f}% | "
            f"Tr:{bt['trades']:3d} WR:{bt['wr']:5.1f}% P&L:${bt['pnl']:+,.0f} "
            f"DD:{bt['dd']:4.1f}% PF:{pf}")


# ============================================================
# AGENT 1: GRID SEARCH — 2-param combinaties
# ============================================================

def agent_grid_search(indicators, coins, scoreboard, quick=False):
    """Systematisch alle 2-param combinaties vanuit BEST_KNOWN."""
    agent_id = 1
    scoreboard.update_agent_status(agent_id, 'RUNNING: Grid Search')
    print(f"\n{'='*80}")
    print(f"AGENT 1: GRID SEARCH — 2-param combinaties")
    print(f"{'='*80}")

    best = scoreboard.get_best_config() or deepcopy(BEST_KNOWN)

    # Trail params die samen getest worden
    GRID_PARAMS = {
        'vol_spike_mult': [2.0, 2.5, 3.0, 3.5, 4.0, 5.0],
        'rsi_max':         [30, 35, 38, 40, 42, 45, 48],
        'rsi_rec_target':  [40, 42, 44, 45, 46, 47, 48],
        'time_max_bars':   [4, 6, 8, 10, 12, 15],
        'atr_mult':        [1.5, 2.0, 2.5, 3.0],
        'be_trigger':      [1.5, 2.0, 2.5, 3.0, 4.0],
        'max_stop_pct':    [8.0, 10.0, 12.0, 15.0, 20.0],
    }
    if quick:
        # Minder waarden per param
        GRID_PARAMS = {k: v[::2] for k, v in GRID_PARAMS.items()}

    param_names = list(GRID_PARAMS.keys())
    total_combos = 0
    evaluated = 0
    improved = 0
    t0 = time.time()

    # Tel totaal
    for i in range(len(param_names)):
        for j in range(i + 1, len(param_names)):
            total_combos += len(GRID_PARAMS[param_names[i]]) * len(GRID_PARAMS[param_names[j]])

    print(f"  Totaal 2-param combos: {total_combos}")

    for i in range(len(param_names)):
        for j in range(i + 1, len(param_names)):
            p1, p2 = param_names[i], param_names[j]
            for v1 in GRID_PARAMS[p1]:
                for v2 in GRID_PARAMS[p2]:
                    # Skip als beide gelijk aan best known
                    if v1 == best.get(p1) and v2 == best.get(p2):
                        evaluated += 1
                        continue

                    cfg = deepcopy(best)
                    cfg[p1] = v1
                    cfg[p2] = v2
                    label = f"grid-{p1}={v1}-{p2}={v2}"

                    # Quick screen eerst
                    qr = evaluate_quick(indicators, coins, cfg, label)
                    evaluated += 1
                    if qr is None:
                        continue

                    # Alleen full eval als screen belovend (> 20 trades OF hoge P&L)
                    if qr['trades'] < 15 and qr['pnl'] < 500:
                        continue

                    result = evaluate_full(indicators, coins, cfg, label)
                    is_new_best = scoreboard.post_result(result, agent_id)
                    if is_new_best:
                        improved += 1
                        print(f"  🏆 NEW BEST: {label}")
                        print(f"     {fmt_result(result)}")
                    elif result['score'] >= 85:
                        print(f"  ✅ {label}: {fmt_result(result)}")

                    if evaluated % 100 == 0:
                        elapsed = time.time() - t0
                        pct = evaluated / total_combos * 100
                        print(f"  ... {evaluated}/{total_combos} ({pct:.0f}%) "
                              f"| {elapsed:.0f}s | verbeteringen: {improved}")

    elapsed = time.time() - t0
    print(f"\n  Agent 1 klaar: {evaluated} geëvalueerd, {improved} verbeteringen, {elapsed:.0f}s")
    scoreboard.update_agent_status(agent_id, f'DONE: {evaluated} eval, {improved} improved, {elapsed:.0f}s')


# ============================================================
# AGENT 2: WIDE EXPLORER — andere exit types + extreme params
# ============================================================

def agent_wide_explorer(indicators, coins, scoreboard, quick=False):
    """Verken radicaal andere strategieen."""
    agent_id = 2
    scoreboard.update_agent_status(agent_id, 'RUNNING: Wide Explorer')
    print(f"\n{'='*80}")
    print(f"AGENT 2: WIDE EXPLORER — andere exit types + extreme params")
    print(f"{'='*80}")

    best = scoreboard.get_best_config() or deepcopy(BEST_KNOWN)
    evaluated = 0
    improved = 0
    t0 = time.time()

    # --- Phase A: hybrid_notrl (geen trail stop) ---
    print(f"\n  Phase A: hybrid_notrl varianten")
    for rsi_max in ([35, 40, 42, 45] if not quick else [40, 42]):
        for vol_spike in ([2.0, 3.0, 4.0, 5.0] if not quick else [3.0, 4.0]):
            for tm_bars in ([6, 8, 10, 15, 20] if not quick else [8, 12]):
                for max_stop in ([10, 12, 15, 20] if not quick else [12, 15]):
                    for rsi_rec in ([False, 42, 45, 47] if not quick else [45]):
                        cfg = {
                            'exit_type': 'hybrid_notrl',
                            'rsi_max': rsi_max, 'vol_spike_mult': vol_spike,
                            'vol_confirm': True, 'max_stop_pct': max_stop,
                            'time_max_bars': tm_bars, 'max_pos': 1,
                            'breakeven': False,
                        }
                        if rsi_rec is not False:
                            cfg['rsi_recovery'] = True
                            cfg['rsi_rec_target'] = rsi_rec
                        else:
                            cfg['rsi_recovery'] = False

                        label = f"notrl-rsi{rsi_max}-vs{vol_spike}-tm{tm_bars}-ms{max_stop}-rec{rsi_rec}"
                        qr = evaluate_quick(indicators, coins, cfg, label)
                        evaluated += 1
                        if qr is None or (qr['trades'] < 10 and qr['pnl'] < 0):
                            continue
                        result = evaluate_full(indicators, coins, cfg, label)
                        is_new = scoreboard.post_result(result, agent_id)
                        if is_new:
                            improved += 1
                            print(f"  🏆 NEW BEST: {label}")
                            print(f"     {fmt_result(result)}")
                        elif result['score'] >= 80:
                            print(f"  ✅ {label}: {fmt_result(result)}")

    # --- Phase B: tp_sl varianten ---
    print(f"\n  Phase B: tp_sl varianten")
    for tp in ([5.0, 7.0, 8.0, 10.0, 12.0] if not quick else [7.0, 10.0]):
        for sl in ([8.0, 10.0, 15.0, 20.0] if not quick else [10.0, 15.0]):
            for tm in ([8, 10, 15, 20, 999] if not quick else [10, 15]):
                for rsi_max in ([35, 40, 42] if not quick else [40]):
                    for vol_spike in ([2.0, 3.0, 4.0] if not quick else [3.0]):
                        cfg = {
                            'exit_type': 'tp_sl',
                            'rsi_max': rsi_max, 'vol_spike_mult': vol_spike,
                            'vol_confirm': True,
                            'tp_pct': tp, 'sl_pct': sl, 'tm_bars': tm,
                            'max_pos': 1,
                        }
                        label = f"tpsl-tp{tp}-sl{sl}-tm{tm}-rsi{rsi_max}-vs{vol_spike}"
                        qr = evaluate_quick(indicators, coins, cfg, label)
                        evaluated += 1
                        if qr is None or (qr['trades'] < 10 and qr['pnl'] < 0):
                            continue
                        result = evaluate_full(indicators, coins, cfg, label)
                        is_new = scoreboard.post_result(result, agent_id)
                        if is_new:
                            improved += 1
                            print(f"  🏆 NEW BEST: {label}")
                            print(f"     {fmt_result(result)}")
                        elif result['score'] >= 80:
                            print(f"  ✅ {label}: {fmt_result(result)}")

    # --- Phase C: trail met extreme params ---
    print(f"\n  Phase C: trail extreme params")
    for vol_spike in ([1.5, 2.0, 5.0, 6.0, 8.0] if not quick else [2.0, 5.0]):
        for rsi_max in ([25, 30, 48, 50] if not quick else [30, 48]):
            for atr_mult in ([1.0, 1.5, 3.5, 4.0] if not quick else [1.5, 3.5]):
                cfg = deepcopy(best)
                cfg['vol_spike_mult'] = vol_spike
                cfg['rsi_max'] = rsi_max
                cfg['atr_mult'] = atr_mult
                label = f"extreme-vs{vol_spike}-rsi{rsi_max}-atr{atr_mult}"
                qr = evaluate_quick(indicators, coins, cfg, label)
                evaluated += 1
                if qr is None:
                    continue
                if qr['trades'] >= 10 or qr['pnl'] > 500:
                    result = evaluate_full(indicators, coins, cfg, label)
                    is_new = scoreboard.post_result(result, agent_id)
                    if is_new:
                        improved += 1
                        print(f"  🏆 NEW BEST: {label}")
                        print(f"     {fmt_result(result)}")
                    elif result['score'] >= 80:
                        print(f"  ✅ {label}: {fmt_result(result)}")

    # --- Phase D: max_pos variaties op beste configs ---
    print(f"\n  Phase D: max_pos variaties op huidige top-3")
    top_cfgs = scoreboard.get_top_configs(3)
    for entry in top_cfgs:
        for mp in [1, 2, 3]:
            cfg = deepcopy(entry['cfg'])
            cfg['max_pos'] = mp
            label = f"mp{mp}-{entry.get('label', 'top')}"
            qr = evaluate_quick(indicators, coins, cfg, label)
            evaluated += 1
            if qr is not None and (qr['trades'] >= 10 or qr['pnl'] > 0):
                result = evaluate_full(indicators, coins, cfg, label)
                scoreboard.post_result(result, agent_id)
                if result['score'] >= 80:
                    print(f"  ✅ {label}: {fmt_result(result)}")

    elapsed = time.time() - t0
    print(f"\n  Agent 2 klaar: {evaluated} geëvalueerd, {improved} verbeteringen, {elapsed:.0f}s")
    scoreboard.update_agent_status(agent_id, f'DONE: {evaluated} eval, {improved} improved, {elapsed:.0f}s')


# ============================================================
# AGENT 3: FINE TUNER — fijne stappen rond beste config
# ============================================================

def agent_fine_tuner(indicators, coins, scoreboard, quick=False):
    """Fijne optimalisatie rondom de huidige beste config."""
    agent_id = 3
    scoreboard.update_agent_status(agent_id, 'RUNNING: Fine Tuner')
    print(f"\n{'='*80}")
    print(f"AGENT 3: FINE TUNER — fijne stappen rond beste config")
    print(f"{'='*80}")

    best = scoreboard.get_best_config() or deepcopy(BEST_KNOWN)
    evaluated = 0
    improved = 0
    t0 = time.time()

    # Fijne param ranges rondom de huidige best
    def fine_range(val, steps, step_size, minimum=None, maximum=None):
        """Genereer waarden rondom val met fijne stappen."""
        values = []
        for i in range(-steps, steps + 1):
            v = val + i * step_size
            if minimum is not None and v < minimum:
                continue
            if maximum is not None and v > maximum:
                continue
            values.append(round(v, 2))
        return sorted(set(values))

    # --- Phase A: Single-param fine sweep ---
    print(f"\n  Phase A: Single-param fine sweep")
    fine_params = {
        'vol_spike_mult': fine_range(best.get('vol_spike_mult', 3.0), 4, 0.25, 1.5, 8.0),
        'rsi_max':         fine_range(best.get('rsi_max', 42), 5, 1, 25, 50),
        'rsi_rec_target':  fine_range(best.get('rsi_rec_target', 45), 4, 1, 38, 52),
        'time_max_bars':   fine_range(best.get('time_max_bars', 6), 4, 1, 3, 25),
        'atr_mult':        fine_range(best.get('atr_mult', 2.0), 4, 0.25, 1.0, 5.0),
        'be_trigger':      fine_range(best.get('be_trigger', 2.0), 4, 0.25, 0.5, 6.0),
        'max_stop_pct':    fine_range(best.get('max_stop_pct', 12.0), 4, 1.0, 5.0, 30.0),
    }

    for param, values in fine_params.items():
        for val in values:
            if val == best.get(param):
                continue
            cfg = deepcopy(best)
            cfg[param] = val
            label = f"fine-{param}={val}"
            qr = evaluate_quick(indicators, coins, cfg, label)
            evaluated += 1
            if qr is None:
                continue
            if qr['trades'] >= 10 or qr['pnl'] > 500:
                result = evaluate_full(indicators, coins, cfg, label)
                is_new = scoreboard.post_result(result, agent_id)
                if is_new:
                    improved += 1
                    best = deepcopy(cfg)  # Update lokale best
                    print(f"  🏆 NEW BEST: {label}")
                    print(f"     {fmt_result(result)}")

    # --- Phase B: Hill climbing vanuit huidige beste ---
    print(f"\n  Phase B: Hill climbing vanuit scoreboard-best")
    best = scoreboard.get_best_config() or deepcopy(BEST_KNOWN)  # Refresh van scoreboard
    no_improve_rounds = 0
    max_rounds = 5 if not quick else 2

    while no_improve_rounds < 3:
        if no_improve_rounds >= max_rounds:
            break
        round_improved = False
        for param, values in fine_params.items():
            for val in values:
                if val == best.get(param):
                    continue
                cfg = deepcopy(best)
                cfg[param] = val
                label = f"hc-r{no_improve_rounds}-{param}={val}"
                qr = evaluate_quick(indicators, coins, cfg, label)
                evaluated += 1
                if qr is None:
                    continue
                if qr['trades'] >= 10 or qr['pnl'] > 500:
                    result = evaluate_full(indicators, coins, cfg, label)
                    is_new = scoreboard.post_result(result, agent_id)
                    if is_new:
                        improved += 1
                        best = deepcopy(cfg)
                        round_improved = True
                        print(f"  🏆 HC IMPROVED: {label}")
                        print(f"     {fmt_result(result)}")

        if not round_improved:
            no_improve_rounds += 1
            print(f"  ... Hill climb ronde zonder verbetering ({no_improve_rounds}/3)")
        else:
            no_improve_rounds = 0

    elapsed = time.time() - t0
    print(f"\n  Agent 3 klaar: {evaluated} geëvalueerd, {improved} verbeteringen, {elapsed:.0f}s")
    scoreboard.update_agent_status(agent_id, f'DONE: {evaluated} eval, {improved} improved, {elapsed:.0f}s')


# ============================================================
# AGENT 4: WALK-FORWARD VALIDATOR — test robuustheid
# ============================================================

def agent_walk_forward(indicators, coins, data, scoreboard, quick=False):
    """Walk-forward validatie op top ontdekkingen van Agent 1/2/3.
    BELANGRIJK: herberekent indicators per fold (geen data leakage)."""
    agent_id = 4
    scoreboard.update_agent_status(agent_id, 'RUNNING: Walk-Forward Validator')
    print(f"\n{'='*80}")
    print(f"AGENT 4: WALK-FORWARD VALIDATOR")
    print(f"{'='*80}")

    t0 = time.time()
    n_folds = 5 if not quick else 3

    # Haal top configs van scoreboard (ontdekkingen van Agent 1/2/3)
    top_entries = scoreboard.get_top_configs(10 if not quick else 5)

    # Voeg altijd BEST_KNOWN en BASELINE toe als referentie
    known_cfgs = [
        ('BASELINE_V5+VolSpk3', BASELINE_V5_VOLSPK3),
        ('BEST_KNOWN_sweep', BEST_KNOWN),
    ]

    # Combineer: scoreboard top + known configs (deduplicate)
    configs_to_test = []
    seen_keys = set()

    for entry in top_entries:
        cfg_key = json.dumps(entry['cfg'], sort_keys=True)
        if cfg_key not in seen_keys:
            seen_keys.add(cfg_key)
            configs_to_test.append((entry.get('label', f"top-{len(configs_to_test)}"), entry['cfg']))

    for label, cfg in known_cfgs:
        cfg_key = json.dumps(cfg, sort_keys=True)
        if cfg_key not in seen_keys:
            seen_keys.add(cfg_key)
            configs_to_test.append((label, cfg))

    print(f"  Configs te testen: {len(configs_to_test)}")
    print(f"  Walk-forward folds: {n_folds}")

    # Bepaal max bars
    coin_list = [c for c in coins if c in indicators]
    max_bars = max(indicators[p]['n'] for p in coin_list)
    usable_bars = max_bars - START_BAR
    fold_size = usable_bars // n_folds

    print(f"  Totaal bars: {max_bars}, bruikbaar: {usable_bars}, per fold: {fold_size}")

    results = []
    for cfg_label, cfg in configs_to_test:
        folds_profitable = 0
        fold_details = []

        for fold in range(n_folds):
            # Train: eerste 70% van fold, Test: laatste 30%
            fold_start = START_BAR + fold * fold_size
            fold_end = fold_start + fold_size
            if fold == n_folds - 1:
                fold_end = max_bars  # Laatste fold pakt alles

            train_end = fold_start + int(fold_size * 0.7)
            test_start = train_end
            test_end = fold_end

            # HERBEREKEN indicators voor ALLEEN deze fold periode
            # (voorkomt data leakage van toekomstige bars in RSI/ATR etc.)
            fold_indicators = precompute_all(data, coins, end_bar=fold_end)

            # Train backtest
            bt_train = run_backtest_realistic(fold_indicators, coins, cfg,
                                               start_bar=fold_start, end_bar=train_end)
            # Test backtest
            bt_test = run_backtest_realistic(fold_indicators, coins, cfg,
                                              start_bar=test_start, end_bar=test_end)

            test_profitable = bt_test['pnl'] > 0
            if test_profitable:
                folds_profitable += 1

            fold_details.append({
                'fold': fold + 1,
                'train_bars': f"{fold_start}-{train_end}",
                'test_bars': f"{test_start}-{test_end}",
                'train_trades': bt_train['trades'],
                'train_pnl': round(bt_train['pnl'], 2),
                'test_trades': bt_test['trades'],
                'test_pnl': round(bt_test['pnl'], 2),
                'test_profitable': test_profitable,
            })

        wf_ratio = folds_profitable / n_folds
        wf_label = f"{folds_profitable}/{n_folds}"
        passed = folds_profitable >= (n_folds // 2 + 1)  # Majority rule

        result = {
            'label': cfg_label,
            'cfg': cfg,
            'wf_folds': wf_label,
            'wf_ratio': wf_ratio,
            'passed': passed,
            'fold_details': fold_details,
        }
        results.append(result)
        scoreboard.post_walk_forward(result)

        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} {cfg_label}: WF {wf_label} | "
              f"Test P&L: {[f['test_pnl'] for f in fold_details]}")

    # Sorteer op WF ratio
    results.sort(key=lambda x: x['wf_ratio'], reverse=True)

    print(f"\n  {'='*60}")
    print(f"  WALK-FORWARD RANKING:")
    print(f"  {'='*60}")
    for i, r in enumerate(results):
        status = "✅" if r['passed'] else "❌"
        print(f"  {i+1}. {status} {r['label']}: {r['wf_folds']} folds winstgevend")

    elapsed = time.time() - t0
    print(f"\n  Agent 4 klaar: {len(configs_to_test)} configs × {n_folds} folds, {elapsed:.0f}s")
    scoreboard.update_agent_status(agent_id, f'DONE: {len(configs_to_test)} configs, {elapsed:.0f}s')
    return results


# ============================================================
# SANITY CHECK
# ============================================================

def sanity_check(indicators, coins, scoreboard):
    """Verifieer dat de backtest engine correct werkt."""
    print(f"\n{'='*80}")
    print(f"SANITY CHECK: Vergelijk met bekende V5+VolSpk3 baseline")
    print(f"{'='*80}")

    bt = run_backtest_realistic(indicators, coins, BASELINE_V5_VOLSPK3)
    trades = bt['trades']
    pnl = bt['pnl']

    print(f"  Verwacht: ~{BASELINE_EXPECTED_TRADES} trades, >= ${BASELINE_EXPECTED_PNL_MIN} P&L")
    print(f"  Gevonden: {trades} trades, ${pnl:+,.2f} P&L")

    # Tolerantie: ±5 trades, P&L > minimum
    trade_ok = abs(trades - BASELINE_EXPECTED_TRADES) <= 5
    pnl_ok = pnl >= BASELINE_EXPECTED_PNL_MIN

    if trade_ok and pnl_ok:
        print(f"  ✅ SANITY CHECK PASSED")
        scoreboard.set_baseline_ok(True)
        return True
    else:
        if not trade_ok:
            print(f"  ❌ TRADE COUNT MISMATCH: verwacht ~{BASELINE_EXPECTED_TRADES}, kreeg {trades}")
        if not pnl_ok:
            print(f"  ❌ P&L TE LAAG: verwacht >= ${BASELINE_EXPECTED_PNL_MIN}, kreeg ${pnl:+,.2f}")
        print(f"  ❌ SANITY CHECK FAILED — STOP! Fix de engine eerst.")
        scoreboard.set_baseline_ok(False)
        return False


# ============================================================
# FINAL REPORT
# ============================================================

def generate_report(scoreboard, wf_results):
    """Genereer eindrapport."""
    scoreboard._load()
    print(f"\n{'='*80}")
    print(f"EINDRAPPORT AGENT TEAM")
    print(f"{'='*80}")

    print(f"\n  Started: {scoreboard.data.get('started', '?')}")
    print(f"  Configs evaluated: {scoreboard.data.get('configs_evaluated', 0)}")

    # Agent status
    print(f"\n  Agent Status:")
    for agent_id, status in scoreboard.data.get('agent_status', {}).items():
        print(f"    Agent {agent_id}: {status.get('status', '?')} ({status.get('timestamp', '')})")

    # Top 10
    print(f"\n  TOP 10 CONFIGS (sorted by score):")
    print(f"  {'#':>3} {'Score':>6} {'Label':<45} {'Tr':>4} {'P&L':>8} {'WR':>6} {'DD':>5} {'MC%':>5} {'NT%':>5}")
    print(f"  {'-'*90}")
    for i, entry in enumerate(scoreboard.data.get('top20', [])[:10]):
        print(f"  {i+1:>3} {entry['score']:>5.1f} {entry['label']:<45} "
              f"{entry['trades']:>4} ${entry['pnl']:>+7,.0f} {entry['wr']:>5.1f}% "
              f"{entry['dd']:>4.1f}% {entry['mc_win']:>4.0f}% {entry['notop']:>4.0f}%")

    # Walk-forward resultaten
    if wf_results:
        print(f"\n  WALK-FORWARD RESULTATEN:")
        for r in wf_results:
            status = "✅" if r['passed'] else "❌"
            print(f"    {status} {r['label']}: {r['wf_folds']}")

    # Beste config
    best = scoreboard.data.get('best_config')
    if best:
        print(f"\n  BESTE CONFIG:")
        print(f"    Label: {scoreboard.data.get('best_label', '?')}")
        print(f"    Score: {scoreboard.data.get('best_score', 0):.1f}")
        for k, v in sorted(best.items()):
            print(f"    {k}: {v}")

    # Save results
    report = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'configs_evaluated': scoreboard.data.get('configs_evaluated', 0),
        'best_score': scoreboard.data.get('best_score', 0),
        'best_label': scoreboard.data.get('best_label', ''),
        'best_config': scoreboard.data.get('best_config'),
        'top10': scoreboard.data.get('top20', [])[:10],
        'walk_forward': wf_results,
        'agent_status': scoreboard.data.get('agent_status', {}),
    }
    with open(RESULTS_FILE, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Resultaten opgeslagen: {RESULTS_FILE}")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Agent Team — Multi-Agent Optimizer')
    parser.add_argument('--quick', action='store_true', help='Snelle test (~15 min)')
    parser.add_argument('--agent', type=int, choices=[1, 2, 3, 4], help='Alleen specifieke agent')
    parser.add_argument('--hours', type=float, default=4.0, help='Max runtime in uren')
    parser.add_argument('--skip-sanity', action='store_true', help='Skip sanity check')
    args = parser.parse_args()

    print(f"{'='*80}")
    print(f"AGENT TEAM — Multi-Agent Optimizer")
    print(f"{'='*80}")
    print(f"  Mode: {'QUICK' if args.quick else 'FULL'}")
    print(f"  Agent: {'ALL' if args.agent is None else args.agent}")
    print(f"  Max runtime: {args.hours} uur")
    print(f"  Start: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Load data
    print(f"\n  Laden {CACHE_FILE}...")
    with open(CACHE_FILE) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith('_')])
    print(f"  Geladen: {len(coins)} coins")

    # Precompute (full dataset)
    print(f"  Precomputing indicators...")
    t0 = time.time()
    indicators = precompute_all(data, coins)
    print(f"  Precompute klaar: {time.time()-t0:.1f}s")

    # Scoreboard
    scoreboard = Scoreboard()

    # Sanity check
    if not args.skip_sanity:
        if not sanity_check(indicators, coins, scoreboard):
            print(f"\n  ❌ ABORT: Sanity check failed. Fix de backtest engine eerst.")
            sys.exit(1)
    else:
        print(f"\n  ⚠️ Sanity check overgeslagen (--skip-sanity)")
        scoreboard.set_baseline_ok(True)

    # Evalueer BEST_KNOWN als startpunt
    print(f"\n  Evalueren BEST_KNOWN als startpunt...")
    baseline_result = evaluate_full(indicators, coins, BEST_KNOWN, "BEST_KNOWN_sweep")
    scoreboard.post_result(baseline_result, 0)
    print(f"  Startpunt: {fmt_result(baseline_result)}")

    # Run agents
    deadline = time.time() + args.hours * 3600

    if args.agent is None or args.agent == 1:
        if time.time() < deadline:
            agent_grid_search(indicators, coins, scoreboard, quick=args.quick)

    if args.agent is None or args.agent == 2:
        if time.time() < deadline:
            agent_wide_explorer(indicators, coins, scoreboard, quick=args.quick)

    if args.agent is None or args.agent == 3:
        if time.time() < deadline:
            agent_fine_tuner(indicators, coins, scoreboard, quick=args.quick)

    if args.agent is None or args.agent == 4:
        if time.time() < deadline:
            wf_results = agent_walk_forward(indicators, coins, data, scoreboard, quick=args.quick)
        else:
            wf_results = []
    else:
        wf_results = []

    # Eindrapport
    generate_report(scoreboard, wf_results)

    total_time = time.time() - t0
    print(f"\n  Totale runtime: {total_time/60:.1f} minuten")
    print(f"  KLAAR!")


if __name__ == '__main__':
    main()

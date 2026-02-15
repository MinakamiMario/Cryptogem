#!/usr/bin/env python3
"""
OVERNIGHT OPTIMIZER — Realistic Equity + Monte Carlo + Continue Optimalisatie
=============================================================================
1. REALISTIC EQUITY: je zet in wat je hebt, niet meer
2. MONTE CARLO: 10.000 trade-volgorde shuffles → winstkans berekenen
3. PARAMETER SWEEP: systematisch alle knoppen doordraaien
4. HILL CLIMBING: vanuit beste config, stap voor stap verbeteren
5. NOOIT STOPPEN: bij verslechtering → terug naar beste, andere richting

Output: overnight_results.json met alle gevonden configs + scores

Gebruik:
    python overnight_optimizer.py              # Volledige nacht-run
    python overnight_optimizer.py --quick      # Snelle test (minder sims)
"""
import sys
import json
import time
import random
import math
from pathlib import Path
from dataclasses import dataclass
from copy import deepcopy

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

CACHE_FILE = BASE_DIR / 'candle_cache_532.json'
KRAKEN_FEE = 0.0026

# ============================================================
# INDICATOR PRECOMPUTE (identical to mega_vergelijk)
# ============================================================

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


def precompute_all(data, coins):
    """Precompute ALL indicators for ALL coins."""
    print(f"  Precomputing indicators voor {len(coins)} coins...", flush=True)
    t0 = time.time()
    indicators = {}
    for ci, pair in enumerate(coins):
        candles = data[pair]
        n = len(candles)
        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        volumes = [c.get('volume', 0) for c in candles]
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
        if (ci + 1) % 100 == 0:
            print(f"    ... {ci+1}/{len(coins)} ({time.time()-t0:.0f}s)", flush=True)
    print(f"  Precompute klaar: {time.time()-t0:.1f}s", flush=True)
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
# REALISTIC EQUITY BACKTEST
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
    """
    REALISTIC backtest:
    - Start met INITIAL_CAPITAL
    - Per trade zet je in wat je hebt (equity), niet meer
    - Bij meerdere posities: equity / max_pos per positie
    - Als equity <= 0: je bent broke, stop
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

    last_exit_bar = {p: -999 for p in coin_list}
    last_exit_was_stop = {p: False for p in coin_list}

    for bar in range(start_bar, max_bars):
        if equity < 0:
            broke = True
            break

        sells = []

        # ---- EXIT CHECK ----
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

        # Process sells FIRST (free up equity)
        for pair, exit_price, reason, pos in sells:
            gross = (exit_price - pos.entry_price) / pos.entry_price * pos.size_usd
            fees = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
            net = gross - fees
            equity += pos.size_usd + net  # Return invested capital + P&L
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

        # ---- ENTRY CHECK (use available equity) ----
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

        # Calculate available equity for new positions
        invested = sum(p.size_usd for p in positions.values())
        available = equity - invested

        if len(positions) < max_pos and buys and available > 10:
            buys.sort(key=lambda x: x[1], reverse=True)
            slots = max_pos - len(positions)
            size_per_pos = available / slots  # Divide available equity equally

            for pair, vol_ratio in buys:
                if len(positions) >= max_pos:
                    break
                if size_per_pos < 10:  # Minimum $10 per trade
                    break

                ind = indicators[pair]
                ep = ind['closes'][bar]
                atr = ind['atr'][bar] or 0
                if exit_type in ('trail',):
                    stop = ep - atr * cfg.get('atr_mult', 2.0)
                    hard = ep * (1 - cfg.get('max_stop_pct', 15.0) / 100)
                    if stop < hard:
                        stop = hard
                else:
                    stop = ep * (1 - cfg.get('sl_pct', cfg.get('max_stop_pct', 15.0)) / 100)

                # REALISTIC: invest what you have, not more
                equity -= size_per_pos  # Lock up capital
                positions[pair] = Pos(
                    pair=pair, entry_price=ep, entry_bar=bar,
                    size_usd=size_per_pos, stop_price=stop, highest_price=ep)

        # Equity tracking (mark-to-market: equity + unrealized P&L of open positions)
        total_value = equity  # Free cash
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
# MONTE CARLO: Shuffle trade order, run N simulations
# ============================================================

def monte_carlo(trade_pnl_pcts, n_sims=10000, seed=42):
    """
    Monte Carlo met realistic equity:
    - Neem de trade P&L percentages (niet dollar bedragen)
    - Shuffle de volgorde
    - Start met $2000, zet alles in per trade
    - Tel hoe vaak je winstgevend eindigt
    """
    rng = random.Random(seed)
    n_trades = len(trade_pnl_pcts)
    if n_trades < 3:
        return {'win_pct': 0, 'median_equity': INITIAL_CAPITAL, 'mean_equity': INITIAL_CAPITAL,
                'p5': INITIAL_CAPITAL, 'p25': INITIAL_CAPITAL, 'p75': INITIAL_CAPITAL,
                'p95': INITIAL_CAPITAL, 'min_equity': INITIAL_CAPITAL, 'max_equity': INITIAL_CAPITAL,
                'broke_pct': 0, 'n_sims': 0, 'n_trades': n_trades}

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
            # Invest all available equity
            trade_pnl = eq * (pnl_pct / 100)
            eq += trade_pnl
        final_equities.append(eq)

    final_equities.sort()
    n = len(final_equities)
    winners = sum(1 for e in final_equities if e > INITIAL_CAPITAL)

    return {
        'win_pct': winners / n * 100,
        'median_equity': final_equities[n // 2],
        'mean_equity': sum(final_equities) / n,
        'p5': final_equities[int(n * 0.05)],
        'p25': final_equities[int(n * 0.25)],
        'p75': final_equities[int(n * 0.75)],
        'p95': final_equities[int(n * 0.95)],
        'min_equity': final_equities[0],
        'max_equity': final_equities[-1],
        'broke_pct': broke_count / n * 100,
        'n_sims': n_sims,
        'n_trades': n_trades,
    }


# ============================================================
# CONFIG EVALUATION: backtest + monte carlo → score
# ============================================================

def evaluate_config(indicators, coins, cfg, n_sims=10000, label=""):
    """Full evaluation: realistic backtest + Monte Carlo."""
    bt = run_backtest_realistic(indicators, coins, cfg)

    # Extract trade P&L percentages for Monte Carlo
    pnl_pcts = [t['pnl_pct'] for t in bt['trade_list']]

    mc = monte_carlo(pnl_pcts, n_sims=n_sims)

    # Composite score:
    # 40% Monte Carlo win percentage (most important: how often do you profit?)
    # 25% Median equity (how much do you typically end with?)
    # 15% Walk-forward robustness approximation (P&L without best trade)
    # 10% Trade count (more trades = more statistical significance)
    # 10% Low drawdown bonus

    mc_score = mc['win_pct']  # 0-100
    median_score = min(100, max(0, (mc['median_equity'] - 1000) / 40))  # $1000-$5000 → 0-100
    n_trades = bt['trades']
    trade_score = min(100, n_trades / 0.5)  # 0-50 trades → 0-100
    dd_score = max(0, 100 - bt['dd'] * 1.5)  # low DD = high score

    # NoTop: remove best trade and check if still profitable
    if len(pnl_pcts) > 1:
        sorted_pcts = sorted(pnl_pcts, reverse=True)
        notop_pcts = sorted_pcts[1:]  # Remove best
        mc_notop = monte_carlo(notop_pcts, n_sims=min(3000, n_sims), seed=123)
        notop_score = mc_notop['win_pct']
    else:
        notop_score = 0

    total_score = (mc_score * 0.35 +
                   notop_score * 0.20 +
                   median_score * 0.20 +
                   trade_score * 0.10 +
                   dd_score * 0.15)

    return {
        'label': label,
        'cfg': cfg,
        'backtest': {
            'trades': bt['trades'], 'wr': round(bt['wr'], 1),
            'pnl': round(bt['pnl'], 2),
            'final_equity': round(bt['final_equity'], 2),
            'pf': round(bt['pf'], 2) if bt['pf'] < 999 else 'INF',
            'dd': round(bt['dd'], 1),
            'broke': bt['broke'],
        },
        'monte_carlo': {
            'win_pct': round(mc['win_pct'], 1),
            'median_eq': round(mc['median_equity'], 0),
            'mean_eq': round(mc['mean_equity'], 0),
            'p5': round(mc['p5'], 0),
            'p95': round(mc['p95'], 0),
            'broke_pct': round(mc['broke_pct'], 1),
        },
        'notop_win_pct': round(notop_score, 1),
        'score': round(total_score, 1),
        'n_trades_pcts': pnl_pcts,  # For further analysis
    }


# ============================================================
# PARAMETER SPACE: all knobs to turn
# ============================================================

BASE_CONFIG = {
    'exit_type': 'trail',
    'rsi_max': 40, 'atr_mult': 2.0,
    'vol_spike_mult': 3.0, 'vol_confirm': True,
    'breakeven': True, 'be_trigger': 3.0,
    'time_max_bars': 10,
    'rsi_recovery': True, 'rsi_rec_target': 45,
    'max_stop_pct': 15.0,
    'max_pos': 1,
}

# Each parameter and its possible values to sweep
PARAM_SPACE = {
    'vol_spike_mult': [2.0, 2.5, 3.0, 3.5, 4.0, 5.0],
    'rsi_max': [30, 35, 38, 40, 42, 45],
    'atr_mult': [1.5, 2.0, 2.5, 3.0, 3.5],
    'time_max_bars': [6, 8, 10, 12, 15, 20],
    'rsi_rec_target': [40, 42, 44, 45, 46, 47, 48, 50],
    'be_trigger': [2.0, 2.5, 3.0, 3.5, 4.0, 5.0],
    'max_stop_pct': [8.0, 10.0, 12.0, 15.0, 20.0, 25.0],
    'max_pos': [1, 2, 3],
    # V9-style exit parameters (for tp_sl exit_type)
    'tp_pct': [3.0, 5.0, 7.0, 8.0, 10.0],
    'sl_pct': [8.0, 10.0, 15.0, 20.0, 25.0],
    'time_max_bars': [8, 10, 12, 15, 20],
    # Exit type
    'exit_type': ['trail', 'tp_sl', 'hybrid_notrl'],
    # Toggle features
    'breakeven': [True, False],
    'rsi_recovery': [True, False],
    'vol_confirm': [True, False],
}


# ============================================================
# OPTIMIZATION ENGINE
# ============================================================

def print_result(r, prefix=""):
    bt = r['backtest']
    mc = r['monte_carlo']
    pf_s = f"{bt['pf']}" if bt['pf'] != 'INF' else 'INF'
    print(f"{prefix}{r['label']:<40} "
          f"SC:{r['score']:>5.1f} | "
          f"MC:{mc['win_pct']:>5.1f}% | "
          f"NT:{r['notop_win_pct']:>5.1f}% | "
          f"Med:${mc['median_eq']:>6.0f} | "
          f"Tr:{bt['trades']:>3} WR:{bt['wr']:>5.1f}% "
          f"P&L:${bt['pnl']:>+8.0f} DD:{bt['dd']:>5.1f}% "
          f"PF:{pf_s:>5}", flush=True)


def hill_climb(indicators, coins, best_cfg, best_score, best_label,
               results_log, n_sims=10000, max_rounds=50):
    """
    Hill climbing optimizer:
    - Start vanuit best_cfg
    - Probeer elk parameter één stapje omhoog/omlaag
    - Als beter: accepteer en ga verder
    - Als niet beter: probeer volgende parameter
    - Stop na max_rounds zonder verbetering
    """
    current_cfg = deepcopy(best_cfg)
    current_score = best_score
    rounds_without_improvement = 0
    total_evals = 0

    # Which params to try based on exit type
    param_order = ['vol_spike_mult', 'rsi_max', 'rsi_rec_target',
                    'time_max_bars', 'atr_mult', 'be_trigger',
                    'max_stop_pct', 'max_pos', 'breakeven',
                    'rsi_recovery', 'vol_confirm']

    if current_cfg.get('exit_type') == 'tp_sl':
        param_order = ['vol_spike_mult', 'rsi_max', 'tp_pct', 'sl_pct',
                        'time_max_bars', 'max_pos', 'vol_confirm']

    print(f"\n  Hill climbing vanuit score {current_score:.1f}...", flush=True)

    while rounds_without_improvement < max_rounds:
        improved_this_cycle = False

        for param in param_order:
            if param not in PARAM_SPACE:
                continue
            values = PARAM_SPACE[param]
            current_val = current_cfg.get(param)

            # Skip irrelevant params
            if param in ('tp_pct', 'sl_pct', 'time_max_bars') and current_cfg.get('exit_type') != 'tp_sl':
                continue
            if param in ('atr_mult', 'be_trigger') and current_cfg.get('exit_type') == 'tp_sl':
                continue
            if param == 'rsi_rec_target' and not current_cfg.get('rsi_recovery', False):
                continue

            for val in values:
                if val == current_val:
                    continue

                test_cfg = deepcopy(current_cfg)
                test_cfg[param] = val
                total_evals += 1

                label = f"HC-{param}={val}"
                r = evaluate_config(indicators, coins, test_cfg, n_sims=n_sims, label=label)

                if r['score'] > current_score:
                    print(f"    ✅ {param}: {current_val} → {val} | "
                          f"score {current_score:.1f} → {r['score']:.1f} "
                          f"(+{r['score']-current_score:.1f})", flush=True)
                    current_cfg = test_cfg
                    current_score = r['score']
                    improved_this_cycle = True
                    rounds_without_improvement = 0

                    results_log.append(r)

                    # Update best if global best
                    if r['score'] > best_score:
                        best_cfg = deepcopy(test_cfg)
                        best_score = r['score']
                        best_label = label
                        print_result(r, prefix="    🏆 NEW BEST: ")

        if not improved_this_cycle:
            rounds_without_improvement += 1
            if rounds_without_improvement >= 3:
                break

    print(f"  Hill climb klaar: {total_evals} evaluaties, "
          f"score {best_score:.1f}", flush=True)
    return best_cfg, best_score, best_label


def random_neighbor(cfg):
    """Generate a random neighbor config by changing 1-2 parameters."""
    new_cfg = deepcopy(cfg)
    params = list(PARAM_SPACE.keys())

    # Filter relevant params based on exit type
    if new_cfg.get('exit_type') == 'tp_sl':
        params = [p for p in params if p not in ('atr_mult', 'be_trigger', 'breakeven',
                                                    'rsi_recovery', 'rsi_rec_target')]
    else:
        params = [p for p in params if p not in ('tp_pct', 'sl_pct', 'time_max_bars')]

    n_changes = random.choice([1, 1, 1, 2])  # Usually 1, sometimes 2
    for _ in range(n_changes):
        param = random.choice(params)
        values = PARAM_SPACE[param]
        new_cfg[param] = random.choice(values)

    return new_cfg


# ============================================================
# MAIN OVERNIGHT LOOP
# ============================================================

def main():
    quick = '--quick' in sys.argv
    n_sims = 3000 if quick else 10000
    max_hours = 0.5 if quick else 8  # Run for 8 hours overnight

    print("=" * 100, flush=True)
    print(f"OVERNIGHT OPTIMIZER — Realistic Equity + Monte Carlo", flush=True)
    print(f"Mode: {'QUICK TEST' if quick else 'FULL OVERNIGHT'} | "
          f"MC sims: {n_sims} | Max hours: {max_hours}", flush=True)
    print("=" * 100, flush=True)

    t_start = time.time()

    # Load data
    with open(CACHE_FILE) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith('_')])
    print(f"Geladen: {len(coins)} coins", flush=True)

    indicators = precompute_all(data, coins)

    # ============================================================
    # PHASE 1: Evaluate known good configs
    # ============================================================
    print(f"\n{'=' * 100}", flush=True)
    print("FASE 1: Bekende configs evalueren met realistic equity + Monte Carlo", flush=True)
    print(f"{'=' * 100}", flush=True)

    known_configs = [
        ('V5+VolSpk3 1x$2000', {
            'exit_type': 'trail', 'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike_mult': 3.0, 'vol_confirm': True,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
            'max_stop_pct': 15.0, 'max_pos': 1,
        }),
        ('V5 baseline 1x$2000', {
            'exit_type': 'trail', 'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike_mult': 2.0, 'vol_confirm': True,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
            'max_stop_pct': 15.0, 'max_pos': 1,
        }),
        ('V3+VolSpike 2x$1000', {
            'exit_type': 'trail', 'rsi_max': 35, 'atr_mult': 3.0,
            'vol_spike_mult': 2.0, 'vol_confirm': False,
            'breakeven': False, 'time_max_bars': 999,
            'rsi_recovery': False, 'max_stop_pct': 15.0, 'max_pos': 2,
        }),
        ('HYBRID DC/BB/RSI NoTrail', {
            'exit_type': 'hybrid_notrl', 'rsi_max': 40,
            'vol_spike_mult': 2.0, 'vol_confirm': True,
            'time_max_bars': 15, 'rsi_recovery': True, 'rsi_rec_target': 45,
            'max_stop_pct': 20.0, 'max_pos': 1,
        }),
        ('V9C TP7 SL15 TM15', {
            'exit_type': 'tp_sl', 'rsi_max': 40,
            'vol_spike_mult': 2.0, 'vol_confirm': True,
            'tp_pct': 7.0, 'sl_pct': 15.0, 'time_max_bars': 15,
            'max_pos': 1,
        }),
        ('V5+VolSpk3 2x$1000', {
            'exit_type': 'trail', 'rsi_max': 40, 'atr_mult': 2.0,
            'vol_spike_mult': 3.0, 'vol_confirm': True,
            'breakeven': True, 'be_trigger': 3.0,
            'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
            'max_stop_pct': 15.0, 'max_pos': 2,
        }),
    ]

    results_log = []
    best_result = None
    best_score = 0

    print(f"\n{'Label':<40} {'Score':>6} | {'MC%':>6} | {'NT%':>6} | "
          f"{'MedEq':>8} | {'Tr':>3} {'WR%':>6} {'P&L':>10} {'DD%':>6} {'PF':>5}",
          flush=True)
    print(f"{'─' * 110}", flush=True)

    for label, cfg in known_configs:
        r = evaluate_config(indicators, coins, cfg, n_sims=n_sims, label=label)
        results_log.append(r)
        print_result(r)

        if r['score'] > best_score:
            best_score = r['score']
            best_result = r

    print(f"\n  🏆 Beste bekende config: {best_result['label']} (score: {best_score:.1f})",
          flush=True)

    # ============================================================
    # PHASE 2: Systematic parameter sweep from best config
    # ============================================================
    print(f"\n{'=' * 100}", flush=True)
    print("FASE 2: Systematic sweep vanuit beste config", flush=True)
    print(f"{'=' * 100}", flush=True)

    best_cfg = deepcopy(best_result['cfg'])
    best_label = best_result['label']

    # Sweep each parameter individually
    sweep_params = ['vol_spike_mult', 'rsi_max', 'rsi_rec_target',
                     'time_max_bars', 'atr_mult', 'be_trigger',
                     'max_stop_pct', 'max_pos']

    for param in sweep_params:
        if param not in PARAM_SPACE:
            continue
        if param in ('atr_mult', 'be_trigger') and best_cfg.get('exit_type') == 'tp_sl':
            continue

        values = PARAM_SPACE[param]
        print(f"\n  Sweep: {param} ({len(values)} values)", flush=True)

        for val in values:
            elapsed_hrs = (time.time() - t_start) / 3600
            if elapsed_hrs > max_hours:
                print(f"\n⏰ Tijdslimiet bereikt ({max_hours}h). Stoppen.", flush=True)
                break

            test_cfg = deepcopy(best_cfg)
            test_cfg[param] = val
            label = f"sweep-{param}={val}"
            r = evaluate_config(indicators, coins, test_cfg, n_sims=n_sims, label=label)
            results_log.append(r)

            marker = "⭐" if r['score'] > best_score else "  "
            bt = r['backtest']
            mc = r['monte_carlo']
            print(f"    {marker} {param}={val:<6} SC:{r['score']:>5.1f} "
                  f"MC:{mc['win_pct']:>5.1f}% Med:${mc['median_eq']:>6.0f} "
                  f"Tr:{bt['trades']:>3} P&L:${bt['pnl']:>+7.0f}", flush=True)

            if r['score'] > best_score:
                best_score = r['score']
                best_cfg = deepcopy(test_cfg)
                best_label = label
                best_result = r
                print(f"    🏆 NEW BEST! Score: {best_score:.1f}", flush=True)

    # ============================================================
    # PHASE 3: Hill climbing from best config
    # ============================================================
    elapsed_hrs = (time.time() - t_start) / 3600
    if elapsed_hrs < max_hours:
        print(f"\n{'=' * 100}", flush=True)
        print("FASE 3: Hill climbing optimalisatie", flush=True)
        print(f"{'=' * 100}", flush=True)

        best_cfg, best_score, best_label = hill_climb(
            indicators, coins, best_cfg, best_score, best_label,
            results_log, n_sims=n_sims, max_rounds=10)

    # ============================================================
    # PHASE 4: Random exploration (until time runs out)
    # ============================================================
    elapsed_hrs = (time.time() - t_start) / 3600
    if elapsed_hrs < max_hours:
        print(f"\n{'=' * 100}", flush=True)
        print("FASE 4: Random exploratie (tot tijdslimiet)", flush=True)
        print(f"{'=' * 100}", flush=True)

        explore_count = 0
        improvements = 0
        explore_best_score = best_score
        explore_best_cfg = deepcopy(best_cfg)

        while True:
            elapsed_hrs = (time.time() - t_start) / 3600
            if elapsed_hrs > max_hours:
                break

            # Generate random neighbor of CURRENT best
            test_cfg = random_neighbor(explore_best_cfg)
            explore_count += 1
            label = f"explore-{explore_count}"
            r = evaluate_config(indicators, coins, test_cfg, n_sims=n_sims, label=label)
            results_log.append(r)

            if r['score'] > explore_best_score:
                improvements += 1
                explore_best_score = r['score']
                explore_best_cfg = deepcopy(test_cfg)
                print_result(r, prefix=f"  ✅ #{explore_count} ")

                if r['score'] > best_score:
                    best_score = r['score']
                    best_cfg = deepcopy(test_cfg)
                    best_label = label
                    best_result = r
                    print(f"    🏆 NEW GLOBAL BEST! Score: {best_score:.1f}", flush=True)

                    # Hill climb from new best
                    best_cfg, best_score, best_label = hill_climb(
                        indicators, coins, best_cfg, best_score, best_label,
                        results_log, n_sims=n_sims, max_rounds=5)
                    explore_best_cfg = deepcopy(best_cfg)
                    explore_best_score = best_score

            elif explore_count % 50 == 0:
                remaining_hrs = max_hours - elapsed_hrs
                print(f"  ... {explore_count} exploraties, {improvements} verbeteringen, "
                      f"beste score: {best_score:.1f}, "
                      f"nog {remaining_hrs:.1f}h", flush=True)

        print(f"\n  Exploratie klaar: {explore_count} configs, "
              f"{improvements} verbeteringen", flush=True)

    # ============================================================
    # FINAL REPORT
    # ============================================================
    elapsed_total = time.time() - t_start

    print(f"\n{'=' * 100}", flush=True)
    print(f"EINDRESULTAAT — {elapsed_total/3600:.1f} uur, "
          f"{len(results_log)} configs geëvalueerd", flush=True)
    print(f"{'=' * 100}", flush=True)

    # Top 10
    top10 = sorted(results_log, key=lambda x: x['score'], reverse=True)[:10]
    print(f"\n{'Rk':<4} {'Score':>6} {'Label':<40} {'MC%':>6} {'NT%':>6} "
          f"{'MedEq':>8} {'Tr':>3} {'P&L':>10} {'DD%':>6}", flush=True)
    print(f"{'─' * 100}", flush=True)

    for i, r in enumerate(top10):
        bt = r['backtest']
        mc = r['monte_carlo']
        star = " ⭐" if i == 0 else ""
        print(f"  #{i+1:<2} {r['score']:>5.1f} {r['label']:<40} "
              f"{mc['win_pct']:>5.1f}% {r['notop_win_pct']:>5.1f}% "
              f"${mc['median_eq']:>7.0f} {bt['trades']:>3} "
              f"${bt['pnl']:>+8.0f} {bt['dd']:>5.1f}%{star}", flush=True)

    # Best config details
    br = best_result
    print(f"\n🏆 BESTE CONFIG: {br['label']}", flush=True)
    print(f"   Parameters:", flush=True)
    for k, v in sorted(br['cfg'].items()):
        print(f"     {k}: {v}", flush=True)
    print(f"\n   Backtest:     {br['backtest']}", flush=True)
    print(f"   Monte Carlo:  {br['monte_carlo']}", flush=True)
    print(f"   NoTop Win%:   {br['notop_win_pct']}%", flush=True)
    print(f"   SCORE:        {br['score']}", flush=True)

    # Save report
    report = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'elapsed_hours': round(elapsed_total / 3600, 2),
        'configs_evaluated': len(results_log),
        'n_sims': n_sims,
        'best': {
            'label': br['label'],
            'score': br['score'],
            'cfg': br['cfg'],
            'backtest': br['backtest'],
            'monte_carlo': br['monte_carlo'],
            'notop_win_pct': br['notop_win_pct'],
        },
        'top10': [
            {
                'rank': i + 1,
                'label': r['label'],
                'score': r['score'],
                'cfg': r['cfg'],
                'backtest': r['backtest'],
                'monte_carlo': r['monte_carlo'],
                'notop_win_pct': r['notop_win_pct'],
            }
            for i, r in enumerate(top10)
        ],
    }

    report_file = BASE_DIR / 'overnight_results.json'
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport: {report_file}", flush=True)

    print(f"\nTotaal: {elapsed_total:.0f}s ({elapsed_total/3600:.1f}h)", flush=True)


if __name__ == '__main__':
    main()

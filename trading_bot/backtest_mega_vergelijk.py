#!/usr/bin/env python3
"""
MEGA VERGELIJKING — Alle Historische Configs vs V9C op Dezelfde Dataset
========================================================================
Test ALLE bekende configs uit V3, V4, V5, V5+VolSpk3, V3+VolSpike,
multi-positie varianten, en V9C profit target configs
op de huidige 526-coin dataset met walk-forward validatie.

GEOPTIMALISEERD: Precompute indicators per coin (één keer), dan snelle
backtest per config.

Gebruik:
    python backtest_mega_vergelijk.py
"""
import sys
import json
import time
from pathlib import Path
from dataclasses import dataclass

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

CACHE_FILE = BASE_DIR / 'candle_cache_532.json'
KRAKEN_FEE = 0.0026

# ============================================================
# ALLE CONFIGS
# ============================================================

CONFIGS = {
    # ---- HISTORISCHE TRAIL-BASED CONFIGS ----
    'v4_base': {
        'name': 'V4 DualConfirm Baseline',
        'exit_type': 'trail',
        'rsi_max': 40, 'atr_mult': 2.0,
        'vol_spike_mult': 2.0, 'vol_confirm': True,
        'breakeven': True, 'be_trigger': 3.0,
        'time_max_bars': 10, 'rsi_recovery': False,
        'max_stop_pct': 15.0,
        'max_pos': 1, 'pos_size': 2000,
    },
    'v5_rec45': {
        'name': 'V5 RSI Recovery 45',
        'exit_type': 'trail',
        'rsi_max': 40, 'atr_mult': 2.0,
        'vol_spike_mult': 2.0, 'vol_confirm': True,
        'breakeven': True, 'be_trigger': 3.0,
        'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
        'max_stop_pct': 15.0,
        'max_pos': 1, 'pos_size': 2000,
    },
    'v5_rec47': {
        'name': 'V5 RSI Recovery 47',
        'exit_type': 'trail',
        'rsi_max': 40, 'atr_mult': 2.0,
        'vol_spike_mult': 2.0, 'vol_confirm': True,
        'breakeven': True, 'be_trigger': 3.0,
        'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 47,
        'max_stop_pct': 15.0,
        'max_pos': 1, 'pos_size': 2000,
    },
    'v5_volspk3': {
        'name': 'V5 + VolSpk 3.0x',
        'exit_type': 'trail',
        'rsi_max': 40, 'atr_mult': 2.0,
        'vol_spike_mult': 3.0, 'vol_confirm': True,
        'breakeven': True, 'be_trigger': 3.0,
        'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
        'max_stop_pct': 15.0,
        'max_pos': 1, 'pos_size': 2000,
    },
    'v3_volspike_2x1k': {
        'name': 'V3 + VolSpike 2x$1000',
        'exit_type': 'trail',
        'rsi_max': 35, 'atr_mult': 3.0,
        'vol_spike_mult': 2.0, 'vol_confirm': False,
        'breakeven': False, 'be_trigger': 3.0,
        'time_max_bars': 999, 'rsi_recovery': False,
        'max_stop_pct': 15.0,
        'max_pos': 2, 'pos_size': 1000,
    },
    'v5_2x1000': {
        'name': 'V5 Rec45 2x$1000',
        'exit_type': 'trail',
        'rsi_max': 40, 'atr_mult': 2.0,
        'vol_spike_mult': 2.0, 'vol_confirm': True,
        'breakeven': True, 'be_trigger': 3.0,
        'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
        'max_stop_pct': 15.0,
        'max_pos': 2, 'pos_size': 1000,
    },
    'v5_3x667': {
        'name': 'V5 Rec45 3x$667',
        'exit_type': 'trail',
        'rsi_max': 40, 'atr_mult': 2.0,
        'vol_spike_mult': 2.0, 'vol_confirm': True,
        'breakeven': True, 'be_trigger': 3.0,
        'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
        'max_stop_pct': 15.0,
        'max_pos': 3, 'pos_size': 667,
    },
    'v5_vspk3_2x1k': {
        'name': 'V5 VolSpk3 2x$1000',
        'exit_type': 'trail',
        'rsi_max': 40, 'atr_mult': 2.0,
        'vol_spike_mult': 3.0, 'vol_confirm': True,
        'breakeven': True, 'be_trigger': 3.0,
        'time_max_bars': 10, 'rsi_recovery': True, 'rsi_rec_target': 45,
        'max_stop_pct': 15.0,
        'max_pos': 2, 'pos_size': 1000,
    },

    # ---- V9 PROFIT TARGET CONFIGS ----
    'v9b_tp7_sl15_tm8': {
        'name': 'V9B TP7 SL15 TM8',
        'exit_type': 'tp_sl',
        'rsi_max': 40,
        'vol_spike_mult': 2.0, 'vol_confirm': True,
        'tp_pct': 7.0, 'sl_pct': 15.0, 'tm_bars': 8,
        'max_pos': 1, 'pos_size': 2000,
    },
    'v9c_tp7_sl15_tm15': {
        'name': 'V9C TP7 SL15 TM15',
        'exit_type': 'tp_sl',
        'rsi_max': 40,
        'vol_spike_mult': 2.0, 'vol_confirm': True,
        'tp_pct': 7.0, 'sl_pct': 15.0, 'tm_bars': 15,
        'max_pos': 1, 'pos_size': 2000,
    },
    'v9c_tp7_sl20_tm15': {
        'name': 'V9C TP7 SL20 TM15 (BEST WF)',
        'exit_type': 'tp_sl',
        'rsi_max': 40,
        'vol_spike_mult': 2.0, 'vol_confirm': True,
        'tp_pct': 7.0, 'sl_pct': 20.0, 'tm_bars': 15,
        'max_pos': 1, 'pos_size': 2000,
    },
    'v9c_tp7_sl20_tm12': {
        'name': 'V9C TP7 SL20 TM12',
        'exit_type': 'tp_sl',
        'rsi_max': 40,
        'vol_spike_mult': 2.0, 'vol_confirm': True,
        'tp_pct': 7.0, 'sl_pct': 20.0, 'tm_bars': 12,
        'max_pos': 1, 'pos_size': 2000,
    },

    # ---- HYBRID CONFIGS ----
    'hybrid_notrl': {
        'name': 'HYBRID: DC/BB/RSI, NO trail',
        'exit_type': 'hybrid_notrl',
        'rsi_max': 40,
        'vol_spike_mult': 2.0, 'vol_confirm': True,
        'time_max_bars': 15,
        'rsi_recovery': True, 'rsi_rec_target': 45,
        'max_stop_pct': 20.0,
        'max_pos': 1, 'pos_size': 2000,
    },
    'hybrid_v5_tp7': {
        'name': 'HYBRID: V5 + TP7% cap',
        'exit_type': 'hybrid',
        'rsi_max': 40, 'atr_mult': 2.0,
        'vol_spike_mult': 2.0, 'vol_confirm': True,
        'breakeven': True, 'be_trigger': 3.0,
        'time_max_bars': 15,
        'rsi_recovery': True, 'rsi_rec_target': 45,
        'max_stop_pct': 15.0,
        'tp_pct': 7.0,
        'max_pos': 1, 'pos_size': 2000,
    },
}

# ============================================================
# PRECOMPUTE INDICATORS (ONE TIME, reuse across all configs)
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


def precompute_all(data, coins):
    """Precompute ALL indicators for ALL coins. Run once, reuse for every config."""
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
            'rsi': [None] * n,
            'atr': [None] * n,
            'dc_prev_low': [None] * n,
            'dc_mid': [None] * n,
            'bb_mid': [None] * n,
            'bb_lower': [None] * n,
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
            print(f"    ... {ci+1}/{len(coins)} coins ({time.time()-t0:.0f}s)", flush=True)

    print(f"  Precompute klaar: {time.time()-t0:.1f}s", flush=True)
    return indicators


# ============================================================
# ENTRY CHECK (uses precomputed indicators)
# ============================================================

def check_entry_at_bar(ind, bar, cfg):
    """Check DualConfirm entry for a specific bar using precomputed indicators."""
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
    use_vol_confirm = cfg.get('vol_confirm', False)

    # Base volume filter
    if vol_avg and vol_avg > 0 and cur_vol < vol_avg * VOL_MIN_PCT:
        return False, 0

    # Dual confirm
    dc_sig = (low <= ind['dc_prev_low'][bar] and rsi < rsi_max and close > prev_close)
    bb_sig = (close <= ind['bb_lower'][bar] and rsi < rsi_max and close > prev_close)
    if not (dc_sig and bb_sig):
        return False, 0

    # Volume spike
    if vol_avg and vol_avg > 0 and cur_vol < vol_avg * vol_spike_mult:
        return False, 0

    # Volume confirm (bar-to-bar)
    if use_vol_confirm and prev_vol > 0:
        if cur_vol / prev_vol < 1.0:
            return False, 0

    vol_ratio = cur_vol / vol_avg if vol_avg and vol_avg > 0 else 0
    return True, vol_ratio


# ============================================================
# POSITION
# ============================================================

@dataclass
class Pos:
    pair: str
    entry_price: float
    entry_bar: int
    size_usd: float
    stop_price: float = 0.0
    highest_price: float = 0.0


# ============================================================
# FAST BACKTEST (uses precomputed indicators)
# ============================================================

def run_backtest(indicators, coins, config_key, start_bar=START_BAR, end_bar=None):
    """Fast backtest using precomputed indicators."""
    cfg = CONFIGS[config_key]
    exit_type = cfg['exit_type']
    max_pos = cfg['max_pos']
    pos_size = cfg['pos_size']

    coin_list = [c for c in coins if c in indicators]
    max_bars = max(indicators[p]['n'] for p in coin_list) if coin_list else 0
    if end_bar is not None:
        max_bars = min(max_bars, end_bar)

    positions = {}
    trades = []
    equity = max_pos * pos_size
    initial_eq = equity
    peak_eq = equity
    max_dd = 0

    last_exit_bar = {p: -999 for p in coin_list}
    last_exit_was_stop = {p: False for p in coin_list}

    for bar in range(start_bar, max_bars):
        sells = []
        buys = []

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

            elif exit_type == 'hybrid':
                atr_mult = cfg.get('atr_mult', 2.0)
                max_stop_pct = cfg.get('max_stop_pct', 15.0)
                tp_pct = cfg.get('tp_pct', 7.0)
                tm_bars = cfg.get('time_max_bars', 15)

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

                tp_price = entry_price * (1 + tp_pct / 100)

                if close < hard_stop:
                    exit_price, reason = close, 'HARD STOP'
                elif high >= tp_price:
                    exit_price, reason = tp_price, 'PROFIT TARGET'
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

        # ---- ENTRY CHECK ----
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

        # Process sells
        for pair, exit_price, reason, pos in sells:
            gross = (exit_price - pos.entry_price) / pos.entry_price * pos.size_usd
            fees = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
            net = gross - fees
            equity += net
            is_stop = 'STOP' in reason
            last_exit_bar[pair] = bar
            last_exit_was_stop[pair] = is_stop
            trades.append({
                'pair': pair, 'entry': pos.entry_price, 'exit': exit_price,
                'pnl': net, 'reason': reason, 'bars': bar - pos.entry_bar,
                'entry_bar': pos.entry_bar, 'exit_bar': bar,
            })
            del positions[pair]

        # Process buys
        if len(positions) < max_pos and buys:
            buys.sort(key=lambda x: x[1], reverse=True)
            for pair, vol_ratio in buys:
                if len(positions) >= max_pos:
                    break
                ind = indicators[pair]
                ep = ind['closes'][bar]
                atr = ind['atr'][bar] or 0
                if exit_type in ('trail', 'hybrid'):
                    stop = ep - atr * cfg.get('atr_mult', 2.0)
                    hard = ep * (1 - cfg.get('max_stop_pct', 15.0) / 100)
                    if stop < hard:
                        stop = hard
                else:
                    stop = ep * (1 - cfg.get('sl_pct', cfg.get('max_stop_pct', 15.0)) / 100)
                positions[pair] = Pos(pair=pair, entry_price=ep, entry_bar=bar,
                                      size_usd=pos_size, stop_price=stop, highest_price=ep)

        # Equity tracking
        if equity > peak_eq:
            peak_eq = equity
        dd = (peak_eq - equity) / peak_eq * 100 if peak_eq > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Close remaining
    for pair, pos in list(positions.items()):
        ind = indicators[pair]
        last_idx = min(ind['n'] - 1, max_bars - 1)
        lp = ind['closes'][last_idx]
        gross = (lp - pos.entry_price) / pos.entry_price * pos.size_usd
        fees = pos.size_usd * KRAKEN_FEE + (pos.size_usd + gross) * KRAKEN_FEE
        net = gross - fees
        trades.append({
            'pair': pair, 'entry': pos.entry_price, 'exit': lp,
            'pnl': net, 'reason': 'END', 'bars': max_bars - pos.entry_bar,
            'entry_bar': pos.entry_bar, 'exit_bar': max_bars,
        })

    return compute_metrics(trades, max_dd)


def compute_metrics(trades, max_dd):
    total_pnl = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    n = len(trades)
    wr = len(wins) / n * 100 if n else 0
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else float('inf')
    ev = total_pnl / n if n else 0

    if n > 1:
        sorted_t = sorted(trades, key=lambda x: x['pnl'], reverse=True)
        top = sorted_t[0]
        pnl_no_top = total_pnl - top['pnl']
        ev_no_top = pnl_no_top / (n - 1)
        top_pct = top['pnl'] / total_pnl * 100 if total_pnl > 0 else 0
    else:
        top = trades[0] if trades else None
        pnl_no_top, ev_no_top, top_pct = 0, 0, 100

    reasons = {}
    for t in trades:
        r = t['reason']
        if r not in reasons:
            reasons[r] = {'n': 0, 'pnl': 0, 'wins': 0}
        reasons[r]['n'] += 1
        reasons[r]['pnl'] += t['pnl']
        if t['pnl'] > 0:
            reasons[r]['wins'] += 1

    return {
        'trades': n, 'wins': len(wins), 'wr': wr,
        'pnl': total_pnl, 'pf': pf, 'dd': max_dd, 'ev': ev,
        'pnl_no_top': pnl_no_top, 'ev_no_top': ev_no_top,
        'top_pct': top_pct,
        'top_trade': f"{top['pair']} ${top['pnl']:+.0f}" if top else 'N/A',
        'reasons': reasons, 'trade_list': trades,
    }


# ============================================================
# WALK-FORWARD
# ============================================================

def walk_forward(indicators, coins, config_key, n_folds=5, train_pct=0.7):
    coin_list = [c for c in coins if c in indicators]
    total_bars = max(indicators[p]['n'] for p in coin_list) if coin_list else 0
    usable = total_bars - START_BAR
    fold_size = usable // n_folds
    overlap = int(fold_size * 0.3)

    results = []
    for fold in range(n_folds):
        fs = START_BAR + fold * (fold_size - overlap)
        fe = min(fs + fold_size, total_bars)
        if fe - fs < 30:
            continue
        te = int(fs + (fe - fs) * train_pct)

        train = run_backtest(indicators, coins, config_key, start_bar=fs, end_bar=te)
        test = run_backtest(indicators, coins, config_key, start_bar=te, end_bar=fe)
        results.append({
            'fold': fold + 1,
            'train_pnl': train['pnl'], 'train_trades': train['trades'], 'train_wr': train['wr'],
            'test_pnl': test['pnl'], 'test_trades': test['trades'], 'test_wr': test['wr'],
        })

    profitable = sum(1 for r in results if r['test_pnl'] > 0)
    return {'folds': len(results), 'profitable': profitable,
            'ratio': f"{profitable}/{len(results)}", 'details': results}


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 95, flush=True)
    print("MEGA VERGELIJKING — Alle Configs op 526-Coin Dataset", flush=True)
    print("=" * 95, flush=True)

    t0 = time.time()

    print(f"\nLaden: {CACHE_FILE}", flush=True)
    with open(CACHE_FILE) as f:
        data = json.load(f)
    coins = sorted([k for k in data if not k.startswith('_')])
    print(f"Geladen: {len(coins)} coins", flush=True)

    # Precompute indicators ONCE
    indicators = precompute_all(data, coins)

    # Run all configs
    print(f"\n{'─' * 95}", flush=True)
    print(f"{'Config':<30} {'Tr':>4} {'WR%':>6} {'P&L':>10} {'NoTop':>10} "
          f"{'EV/t':>8} {'PF':>6} {'DD%':>6} {'Top%':>6}", flush=True)
    print(f"{'─' * 95}", flush=True)

    results = {}
    for key in CONFIGS:
        t1 = time.time()
        r = run_backtest(indicators, coins, key)
        dt = time.time() - t1
        results[key] = r

        pf_s = f"{r['pf']:.1f}" if r['pf'] < 100 else "INF"
        print(f"{CONFIGS[key]['name']:<30} {r['trades']:>4} {r['wr']:>5.1f}% "
              f"${r['pnl']:>+8.0f} ${r['pnl_no_top']:>+8.0f} "
              f"${r['ev']:>+6.1f} {pf_s:>6} {r['dd']:>5.1f}% "
              f"{r['top_pct']:>5.0f}%  [{dt:.1f}s]", flush=True)

    # Exit reason breakdown
    print(f"\n{'=' * 95}", flush=True)
    print("EXIT REASON BREAKDOWN", flush=True)
    print(f"{'=' * 95}", flush=True)

    for key in CONFIGS:
        r = results[key]
        print(f"\n  {CONFIGS[key]['name']}:", flush=True)
        for reason, stats in sorted(r['reasons'].items()):
            wr_r = stats['wins'] / stats['n'] * 100 if stats['n'] else 0
            print(f"    {reason:<15} {stats['n']:>3}x | WR {wr_r:>5.1f}% | "
                  f"P&L ${stats['pnl']:>+8.0f}", flush=True)

    # Walk-Forward
    print(f"\n{'=' * 95}", flush=True)
    print("WALK-FORWARD VALIDATIE", flush=True)
    print(f"{'=' * 95}", flush=True)

    wf_results = {}
    for key in CONFIGS:
        t1 = time.time()
        wf3 = walk_forward(indicators, coins, key, n_folds=3)
        wf5 = walk_forward(indicators, coins, key, n_folds=5)
        wf_results[key] = {'wf3': wf3, 'wf5': wf5}
        dt = time.time() - t1

        print(f"\n  {CONFIGS[key]['name']:<30} WF3: {wf3['ratio']:<5} WF5: {wf5['ratio']:<5} [{dt:.1f}s]",
              flush=True)
        for fd in wf5['details']:
            m = "✅" if fd['test_pnl'] > 0 else "❌"
            print(f"      Fold {fd['fold']}: "
                  f"TRAIN {fd['train_trades']:>2}tr ${fd['train_pnl']:>+7.0f} | "
                  f"TEST {fd['test_trades']:>2}tr ${fd['test_pnl']:>+7.0f} {m}", flush=True)

    # Final Ranking
    print(f"\n{'=' * 95}", flush=True)
    print("EINDRANGSCHIKKING", flush=True)
    print(f"{'=' * 95}", flush=True)

    scored = []
    for key in CONFIGS:
        r = results[key]
        wf = wf_results[key]
        wf5_pct = wf['wf5']['profitable'] / max(1, wf['wf5']['folds']) * 100

        pnl_score = min(100, max(0, (r['pnl'] + 500) / 60))
        notop_score = min(100, max(0, (r['pnl_no_top'] + 1000) / 40))
        ev_score = min(100, max(0, (r['ev'] + 50) / 3))
        dd_score = max(0, 100 - r['dd'] * 1.5)
        wf_score = wf5_pct

        total = (pnl_score * 0.15 + notop_score * 0.25 +
                 wf_score * 0.30 + ev_score * 0.15 + dd_score * 0.15)
        scored.append((key, total, r, wf))

    scored.sort(key=lambda x: x[1], reverse=True)

    print(f"\n{'Rk':<4} {'Score':>6} {'Config':<30} {'Tr':>4} {'P&L':>10} "
          f"{'NoTop':>10} {'EV/t':>8} {'WF3':>5} {'WF5':>5} {'DD%':>6}", flush=True)
    print(f"{'─' * 100}", flush=True)

    for i, (key, score, r, wf) in enumerate(scored):
        star = " ⭐" if i == 0 else ""
        print(f"  #{i+1:<2} {score:>5.1f} {CONFIGS[key]['name']:<30} "
              f"{r['trades']:>4} ${r['pnl']:>+8.0f} ${r['pnl_no_top']:>+8.0f} "
              f"${r['ev']:>+6.1f} {wf['wf3']['ratio']:>5} {wf['wf5']['ratio']:>5} "
              f"{r['dd']:>5.1f}%{star}", flush=True)

    elapsed = time.time() - t0
    print(f"\nTotaal: {elapsed:.0f}s ({elapsed/60:.1f}min)", flush=True)

    # Save report
    report = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'coins': len(coins), 'elapsed_sec': round(elapsed, 1),
        'ranking': [
            {
                'rank': i + 1, 'key': key,
                'name': CONFIGS[key]['name'],
                'score': round(score, 1),
                'trades': r['trades'], 'wr': round(r['wr'], 1),
                'pnl': round(r['pnl'], 2),
                'pnl_no_top': round(r['pnl_no_top'], 2),
                'ev': round(r['ev'], 2),
                'pf': round(r['pf'], 2) if r['pf'] < 999 else 'INF',
                'dd': round(r['dd'], 1),
                'top_pct': round(r['top_pct'], 1),
                'wf3': wf['wf3']['ratio'], 'wf5': wf['wf5']['ratio'],
            }
            for i, (key, score, r, wf) in enumerate(scored)
        ],
    }
    report_file = BASE_DIR / 'mega_vergelijk_report.json'
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\nReport: {report_file}", flush=True)


if __name__ == '__main__':
    main()

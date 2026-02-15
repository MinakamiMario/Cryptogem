#!/usr/bin/env python3
"""
Exit Strategie Optimalisatie Backtest
======================================
Pre-compute entries & indicators ONCE, then test 30+ exit variants efficiently.

Varianten:
  A) Profit targets: vaste %, DC upper, BB upper
  B) Partial exits: 50% bij mid, rest trailing
  C) Trailing stop varianten: Chandelier, Parabolic SAR, break-even
  D) RSI exit tuning: 60, 65, 70, 75, 80, geen
  E) Time-based exits: max bars, time decay
  F) Combinaties: break-even + upper target, partial + upper

Gebruik:
    python backtest_exit_optimization.py
"""
import os
import sys
import json
import time
import logging
from pathlib import Path
from dotenv import load_dotenv
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / '.env')

CACHE_FILE = BASE_DIR / 'candle_cache_60d.json'
KRAKEN_FEE = 0.0026

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('exit_opt')


# ============================================================
# DATA & PRE-COMPUTATION
# ============================================================

def load_cache():
    if not CACHE_FILE.exists():
        logger.error(f"Cache niet gevonden: {CACHE_FILE}")
        sys.exit(1)
    with open(CACHE_FILE) as f:
        cache = json.load(f)
    coins = len([k for k in cache if not k.startswith('_')])
    logger.info(f"Cache: {coins} coins, {cache.get('_days', '?')}d")
    return cache


def precompute_indicators(cache):
    """
    Pre-compute alle indicators per coin per bar.
    Returns dict: pair -> list of bar_data dicts.
    """
    result = {}
    coins = [k for k in cache if not k.startswith('_')]

    for pair in coins:
        candles = cache[pair]
        if not isinstance(candles, list) or len(candles) < 30:
            continue

        bars = []
        for i in range(25, len(candles)):
            window = candles[:i + 1]
            closes = [c['close'] for c in window]
            highs = [c['high'] for c in window]
            lows = [c['low'] for c in window]

            rsi = calc_rsi(closes, 14)
            atr = calc_atr(highs, lows, closes, 14)

            prev_highs = highs[:-1]
            prev_lows = lows[:-1]
            _, prev_lowest, _ = calc_donchian(prev_highs, prev_lows, 20)
            dc_high, dc_low, dc_mid = calc_donchian(highs, lows, 20)
            bb_mid, bb_upper, bb_lower = calc_bollinger(closes, 20, 2.0)

            current = candles[i]
            prev = candles[i - 1]

            # Volume
            volumes = [c.get('volume', 0) for c in candles[max(0, i-19):i+1]]
            avg_vol = sum(volumes) / len(volumes) if volumes else 0
            cur_vol = current.get('volume', 0)

            bars.append({
                'idx': i,
                'time': current['time'],
                'open': current['open'],
                'high': current['high'],
                'low': current['low'],
                'close': current['close'],
                'volume': cur_vol,
                'rsi': rsi,
                'atr': atr,
                'prev_lowest': prev_lowest,
                'dc_high': dc_high,
                'dc_low': dc_low,
                'dc_mid': dc_mid,
                'bb_mid': bb_mid,
                'bb_upper': bb_upper,
                'bb_lower': bb_lower,
                'prev_close': prev['close'],
                'vol_ok': cur_vol >= avg_vol * 0.5 if avg_vol > 0 else True,
            })

        result[pair] = bars

    logger.info(f"Pre-computed indicators voor {len(result)} coins")
    return result


def find_entries(indicator_data):
    """
    Find all DualConfirm entry signals. Returns list of entry dicts.
    Entry logic is IDENTICAL for all exit variants.
    """
    entries = []

    for pair, bars in indicator_data.items():
        cooldown_until = -999
        cooldown_after_stop_until = -999

        for b in bars:
            idx = b['idx']

            # Check cooldown
            if idx < cooldown_until or idx < cooldown_after_stop_until:
                continue

            # DualConfirm entry
            donchian_ok = (
                b['prev_lowest'] is not None and
                b['low'] <= b['prev_lowest'] and
                b['rsi'] < 35 and
                b['close'] > b['prev_close']
            )
            bb_ok = (
                b['bb_lower'] is not None and
                b['close'] <= b['bb_lower'] and
                b['rsi'] < 35 and
                b['close'] > b['prev_close']
            )
            vol_ok = b['vol_ok']

            if donchian_ok and bb_ok and vol_ok:
                atr = b['atr']
                stop = b['close'] - atr * 3.0
                max_stop = b['close'] * (1 - 15.0 / 100)
                if stop < max_stop:
                    stop = max_stop

                entries.append({
                    'pair': pair,
                    'bar_idx': idx,
                    'time': b['time'],
                    'entry_price': b['close'],
                    'atr': atr,
                    'rsi': b['rsi'],
                    'initial_stop': stop,
                })

                # We need to simulate where this trade exits to know cooldown.
                # For entry finding, use a simple "skip next 4 bars" heuristic.
                # The actual exit simulation will handle this properly.
                # Mark that we have an entry from this bar
                cooldown_until = idx + 4  # Minimum cooldown

    entries.sort(key=lambda x: x['time'])
    logger.info(f"Gevonden: {len(entries)} entry signalen")
    return entries


# ============================================================
# EXIT SIMULATION ENGINE
# ============================================================

def simulate_exits(indicator_data, entries, exit_config, max_positions, capital_per_trade):
    """
    Simulate a specific exit strategy on the pre-computed entries.
    Returns list of closed trades.

    exit_config dict keys:
      - target_mode: 'dc_mid', 'bb_mid', 'dc_upper', 'bb_upper', 'fixed_pct', 'none'
      - target_pct: float (for fixed_pct)
      - rsi_exit: float or None (None = no RSI exit)
      - trail_mode: 'atr', 'chandelier', 'parabolic', 'none'
      - trail_atr_mult: float
      - breakeven_trigger: float or None (move stop to entry after +X%)
      - max_bars: int or None
      - time_decay_bars: int or None
      - time_decay_atr: float
      - partial: bool (50% at mid target, rest to upper)
      - parabolic_start, parabolic_step, parabolic_max: floats
    """
    cfg = exit_config

    # Build bar lookup: pair -> {idx: bar_data}
    bar_lookup = {}
    bar_indices = {}
    for pair, bars in indicator_data.items():
        bar_lookup[pair] = {b['idx']: b for b in bars}
        bar_indices[pair] = [b['idx'] for b in bars]

    # Portfolio state
    positions = {}
    closed_trades = []
    cooldown = {}  # pair -> cooldown_until_idx
    cooldown_stop = {}  # pair -> cooldown_until_idx (after stop loss)

    # Process chronologically: first collect all events with timing
    # We need to iterate bar-by-bar across all coins simultaneously
    # Group bars by time
    all_times = set()
    for pair, bars in indicator_data.items():
        for b in bars:
            all_times.add((b['time'], b['idx'], pair))

    # Sort by time
    all_bar_events = sorted(all_times)

    # Entry lookup: pair -> list of entry bar_idx
    entry_lookup = {}
    for e in entries:
        pair = e['pair']
        if pair not in entry_lookup:
            entry_lookup[pair] = {}
        entry_lookup[pair][e['bar_idx']] = e

    for bar_time, bar_idx, pair in all_bar_events:
        if pair not in bar_lookup or bar_idx not in bar_lookup[pair]:
            continue

        b = bar_lookup[pair][bar_idx]

        # Check if we have an open position for this pair
        if pair in positions:
            pos = positions[pair]
            pnl_pct = (b['close'] - pos['entry_price']) / pos['entry_price'] * 100
            bars_in_trade = bar_idx - pos['entry_bar']

            # Track highest price
            if b['close'] > pos['highest_price']:
                pos['highest_price'] = b['close']
            if b['high'] > pos['highest_price']:
                pos['highest_price'] = b['high']

            exit_signal = None
            exit_type = None
            is_stop = False

            # --- HARD STOP (altijd) ---
            hard_stop = pos['entry_price'] * (1 - 15.0 / 100)
            if b['close'] < hard_stop:
                exit_signal = b['close']
                exit_type = 'HARD_STOP'
                is_stop = True

            if exit_signal is None:
                # --- PARTIAL EXIT LOGIC ---
                if cfg.get('partial', False) and not pos.get('partial_taken', False):
                    # Check mid target for partial
                    mid_hit = False
                    if b['dc_mid'] and b['close'] >= b['dc_mid']:
                        mid_hit = True
                    elif b['bb_mid'] and b['close'] >= b['bb_mid']:
                        mid_hit = True

                    if mid_hit:
                        pos['partial_taken'] = True
                        pos['partial_price'] = b['close']
                        pos['partial_pnl_pct'] = pnl_pct
                        # Move stop to entry (break-even)
                        pos['stop_price'] = max(pos['stop_price'], pos['entry_price'])
                        # Don't exit yet, continue to upper target

                elif not cfg.get('partial', False):
                    # --- TARGET EXITS ---
                    tm = cfg.get('target_mode', 'dc_mid')

                    if tm == 'dc_mid':
                        if b['dc_mid'] and b['close'] >= b['dc_mid']:
                            exit_signal = b['close']
                            exit_type = 'DC_MID'
                        elif b['bb_mid'] and b['close'] >= b['bb_mid']:
                            exit_signal = b['close']
                            exit_type = 'BB_MID'

                    elif tm == 'dc_upper':
                        if b['dc_high'] and b['close'] >= b['dc_high']:
                            exit_signal = b['close']
                            exit_type = 'DC_UPPER'

                    elif tm == 'bb_upper':
                        if b['bb_upper'] and b['close'] >= b['bb_upper']:
                            exit_signal = b['close']
                            exit_type = 'BB_UPPER'

                    elif tm == 'fixed_pct':
                        target_price = pos['entry_price'] * (1 + cfg.get('target_pct', 8.0) / 100)
                        if b['close'] >= target_price:
                            exit_signal = b['close']
                            exit_type = f"FIXED_{cfg.get('target_pct', 8.0)}%"

                    elif tm == 'upper':
                        # DC upper or BB upper
                        if b['dc_high'] and b['close'] >= b['dc_high']:
                            exit_signal = b['close']
                            exit_type = 'DC_UPPER'
                        elif b['bb_upper'] and b['close'] >= b['bb_upper']:
                            exit_signal = b['close']
                            exit_type = 'BB_UPPER'

                # Partial: after partial taken, look for upper target
                if cfg.get('partial', False) and pos.get('partial_taken', False):
                    if exit_signal is None:
                        if b['dc_high'] and b['close'] >= b['dc_high']:
                            exit_signal = b['close']
                            exit_type = 'PARTIAL_REST_UPPER'
                        elif b['bb_upper'] and b['close'] >= b['bb_upper']:
                            exit_signal = b['close']
                            exit_type = 'PARTIAL_REST_UPPER'

            # --- RSI EXIT ---
            if exit_signal is None:
                rsi_threshold = cfg.get('rsi_exit', 70)
                if rsi_threshold is not None and b['rsi'] > rsi_threshold:
                    exit_signal = b['close']
                    exit_type = f"RSI>{rsi_threshold}"

            # --- TIME EXIT ---
            if exit_signal is None:
                max_b = cfg.get('max_bars', None)
                if max_b is not None and bars_in_trade >= max_b:
                    exit_signal = b['close']
                    exit_type = f"TIME_{max_b}"

            # --- BREAK-EVEN STOP update ---
            if exit_signal is None:
                be_trigger = cfg.get('breakeven_trigger', None)
                if be_trigger is not None and pnl_pct >= be_trigger:
                    be_price = pos['entry_price'] * 1.001
                    if be_price > pos['stop_price']:
                        pos['stop_price'] = be_price

            # --- TRAILING STOP ---
            if exit_signal is None:
                trail_mode = cfg.get('trail_mode', 'atr')
                atr = b['atr']

                if trail_mode == 'atr':
                    # Time decay: tighter trail after X bars
                    td_bars = cfg.get('time_decay_bars', None)
                    if td_bars and bars_in_trade >= td_bars:
                        eff_mult = cfg.get('time_decay_atr', 2.0)
                    else:
                        eff_mult = cfg.get('trail_atr_mult', 3.0)

                    new_stop = pos['highest_price'] - atr * eff_mult
                    max_stop = pos['entry_price'] * (1 - 15.0 / 100)
                    if new_stop < max_stop:
                        new_stop = max_stop
                    if new_stop > pos['stop_price']:
                        pos['stop_price'] = new_stop

                elif trail_mode == 'chandelier':
                    ch_mult = cfg.get('trail_atr_mult', 3.0)
                    new_stop = pos['highest_price'] - atr * ch_mult
                    max_stop = pos['entry_price'] * (1 - 15.0 / 100)
                    if new_stop < max_stop:
                        new_stop = max_stop
                    if new_stop > pos['stop_price']:
                        pos['stop_price'] = new_stop

                elif trail_mode == 'parabolic':
                    if 'sar_af' not in pos:
                        pos['sar_af'] = cfg.get('parabolic_start', 0.02)
                        pos['sar_stop'] = pos['stop_price']

                    if b['close'] > pos.get('prev_highest', pos['entry_price']):
                        pos['sar_af'] = min(
                            pos['sar_af'] + cfg.get('parabolic_step', 0.02),
                            cfg.get('parabolic_max', 0.20)
                        )
                    pos['prev_highest'] = pos['highest_price']

                    new_sar = pos['sar_stop'] + pos['sar_af'] * (pos['highest_price'] - pos['sar_stop'])
                    max_stop = pos['entry_price'] * (1 - 15.0 / 100)
                    if new_sar < max_stop:
                        new_sar = max_stop
                    if new_sar > pos['sar_stop']:
                        pos['sar_stop'] = new_sar
                    pos['stop_price'] = pos['sar_stop']

                elif trail_mode == 'none':
                    pass  # No trailing, only hard stop and targets

                # Check stop hit
                if b['close'] < pos['stop_price']:
                    exit_signal = b['close']
                    exit_type = 'TRAIL_STOP'
                    is_stop = True

            # --- PROCESS EXIT ---
            if exit_signal is not None:
                volume = pos['volume']
                entry_price = pos['entry_price']
                partial_taken = pos.get('partial_taken', False)

                if partial_taken:
                    partial_price = pos.get('partial_price', exit_signal)
                    half_vol = volume / 2
                    # Part 1
                    g1 = (partial_price - entry_price) * half_vol
                    f1 = (entry_price * half_vol + partial_price * half_vol) * KRAKEN_FEE
                    # Part 2
                    g2 = (exit_signal - entry_price) * half_vol
                    f2 = (entry_price * half_vol + exit_signal * half_vol) * KRAKEN_FEE
                    net_pnl = (g1 - f1) + (g2 - f2)
                    avg_exit = (partial_price + exit_signal) / 2
                    final_pnl_pct = (avg_exit - entry_price) / entry_price * 100
                else:
                    gross = (exit_signal - entry_price) * volume
                    fees = (entry_price * volume + exit_signal * volume) * KRAKEN_FEE
                    net_pnl = gross - fees
                    final_pnl_pct = (exit_signal - entry_price) / entry_price * 100

                mfe_pct = (pos['highest_price'] - entry_price) / entry_price * 100

                closed_trades.append({
                    'pair': pair,
                    'pnl': net_pnl,
                    'pnl_pct': final_pnl_pct,
                    'exit_type': 'STOP' if is_stop else 'TARGET',
                    'exit_reason': exit_type,
                    'bars_held': bars_in_trade,
                    'mfe_pct': mfe_pct,
                    'capital': pos['capital'],
                    'partial': partial_taken,
                })

                del positions[pair]
                if is_stop:
                    cooldown_stop[pair] = bar_idx + 8
                else:
                    cooldown[pair] = bar_idx + 4

        else:
            # Check for entry
            if pair in entry_lookup and bar_idx in entry_lookup[pair]:
                e = entry_lookup[pair][bar_idx]

                # Cooldown check
                if pair in cooldown and bar_idx < cooldown[pair]:
                    continue
                if pair in cooldown_stop and bar_idx < cooldown_stop[pair]:
                    continue

                # Max positions check
                if len(positions) >= max_positions:
                    continue

                volume = capital_per_trade / e['entry_price']
                positions[pair] = {
                    'entry_price': e['entry_price'],
                    'volume': volume,
                    'entry_bar': bar_idx,
                    'entry_time': e['time'],
                    'highest_price': e['entry_price'],
                    'stop_price': e['initial_stop'],
                    'atr': e['atr'],
                    'capital': capital_per_trade,
                }

    return closed_trades


# ============================================================
# METRICS & DISPLAY
# ============================================================

def calc_metrics(trades, capital_per_trade, max_positions):
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
    avg_bars = sum(t['bars_held'] for t in trades) / total
    avg_mfe = sum(t.get('mfe_pct', 0) for t in trades) / total

    stop_trades = [t for t in trades if t['exit_type'] == 'STOP']
    target_trades = [t for t in trades if t['exit_type'] == 'TARGET']
    stop_pnl = sum(t['pnl'] for t in stop_trades)
    target_pnl = sum(t['pnl'] for t in target_trades)

    total_bars = sum(t['bars_held'] for t in trades)
    ppb = total_pnl / total_bars if total_bars > 0 else 0

    return {
        'trades': total, 'wins': len(wins), 'losses': len(losses),
        'wr': wr, 'pnl': total_pnl, 'roi': roi, 'pf': pf,
        'avg_pnl': avg_pnl, 'avg_win': avg_win, 'avg_loss': avg_loss,
        'avg_bars': avg_bars, 'avg_mfe': avg_mfe,
        'stop_count': len(stop_trades), 'stop_pnl': stop_pnl,
        'target_count': len(target_trades), 'target_pnl': target_pnl,
        'ppb': ppb,
    }


def print_row(name, m, baseline_pnl=None):
    if m is None:
        print(f"  {name:<45} | Geen trades")
        return
    diff = ""
    if baseline_pnl is not None:
        d = m['pnl'] - baseline_pnl
        diff = f" ({'+' if d >= 0 else ''}{d:.0f})"
    print(f"  {name:<45} | {m['trades']:>3} tr | WR {m['wr']:>5.1f}% | "
          f"P&L ${m['pnl']:>+8.0f}{diff:<8} | PF {m['pf']:>5.2f} | "
          f"Avg ${m['avg_pnl']:>+6.0f} | Bars {m['avg_bars']:>4.1f} | "
          f"$/bar {m['ppb']:>+5.1f}")


# ============================================================
# MAIN
# ============================================================

def main():
    t0 = time.time()

    print(f"\n{'='*130}")
    print(f"  EXIT STRATEGIE OPTIMALISATIE - 60 DAGEN BACKTEST")
    print(f"  Entry: DualConfirm + Volume filter + Smart cooldown | 0.26% fee")
    print(f"{'='*130}\n")

    cache = load_cache()

    # STAP 1: Pre-compute indicators (EENMALIG)
    logger.info("Pre-computing indicators...")
    indicator_data = precompute_indicators(cache)

    # STAP 2: Find entries (EENMALIG)
    logger.info("Finding entry signals...")
    entries = find_entries(indicator_data)

    # STAP 3: Define exit variants
    variants = []

    # 0. BASELINE
    variants.append(("BASELINE (DC/BB mid + RSI>70 + ATR3.0)",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0}))

    # --- A) PROFIT TARGETS ---
    for pct in [5, 8, 10, 15]:
        variants.append((f"A) Fixed target +{pct}%",
                         {'target_mode': 'fixed_pct', 'target_pct': pct, 'rsi_exit': 70,
                          'trail_mode': 'atr', 'trail_atr_mult': 3.0}))

    variants.append(("A) DC upper target",
                     {'target_mode': 'dc_upper', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0}))

    variants.append(("A) BB upper target",
                     {'target_mode': 'bb_upper', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0}))

    # --- B) PARTIAL EXITS ---
    variants.append(("B) Partial 50% bij mid, rest trail",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0,
                      'partial': True}))

    # --- C) TRAILING STOP VARIANTEN ---
    variants.append(("C) Chandelier Exit (ATR 3.0x)",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'chandelier', 'trail_atr_mult': 3.0}))

    variants.append(("C) Chandelier Exit (ATR 4.0x)",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'chandelier', 'trail_atr_mult': 4.0}))

    variants.append(("C) Parabolic trail (0.02/0.02/0.20)",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'parabolic',
                      'parabolic_start': 0.02, 'parabolic_step': 0.02, 'parabolic_max': 0.20}))

    variants.append(("C) Parabolic trail slow (0.01/0.01/0.10)",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'parabolic',
                      'parabolic_start': 0.01, 'parabolic_step': 0.01, 'parabolic_max': 0.10}))

    variants.append(("C) Break-even stop (+3% trigger)",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0,
                      'breakeven_trigger': 3.0}))

    variants.append(("C) Break-even stop (+5% trigger)",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0,
                      'breakeven_trigger': 5.0}))

    variants.append(("C) No trailing stop (targets only)",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'none'}))

    # --- D) RSI EXIT TUNING ---
    for rsi_val in [60, 65, 75, 80]:
        variants.append((f"D) RSI exit > {rsi_val}",
                         {'target_mode': 'dc_mid', 'rsi_exit': rsi_val, 'trail_mode': 'atr', 'trail_atr_mult': 3.0}))

    variants.append(("D) GEEN RSI exit",
                     {'target_mode': 'dc_mid', 'rsi_exit': None, 'trail_mode': 'atr', 'trail_atr_mult': 3.0}))

    # --- E) TIME-BASED EXITS ---
    for bars in [12, 16, 20, 24, 30]:
        variants.append((f"E) Time max {bars} bars",
                         {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0,
                          'max_bars': bars}))

    variants.append(("E) Time decay: 15 bars -> ATR 2.0x",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0,
                      'time_decay_bars': 15, 'time_decay_atr': 2.0}))

    variants.append(("E) Time decay: 12 bars -> ATR 1.5x",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0,
                      'time_decay_bars': 12, 'time_decay_atr': 1.5}))

    # --- F) COMBINATIES ---
    variants.append(("F) BE(+3%) + DC upper target",
                     {'target_mode': 'upper', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0,
                      'breakeven_trigger': 3.0}))

    variants.append(("F) BE(+5%) + DC upper target",
                     {'target_mode': 'upper', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0,
                      'breakeven_trigger': 5.0}))

    variants.append(("F) BE(+3%) + upper + RSI>80",
                     {'target_mode': 'upper', 'rsi_exit': 80, 'trail_mode': 'atr', 'trail_atr_mult': 3.0,
                      'breakeven_trigger': 3.0}))

    variants.append(("F) BE(+3%) + upper + no RSI",
                     {'target_mode': 'upper', 'rsi_exit': None, 'trail_mode': 'atr', 'trail_atr_mult': 3.0,
                      'breakeven_trigger': 3.0}))

    variants.append(("F) Partial mid + BE + upper",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0,
                      'partial': True, 'breakeven_trigger': 3.0}))

    variants.append(("F) BE(+3%) + upper + ATR 4.0x",
                     {'target_mode': 'upper', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 4.0,
                      'breakeven_trigger': 3.0}))

    variants.append(("F) BE(+3%) + DC mid + time 24bar",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0,
                      'breakeven_trigger': 3.0, 'max_bars': 24}))

    variants.append(("F) No RSI + DC mid + ATR 4.0x",
                     {'target_mode': 'dc_mid', 'rsi_exit': None, 'trail_mode': 'atr', 'trail_atr_mult': 4.0}))

    variants.append(("F) BE(+3%) + mid + time decay 15->2x",
                     {'target_mode': 'dc_mid', 'rsi_exit': 70, 'trail_mode': 'atr', 'trail_atr_mult': 3.0,
                      'breakeven_trigger': 3.0, 'time_decay_bars': 15, 'time_decay_atr': 2.0}))

    # ============================================================
    # RUN
    # ============================================================
    configs = [
        ('2x$1000', 2, 1000),
        ('3x$700', 3, 700),
    ]

    all_results = {}
    total_variants = len(variants)

    for config_name, max_pos, capital in configs:
        print(f"\n  {'='*128}")
        print(f"  CONFIG: {config_name} (max {max_pos} posities, ${capital}/trade)")
        print(f"  {'='*128}")
        print(f"  {'VARIANT':<45} | {'#':>3} TR | {'WR':>7} | "
              f"{'P&L':>20} | {'PF':>6} | {'AVG':>7} | {'BARS':>5} | {'$/BAR':>6}")
        print(f"  {'-'*128}")

        config_results = []
        baseline_pnl = None

        for vi, (name, ecfg) in enumerate(variants):
            trades = simulate_exits(indicator_data, entries, ecfg, max_pos, capital)
            m = calc_metrics(trades, capital, max_pos)

            if m:
                if baseline_pnl is None:
                    baseline_pnl = m['pnl']
                print_row(name, m, baseline_pnl)
                m['name'] = name
                config_results.append(m)
            else:
                print(f"  {name:<45} | Geen trades")

        all_results[config_name] = config_results

    # ============================================================
    # CATEGORIE ANALYSE
    # ============================================================
    print(f"\n\n{'='*130}")
    print(f"  CATEGORIE ANALYSE")
    print(f"{'='*130}")

    categories = {
        'A) Profit Targets': lambda n: n.startswith('A)'),
        'B) Partial Exits': lambda n: n.startswith('B)'),
        'C) Trailing Stops': lambda n: n.startswith('C)'),
        'D) RSI Exit Tuning': lambda n: n.startswith('D)'),
        'E) Time-Based': lambda n: n.startswith('E)'),
        'F) Combinaties': lambda n: n.startswith('F)'),
    }

    for config_name, _, _ in configs:
        results = all_results.get(config_name, [])
        if not results:
            continue

        baseline = results[0]
        print(f"\n  --- {config_name} ---")
        print(f"  Baseline: P&L ${baseline['pnl']:>+.0f} | PF {baseline['pf']:.2f} | "
              f"WR {baseline['wr']:.1f}% | {baseline['trades']} trades | $/bar {baseline['ppb']:+.1f}")

        for cat_name, cat_filter in categories.items():
            cat_results = [r for r in results if cat_filter(r['name'])]
            if not cat_results:
                continue
            best = max(cat_results, key=lambda x: x['pnl'])
            diff = best['pnl'] - baseline['pnl']
            marker = "BETER" if diff > 0 else "SLECHTER" if diff < 0 else "GELIJK"
            print(f"  {cat_name:<25} | Beste: {best['name']:<40} | "
                  f"P&L ${best['pnl']:>+.0f} ({'+' if diff >= 0 else ''}{diff:.0f}) [{marker}]")

    # ============================================================
    # TOP 10 RANKING
    # ============================================================
    print(f"\n\n{'='*130}")
    print(f"  TOP 10 EXIT STRATEGIEEN (OP P&L)")
    print(f"{'='*130}")

    for config_name, _, _ in configs:
        results = all_results.get(config_name, [])
        if not results:
            continue

        baseline = results[0]
        ranked = sorted(results, key=lambda x: x['pnl'], reverse=True)

        print(f"\n  --- {config_name} ---")
        print(f"  {'#':<4} {'VARIANT':<45} | {'P&L':>8} | {'DIFF':>8} | "
              f"{'PF':>6} | {'WR':>6} | {'#TR':>4} | {'BARS':>5} | {'$/BAR':>6} | {'STOPS':>10}")
        print(f"  {'-'*128}")

        for i, r in enumerate(ranked[:10]):
            diff = r['pnl'] - baseline['pnl']
            star = " ***" if i == 0 else ""
            print(f"  {i+1:<4} {r['name']:<45} | ${r['pnl']:>+7.0f} | "
                  f"${diff:>+7.0f} | {r['pf']:>5.2f} | {r['wr']:>5.1f}% | "
                  f"{r['trades']:>4} | {r['avg_bars']:>4.1f} | ${r['ppb']:>+5.1f} | "
                  f"{r['stop_count']:>3} (${r['stop_pnl']:>+.0f}){star}")

    # ============================================================
    # COMPOSITE SCORE
    # ============================================================
    print(f"\n\n{'='*130}")
    print(f"  COMPOSITE SCORE (P&L 40% + PF 25% + WR 15% + $/bar 20%)")
    print(f"{'='*130}")

    for config_name, _, _ in configs:
        results = all_results.get(config_name, [])
        if not results:
            continue

        vals = {
            'pnl': [r['pnl'] for r in results],
            'pf': [min(r['pf'], 10) for r in results],  # Cap PF at 10
            'wr': [r['wr'] for r in results],
            'ppb': [r['ppb'] for r in results],
        }

        def norm(v):
            mn, mx = min(v), max(v)
            rng = mx - mn
            return [(x - mn) / rng if rng > 0 else 0.5 for x in v]

        n = {k: norm(v) for k, v in vals.items()}

        for i, r in enumerate(results):
            r['composite'] = n['pnl'][i]*0.40 + n['pf'][i]*0.25 + n['wr'][i]*0.15 + n['ppb'][i]*0.20

        ranked = sorted(results, key=lambda x: x['composite'], reverse=True)
        baseline = results[0]

        print(f"\n  --- {config_name} ---")
        print(f"  {'#':<4} {'VARIANT':<45} | {'SCORE':>6} | {'P&L':>8} | "
              f"{'PF':>6} | {'WR':>6} | {'$/BAR':>6}")
        print(f"  {'-'*110}")

        for i, r in enumerate(ranked[:10]):
            diff = r['pnl'] - baseline['pnl']
            star = " <-- BEST" if i == 0 else ""
            print(f"  {i+1:<4} {r['name']:<45} | {r['composite']:>5.3f} | ${r['pnl']:>+7.0f} | "
                  f"{r['pf']:>5.2f} | {r['wr']:>5.1f}% | ${r['ppb']:>+5.1f}{star}")

    # ============================================================
    # CONCLUSIE
    # ============================================================
    print(f"\n\n{'='*130}")
    print(f"  CONCLUSIE & AANBEVELINGEN")
    print(f"{'='*130}")

    for config_name, _, _ in configs:
        results = all_results.get(config_name, [])
        if not results:
            continue

        baseline = results[0]
        ranked_pnl = sorted(results, key=lambda x: x['pnl'], reverse=True)
        ranked_comp = sorted(results, key=lambda x: x.get('composite', 0), reverse=True)

        print(f"\n  {config_name}:")
        print(f"  {'─'*100}")
        print(f"  Baseline: P&L ${baseline['pnl']:>+.0f} | PF {baseline['pf']:.2f} | "
              f"WR {baseline['wr']:.1f}% | {baseline['trades']} trades")

        print(f"\n  TOP 3 op P&L:")
        for i, r in enumerate(ranked_pnl[:3]):
            diff = r['pnl'] - baseline['pnl']
            print(f"    {i+1}. {r['name']:<45} | P&L ${r['pnl']:>+.0f} ({'+' if diff >= 0 else ''}{diff:.0f}) | "
                  f"PF {r['pf']:.2f} | WR {r['wr']:.1f}% | {r['trades']} trades")

        print(f"\n  TOP 3 op Composite:")
        for i, r in enumerate(ranked_comp[:3]):
            diff = r['pnl'] - baseline['pnl']
            print(f"    {i+1}. {r['name']:<45} | Score {r['composite']:.3f} | P&L ${r['pnl']:>+.0f} ({'+' if diff >= 0 else ''}{diff:.0f}) | "
                  f"PF {r['pf']:.2f}")

    elapsed = time.time() - t0
    print(f"\n  Runtime: {elapsed:.1f}s")
    print(f"{'='*130}\n")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Paper Trade — MEXC 4H Vol Capitulation (Sprint 4 Config 041 + Wrappers)
========================================================================
Live paper trading for the MEXC deploy config (ADR-4H-014, 7/7 gates).

Signal: Vol Capitulation (H4S4-G05)
  - vol_mult=3.5, rsi_max=35
  - DC geometry gate (close<dc_mid AND close<bb_mid AND rsi<threshold)
  - 3.5x volume spike + low within 1 ATR of dc_prev_low

Exits: hybrid_notrl (FIXED STOP → TIME MAX → RSI RECOVERY → DC TARGET → BB TARGET)
  - max_stop_pct=15, time_max_bars=15, rsi_rec_target=45, rsi_rec_min_bars=5

Wrappers (real-time):
  - dd_throttle: >5% DD → scale P&L by 0.22x (skip new entries)
  - adaptive_maxpos: normal=3, warning=2, critical=1

Fee: MEXC SPOT 10bps per side (conservative).
Sizing: Fixed $2,000/trade.

Usage:
    python paper_mexc_4h.py                  # Live only (infinite)
    python paper_mexc_4h.py --hours 168      # Live for 7 days
    python paper_mexc_4h.py --report         # Show report
    python paper_mexc_4h.py --dry-run        # One check cycle then exit
"""
import os
import sys
import json
import time
import logging
import argparse
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict
from pathlib import Path
from dataclasses import dataclass

# ─── Path setup ─────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
REPO_ROOT = BASE_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / '.env')

# ─── Imports from screening infra (indicators, signal, exits) ───
# Note: strategies/4h/ has a dot in the path — must use importlib
import importlib
from strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger

_exits_mod = importlib.import_module('strategies.4h.sprint3.exits')
evaluate_exit_hybrid_notrl = _exits_mod.evaluate_exit_hybrid_notrl
ExitSignal = _exits_mod.ExitSignal

_hyps_mod = importlib.import_module('strategies.4h.sprint4.hypotheses')
signal_vol_capitulation = _hyps_mod.signal_vol_capitulation
_check_dc_geometry = _hyps_mod._check_dc_geometry

# ─── Constants ──────────────────────────────────────────────
TAG = 'mexc_4h_paper'
STATE_FILE = BASE_DIR / f'paper_state_{TAG}.json'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# Deploy config (ADR-4H-014, frozen)
MEXC_FEE = 0.0010          # 10bps per side (conservative)
CAPITAL_PER_TRADE = 2000.0
INITIAL_EQUITY = 10000.0    # Paper equity pool

# Entry params
ENTRY_PARAMS = {
    'vol_mult': 3.5,
    'rsi_max': 35,
    'require_dc_low_zone': True,
    'require_bb_lower': False,
    'require_green': False,
    'max_stop_pct': 15.0,
    'time_max_bars': 15,
}

# Exit params
EXIT_PARAMS = {
    'max_stop_pct': 15.0,
    'time_max_bars': 15,
    'rsi_recovery': True,
    'rsi_rec_target': 45.0,
    'rsi_rec_min_bars': 5,
}

# Wrapper params
DD_THROTTLE_THRESHOLD = 0.05   # 5%
DD_THROTTLE_SCALE = 0.22
ADAPTIVE_MAXPOS = {'normal': 3, 'warning': 2, 'critical': 1}

# Indicator params (matching backtest)
RSI_PERIOD = 14
ATR_PERIOD = 14
DC_PERIOD = 20
BB_PERIOD = 20
BB_DEV = 2.0
VOL_AVG_PERIOD = 20

# Cooldown
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8

# Minimum candles needed for indicator warmup
MIN_CANDLES = 60


# ─── Logging ────────────────────────────────────────────────

def setup_logging():
    log_file = LOG_DIR / f"paper_{TAG}_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ]
    )
    return logging.getLogger('paper_mexc_4h')


# ─── State Management ──────────────────────────────────────

def new_state() -> dict:
    return {
        'positions': {},
        'equity': INITIAL_EQUITY,
        'peak_equity': INITIAL_EQUITY,
        'start_time': datetime.now(timezone.utc).isoformat(),
        'total_trades': 0,
        'closed_trades': 0,
        'total_pnl': 0.0,
        'wins': 0,
        'losses': 0,
        'gross_wins': 0.0,
        'gross_losses': 0.0,
        'biggest_win': 0.0,
        'biggest_loss': 0.0,
        'checks': 0,
        'dd_current': 0.0,
        'dd_max': 0.0,
        'trades_skipped_dd': 0,
        'exit_class_a': {},
        'exit_class_b': {},
        'trade_log': [],
        # Cooldown tracking
        'last_exit_bar': {},       # pair → bar_index
        'last_exit_was_stop': {},  # pair → bool
        # Monitoring
        'rolling_pf': 0.0,
        'rolling_wr': 0.0,
        'rolling_a_share': 0.0,
        'consecutive_losses': 0,
        'max_consecutive_losses': 0,
        'alerts': [],
    }


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return new_state()


def save_state(state: dict):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)


# ─── Indicator Computation (live context) ───────────────────

def compute_indicators_for_coin(candles: list) -> Optional[dict]:
    """Compute all indicators needed for signal + exit evaluation.

    Uses the same functions as the backtest (strategy.py), producing
    arrays indexed by bar number.

    Returns None if insufficient data.
    """
    n = len(candles)
    if n < MIN_CANDLES:
        return None

    closes = [c['close'] for c in candles]
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]
    volumes = [c.get('volume', 0) for c in candles]

    # RSI (full array)
    rsi_arr = [None] * n
    for i in range(RSI_PERIOD + 1, n):
        rsi_arr[i] = calc_rsi(closes[:i + 1], RSI_PERIOD)

    # ATR (full array)
    atr_arr = [None] * n
    for i in range(ATR_PERIOD + 1, n):
        atr_arr[i] = calc_atr(
            highs[:i + 1], lows[:i + 1], closes[:i + 1], ATR_PERIOD
        )

    # Donchian Channel — calc_donchian returns (high, low, mid) tuple
    dc_high_arr = [None] * n
    dc_low_arr = [None] * n
    dc_mid_arr = [None] * n
    dc_prev_low_arr = [None] * n
    for i in range(DC_PERIOD, n):
        dc_h, dc_l, dc_m = calc_donchian(highs[:i + 1], lows[:i + 1], DC_PERIOD)
        dc_high_arr[i] = dc_h
        dc_low_arr[i] = dc_l
        dc_mid_arr[i] = dc_m
        # Causal previous-bar low (for entry zone check)
        if i >= DC_PERIOD + 1:
            _, dc_prev_l, _ = calc_donchian(highs[:i], lows[:i], DC_PERIOD)
            dc_prev_low_arr[i] = dc_prev_l

    # Bollinger Bands — calc_bollinger returns (mid, upper, lower) tuple
    bb_upper_arr = [None] * n
    bb_mid_arr = [None] * n
    bb_lower_arr = [None] * n
    for i in range(BB_PERIOD, n):
        bb_m, bb_u, bb_l = calc_bollinger(closes[:i + 1], BB_PERIOD, BB_DEV)
        bb_upper_arr[i] = bb_u
        bb_mid_arr[i] = bb_m
        bb_lower_arr[i] = bb_l

    # Volume average
    vol_avg_arr = [None] * n
    for i in range(VOL_AVG_PERIOD, n):
        vol_avg_arr[i] = sum(volumes[i - VOL_AVG_PERIOD:i]) / VOL_AVG_PERIOD

    return {
        'closes': closes,
        'highs': highs,
        'lows': lows,
        'volumes': volumes,
        'rsi': rsi_arr,
        'atr': atr_arr,
        'dc_high': dc_high_arr,
        'dc_low': dc_low_arr,
        'dc_mid': dc_mid_arr,
        'dc_prev_low': dc_prev_low_arr,
        'bb_upper': bb_upper_arr,
        'bb_mid': bb_mid_arr,
        'bb_lower': bb_lower_arr,
        'vol_avg': vol_avg_arr,
        'n': n,
    }


# ─── Wrapper Logic (real-time) ──────────────────────────────

def get_current_dd(state: dict) -> float:
    """Current drawdown as fraction (0.0 = no DD, 1.0 = -100%)."""
    equity = state['equity']
    peak = state['peak_equity']
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - equity) / peak)


def get_adaptive_maxpos(dd: float) -> int:
    """Adaptive max positions based on current DD."""
    if dd >= 0.10:   # ≥10% DD → critical
        return ADAPTIVE_MAXPOS['critical']
    elif dd >= DD_THROTTLE_THRESHOLD:  # ≥5% DD → warning
        return ADAPTIVE_MAXPOS['warning']
    else:
        return ADAPTIVE_MAXPOS['normal']


def should_throttle(state: dict) -> bool:
    """Check if dd_throttle should block new entries."""
    dd = get_current_dd(state)
    return dd >= DD_THROTTLE_THRESHOLD


# ─── Core Paper Trading Engine ──────────────────────────────

def process_check(
    mexc_client,
    coins: List[str],
    state: dict,
    logger,
    check_time: datetime,
) -> dict:
    """Process one 4H candle check across all coins.

    Phase 1: Process exits for open positions.
    Phase 2: Process entries (new signals).

    Returns updated state.
    """
    check_str = check_time.strftime('%Y-%m-%d %H:%M UTC')
    check_ts = int(check_time.timestamp())
    state['checks'] += 1

    dd = get_current_dd(state)
    max_pos = get_adaptive_maxpos(dd)
    throttled = should_throttle(state)

    n_open = len(state['positions'])
    logger.info(f"\n{'='*60}")
    logger.info(f"CHECK #{state['checks']} — {check_str}")
    logger.info(f"Equity: ${state['equity']:.2f} | DD: {dd*100:.1f}% | "
                f"Open: {n_open}/{max_pos} | Throttle: {'ON' if throttled else 'OFF'}")
    logger.info(f"{'='*60}")

    # ─── Phase 1: Process exits ─────────────────────────────
    pairs_to_close = []
    for pair, pos_data in list(state['positions'].items()):
        candles = mexc_client.get_ohlc(pair, interval=240)
        if not candles or len(candles) < MIN_CANDLES:
            logger.warning(f"  Skip exit check {pair}: insufficient candles")
            continue

        indicators = compute_indicators_for_coin(candles)
        if indicators is None:
            continue

        bar = indicators['n'] - 1  # Last completed bar
        entry_bar = pos_data['entry_bar']
        bars_in = bar - entry_bar if entry_bar >= 0 else pos_data.get('bars_held', 0) + 1

        # Use global bar counter for time tracking
        pos_data['bars_held'] = pos_data.get('bars_held', 0) + 1
        actual_bars = pos_data['bars_held']

        low = indicators['lows'][bar]
        high = indicators['highs'][bar]
        close = indicators['closes'][bar]
        rsi_val = indicators['rsi'][bar]
        dc_mid_val = indicators['dc_mid'][bar]
        bb_mid_val = indicators['bb_mid'][bar]

        # Evaluate exit using sprint3 engine
        exit_sig = evaluate_exit_hybrid_notrl(
            entry_price=pos_data['entry_price'],
            entry_bar=0,       # Normalize: use 0 as base
            bar=actual_bars,   # bars_held = effective bars_in
            low=low,
            high=high,
            close=close,
            rsi=rsi_val,
            dc_mid=dc_mid_val,
            bb_mid=bb_mid_val,
            max_stop_pct=EXIT_PARAMS['max_stop_pct'],
            time_max_bars=EXIT_PARAMS['time_max_bars'],
            rsi_recovery=EXIT_PARAMS['rsi_recovery'],
            rsi_rec_target=EXIT_PARAMS['rsi_rec_target'],
            rsi_rec_min_bars=EXIT_PARAMS['rsi_rec_min_bars'],
        )

        if exit_sig is not None:
            # Calculate P&L
            entry_price = pos_data['entry_price']
            size_usd = pos_data['size_usd']
            gross = size_usd * (exit_sig.price / entry_price - 1.0)
            fees = size_usd * MEXC_FEE + (size_usd + gross) * MEXC_FEE
            net_pnl = gross - fees

            # Apply dd_throttle scaling to P&L if in throttled state
            # (In backtest this scales position size; here we scale P&L equivalently)
            if throttled and net_pnl > 0:
                net_pnl *= DD_THROTTLE_SCALE

            # Update state
            state['equity'] += net_pnl
            state['total_pnl'] += net_pnl
            state['closed_trades'] += 1

            if net_pnl >= 0:
                state['wins'] += 1
                state['gross_wins'] += net_pnl
                state['biggest_win'] = max(state['biggest_win'], net_pnl)
                state['consecutive_losses'] = 0
            else:
                state['losses'] += 1
                state['gross_losses'] += net_pnl
                state['biggest_loss'] = min(state['biggest_loss'], net_pnl)
                state['consecutive_losses'] += 1
                state['max_consecutive_losses'] = max(
                    state['max_consecutive_losses'],
                    state['consecutive_losses']
                )

            # Update peak equity and DD
            if state['equity'] > state['peak_equity']:
                state['peak_equity'] = state['equity']
            new_dd = get_current_dd(state)
            state['dd_current'] = new_dd
            state['dd_max'] = max(state['dd_max'], new_dd)

            # Exit class tracking
            cls = 'A' if exit_sig.class_ == 'A' else 'B'
            cls_dict = state[f'exit_class_{cls.lower()}']
            reason = exit_sig.reason
            if reason not in cls_dict:
                cls_dict[reason] = {'count': 0, 'pnl': 0.0, 'wins': 0}
            cls_dict[reason]['count'] += 1
            cls_dict[reason]['pnl'] += net_pnl
            if net_pnl > 0:
                cls_dict[reason]['wins'] += 1

            # Cooldown
            state['last_exit_bar'][pair] = state['checks']
            state['last_exit_was_stop'][pair] = reason in ('FIXED STOP', 'HARD STOP')

            # Trade log entry
            trade_record = {
                'nr': state['closed_trades'],
                'pair': pair,
                'entry_price': entry_price,
                'exit_price': exit_sig.price,
                'size_usd': size_usd,
                'pnl': round(net_pnl, 2),
                'pnl_pct': round(net_pnl / size_usd * 100, 2),
                'exit_reason': reason,
                'exit_class': cls,
                'bars_held': actual_bars,
                'entry_time': pos_data.get('entry_time', ''),
                'exit_time': check_str,
                'rsi_at_entry': pos_data.get('rsi_at_entry', 0),
                'rsi_at_exit': rsi_val,
                'throttled': throttled,
                'equity_after': round(state['equity'], 2),
            }
            state['trade_log'].append(trade_record)

            pnl_pct = net_pnl / size_usd * 100
            logger.info(
                f"  {'🟢' if net_pnl >= 0 else '🔴'} EXIT {pair} [{reason}] "
                f"${exit_sig.price:.6f} | P&L=${net_pnl:+.2f} ({pnl_pct:+.1f}%) "
                f"| {actual_bars} bars | Eq=${state['equity']:.2f}"
            )

            pairs_to_close.append(pair)
            time.sleep(0.25)  # Rate limit

    # Remove closed positions
    for pair in pairs_to_close:
        del state['positions'][pair]

    # ─── Phase 2: Process entries ────────────────────────────
    dd = get_current_dd(state)
    max_pos = get_adaptive_maxpos(dd)
    throttled = should_throttle(state)
    n_open = len(state['positions'])

    if n_open < max_pos and not throttled:
        candidates = []

        for pair in coins:
            if pair in state['positions']:
                continue

            # Cooldown check
            last_exit = state['last_exit_bar'].get(pair, -999)
            was_stop = state['last_exit_was_stop'].get(pair, False)
            cd = COOLDOWN_AFTER_STOP if was_stop else COOLDOWN_BARS
            if (state['checks'] - last_exit) < cd:
                continue

            try:
                candles = mexc_client.get_ohlc(pair, interval=240)
                if not candles or len(candles) < MIN_CANDLES:
                    continue

                indicators = compute_indicators_for_coin(candles)
                if indicators is None:
                    continue

                bar = indicators['n'] - 1  # Last completed bar

                # Run signal function
                sig = signal_vol_capitulation(candles, bar, indicators, ENTRY_PARAMS)
                if sig is not None:
                    candidates.append((pair, sig['strength'], sig, indicators, candles))

            except Exception as e:
                logger.debug(f"  Signal error {pair}: {e}")

            time.sleep(0.25)  # Rate limit

        # Rank by strength, fill available slots
        candidates.sort(key=lambda x: x[1], reverse=True)
        slots = max_pos - n_open

        for pair, strength, sig, indicators, candles in candidates[:slots]:
            bar = indicators['n'] - 1
            close = indicators['closes'][bar]
            rsi_val = indicators['rsi'][bar]

            size_usd = min(CAPITAL_PER_TRADE, state['equity'] * 0.95)  # Safety margin
            if size_usd < 100:
                logger.warning(f"  Skip entry {pair}: insufficient equity (${state['equity']:.2f})")
                break

            state['total_trades'] += 1
            state['positions'][pair] = {
                'pair': pair,
                'entry_price': close,
                'size_usd': size_usd,
                'entry_bar': bar,
                'entry_time': check_str,
                'bars_held': 0,
                'rsi_at_entry': rsi_val,
                'strength': strength,
                'trade_nr': state['total_trades'],
            }

            logger.info(
                f"  🟢 ENTRY {pair} @ ${close:.6f} | RSI={rsi_val:.1f} "
                f"| Str={strength:.2f} | ${size_usd:.0f}"
            )

    elif throttled and n_open < max_pos:
        state['trades_skipped_dd'] += 1
        logger.info(f"  ⏸️  DD throttle active ({dd*100:.1f}%) — skipping entries")

    # Update rolling metrics
    _update_rolling_metrics(state)

    return state


def _update_rolling_metrics(state: dict):
    """Update rolling PF, WR, and check alert conditions."""
    closed = state['closed_trades']
    if closed == 0:
        return

    wins = state['wins']
    state['rolling_wr'] = wins / closed * 100

    gw = state['gross_wins']
    gl = abs(state['gross_losses'])
    state['rolling_pf'] = gw / gl if gl > 0 else 99.0

    # ─── Alert checks ────────────────────────────────────────
    alerts = []

    # Rollback criterion 1: PF drops below 1.0 after 30+ trades
    if closed >= 30 and state['rolling_pf'] < 1.0:
        alerts.append({
            'type': 'ROLLBACK_PF',
            'severity': 'CRITICAL',
            'msg': f"PF={state['rolling_pf']:.2f} < 1.0 after {closed} trades",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # Rollback criterion 2: DD exceeds 25%
    dd_max = state.get('dd_max', 0)
    if dd_max >= 0.25:
        alerts.append({
            'type': 'ROLLBACK_DD',
            'severity': 'CRITICAL',
            'msg': f"Max DD={dd_max*100:.1f}% exceeds 25% threshold",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # Rollback criterion 3: 8+ consecutive losses (ADR-4H-015 R3)
    if state['consecutive_losses'] >= 8:
        alerts.append({
            'type': 'ROLLBACK_CONSEC',
            'severity': 'CRITICAL',
            'msg': f"{state['consecutive_losses']} consecutive losses (≥8 = rollback)",
            'time': datetime.now(timezone.utc).isoformat(),
        })
    # Warning: 5 consecutive losses (early warning)
    elif state['consecutive_losses'] >= 5:
        alerts.append({
            'type': 'CONSECUTIVE_LOSSES',
            'severity': 'WARNING',
            'msg': f"{state['consecutive_losses']} consecutive losses",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # Rollback criterion 4: Class A share < 30% after 20+ trades (ADR-4H-015 R4)
    if closed >= 20:
        # Compute Class A profit share using positive profit attribution
        a_profit = sum(
            max(0, d['pnl']) for d in state.get('exit_class_a', {}).values()
        )
        total_profit = a_profit + sum(
            max(0, d['pnl']) for d in state.get('exit_class_b', {}).values()
        )
        a_share = (a_profit / total_profit * 100) if total_profit > 0 else 0.0
        state['rolling_a_share'] = round(a_share, 1)

        if a_share < 30.0:
            alerts.append({
                'type': 'ROLLBACK_A_SHARE',
                'severity': 'CRITICAL',
                'msg': f"Class A share={a_share:.1f}% < 30% after {closed} trades",
                'time': datetime.now(timezone.utc).isoformat(),
            })

    # Warning: WR drops below 40% after 20+ trades
    if closed >= 20 and state['rolling_wr'] < 40.0:
        alerts.append({
            'type': 'LOW_WINRATE',
            'severity': 'WARNING',
            'msg': f"WR={state['rolling_wr']:.1f}% < 40% after {closed} trades",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # Warning: single trade loss > 5% of peak equity
    if state['trade_log']:
        last_trade = state['trade_log'][-1]
        if last_trade['pnl'] < -(state['peak_equity'] * 0.05):
            alerts.append({
                'type': 'LARGE_LOSS',
                'severity': 'WARNING',
                'msg': f"Trade {last_trade['pair']} lost ${abs(last_trade['pnl']):.2f} "
                       f"(>{5}% of peak equity)",
                'time': datetime.now(timezone.utc).isoformat(),
            })

    if alerts:
        state['alerts'].extend(alerts)

    return alerts


# ─── Telegram Integration ───────────────────────────────────

def send_telegram_alert(alerts: list, state: dict, logger):
    """Send alerts via Telegram if configured."""
    try:
        from telegram_notifier import TelegramNotifier
        tg = TelegramNotifier()

        for alert in alerts:
            icon = '🚨' if alert['severity'] == 'CRITICAL' else '⚠️'
            msg = (
                f"{icon} <b>MEXC 4H Paper Alert</b>\n"
                f"Type: {alert['type']}\n"
                f"Severity: {alert['severity']}\n"
                f"{alert['msg']}\n\n"
                f"Equity: ${state['equity']:.2f} | DD: {state['dd_current']*100:.1f}% | "
                f"Trades: {state['closed_trades']} | PF: {state['rolling_pf']:.2f}"
            )
            tg.send(msg)
            logger.info(f"  📱 Telegram alert sent: {alert['type']}")

    except Exception as e:
        logger.warning(f"  Telegram alert failed: {e}")


def send_telegram_status(state: dict, logger):
    """Send periodic status update via Telegram."""
    try:
        from telegram_notifier import TelegramNotifier
        tg = TelegramNotifier()

        closed = state['closed_trades']
        pf = state['rolling_pf']
        wr = state['rolling_wr']
        dd = state['dd_current'] * 100
        n_open = len(state['positions'])

        msg = (
            f"📊 <b>MEXC 4H Paper Status</b>\n"
            f"Check #{state['checks']} | {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n\n"
            f"💰 Equity: ${state['equity']:.2f}\n"
            f"📈 P&L: ${state['total_pnl']:+.2f}\n"
            f"📉 DD: {dd:.1f}% (max {state['dd_max']*100:.1f}%)\n"
            f"🔄 Trades: {closed} (W:{state['wins']} L:{state['losses']})\n"
            f"📊 PF: {pf:.2f} | WR: {wr:.1f}%\n"
            f"📋 Open: {n_open}/{get_adaptive_maxpos(state['dd_current'])}\n"
        )

        # Add open positions detail
        if state['positions']:
            msg += "\n<b>Open:</b>\n"
            for pair, pos in state['positions'].items():
                msg += f"  • {pair} @ ${pos['entry_price']:.6f} ({pos.get('bars_held', 0)} bars)\n"

        # Exit class summary
        if state['exit_class_a'] or state['exit_class_b']:
            msg += "\n<b>Exit Attribution:</b>\n"
            for reason, d in state['exit_class_a'].items():
                msg += f"  A: {reason}: {d['count']}x ${d['pnl']:+.2f}\n"
            for reason, d in state['exit_class_b'].items():
                msg += f"  B: {reason}: {d['count']}x ${d['pnl']:+.2f}\n"

        tg.send(msg)

    except Exception as e:
        logger.debug(f"  Telegram status failed: {e}")


# ─── Report ─────────────────────────────────────────────────

def print_report(state: dict):
    """Print paper trading report to stdout."""
    closed = state.get('closed_trades', 0)
    wins = state.get('wins', 0)
    losses = state.get('losses', 0)
    pnl = state.get('total_pnl', 0)
    gw = state.get('gross_wins', 0)
    gl = abs(state.get('gross_losses', 0))
    wr = (wins / closed * 100) if closed > 0 else 0
    avg = (pnl / closed) if closed > 0 else 0
    pf = (gw / gl) if gl > 0 else 0

    print(f"\n{'='*60}")
    print(f"  PAPER TRADING — MEXC 4H Vol Capitulation")
    print(f"{'='*60}")
    print(f"  Config:          Vol Cap 3.5x BBlow RSI35 + DC hybrid_notrl")
    print(f"  Wrappers:        dd_throttle(5%/0.22x) + adaptive_maxpos(3/2/1)")
    print(f"  Fee:             MEXC 10bps/side")
    print(f"  Capital/trade:   ${CAPITAL_PER_TRADE:.0f}")
    print(f"  Started:         {state.get('start_time', 'N/A')}")
    print(f"  Checks:          {state.get('checks', 0)}")
    print(f"{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Equity:          ${state.get('equity', 0):.2f}")
    print(f"  Total P&L:       ${pnl:+.2f}")
    print(f"  Trades:          {closed} (W:{wins} L:{losses})")
    print(f"  Win rate:         {wr:.1f}%")
    print(f"  Profit Factor:   {pf:.2f}")
    print(f"  Avg P&L/trade:   ${avg:+.2f}")
    print(f"  Biggest win:     ${state.get('biggest_win', 0):+.2f}")
    print(f"  Biggest loss:    ${state.get('biggest_loss', 0):+.2f}")
    print(f"  Max DD:          {state.get('dd_max', 0)*100:.1f}%")
    print(f"  Current DD:      {state.get('dd_current', 0)*100:.1f}%")
    print(f"  Consec. losses:  {state.get('max_consecutive_losses', 0)} (max)")
    print(f"  Class A share:   {state.get('rolling_a_share', 0):.1f}%")
    print(f"  Entries skipped: {state.get('trades_skipped_dd', 0)} (DD throttle)")
    print(f"{'='*60}")

    # Exit attribution
    print(f"  EXIT ATTRIBUTION")
    print(f"{'='*60}")
    for cls_name, cls_key in [('Class A (smart)', 'exit_class_a'),
                               ('Class B (stop/time)', 'exit_class_b')]:
        cls_data = state.get(cls_key, {})
        if cls_data:
            print(f"  {cls_name}:")
            for reason, d in cls_data.items():
                wr_r = d['wins'] / d['count'] * 100 if d['count'] > 0 else 0
                print(f"    {reason}: {d['count']}x | ${d['pnl']:+.2f} | WR {wr_r:.0f}%")
    print(f"{'='*60}")

    # Open positions
    positions = state.get('positions', {})
    if positions:
        print(f"  OPEN POSITIONS ({len(positions)})")
        print(f"{'='*60}")
        for pair, pos in positions.items():
            print(f"    {pair}: ${pos['entry_price']:.6f} | "
                  f"${pos['size_usd']:.0f} | {pos.get('bars_held', 0)} bars")
    print(f"{'='*60}")

    # Alerts
    alerts = state.get('alerts', [])
    if alerts:
        print(f"\n  ALERTS ({len(alerts)})")
        for a in alerts[-10:]:  # Show last 10
            print(f"    [{a['severity']}] {a['type']}: {a['msg']}")
    print()


# ─── Monitoring Dashboard (JSON export) ─────────────────────

def export_dashboard(state: dict):
    """Export monitoring dashboard as JSON for external consumption."""
    dashboard_file = BASE_DIR / f'dashboard_{TAG}.json'

    closed = state.get('closed_trades', 0)
    gw = state.get('gross_wins', 0)
    gl = abs(state.get('gross_losses', 0))

    dashboard = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'config': {
            'signal': 'Vol Capitulation H4S4-G05',
            'exchange': 'MEXC SPOT',
            'fee_bps': MEXC_FEE * 10000,
            'capital_per_trade': CAPITAL_PER_TRADE,
            'entry_params': ENTRY_PARAMS,
            'exit_params': EXIT_PARAMS,
            'wrappers': {
                'dd_throttle': {'threshold': DD_THROTTLE_THRESHOLD, 'scale': DD_THROTTLE_SCALE},
                'adaptive_maxpos': ADAPTIVE_MAXPOS,
            },
        },
        'metrics': {
            'equity': round(state.get('equity', 0), 2),
            'pnl': round(state.get('total_pnl', 0), 2),
            'trades': closed,
            'wins': state.get('wins', 0),
            'losses': state.get('losses', 0),
            'win_rate': round(state.get('rolling_wr', 0), 1),
            'profit_factor': round(gw / gl if gl > 0 else 0, 2),
            'avg_pnl': round(state.get('total_pnl', 0) / closed if closed > 0 else 0, 2),
            'dd_current': round(state.get('dd_current', 0) * 100, 1),
            'dd_max': round(state.get('dd_max', 0) * 100, 1),
            'consecutive_losses': state.get('consecutive_losses', 0),
            'max_consecutive_losses': state.get('max_consecutive_losses', 0),
            'trades_skipped_dd': state.get('trades_skipped_dd', 0),
            'class_a_share': state.get('rolling_a_share', 0),
        },
        'positions': state.get('positions', {}),
        'exit_attribution': {
            'class_a': state.get('exit_class_a', {}),
            'class_b': state.get('exit_class_b', {}),
        },
        'alerts': state.get('alerts', [])[-20:],  # Last 20 alerts
        'rollback_criteria': {
            'pf_below_1_after_30': closed >= 30 and (gw / gl if gl > 0 else 99) < 1.0,
            'dd_above_25': state.get('dd_max', 0) >= 0.25,
            'consecutive_losses_5': state.get('consecutive_losses', 0) >= 5,
            'wr_below_40_after_20': closed >= 20 and state.get('rolling_wr', 0) < 40.0,
            'a_share_below_30_after_20': closed >= 20 and state.get('rolling_a_share', 100) < 30.0,
            'consec_losses_8': state.get('consecutive_losses', 0) >= 8,
        },
        'checks': state.get('checks', 0),
        'last_trades': state.get('trade_log', [])[-10:],  # Last 10 trades
    }

    with open(dashboard_file, 'w') as f:
        json.dump(dashboard, f, indent=2, default=str)


# ─── Main Loop ──────────────────────────────────────────────

def run_live(mexc_client, coins: List[str], logger,
             duration_hours: Optional[int] = None, dry_run: bool = False):
    """Main paper trading loop."""

    state = load_state()

    # Reset if fresh start
    if state['checks'] == 0:
        state = new_state()
        logger.info("Fresh start — new state created")

    if duration_hours:
        end_time = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        logger.info(f"Live paper trading tot {end_time.strftime('%Y-%m-%d %H:%M UTC')} ({duration_hours}h)")
    else:
        end_time = None
        logger.info("Live paper trading — infinite (Ctrl+C to stop)")

    logger.info(f"Coins: {len(coins)} USDT pairs")
    logger.info(f"Config: Vol Cap 3.5x RSI35 + DC hybrid_notrl")
    logger.info(f"Wrappers: dd_throttle(5%/0.22x) + adaptive_maxpos(3/2/1)")
    logger.info(f"Fee: MEXC 10bps/side | Capital: ${CAPITAL_PER_TRADE}/trade")

    # Send startup notification
    try:
        from telegram_notifier import TelegramNotifier
        tg = TelegramNotifier()
        tg.send(
            f"🚀 <b>MEXC 4H Paper Trader Started</b>\n"
            f"Signal: Vol Cap 3.5x RSI35\n"
            f"Coins: {len(coins)} | Equity: ${state['equity']:.2f}\n"
            f"Wrappers: dd_throttle(5%/0.22x) + maxpos(3/2/1)"
        )
    except Exception:
        pass

    iteration = 0
    while True:
        if end_time and datetime.now(timezone.utc) >= end_time:
            logger.info("End time reached!")
            break

        if dry_run and iteration > 0:
            logger.info("Dry run — one check completed, exiting")
            break

        # Calculate next 4H candle close + 2 min buffer
        now = datetime.now(timezone.utc)

        if iteration > 0:
            # Wait for next 4H candle
            next_4h = now.replace(minute=2, second=0, microsecond=0)
            next_4h_hour = ((now.hour // 4) + 1) * 4
            if next_4h_hour >= 24:
                next_4h = next_4h.replace(hour=0) + timedelta(days=1)
            else:
                next_4h = next_4h.replace(hour=next_4h_hour)

            wait_seconds = max((next_4h - now).total_seconds(), 60)

            if end_time:
                remaining = (end_time - now).total_seconds() / 3600
                logger.info(f"\nNext check: {next_4h.strftime('%H:%M UTC')} "
                            f"(in {wait_seconds/60:.0f} min) | Remaining: {remaining:.1f}h")
            else:
                logger.info(f"\nNext check: {next_4h.strftime('%H:%M UTC')} "
                            f"(in {wait_seconds/60:.0f} min)")

            try:
                time.sleep(wait_seconds)
            except KeyboardInterrupt:
                logger.info("\nStopped by user (Ctrl+C)")
                break

        # Process check
        check_time = datetime.now(timezone.utc)
        state = process_check(mexc_client, coins, state, logger, check_time)

        # Save state
        save_state(state)
        export_dashboard(state)

        # Check for alerts and send via Telegram
        if state.get('alerts'):
            recent_alerts = [a for a in state['alerts']
                            if a.get('time', '') > (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()]
            if recent_alerts:
                send_telegram_alert(recent_alerts, state, logger)

        # Send status update every 6 checks (24h at 4H interval)
        if state['checks'] % 6 == 0:
            send_telegram_status(state, logger)

        # Check rollback criteria
        if state.get('closed_trades', 0) >= 30 and state.get('rolling_pf', 99) < 1.0:
            logger.warning("🚨 ROLLBACK CRITERION MET: PF < 1.0 after 30+ trades")
            logger.warning("   Consider stopping paper trading and investigating")

        if state.get('dd_max', 0) >= 0.25:
            logger.warning("🚨 ROLLBACK CRITERION MET: Max DD >= 25%")
            logger.warning("   Consider stopping paper trading and investigating")

        if state.get('consecutive_losses', 0) >= 8:
            logger.warning("🚨 ROLLBACK CRITERION MET: 8+ consecutive losses")
            logger.warning("   Consider stopping paper trading and investigating")

        if state.get('rolling_a_share', 100) < 30.0 and state.get('closed_trades', 0) >= 20:
            logger.warning("🚨 ROLLBACK CRITERION MET: Class A share < 30%")
            logger.warning("   Consider stopping paper trading and investigating")

        iteration += 1

    # Final report
    print_report(state)
    save_state(state)
    export_dashboard(state)

    # Send final status
    send_telegram_status(state, logger)


# ─── Main ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Paper Trade — MEXC 4H Vol Capitulation (Sprint 4 Deploy Config)')
    parser.add_argument('--hours', type=int, default=None,
                        help='Live duration in hours (default: infinite)')
    parser.add_argument('--report', action='store_true',
                        help='Show report from existing state')
    parser.add_argument('--dry-run', action='store_true',
                        help='Run one check cycle then exit')
    parser.add_argument('--reset', action='store_true',
                        help='Reset state (fresh start)')
    parser.add_argument('--coins', type=str, default=None,
                        help='Comma-separated coin list (default: top 200 by volume)')
    parser.add_argument('--max-coins', type=int, default=200,
                        help='Max coins to scan (default: 200)')
    args = parser.parse_args()

    if args.report:
        state = load_state()
        if state.get('checks', 0) > 0:
            print_report(state)
        else:
            print("No state found. Start paper trading first.")
        return

    logger = setup_logging()

    if args.reset:
        state = new_state()
        save_state(state)
        logger.info("State reset — fresh start")

    # MEXC client
    mexc_key = os.getenv('MEXC_API_KEY', '')
    mexc_secret = os.getenv('MEXC_SECRET', '')

    if not mexc_key or not mexc_secret:
        logger.error("MEXC_API_KEY or MEXC_SECRET not set in .env")
        logger.error("Add to trading_bot/.env:")
        logger.error("  MEXC_API_KEY=your_key")
        logger.error("  MEXC_SECRET=your_secret")
        sys.exit(1)

    from exchange_manager import MEXCExchangeClient
    mexc = MEXCExchangeClient(api_key=mexc_key, secret=mexc_secret)

    if not mexc.test_connection():
        logger.error("MEXC connection failed!")
        sys.exit(1)
    logger.info("MEXC connection OK")

    # Get coin universe
    if args.coins:
        coins = [c.strip() for c in args.coins.split(',')]
        logger.info(f"Coins (from CLI): {len(coins)}")
    else:
        all_pairs = mexc.get_tradeable_pairs()
        # Filter to top N by fetching tickers (approximation: use sorted list)
        # For now, use all USDT pairs limited to max_coins
        coins = all_pairs[:args.max_coins]
        logger.info(f"Coins (top {args.max_coins} USDT): {len(coins)}")

    # Run
    run_live(mexc, coins, logger, args.hours, args.dry_run)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Paper Trade — MEXC 4H Market Structure (ms_018 shift_pb shallow)
===================================================================
Live paper trading for the ms_018 MS deploy candidate (ADR-MS-002/003).

Signal: Structure Shift + Pullback (shift_pb shallow)
  - max_bos_age=15, pullback_pct=0.382, max_pullback_bars=6
  - Structural entry: bullish BoS → pullback to swing low zone

Exits: hybrid_notrl (FIXED STOP → TIME MAX → RSI RECOVERY → DC TARGET → BB TARGET)
  - max_stop_pct=15, time_max_bars=15, rsi_rec_target=45, rsi_rec_min_bars=2

Fee: MEXC SPOT 10bps/side (taker, conservative).
Sizing: Fixed $5,000/trade, max 2 positions (ADR-MS-005 optimal).

Backtest baseline (ms_018 on Kraken 26bps): PF=2.08, P5_PF=1.48, DD=21.3%, 697 trades
Note: MEXC fees (10bps) are lower than backtest (26bps), so live PF should be >= backtest.

Usage:
    python paper_ms_4h.py                   # Live (infinite)
    python paper_ms_4h.py --hours 168       # Live for 7 days
    python paper_ms_4h.py --report          # Show report
    python paper_ms_4h.py --dry-run         # One check cycle then exit
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

# ─── Path setup ─────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
REPO_ROOT = BASE_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / '.env')

# ─── Imports from MS + Sprint 3 infra ──────────────────────
import importlib

_exits_mod = importlib.import_module('strategies.4h.sprint3.exits')
evaluate_exit_hybrid_notrl = _exits_mod.evaluate_exit_hybrid_notrl
ExitSignal = _exits_mod.ExitSignal

_hyps_mod = importlib.import_module('strategies.ms.hypotheses')
signal_structure_shift_pullback = _hyps_mod.signal_structure_shift_pullback

_ind_mod = importlib.import_module('strategies.ms.indicators')
precompute_ms_indicators = _ind_mod.precompute_ms_indicators

# ─── Constants ──────────────────────────────────────────────
TAG = 'ms_4h_paper'
STATE_FILE = BASE_DIR / f'paper_state_{TAG}.json'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# MEXC fee (taker, conservative — actual may be 0% maker / 5bps taker)
MEXC_FEE = 0.0010  # 10bps per side

# Sizing (ADR-MS-005: max_pos=2 optimal from sensitivity analysis)
CAPITAL_PER_TRADE = 5000.0
INITIAL_EQUITY = 10000.0
MAX_POSITIONS = 2

# ─── ms_018 config (frozen from ADR-MS-002) ─────────────────
ENTRY_PARAMS = {
    'max_bos_age': 15,
    'pullback_pct': 0.382,
    'max_pullback_bars': 6,
    'max_stop_pct': 15.0,
    'time_max_bars': 15,
    'rsi_recovery': True,
    'rsi_rec_target': 45.0,
    'rsi_rec_min_bars': 2,
}

EXIT_PARAMS = {
    'max_stop_pct': 15.0,
    'time_max_bars': 15,
    'rsi_recovery': True,
    'rsi_rec_target': 45.0,
    'rsi_rec_min_bars': 2,
}

# Cooldown
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8

# Minimum candles needed for MS structural indicator warmup
# (swing detection needs lookback, BoS needs swings, etc.)
MIN_CANDLES = 120

# ─── Backtest Baseline (drift detection) ────────────────────
# Backtest was on Kraken 26bps; MEXC 10bps is more favorable.
# PF should be at least backtest level, likely better.
BASELINE = {
    'pf': 2.04,           # max_pos=2 baseline (ADR-MS-005)
    'p5_pf': 1.48,        # conservative: keep P5 from max_pos=3 bootstrap
    'dd_max': 0.204,      # max_pos=2 DD (was 21.3% at max_pos=3)
    'trades_per_487coins_721bars': 447,  # max_pos=2 trades (was 697 at max_pos=3)
    'backtest_fee_bps': 26,
    'live_fee_bps': 10,
}

# Drift thresholds
DRIFT_PF_FLOOR = 1.0       # rollback if PF < 1.0 after 30+ trades
DRIFT_DD_CEILING = 0.30    # alert if DD > 30% (baseline 21.3% + margin)
DRIFT_CONSEC_LOSS = 8      # rollback on 8+ consecutive losses


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
    return logging.getLogger('paper_ms_4h')


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
        'exit_class_a': {},
        'exit_class_b': {},
        'trade_log': [],
        # Cooldown tracking
        'last_exit_bar': {},
        'last_exit_was_stop': {},
        # Monitoring
        'rolling_pf': 0.0,
        'rolling_wr': 0.0,
        'consecutive_losses': 0,
        'max_consecutive_losses': 0,
        'alerts': [],
        # Drift detection
        'drift_checks': [],
    }


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return new_state()


def save_state(state: dict):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)


# ─── Indicator Computation (live, per-coin) ──────────────────

def compute_ms_indicators_for_coin(pair: str, candles: list) -> Optional[dict]:
    """Compute MS structural + base indicators for a single coin.

    Uses precompute_ms_indicators() with a single-coin dict,
    returning the indicator dict for that coin.
    """
    n = len(candles)
    if n < MIN_CANDLES:
        return None

    data = {pair: candles}
    try:
        result = precompute_ms_indicators(data, [pair])
        return result.get(pair)
    except Exception:
        return None


# ─── Drawdown Helpers ───────────────────────────────────────

def get_current_dd(state: dict) -> float:
    """Current drawdown as fraction (0.0 = no DD, 1.0 = -100%)."""
    equity = state['equity']
    peak = state['peak_equity']
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - equity) / peak)


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
    state['checks'] += 1

    dd = get_current_dd(state)
    n_open = len(state['positions'])
    logger.info(f"\n{'='*60}")
    logger.info(f"CHECK #{state['checks']} -- {check_str}")
    logger.info(f"Equity: ${state['equity']:.2f} | DD: {dd*100:.1f}% | "
                f"Open: {n_open}/{MAX_POSITIONS}")
    logger.info(f"{'='*60}")

    # ─── Phase 1: Process exits ─────────────────────────────
    pairs_to_close = []
    for pair, pos_data in list(state['positions'].items()):
        try:
            candles = mexc_client.get_ohlc(pair, interval=240)
        except Exception as e:
            logger.warning(f"  Skip exit check {pair}: API error: {e}")
            continue

        if not candles or len(candles) < MIN_CANDLES:
            logger.warning(f"  Skip exit check {pair}: insufficient candles ({len(candles) if candles else 0})")
            continue

        indicators = compute_ms_indicators_for_coin(pair, candles)
        if indicators is None:
            continue

        bar = indicators['n'] - 1

        # Track bars held via check count
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
            entry_bar=0,
            bar=actual_bars,
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
            entry_price = pos_data['entry_price']
            size_usd = pos_data['size_usd']
            gross = size_usd * (exit_sig.price / entry_price - 1.0)
            fees = size_usd * MEXC_FEE + (size_usd + gross) * MEXC_FEE
            net_pnl = gross - fees

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
                'equity_after': round(state['equity'], 2),
            }
            state['trade_log'].append(trade_record)

            pnl_pct = net_pnl / size_usd * 100
            logger.info(
                f"  {'WIN' if net_pnl >= 0 else 'LOSS'} EXIT {pair} [{reason}] "
                f"${exit_sig.price:.6f} | P&L=${net_pnl:+.2f} ({pnl_pct:+.1f}%) "
                f"| {actual_bars} bars | Eq=${state['equity']:.2f}"
            )

            pairs_to_close.append(pair)
            time.sleep(0.25)  # MEXC rate limit (20 req/sec)

    # Remove closed positions
    for pair in pairs_to_close:
        del state['positions'][pair]

    # ─── Phase 2: Process entries ────────────────────────────
    n_open = len(state['positions'])

    if n_open < MAX_POSITIONS:
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

                indicators = compute_ms_indicators_for_coin(pair, candles)
                if indicators is None:
                    continue

                bar = indicators['n'] - 1

                # Run signal function
                sig = signal_structure_shift_pullback(candles, bar, indicators, ENTRY_PARAMS)
                if sig is not None:
                    candidates.append((pair, sig['strength'], sig, indicators, candles))

            except Exception as e:
                logger.debug(f"  Signal error {pair}: {e}")

            time.sleep(0.25)  # MEXC rate limit

        # Rank by strength, fill available slots
        candidates.sort(key=lambda x: x[1], reverse=True)
        slots = MAX_POSITIONS - n_open

        for pair, strength, sig, indicators, candles in candidates[:slots]:
            bar = indicators['n'] - 1
            close = indicators['closes'][bar]
            rsi_val = indicators['rsi'][bar]

            size_usd = min(CAPITAL_PER_TRADE, state['equity'] * 0.95)
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
                f"  ENTRY {pair} @ ${close:.6f} | RSI={rsi_val:.1f} "
                f"| Str={strength:.2f} | ${size_usd:.0f}"
            )

    # Update rolling metrics + drift detection
    alerts = _update_rolling_metrics(state)
    if alerts:
        for a in alerts:
            logger.warning(f"  ALERT [{a['severity']}] {a['type']}: {a['msg']}")

    return state


def _update_rolling_metrics(state: dict) -> list:
    """Update rolling PF, WR, and check drift/rollback conditions."""
    closed = state['closed_trades']
    if closed == 0:
        return []

    wins = state['wins']
    state['rolling_wr'] = wins / closed * 100

    gw = state['gross_wins']
    gl = abs(state['gross_losses'])
    state['rolling_pf'] = gw / gl if gl > 0 else 99.0

    alerts = []

    # ─── Rollback criteria ──────────────────────────────────

    # R1: PF drops below 1.0 after 30+ trades
    if closed >= 30 and state['rolling_pf'] < DRIFT_PF_FLOOR:
        alerts.append({
            'type': 'ROLLBACK_PF',
            'severity': 'CRITICAL',
            'msg': f"PF={state['rolling_pf']:.2f} < {DRIFT_PF_FLOOR} after {closed} trades",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # R2: DD exceeds ceiling
    dd_max = state.get('dd_max', 0)
    if dd_max >= DRIFT_DD_CEILING:
        alerts.append({
            'type': 'ROLLBACK_DD',
            'severity': 'CRITICAL',
            'msg': f"Max DD={dd_max*100:.1f}% exceeds {DRIFT_DD_CEILING*100:.0f}% threshold",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # R3: 8+ consecutive losses
    if state['consecutive_losses'] >= DRIFT_CONSEC_LOSS:
        alerts.append({
            'type': 'ROLLBACK_CONSEC',
            'severity': 'CRITICAL',
            'msg': f"{state['consecutive_losses']} consecutive losses (>={DRIFT_CONSEC_LOSS} = rollback)",
            'time': datetime.now(timezone.utc).isoformat(),
        })
    elif state['consecutive_losses'] >= 5:
        alerts.append({
            'type': 'CONSECUTIVE_LOSSES',
            'severity': 'WARNING',
            'msg': f"{state['consecutive_losses']} consecutive losses",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # ─── Drift detection ────────────────────────────────────

    # D1: PF drift — warn if PF < P5 baseline after 50+ trades
    if closed >= 50 and state['rolling_pf'] < BASELINE['p5_pf']:
        alerts.append({
            'type': 'DRIFT_PF_BELOW_P5',
            'severity': 'WARNING',
            'msg': f"PF={state['rolling_pf']:.2f} below P5 baseline ({BASELINE['p5_pf']}) after {closed} trades",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # D2: WR drift — warn if WR < 35% after 30+ trades
    if closed >= 30 and state['rolling_wr'] < 35.0:
        alerts.append({
            'type': 'DRIFT_LOW_WR',
            'severity': 'WARNING',
            'msg': f"WR={state['rolling_wr']:.1f}% < 35% after {closed} trades",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # D3: Exit class dominance — warn if Class A < 40% of profit after 20+ trades
    if closed >= 20:
        a_profit = sum(
            max(0, d['pnl']) for d in state.get('exit_class_a', {}).values()
        )
        total_profit = a_profit + sum(
            max(0, d['pnl']) for d in state.get('exit_class_b', {}).values()
        )
        a_share = (a_profit / total_profit * 100) if total_profit > 0 else 0.0

        if a_share < 40.0:
            alerts.append({
                'type': 'DRIFT_LOW_A_SHARE',
                'severity': 'WARNING',
                'msg': f"Class A share={a_share:.1f}% < 40% after {closed} trades",
                'time': datetime.now(timezone.utc).isoformat(),
            })

    # Periodic drift checkpoint (every 25 trades)
    if closed > 0 and closed % 25 == 0:
        checkpoint = {
            'trades': closed,
            'pf': round(state['rolling_pf'], 2),
            'wr': round(state['rolling_wr'], 1),
            'dd_max': round(state['dd_max'] * 100, 1),
            'equity': round(state['equity'], 2),
            'time': datetime.now(timezone.utc).isoformat(),
        }
        state.setdefault('drift_checks', []).append(checkpoint)

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
            icon = 'CRITICAL' if alert['severity'] == 'CRITICAL' else 'WARNING'
            msg = (
                f"[{icon}] MS 4H Paper Alert\n"
                f"Type: {alert['type']}\n"
                f"Severity: {alert['severity']}\n"
                f"{alert['msg']}\n\n"
                f"Equity: ${state['equity']:.2f} | DD: {state['dd_current']*100:.1f}% | "
                f"Trades: {state['closed_trades']} | PF: {state['rolling_pf']:.2f}"
            )
            tg.send(msg)
            logger.info(f"  Telegram alert sent: {alert['type']}")

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
            f"MS 4H Paper Status (MEXC)\n"
            f"Check #{state['checks']} | {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n\n"
            f"Equity: ${state['equity']:.2f}\n"
            f"P&L: ${state['total_pnl']:+.2f}\n"
            f"DD: {dd:.1f}% (max {state['dd_max']*100:.1f}%)\n"
            f"Trades: {closed} (W:{state['wins']} L:{state['losses']})\n"
            f"PF: {pf:.2f} | WR: {wr:.1f}%\n"
            f"Open: {n_open}/{MAX_POSITIONS}\n"
        )

        if state['positions']:
            msg += "\nOpen:\n"
            for pair, pos in state['positions'].items():
                msg += f"  {pair} @ ${pos['entry_price']:.6f} ({pos.get('bars_held', 0)} bars)\n"

        if state['exit_class_a'] or state['exit_class_b']:
            msg += "\nExit Attribution:\n"
            for reason, d in state['exit_class_a'].items():
                msg += f"  A: {reason}: {d['count']}x ${d['pnl']:+.2f}\n"
            for reason, d in state['exit_class_b'].items():
                msg += f"  B: {reason}: {d['count']}x ${d['pnl']:+.2f}\n"

        drift = state.get('drift_checks', [])
        if drift:
            latest = drift[-1]
            msg += f"\nDrift: PF={latest['pf']} WR={latest['wr']}% DD={latest['dd_max']}% @ {latest['trades']}t\n"

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
    print(f"  PAPER TRADING -- MEXC 4H MS shift_pb (ms_018)")
    print(f"{'='*60}")
    print(f"  Config:          shift_pb shallow (max_bos_age=15, pb=0.382)")
    print(f"  Exits:           hybrid_notrl (DC+RSI+BB targets)")
    print(f"  Fee:             MEXC 10bps/side (taker)")
    print(f"  Capital/trade:   ${CAPITAL_PER_TRADE:.0f}")
    print(f"  Max positions:   {MAX_POSITIONS}")
    print(f"  Started:         {state.get('start_time', 'N/A')}")
    print(f"  Checks:          {state.get('checks', 0)}")
    print(f"{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Equity:          ${state.get('equity', 0):.2f}")
    print(f"  Total P&L:       ${pnl:+.2f}")
    print(f"  Trades:          {closed} (W:{wins} L:{losses})")
    print(f"  Win rate:        {wr:.1f}%")
    print(f"  Profit Factor:   {pf:.2f}")
    print(f"  Avg P&L/trade:   ${avg:+.2f}")
    print(f"  Biggest win:     ${state.get('biggest_win', 0):+.2f}")
    print(f"  Biggest loss:    ${state.get('biggest_loss', 0):+.2f}")
    print(f"  Max DD:          {state.get('dd_max', 0)*100:.1f}%")
    print(f"  Current DD:      {state.get('dd_current', 0)*100:.1f}%")
    print(f"  Consec. losses:  {state.get('max_consecutive_losses', 0)} (max)")
    print(f"{'='*60}")

    # Baseline comparison
    print(f"  DRIFT DETECTION (vs backtest baseline)")
    print(f"{'='*60}")
    print(f"  Backtest PF:     {BASELINE['pf']} (P5={BASELINE['p5_pf']}) @ {BASELINE['backtest_fee_bps']}bps")
    print(f"  Live PF:         {pf:.2f} {'OK' if pf >= BASELINE['p5_pf'] else 'BELOW P5'} @ {BASELINE['live_fee_bps']}bps")
    print(f"  Backtest DD:     {BASELINE['dd_max']*100:.1f}%")
    print(f"  Live DD:         {state.get('dd_max', 0)*100:.1f}%")
    drift = state.get('drift_checks', [])
    if drift:
        print(f"  Checkpoints:     {len(drift)}")
        for dc in drift[-5:]:
            print(f"    @{dc['trades']}t: PF={dc['pf']} WR={dc['wr']}% DD={dc['dd_max']}%")
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
        for a in alerts[-10:]:
            print(f"    [{a['severity']}] {a['type']}: {a['msg']}")
    print()


# ─── Dashboard Export ────────────────────────────────────────

def export_dashboard(state: dict):
    """Export monitoring dashboard as JSON."""
    dashboard_file = BASE_DIR / f'dashboard_{TAG}.json'

    closed = state.get('closed_trades', 0)
    gw = state.get('gross_wins', 0)
    gl = abs(state.get('gross_losses', 0))

    dashboard = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'config': {
            'signal': 'MS shift_pb shallow (ms_018)',
            'exchange': 'MEXC SPOT',
            'fee_bps': MEXC_FEE * 10000,
            'capital_per_trade': CAPITAL_PER_TRADE,
            'max_positions': MAX_POSITIONS,
            'entry_params': ENTRY_PARAMS,
            'exit_params': EXIT_PARAMS,
        },
        'baseline': BASELINE,
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
        },
        'positions': state.get('positions', {}),
        'exit_attribution': {
            'class_a': state.get('exit_class_a', {}),
            'class_b': state.get('exit_class_b', {}),
        },
        'drift_checks': state.get('drift_checks', []),
        'alerts': state.get('alerts', [])[-20:],
        'rollback_criteria': {
            'pf_below_1_after_30': closed >= 30 and (gw / gl if gl > 0 else 99) < DRIFT_PF_FLOOR,
            'dd_above_30': state.get('dd_max', 0) >= DRIFT_DD_CEILING,
            'consecutive_losses_8': state.get('consecutive_losses', 0) >= DRIFT_CONSEC_LOSS,
        },
        'checks': state.get('checks', 0),
        'last_trades': state.get('trade_log', [])[-10:],
    }

    with open(dashboard_file, 'w') as f:
        json.dump(dashboard, f, indent=2, default=str)


# ─── Main Loop ──────────────────────────────────────────────

def run_live(mexc_client, coins: List[str], logger,
             duration_hours: Optional[int] = None, dry_run: bool = False):
    """Main paper trading loop."""

    state = load_state()

    if state['checks'] == 0:
        state = new_state()
        logger.info("Fresh start -- new state created")

    if duration_hours:
        end_time = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        logger.info(f"Live paper trading until {end_time.strftime('%Y-%m-%d %H:%M UTC')} ({duration_hours}h)")
    else:
        end_time = None
        logger.info("Live paper trading -- infinite (Ctrl+C to stop)")

    logger.info(f"Coins: {len(coins)} USDT pairs")
    logger.info(f"Config: MS shift_pb shallow (ms_018) + DC hybrid_notrl exits")
    logger.info(f"Fee: MEXC 10bps/side | Capital: ${CAPITAL_PER_TRADE}/trade | Max pos: {MAX_POSITIONS}")
    logger.info(f"Baseline: PF={BASELINE['pf']} (P5={BASELINE['p5_pf']}) @ {BASELINE['backtest_fee_bps']}bps, "
                f"live @ {BASELINE['live_fee_bps']}bps")

    # Startup notification
    try:
        from telegram_notifier import TelegramNotifier
        tg = TelegramNotifier()
        tg.send(
            f"MS 4H Paper Trader Started (MEXC)\n"
            f"Signal: shift_pb shallow (ms_018)\n"
            f"Coins: {len(coins)} | Equity: ${state['equity']:.2f}\n"
            f"Baseline PF: {BASELINE['pf']} (P5={BASELINE['p5_pf']}) @ {BASELINE['backtest_fee_bps']}bps"
        )
    except Exception:
        pass

    iteration = 0
    while True:
        if end_time and datetime.now(timezone.utc) >= end_time:
            logger.info("End time reached!")
            break

        if dry_run and iteration > 0:
            logger.info("Dry run -- one check completed, exiting")
            break

        now = datetime.now(timezone.utc)

        if iteration > 0:
            # Wait for next 4H candle close + 2 min buffer
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

        # Telegram alerts
        if state.get('alerts'):
            recent_alerts = [a for a in state['alerts']
                            if a.get('time', '') > (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()]
            if recent_alerts:
                send_telegram_alert(recent_alerts, state, logger)

        # Status update every 6 checks (24h at 4H interval)
        if state['checks'] % 6 == 0:
            send_telegram_status(state, logger)

        # Log rollback warnings
        if state.get('closed_trades', 0) >= 30 and state.get('rolling_pf', 99) < DRIFT_PF_FLOOR:
            logger.warning("ROLLBACK CRITERION: PF < 1.0 after 30+ trades")

        if state.get('dd_max', 0) >= DRIFT_DD_CEILING:
            logger.warning(f"ROLLBACK CRITERION: Max DD >= {DRIFT_DD_CEILING*100:.0f}%")

        if state.get('consecutive_losses', 0) >= DRIFT_CONSEC_LOSS:
            logger.warning(f"ROLLBACK CRITERION: {DRIFT_CONSEC_LOSS}+ consecutive losses")

        iteration += 1

    # Final report
    print_report(state)
    save_state(state)
    export_dashboard(state)
    send_telegram_status(state, logger)


# ─── Main ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Paper Trade -- MEXC 4H MS shift_pb (ms_018)')
    parser.add_argument('--hours', type=int, default=None,
                        help='Live duration in hours (default: infinite)')
    parser.add_argument('--report', action='store_true',
                        help='Show report from existing state')
    parser.add_argument('--dry-run', action='store_true',
                        help='Run one check cycle then exit')
    parser.add_argument('--reset', action='store_true',
                        help='Reset state (fresh start)')
    parser.add_argument('--coins', type=str, default=None,
                        help='Comma-separated coin list (default: top N USDT pairs)')
    parser.add_argument('--max-coins', type=int, default=300,
                        help='Max coins to scan (default: 300)')
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
        logger.info("State reset -- fresh start")

    # MEXC client
    mexc_key = os.getenv('MEXC_API_KEY', '')
    mexc_secret = os.getenv('MEXC_SECRET_KEY', '') or os.getenv('MEXC_SECRET', '')

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
        coins = all_pairs[:args.max_coins]
        logger.info(f"Coins (top {args.max_coins} USDT pairs): {len(coins)}")

    # Run
    run_live(mexc, coins, logger, args.hours, args.dry_run)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Live Trader — Generic Strategy Execution Framework
=====================================================
Strategy-agnostic trading bot. All strategy logic loaded via StrategyConfig.

Invariants (non-negotiable):
1. Atomic state writes (tmp → bak → rename)
2. Reconciliation per cycle (exchange vs local state)
3. Idempotent panic sell (no delete-before-confirm)
4. Hard liquidity gate (quoteVolume)
5. Circuit breaker with real action + TG alerts

Usage:
    python live_trader.py --strategy ms_018                      # Paper (default)
    python live_trader.py --strategy ms_018 --live               # Live MEXC
    python live_trader.py --strategy ms_018 --live --micro       # Smoke test ($50)
    python live_trader.py --strategy ms_018 --report             # Show report
    python live_trader.py --strategy ms_018 --dry-run            # One cycle test
"""
import os
import sys
import json
import time
import signal
import shutil
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

# ─── Imports ────────────────────────────────────────────────
import importlib

_exits_mod = importlib.import_module('strategies.4h.sprint3.exits')
evaluate_exit_hybrid_notrl = _exits_mod.evaluate_exit_hybrid_notrl
ExitSignal = _exits_mod.ExitSignal

from trading_bot.strategy_config import load_strategy, StrategyConfig
from trading_bot.order_executor import OrderExecutor, OrderResult
from trading_bot.circuit_breaker import CircuitBreaker

# ─── Globals (set by main) ──────────────────────────────────
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# Graceful shutdown flag
_shutdown_requested = False


def _graceful_shutdown(signum, frame):
    """Signal handler: save state, do NOT sell, exit clean."""
    global _shutdown_requested
    _shutdown_requested = True
    sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
    logging.getLogger('trading_bot').info(f"\nGraceful shutdown requested ({sig_name})")


signal.signal(signal.SIGTERM, _graceful_shutdown)
signal.signal(signal.SIGINT, _graceful_shutdown)


# ─── Logging ────────────────────────────────────────────────

def setup_logging(tag: str):
    log_file = LOG_DIR / f"live_{tag}_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ]
    )
    return logging.getLogger('trading_bot')


# ─── State Management (INVARIANT: atomic writes) ────────────

def get_state_file(config: StrategyConfig, live: bool) -> Path:
    mode = 'live' if live else 'paper'
    return BASE_DIR / f'state_{config.name}_{mode}.json'


def new_state(config: StrategyConfig) -> dict:
    return {
        'strategy': config.name,
        'positions': {},
        'equity': config.initial_equity,
        'peak_equity': config.initial_equity,
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
        'last_exit_bar': {},
        'last_exit_was_stop': {},
        'rolling_pf': 0.0,
        'rolling_wr': 0.0,
        'consecutive_losses': 0,
        'max_consecutive_losses': 0,
        'alerts': [],
        'drift_checks': [],
        'circuit_breaker': None,
        'entries_paused_until': 0,
        'slippage_log': [],
    }


def load_state(state_file: Path, config: StrategyConfig) -> dict:
    if state_file.exists():
        with open(state_file) as f:
            return json.load(f)
    return new_state(config)


def save_state(state: dict, state_file: Path):
    """INVARIANT: Atomic write — tmp → backup → rename."""
    tmp = state_file.with_suffix('.tmp')
    bak = state_file.with_suffix('.bak')
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=2, default=str)
    if state_file.exists():
        shutil.copy2(state_file, bak)
    tmp.rename(state_file)


# ─── Indicator Computation ──────────────────────────────────

def compute_indicators_for_coin(pair: str, candles: list, config: StrategyConfig):
    """Compute indicators for a single coin using strategy's precompute_fn."""
    if len(candles) < config.min_candles:
        return None
    data = {pair: candles}
    try:
        result = config.precompute_fn(data, [pair])
        return result.get(pair)
    except Exception:
        return None


# ─── Drawdown Helper ────────────────────────────────────────

def get_current_dd(state: dict) -> float:
    equity = state['equity']
    peak = state['peak_equity']
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - equity) / peak)


# ─── Reconciliation (INVARIANT: every cycle) ────────────────

def reconcile_positions(state: dict, client, logger) -> list:
    """INVARIANT: Reconcile exchange balances vs local state every cycle.

    Returns list of alerts. Halts new entries on >5% mismatch.
    """
    alerts = []
    if not state.get('positions'):
        return alerts

    try:
        balance = client.get_balance()
    except Exception as e:
        logger.warning(f"  Reconciliation failed (balance error): {e}")
        return alerts

    if balance is None:
        logger.warning("  Reconciliation skipped: could not fetch balance")
        return alerts

    for pair, pos in list(state['positions'].items()):
        base_asset = pair.split('/')[0]
        expected_qty = pos['size_usd'] / pos['entry_price']
        actual_qty = balance.get(base_asset, 0)

        # Dust threshold: ignore < $1
        ticker = client.get_ticker(pair)
        if ticker:
            actual_usd = actual_qty * ticker['last']
            if actual_usd < 1.0 and expected_qty * ticker['last'] < 1.0:
                continue

        if expected_qty > 0:
            mismatch_pct = abs(actual_qty - expected_qty) / expected_qty
            if mismatch_pct > 0.05:
                msg = (f"RECONCILIATION MISMATCH: {pair} "
                       f"expected={expected_qty:.6f} actual={actual_qty:.6f} "
                       f"({mismatch_pct*100:.1f}%)")
                logger.critical(msg)
                alerts.append({
                    'type': 'RECONCILIATION_MISMATCH',
                    'severity': 'CRITICAL',
                    'msg': msg,
                    'time': datetime.now(timezone.utc).isoformat(),
                })
                # HALT new entries
                state['entries_paused_until'] = time.time() + 86400
    return alerts


# ─── Liquidity Filter (INVARIANT: hard gate) ────────────────

def passes_liquidity_gate(pair: str, client, min_volume: float) -> bool:
    """INVARIANT: Hard liquidity gate — only coins with sufficient volume."""
    try:
        ticker = client.get_ticker(pair)
        if not ticker:
            return False
        quote_vol = ticker.get('quote_volume_24h', 0)
        return quote_vol >= min_volume
    except Exception:
        return False


# ─── Core Check Cycle ───────────────────────────────────────

def process_check(
    client, coins: List[str], state: dict, config: StrategyConfig,
    executor: OrderExecutor, circuit: CircuitBreaker,
    logger, check_time: datetime, is_live: bool,
) -> dict:
    """Process one candle check across all coins.

    Flow:
    1. Check circuit breaker
    2. Reconcile (live mode)
    3. Exits
    4. Entries (with liquidity gate)
    5. Rolling metrics + circuit breaker check
    6. Atomic state save
    """
    check_str = check_time.strftime('%Y-%m-%d %H:%M UTC')
    state['checks'] += 1

    dd = get_current_dd(state)
    n_open = len(state['positions'])
    logger.info(f"\n{'='*60}")
    logger.info(f"CHECK #{state['checks']} -- {check_str}")
    logger.info(f"Equity: ${state['equity']:.2f} | DD: {dd*100:.1f}% | "
                f"Open: {n_open}/{config.max_positions} | Mode: {'LIVE' if is_live else 'PAPER'}")
    logger.info(f"{'='*60}")

    # 1. Circuit breaker check
    if circuit.is_tripped(state):
        logger.critical("CIRCUIT BREAKER TRIPPED — skipping all operations")
        return state

    # 2. Reconciliation (live mode only)
    if is_live:
        recon_alerts = reconcile_positions(state, client, logger)
        if recon_alerts:
            for a in recon_alerts:
                logger.critical(f"  {a['msg']}")
            state.setdefault('alerts', []).extend(recon_alerts)

    # 3. Process exits
    pairs_to_close = []
    for pair, pos_data in list(state['positions'].items()):
        try:
            candles = client.get_ohlc(pair, interval=config.timeframe_minutes)
        except Exception as e:
            logger.warning(f"  Skip exit check {pair}: {e}")
            continue

        if not candles or len(candles) < config.min_candles:
            continue

        indicators = compute_indicators_for_coin(pair, candles, config)
        if indicators is None:
            continue

        bar = indicators['n'] - 1
        pos_data['bars_held'] = pos_data.get('bars_held', 0) + 1
        actual_bars = pos_data['bars_held']

        exit_sig = evaluate_exit_hybrid_notrl(
            entry_price=pos_data['entry_price'],
            entry_bar=0,
            bar=actual_bars,
            low=indicators['lows'][bar],
            high=indicators['highs'][bar],
            close=indicators['closes'][bar],
            rsi=indicators['rsi'][bar],
            dc_mid=indicators['dc_mid'][bar],
            bb_mid=indicators['bb_mid'][bar],
            max_stop_pct=config.exit_params['max_stop_pct'],
            time_max_bars=config.exit_params['time_max_bars'],
            rsi_recovery=config.exit_params.get('rsi_recovery', False),
            rsi_rec_target=config.exit_params.get('rsi_rec_target', 45.0),
            rsi_rec_min_bars=config.exit_params.get('rsi_rec_min_bars', 2),
        )

        if exit_sig is not None:
            # Execute sell
            qty = pos_data['size_usd'] / pos_data['entry_price']
            current_price = exit_sig.price

            # Get volume for slippage estimation
            ticker = client.get_ticker(pair)
            vol_usd = ticker.get('quote_volume_24h', 0) if ticker else 0

            result = executor.sell(pair, qty, current_price, bar_volume_usd=vol_usd)

            if result.filled:
                entry_price = pos_data['entry_price']
                size_usd = pos_data['size_usd']
                # Use actual fill price for P&L
                gross = size_usd * (result.fill_price / entry_price - 1.0)
                entry_fee = size_usd * config.fee_rate
                net_pnl = gross - entry_fee - result.fees

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

                # Trade log
                state['trade_log'].append({
                    'nr': state['closed_trades'],
                    'pair': pair,
                    'entry_price': entry_price,
                    'exit_price': result.fill_price,
                    'size_usd': size_usd,
                    'pnl': round(net_pnl, 2),
                    'pnl_pct': round(net_pnl / size_usd * 100, 2),
                    'exit_reason': reason,
                    'exit_class': cls,
                    'bars_held': actual_bars,
                    'entry_time': pos_data.get('entry_time', ''),
                    'exit_time': check_str,
                    'order_id': result.order_id,
                    'slippage_bps': round(result.slippage_bps, 1),
                    'equity_after': round(state['equity'], 2),
                })

                # Slippage tracking
                state.setdefault('slippage_log', []).append({
                    'pair': pair,
                    'side': 'sell',
                    'expected': current_price,
                    'actual': result.fill_price,
                    'bps': round(result.slippage_bps, 1),
                    'time': check_str,
                })

                pnl_pct = net_pnl / size_usd * 100
                logger.info(
                    f"  {'WIN' if net_pnl >= 0 else 'LOSS'} EXIT {pair} [{reason}] "
                    f"${result.fill_price:.6f} | P&L=${net_pnl:+.2f} ({pnl_pct:+.1f}%) "
                    f"| {actual_bars} bars | Eq=${state['equity']:.2f} "
                    f"| slip={result.slippage_bps:.1f}bps"
                )

                pairs_to_close.append(pair)
            else:
                logger.error(f"  SELL FAILED {pair}: {result.error}")

            time.sleep(0.25)

    for pair in pairs_to_close:
        del state['positions'][pair]

    # 4. Process entries
    n_open = len(state['positions'])
    entries_paused = circuit.is_paused(state)

    if n_open < config.max_positions and not entries_paused:
        cap_per_trade = config.capital_per_trade

        candidates = []
        for pair in coins:
            if pair in state['positions']:
                continue

            # Cooldown
            last_exit = state['last_exit_bar'].get(pair, -999)
            was_stop = state['last_exit_was_stop'].get(pair, False)
            cd = config.cooldown_after_stop if was_stop else config.cooldown_bars
            if (state['checks'] - last_exit) < cd:
                continue

            # INVARIANT: Hard liquidity gate
            if not passes_liquidity_gate(pair, client, config.min_volume_24h):
                continue

            try:
                candles = client.get_ohlc(pair, interval=config.timeframe_minutes)
                if not candles or len(candles) < config.min_candles:
                    continue

                indicators = compute_indicators_for_coin(pair, candles, config)
                if indicators is None:
                    continue

                bar = indicators['n'] - 1
                sig = config.signal_fn(candles, bar, indicators, config.entry_params)
                if sig is not None:
                    candidates.append((pair, sig['strength'], sig, indicators, candles))
            except Exception as e:
                logger.debug(f"  Signal error {pair}: {e}")

            time.sleep(0.25)

        # Rank by strength, fill available slots
        candidates.sort(key=lambda x: x[1], reverse=True)
        slots = config.max_positions - n_open

        for pair, strength, sig, indicators, candles in candidates[:slots]:
            bar = indicators['n'] - 1
            close = indicators['closes'][bar]
            rsi_val = indicators['rsi'][bar]

            size_usd = min(cap_per_trade, state['equity'] * 0.95)
            if size_usd < 50:
                logger.warning(f"  Skip entry {pair}: insufficient equity (${state['equity']:.2f})")
                break

            # INVARIANT: Pending order pre-write (crash recovery)
            state['total_trades'] += 1
            state['positions'][pair] = {
                'pair': pair,
                'entry_price': close,        # placeholder, updated after fill
                'size_usd': size_usd,
                'entry_bar': bar,
                'entry_time': check_str,
                'bars_held': 0,
                'rsi_at_entry': rsi_val,
                'strength': strength,
                'trade_nr': state['total_trades'],
                'status': 'pending',          # pre-write marker
            }

            # Get volume for slippage estimation
            ticker = client.get_ticker(pair)
            vol_usd = ticker.get('quote_volume_24h', 0) if ticker else 0

            result = executor.buy(pair, size_usd, close, bar_volume_usd=vol_usd)

            if result.filled:
                # Update position with actual fill
                state['positions'][pair].update({
                    'entry_price': result.fill_price,
                    'order_id': result.order_id,
                    'status': 'open',
                })

                # Slippage tracking
                state.setdefault('slippage_log', []).append({
                    'pair': pair,
                    'side': 'buy',
                    'expected': close,
                    'actual': result.fill_price,
                    'bps': round(result.slippage_bps, 1),
                    'time': check_str,
                })

                logger.info(
                    f"  ENTRY {pair} @ ${result.fill_price:.6f} | RSI={rsi_val:.1f} "
                    f"| Str={strength:.2f} | ${size_usd:.0f} "
                    f"| slip={result.slippage_bps:.1f}bps"
                )
            else:
                # Remove failed pending entry
                del state['positions'][pair]
                state['total_trades'] -= 1
                logger.error(f"  ENTRY FAILED {pair}: {result.error}")

    elif entries_paused:
        logger.info("  Entries PAUSED (circuit breaker daily loss / reconciliation mismatch)")

    # 5. Rolling metrics + circuit breaker check
    alerts = _update_rolling_metrics(state, config)

    # INVARIANT: Circuit breaker with real action
    cb_result = circuit.check(state)
    if cb_result['tripped']:
        state = circuit.trip(state, cb_result['reasons'])
    elif cb_result['paused']:
        state = circuit.pause_entries(state)
        for r in cb_result['reasons']:
            logger.warning(f"  CIRCUIT BREAKER PAUSE: {r}")

    # Slippage quality alerts
    avg_slip = executor.get_avg_slippage_bps(20)
    if avg_slip > 20:
        alerts.append({
            'type': 'HIGH_AVG_SLIPPAGE',
            'severity': 'WARNING',
            'msg': f"Avg slippage {avg_slip:.1f}bps > 20bps over last 20 trades",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    if alerts:
        state.setdefault('alerts', []).extend(alerts)
        for a in alerts:
            logger.warning(f"  ALERT [{a['severity']}] {a['type']}: {a['msg']}")

    return state


def _update_rolling_metrics(state: dict, config: StrategyConfig) -> list:
    """Update rolling PF, WR, and check drift conditions."""
    closed = state['closed_trades']
    if closed == 0:
        return []

    wins = state['wins']
    state['rolling_wr'] = wins / closed * 100

    gw = state['gross_wins']
    gl = abs(state['gross_losses'])
    state['rolling_pf'] = gw / gl if gl > 0 else 99.0

    alerts = []
    baseline = config.baseline

    # PF drift below P5 baseline
    if closed >= 50 and state['rolling_pf'] < baseline.get('p5_pf', 1.0):
        alerts.append({
            'type': 'DRIFT_PF_BELOW_P5',
            'severity': 'WARNING',
            'msg': f"PF={state['rolling_pf']:.2f} below P5 baseline ({baseline.get('p5_pf', '?')}) after {closed} trades",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # WR drift
    if closed >= 30 and state['rolling_wr'] < 35.0:
        alerts.append({
            'type': 'DRIFT_LOW_WR',
            'severity': 'WARNING',
            'msg': f"WR={state['rolling_wr']:.1f}% < 35% after {closed} trades",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # Periodic checkpoint
    if closed > 0 and closed % 25 == 0:
        state.setdefault('drift_checks', []).append({
            'trades': closed,
            'pf': round(state['rolling_pf'], 2),
            'wr': round(state['rolling_wr'], 1),
            'dd_max': round(state['dd_max'] * 100, 1),
            'equity': round(state['equity'], 2),
            'time': datetime.now(timezone.utc).isoformat(),
        })

    return alerts


# ─── Telegram ───────────────────────────────────────────────

class TelegramBridge:
    """Wrapper for Telegram notifications (optional)."""

    def __init__(self):
        self._tg = None
        try:
            from telegram_notifier import TelegramNotifier
            self._tg = TelegramNotifier()
        except Exception:
            pass

    def send(self, msg: str):
        if self._tg:
            try:
                self._tg.send(msg)
            except Exception:
                pass

    def send_critical(self, msg: str):
        self.send(f"🚨 CRITICAL: {msg}")

    def send_entry(self, pair: str, price: float, size: float,
                   strength: float, config_name: str):
        self.send(
            f"📈 ENTRY {pair}\n"
            f"Price: ${price:.6f}\n"
            f"Size: ${size:.0f}\n"
            f"Strength: {strength:.2f}\n"
            f"Strategy: {config_name}"
        )

    def send_exit(self, pair: str, price: float, pnl: float,
                  reason: str, bars: int, config_name: str):
        icon = '✅' if pnl >= 0 else '❌'
        self.send(
            f"{icon} EXIT {pair} [{reason}]\n"
            f"Price: ${price:.6f}\n"
            f"P&L: ${pnl:+.2f}\n"
            f"Bars: {bars}\n"
            f"Strategy: {config_name}"
        )

    def send_status(self, state: dict, config: StrategyConfig):
        closed = state.get('closed_trades', 0)
        n_open = len(state.get('positions', {}))
        self.send(
            f"📊 {config.name} Status\n"
            f"Equity: ${state.get('equity', 0):.2f}\n"
            f"P&L: ${state.get('total_pnl', 0):+.2f}\n"
            f"DD: {state.get('dd_current', 0)*100:.1f}%\n"
            f"Trades: {closed} | PF: {state.get('rolling_pf', 0):.2f}\n"
            f"Open: {n_open}/{config.max_positions}"
        )


# ─── Report ─────────────────────────────────────────────────

def print_report(state: dict, config: StrategyConfig):
    closed = state.get('closed_trades', 0)
    wins = state.get('wins', 0)
    pnl = state.get('total_pnl', 0)
    gw = state.get('gross_wins', 0)
    gl = abs(state.get('gross_losses', 0))
    wr = (wins / closed * 100) if closed > 0 else 0
    avg = (pnl / closed) if closed > 0 else 0
    pf = (gw / gl) if gl > 0 else 0

    print(f"\n{'='*60}")
    print(f"  LIVE TRADER -- {config.name}")
    print(f"{'='*60}")
    print(f"  Strategy:        {config.name}")
    print(f"  Timeframe:       {config.timeframe}")
    print(f"  Fee:             {config.fee_rate*10000:.0f}bps/side")
    print(f"  Capital/trade:   ${config.capital_per_trade:.0f}")
    print(f"  Max positions:   {config.max_positions}")
    print(f"  Started:         {state.get('start_time', 'N/A')}")
    print(f"  Checks:          {state.get('checks', 0)}")
    print(f"{'='*60}")
    print(f"  Equity:          ${state.get('equity', 0):.2f}")
    print(f"  Total P&L:       ${pnl:+.2f}")
    print(f"  Trades:          {closed} (W:{wins} L:{state.get('losses', 0)})")
    print(f"  Win rate:        {wr:.1f}%")
    print(f"  Profit Factor:   {pf:.2f}")
    print(f"  Avg P&L/trade:   ${avg:+.2f}")
    print(f"  Max DD:          {state.get('dd_max', 0)*100:.1f}%")
    print(f"  Consec. losses:  {state.get('max_consecutive_losses', 0)} (max)")
    print(f"{'='*60}")

    # Exit attribution
    for cls_name, cls_key in [('Class A (smart)', 'exit_class_a'),
                               ('Class B (stop/time)', 'exit_class_b')]:
        cls_data = state.get(cls_key, {})
        if cls_data:
            print(f"  {cls_name}:")
            for reason, d in cls_data.items():
                wr_r = d['wins'] / d['count'] * 100 if d['count'] > 0 else 0
                print(f"    {reason}: {d['count']}x | ${d['pnl']:+.2f} | WR {wr_r:.0f}%")

    # Open positions
    positions = state.get('positions', {})
    if positions:
        print(f"\n  Open Positions ({len(positions)}):")
        for pair, pos in positions.items():
            held = pos.get('bars_held', 0)
            entry = pos.get('entry_price', 0)
            size = pos.get('size_usd', 0)
            rsi = pos.get('rsi_at_entry', 0)
            print(f"    {pair}: ${size:.0f} @ ${entry:.6f} | "
                  f"{held} bars | RSI={rsi:.1f}")

    # Closed trade log
    trade_log = state.get('trade_log', [])
    if trade_log:
        print(f"\n  Trade Log ({len(trade_log)} closed):")
        print(f"    {'Pair':<12} {'Entry':>9} {'Exit':>9} {'P&L':>8} "
              f"{'Bars':>4} {'Reason'}")
        print(f"    {'─'*12} {'─'*9} {'─'*9} {'─'*8} {'─'*4} {'─'*16}")
        for t in trade_log[-20:]:  # last 20 trades
            emoji = '✅' if t.get('pnl', 0) > 0 else '❌'
            print(f"    {t.get('pair',''):<12} "
                  f"${t.get('entry_price',0):>8.5f} "
                  f"${t.get('exit_price',0):>8.5f} "
                  f"${t.get('pnl',0):>+7.2f} "
                  f"{t.get('bars_held',0):>4} "
                  f"{emoji} {t.get('exit_reason','')}")
        if len(trade_log) > 20:
            print(f"    ... ({len(trade_log) - 20} older trades hidden)")

    # Slippage summary
    slip_log = state.get('slippage_log', [])
    if slip_log:
        slips = [abs(s['bps']) for s in slip_log]
        avg_slip = sum(slips) / len(slips)
        max_slip = max(slips)
        print(f"\n  Slippage ({len(slip_log)} fills):")
        print(f"    Avg: {avg_slip:.1f}bps | Max: {max_slip:.1f}bps")
        # Warn if avg > 20bps
        if avg_slip > 20:
            print(f"    ⚠️  AVG SLIPPAGE > 20bps — execution quality concern")

    # Drift checks
    drift = state.get('drift_checks', [])
    if drift:
        last = drift[-1] if drift else {}
        print(f"\n  Last Reconciliation:")
        print(f"    {last.get('time', 'N/A')} — "
              f"{'✅ OK' if not last.get('mismatch') else '❌ MISMATCH'}")

    # Circuit breaker status
    cb = state.get('circuit_breaker')
    if cb:
        print(f"\n  🚨 CIRCUIT BREAKER: {cb}")
        print(f"  Reasons: {state.get('circuit_breaker_reasons', [])}")

    # Alerts
    alerts = state.get('alerts', [])
    if alerts:
        print(f"\n  Alerts ({len(alerts)}):")
        for a in alerts[-5:]:
            print(f"    {a}")

    print(f"\n{'='*60}\n")


# ─── Dashboard Export ───────────────────────────────────────

def export_dashboard(state: dict, config: StrategyConfig, is_live: bool):
    mode = 'live' if is_live else 'paper'
    dashboard_file = BASE_DIR / f'dashboard_{config.name}_{mode}.json'

    closed = state.get('closed_trades', 0)
    gw = state.get('gross_wins', 0)
    gl = abs(state.get('gross_losses', 0))

    dashboard = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'strategy': config.name,
        'mode': mode,
        'config': {
            'timeframe': config.timeframe,
            'fee_bps': config.fee_rate * 10000,
            'capital_per_trade': config.capital_per_trade,
            'max_positions': config.max_positions,
            'min_volume_24h': config.min_volume_24h,
        },
        'baseline': config.baseline,
        'metrics': {
            'equity': round(state.get('equity', 0), 2),
            'pnl': round(state.get('total_pnl', 0), 2),
            'trades': closed,
            'wins': state.get('wins', 0),
            'losses': state.get('losses', 0),
            'win_rate': round(state.get('rolling_wr', 0), 1),
            'profit_factor': round(gw / gl if gl > 0 else 0, 2),
            'dd_current': round(state.get('dd_current', 0) * 100, 1),
            'dd_max': round(state.get('dd_max', 0) * 100, 1),
        },
        'positions': state.get('positions', {}),
        'circuit_breaker': state.get('circuit_breaker'),
        'drift_checks': state.get('drift_checks', []),
        'alerts': state.get('alerts', [])[-20:],
        'last_trades': state.get('trade_log', [])[-10:],
    }

    with open(dashboard_file, 'w') as f:
        json.dump(dashboard, f, indent=2, default=str)


# ─── Main Loop ──────────────────────────────────────────────

def run(client, coins: List[str], config: StrategyConfig,
        executor: OrderExecutor, circuit: CircuitBreaker,
        tg: TelegramBridge, logger,
        duration_hours: Optional[int] = None, dry_run: bool = False,
        is_live: bool = False):
    """Main trading loop."""
    global _shutdown_requested

    state_file = get_state_file(config, is_live)
    state = load_state(state_file, config)

    if state['checks'] == 0:
        state = new_state(config)
        logger.info("Fresh start -- new state created")

    mode_str = 'LIVE' if is_live else 'PAPER'
    logger.info(f"Strategy: {config.name} | Mode: {mode_str}")
    logger.info(f"Coins: {len(coins)} | Capital: ${config.capital_per_trade}/trade | "
                f"Max pos: {config.max_positions}")

    if duration_hours:
        end_time = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        logger.info(f"Running until {end_time.strftime('%Y-%m-%d %H:%M UTC')} ({duration_hours}h)")
    else:
        end_time = None
        logger.info("Running indefinitely (Ctrl+C or SIGTERM to stop)")

    # Startup notification
    tg.send(
        f"🚀 {config.name} Trader Started ({mode_str})\n"
        f"Coins: {len(coins)} | Equity: ${state['equity']:.2f}\n"
        f"Capital: ${config.capital_per_trade}/trade | Max: {config.max_positions} pos"
    )

    iteration = 0
    while not _shutdown_requested:
        if end_time and datetime.now(timezone.utc) >= end_time:
            logger.info("End time reached!")
            break

        if dry_run and iteration > 0:
            logger.info("Dry run -- one check completed, exiting")
            break

        now = datetime.now(timezone.utc)

        if iteration > 0:
            # Wait for next candle close + 2 min buffer
            interval_h = config.timeframe_minutes // 60
            next_check = now.replace(minute=2, second=0, microsecond=0)
            next_hour = ((now.hour // interval_h) + 1) * interval_h
            if next_hour >= 24:
                next_check = next_check.replace(hour=0) + timedelta(days=1)
            else:
                next_check = next_check.replace(hour=next_hour)

            wait_seconds = max((next_check - now).total_seconds(), 60)
            logger.info(f"\nNext check: {next_check.strftime('%H:%M UTC')} "
                        f"(in {wait_seconds/60:.0f} min)")

            # Sleep in short intervals to check shutdown flag
            sleep_end = time.time() + wait_seconds
            while time.time() < sleep_end and not _shutdown_requested:
                time.sleep(min(30, sleep_end - time.time()))

            if _shutdown_requested:
                break

        # Process check
        check_time = datetime.now(timezone.utc)
        state = process_check(
            client, coins, state, config, executor, circuit,
            logger, check_time, is_live,
        )

        # INVARIANT: Atomic state save
        save_state(state, state_file)
        export_dashboard(state, config, is_live)

        # Telegram alerts
        recent_alerts = [
            a for a in state.get('alerts', [])
            if a.get('time', '') > (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        ]
        if recent_alerts:
            for a in recent_alerts:
                tg.send(f"[{a['severity']}] {a['type']}: {a['msg']}")

        # Status update every 6 checks (24h at 4H interval)
        if state['checks'] % 6 == 0:
            tg.send_status(state, config)

        iteration += 1

    # Final save
    logger.info("\nShutting down — saving state...")
    save_state(state, state_file)
    export_dashboard(state, config, is_live)
    print_report(state, config)
    tg.send_status(state, config)


# ─── Main ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Live Trader — Strategy-agnostic execution framework')
    parser.add_argument('--strategy', type=str, default='ms_018',
                        help='Strategy config name (default: ms_018)')
    parser.add_argument('--live', action='store_true',
                        help='Execute real orders on MEXC')
    parser.add_argument('--micro', action='store_true',
                        help='Smoke test: $50/trade')
    parser.add_argument('--hours', type=int, default=None,
                        help='Duration in hours (default: infinite)')
    parser.add_argument('--report', action='store_true',
                        help='Show report from existing state')
    parser.add_argument('--dry-run', action='store_true',
                        help='Run one check cycle then exit')
    parser.add_argument('--reset', action='store_true',
                        help='Reset state (fresh start)')
    parser.add_argument('--max-coins', type=int, default=300,
                        help='Max coins to scan (default: 300)')
    parser.add_argument('--coins-file', type=str, default=None,
                        help='File with coin whitelist (one pair per line, e.g. BTC/USDT)')
    args = parser.parse_args()

    # Load strategy
    config = load_strategy(args.strategy)

    # Micro mode override
    if args.micro:
        config.capital_per_trade = 50.0

    # Report mode
    if args.report:
        state_file = get_state_file(config, args.live)
        if state_file.exists():
            with open(state_file) as f:
                state = json.load(f)
            print_report(state, config)
        else:
            print(f"No state found at {state_file}")
        return

    logger = setup_logging(config.name)

    if args.reset:
        state_file = get_state_file(config, args.live)
        save_state(new_state(config), state_file)
        logger.info("State reset -- fresh start")

    # MEXC client
    mexc_key = os.getenv('MEXC_API_KEY', '')
    mexc_secret = os.getenv('MEXC_SECRET_KEY', '') or os.getenv('MEXC_SECRET', '')

    if not mexc_key or not mexc_secret:
        logger.error("MEXC_API_KEY or MEXC_SECRET not set in .env")
        sys.exit(1)

    from exchange_manager import MEXCExchangeClient
    client = MEXCExchangeClient(api_key=mexc_key, secret=mexc_secret)

    if not client.test_connection():
        logger.error("MEXC connection failed!")
        sys.exit(1)
    logger.info("MEXC connection OK")

    # Coin universe
    all_pairs = client.get_tradeable_pairs()

    if args.coins_file:
        coins_path = Path(args.coins_file)
        if not coins_path.exists():
            logger.error(f"Coins file not found: {coins_path}")
            sys.exit(1)
        whitelist = set()
        for line in coins_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                whitelist.add(line)
        coins = [p for p in all_pairs if p in whitelist]
        logger.info(f"Coins: {len(coins)} from whitelist ({coins_path.name}), "
                     f"{len(whitelist) - len(coins)} not found on exchange")
    else:
        coins = all_pairs[:args.max_coins]
        logger.info(f"Coins: {len(coins)} USDT pairs (top {args.max_coins})")

    # Build execution stack
    mode = 'live' if args.live else 'paper'
    executor = OrderExecutor(client, mode=mode, fee_rate=config.fee_rate)

    tg = TelegramBridge()
    circuit = CircuitBreaker(executor=executor, notifier=tg)

    logger.info(f"Mode: {mode.upper()} | Strategy: {config.name}")
    if args.micro:
        logger.info(f"MICRO MODE: $50/trade (smoke test)")

    # Run
    run(
        client=client,
        coins=coins,
        config=config,
        executor=executor,
        circuit=circuit,
        tg=tg,
        logger=logger,
        duration_hours=args.hours,
        dry_run=args.dry_run,
        is_live=args.live,
    )


if __name__ == '__main__':
    main()

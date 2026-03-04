#!/usr/bin/env python3
"""
Paper Trade — MEXC 1m Scalp FVG Fill (fvg_x2027)
===================================================================
Live paper trading for the verified FVG Fill scalp strategy (ADR-SCALP-002).

Signal: FVG Fill (MS-SB) — price retraces into bullish Fair Value Gap
  - max_fvg_age=25, fill_depth=0.75, rsi_max=40
  - ATR-based exits: tp=2.5×ATR, sl=0.75×ATR, time_limit=15 bars

Cost model: SPREAD ONLY (0% maker/taker fees on MEXC)
  - Live spread measured every cycle via get_ticker()
  - entry_fill = close × (1 + half_spread_bps/10000)
  - exit_fill  = exit_price × (1 - half_spread_bps/10000)

Sizing: Fixed $200/trade, max 1 position per pair (match backtest).

Backtest baseline (fvg_x2027 on 43K 1m bars): PF=1.769, 131 trades,
  bootstrap P5=1.254, 99.6% profitable, PF@P95_spread=1.348.

Usage:
    python paper_scalp_1m.py                       # Live (infinite)
    python paper_scalp_1m.py --hours 168           # Live for 7 days
    python paper_scalp_1m.py --report              # Show report
    python paper_scalp_1m.py --dry-run             # One check cycle then exit
    python paper_scalp_1m.py --pairs XRP/USDT,ETH/USDT  # Multi-pair
    python paper_scalp_1m.py --live --trade-size 25     # Real orders ($25/trade)
    python paper_scalp_1m.py --live --dry-run           # Smoke test (init only)
"""
import os
import sys
import json
import time
import signal
import logging
import argparse
from datetime import datetime, timedelta, timezone
from typing import Optional, List
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

# ─── Imports from scalp infra ────────────────────────────────
import importlib

_ms_ind = importlib.import_module('strategies.scalp.ms_indicators')
precompute_scalp_ms_indicators = _ms_ind.precompute_scalp_ms_indicators

_ms_hyp = importlib.import_module('strategies.scalp.ms_hypotheses')
signal_mssb = _ms_hyp.signal_mssb

# ─── Constants ──────────────────────────────────────────────
TAG = 'scalp_1m_paper'
STATE_FILE = BASE_DIR / f'paper_state_{TAG}.json'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# Polling
POLL_INTERVAL_SEC = 65            # 65s = safe margin after 1m candle close
MIN_CANDLES = 100                 # Warmup for structural indicators

# Cost model: SPREAD ONLY (0% maker/taker on MEXC)
DEFAULT_SPREAD_BPS = 1.5          # Fallback if ticker fails

# Sizing (match backtest exactly)
CAPITAL_PER_TRADE = 200.0
INITIAL_EQUITY = 2000.0
MAX_POSITIONS_PER_PAIR = 1

# Frozen fvg_x2027 params (from Phase 3 verification, ADR-SCALP-002)
ENTRY_PARAMS = {
    'max_fvg_age': 25,
    'fill_depth': 0.75,
    'rsi_max': 40,
    'tp_atr': 2.5,
    'sl_atr': 0.75,
    'time_limit': 15,
}

# Precompute params (match backtest exactly)
PRECOMPUTE_KWARGS = {
    'swing_left': 3,
    'swing_right': 1,
    'min_gap_atr': 0.3,
    'min_impulse_atr': 1.5,
    'lookback_impulse': 3,
    'tolerance_atr': 0.5,
    'min_touches': 2,
}

# Cooldown (match harness defaults)
COOLDOWN_BARS = 2
COOLDOWN_AFTER_STOP = 5

# Backtest baseline (drift detection)
BASELINE = {
    'pf': 1.769,
    'boot_p5_pf': 1.254,
    'pf_at_p95_spread': 1.348,
    'trades_30d': 131,
    'spread_bps_backtest': 1.5,
}

# Circuit breaker thresholds
CB_DD_CEILING = 0.25              # Halt if DD > 25%
CB_PF_FLOOR = 1.0                 # Halt if PF < 1.0 after 30+ trades
CB_CONSEC_LOSS = 8                # Halt after 8 consecutive losses


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
    return logging.getLogger('paper_scalp_1m')


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
        'checks': 0,
        'dd_current': 0.0,
        'dd_max': 0.0,
        'exit_types': {},
        'trade_log': [],
        'spread_log': [],
        'last_exit_time': {},
        'last_exit_was_stop': {},
        'consecutive_losses': 0,
        'max_consecutive_losses': 0,
        'alerts': [],
        'drift_checks': [],
        'circuit_breaker_hit': False,
        'last_candle_time': {},
        # Live mode state
        'live_mode': False,
        'live_trade_size': 0.0,
        'live_total_pnl': 0.0,
        'live_trades': 0,
        'slippage_log': [],
    }


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return new_state()


def save_state(state: dict):
    """Atomic write: .tmp → os.replace() to prevent partial writes."""
    tmp = STATE_FILE.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, STATE_FILE)


# ─── Drawdown Helpers ───────────────────────────────────────

def get_current_dd(state: dict) -> float:
    """Current drawdown as fraction (0.0 = no DD, 1.0 = -100%)."""
    equity = state['equity']
    peak = state['peak_equity']
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - equity) / peak)


# ─── Live Spread Measurement ────────────────────────────────

def measure_spread(mexc_client, pair: str, logger) -> float:
    """Measure live half-spread in bps via get_ticker().

    Returns half-spread per side (= cost per side in the spread-only model).
    Fallback to DEFAULT_SPREAD_BPS on error.
    """
    try:
        ticker = mexc_client.get_ticker(pair)
        if not ticker or ticker['bid'] <= 0 or ticker['ask'] <= 0:
            logger.debug(f"  Ticker unavailable for {pair}, using default spread")
            return DEFAULT_SPREAD_BPS

        mid = (ticker['bid'] + ticker['ask']) / 2.0
        half_spread_bps = (ticker['ask'] - ticker['bid']) / mid * 10000 / 2.0
        return max(half_spread_bps, 0.01)  # Floor at 0.01 bps
    except Exception as e:
        logger.debug(f"  Spread measurement error {pair}: {e}")
        return DEFAULT_SPREAD_BPS


# ─── Candle Validation ──────────────────────────────────────

def validate_candle_continuity(candles: list, logger) -> int:
    """Check for gaps in 1m candle timestamps. Returns gap count."""
    gaps = 0
    for i in range(1, len(candles)):
        dt = candles[i]['time'] - candles[i - 1]['time']
        if dt != 60:
            gaps += 1
            if gaps <= 3:
                logger.warning(
                    f"  Candle gap: {dt}s between idx {i - 1} "
                    f"(t={candles[i - 1]['time']}) and {i} (t={candles[i]['time']})"
                )
    if gaps > 3:
        logger.warning(f"  Total candle gaps: {gaps}")
    return gaps


# ─── Indicator Computation ──────────────────────────────────

def compute_indicators(pair: str, candles: list) -> Optional[dict]:
    """Compute all indicators for one pair using precompute_scalp_ms_indicators."""
    n = len(candles)
    if n < MIN_CANDLES:
        return None

    data = {pair: candles}
    try:
        result = precompute_scalp_ms_indicators(data, [pair], **PRECOMPUTE_KWARGS)
        return result.get(pair)
    except Exception:
        return None


# ─── Exit Logic — EXACT Harness Replication ──────────────────
# Replicates strategies/scalp/harness.py lines 113-188 EXACTLY.
# Exit priority: trailing update → stop → target → time (if/elif chain).
# Spread applied on ALL exit types.

def _update_trailing_stop(pos: dict, high: float, cur_atr: float):
    """Update trailing stop: breakeven + trail. (harness.py lines 113-138)"""
    pos['highest_since_entry'] = max(pos.get('highest_since_entry', pos['entry_fill']), high)

    be_atr = pos.get('breakeven_atr')
    trail_atr = pos.get('trail_atr')
    if be_atr is None and trail_atr is None:
        return  # No trailing stop configured

    if cur_atr is None or cur_atr <= 0:
        return

    # Breakeven: move stop to entry after X ATR profit
    if be_atr and not pos.get('breakeven_hit', False):
        profit = pos['highest_since_entry'] - pos['entry_fill']
        if profit >= be_atr * cur_atr:
            pos['stop_price'] = pos['entry_fill']
            pos['breakeven_hit'] = True

    # Trail: after breakeven, trail stop at Y ATR below highest
    if pos.get('breakeven_hit', False) and trail_atr:
        trail_stop = pos['highest_since_entry'] - trail_atr * cur_atr
        if trail_stop > pos['stop_price']:
            pos['stop_price'] = trail_stop


def check_exit(pos: dict, candle: dict, cur_atr: float, spread_bps: float) -> Optional[dict]:
    """Check exit conditions for one position.

    Returns trade_record dict if exited, None otherwise.

    Exit priority (identical to harness.py lines 140-188):
      1. Stop loss: low <= stop_price → STOP or TRAIL
      2. Target:    high >= target_price → TARGET
      3. Time:      bars_held >= time_limit → TIME

    Spread applied on exit: fill_price = exit_price × (1 - spread_fraction)
    """
    spread_fraction = spread_bps / 10000.0
    low = candle['low']
    high = candle['high']
    close = candle['close']
    current_time = candle['time']

    # bars_held via timestamps (Gap 4 fix)
    bars_held = (current_time - pos['entry_candle_time']) // 60

    exit_price = None
    exit_type = None

    # Check stop loss (harness.py line 148)
    if pos['stop_price'] and low <= pos['stop_price']:
        exit_price = pos['stop_price']
        exit_type = 'TRAIL' if pos.get('breakeven_hit', False) else 'STOP'

    # Check target (harness.py line 153 — elif!)
    elif pos['target_price'] and high >= pos['target_price']:
        exit_price = pos['target_price']
        exit_type = 'TARGET'

    # Check time limit (harness.py line 158 — elif, >=)
    elif pos.get('time_limit') and bars_held >= pos['time_limit']:
        exit_price = close
        exit_type = 'TIME'

    if exit_price is None:
        return None

    # Apply spread cost on exit (harness.py line 164)
    fill_price = exit_price * (1 - spread_fraction)
    pnl = (fill_price - pos['entry_fill']) * pos['qty']

    return {
        'pnl': round(pnl, 4),
        'bars_held': int(bars_held),
        'exit_type': exit_type,
        'entry_price': pos['entry_price'],
        'exit_price': exit_price,
        'entry_time': pos['entry_candle_time'],
        'exit_time': current_time,
        'spread_bps': round(spread_bps, 2),
    }


# ─── Core Paper Trading Engine ──────────────────────────────

def process_check(
    mexc_client,
    pairs: List[str],
    state: dict,
    logger,
    executor=None,
    live_trade_size: float = 25.0,
    dry_run: bool = False,
) -> dict:
    """Process one polling cycle across all pairs.

    Phase 1: Fetch candles, detect new candle, measure spread.
    Phase 2: Process exits for open positions (+ live sell mirror).
    Phase 3: Process entries (new signals) (+ live buy mirror).

    Returns updated state.
    """
    state['checks'] += 1
    check_time = datetime.now(timezone.utc)
    check_str = check_time.strftime('%Y-%m-%d %H:%M:%S UTC')

    dd = get_current_dd(state)
    n_open = len(state['positions'])
    logger.info(f"\n{'=' * 60}")
    logger.info(f"CHECK #{state['checks']} -- {check_str}")
    logger.info(f"Equity: ${state['equity']:.2f} | DD: {dd * 100:.1f}% | "
                f"Open: {n_open} | Trades: {state['closed_trades']}")
    logger.info(f"{'=' * 60}")

    for pair in pairs:
        # ─── Phase 1: Fetch candles + detect new candle ──────
        try:
            candles = mexc_client.get_ohlc(pair, interval=1)
        except Exception as e:
            logger.warning(f"  [{pair}] API error: {e}")
            continue

        if not candles or len(candles) < MIN_CANDLES:
            logger.debug(f"  [{pair}] Insufficient candles: {len(candles) if candles else 0}")
            continue

        last_time = candles[-1]['time']
        prev_time = state['last_candle_time'].get(pair, 0)

        if last_time == prev_time:
            logger.debug(f"  [{pair}] No new candle (t={last_time})")
            continue

        state['last_candle_time'][pair] = last_time

        # Validate candle continuity (first check only, or every 60 checks)
        if state['checks'] <= 1 or state['checks'] % 60 == 0:
            validate_candle_continuity(candles, logger)

        # Measure live spread
        spread_bps = measure_spread(mexc_client, pair, logger)

        # Log spread (keep last 100)
        state['spread_log'].append({
            'time': last_time,
            'pair': pair,
            'spread_bps': round(spread_bps, 2),
        })
        if len(state['spread_log']) > 100:
            state['spread_log'] = state['spread_log'][-100:]

        # Compute indicators
        indicators = compute_indicators(pair, candles)
        if indicators is None:
            logger.warning(f"  [{pair}] Indicator computation failed")
            continue

        bar = indicators['n'] - 1
        cur_atr = indicators['atr14'][bar]
        if cur_atr is None or cur_atr <= 0:
            logger.debug(f"  [{pair}] ATR is None at bar {bar}")
            continue

        # ─── Phase 2: Process exits ──────────────────────────
        if pair in state['positions']:
            pos = state['positions'][pair]

            # Retry failed live sell FIRST (before normal exit check)
            if executor and pos.get('live_sell_failed') and not dry_run:
                result = executor.sell(pair, pos['live_qty'], candles[-1]['close'])
                if result.filled:
                    live_pnl = (result.fill_price - pos['live_fill_price']) * pos['live_qty']
                    state['live_total_pnl'] += live_pnl
                    state['live_trades'] += 1
                    logger.info(
                        f"  LIVE SELL RETRY OK {pair}: fill=${result.fill_price:.6f} "
                        f"pnl=${live_pnl:+.4f}"
                    )
                    pos['live_sell_failed'] = False
                    pos['live_status'] = 'closed'
                    # Paper exit already recorded — remove position
                    del state['positions'][pair]
                    save_state(state)
                    continue
                else:
                    retries = pos.get('live_sell_retries', 0) + 1
                    pos['live_sell_retries'] = retries
                    logger.error(f"  LIVE SELL RETRY FAILED {pair} (attempt {retries})")
                    if retries >= 3:
                        logger.critical(f"  LIVE SELL FAILED 3x {pair}: MANUAL CLOSE REQUIRED")
                        tg = _get_tg()
                        if tg:
                            try:
                                tg.send(
                                    f"🚨 LIVE SELL FAILED 3x\n"
                                    f"Pair: {pair}\nQty: {pos.get('live_qty', 0):.6f}\n"
                                    f"MANUAL CLOSE REQUIRED"
                                )
                            except Exception:
                                pass
                    continue  # Don't process normal exit, keep retrying

            # Update trailing stop (harness.py lines 113-138)
            _update_trailing_stop(pos, candles[-1]['high'], cur_atr)

            # Check exit conditions
            trade_rec = check_exit(pos, candles[-1], cur_atr, spread_bps)

            if trade_rec is not None:
                net_pnl = trade_rec['pnl']

                # Update state
                state['equity'] += net_pnl
                state['total_pnl'] += net_pnl
                state['closed_trades'] += 1

                if net_pnl >= 0:
                    state['wins'] += 1
                    state['gross_wins'] += net_pnl
                    state['consecutive_losses'] = 0
                else:
                    state['losses'] += 1
                    state['gross_losses'] += net_pnl
                    state['consecutive_losses'] += 1
                    state['max_consecutive_losses'] = max(
                        state['max_consecutive_losses'],
                        state['consecutive_losses'],
                    )

                # Update peak equity and DD
                if state['equity'] > state['peak_equity']:
                    state['peak_equity'] = state['equity']
                new_dd = get_current_dd(state)
                state['dd_current'] = new_dd
                state['dd_max'] = max(state['dd_max'], new_dd)

                # Exit type tracking
                et = trade_rec['exit_type']
                if et not in state['exit_types']:
                    state['exit_types'][et] = {'count': 0, 'pnl': 0.0, 'wins': 0}
                state['exit_types'][et]['count'] += 1
                state['exit_types'][et]['pnl'] += net_pnl
                if net_pnl > 0:
                    state['exit_types'][et]['wins'] += 1

                # Cooldown tracking (Gap 1 fix: timestamps)
                state['last_exit_time'][pair] = last_time
                state['last_exit_was_stop'][pair] = (et == 'STOP')

                # Trade log
                trade_rec['pair'] = pair
                trade_rec['nr'] = state['closed_trades']
                trade_rec['equity_after'] = round(state['equity'], 2)
                state['trade_log'].append(trade_rec)

                pnl_pct = net_pnl / pos['size_usd'] * 100
                logger.info(
                    f"  {'WIN' if net_pnl >= 0 else 'LOSS'} EXIT {pair} [{et}] "
                    f"${candles[-1]['close']:.6f} | P&L=${net_pnl:+.4f} ({pnl_pct:+.1f}%) "
                    f"| {trade_rec['bars_held']}bars | Spread={spread_bps:.1f}bps "
                    f"| Eq=${state['equity']:.2f}"
                )

                # ─── Live exit mirror ──────────────────────
                if executor and pos.get('live_status') == 'open' and not dry_run:
                    result = executor.sell(pair, pos['live_qty'], trade_rec['exit_price'])
                    if result.filled:
                        live_pnl = (result.fill_price - pos['live_fill_price']) * pos['live_qty']
                        trade_rec['live_fill_price'] = result.fill_price
                        trade_rec['live_pnl'] = round(live_pnl, 6)
                        trade_rec['live_slippage_bps'] = result.slippage_bps
                        state['live_total_pnl'] += live_pnl
                        state['live_trades'] += 1
                        state.setdefault('slippage_log', []).append({
                            'pair': pair, 'side': 'sell',
                            'expected': trade_rec['exit_price'],
                            'actual': result.fill_price,
                            'bps': result.slippage_bps,
                            'time': datetime.now(timezone.utc).isoformat(),
                        })
                        logger.info(
                            f"  LIVE SELL {pair}: fill=${result.fill_price:.6f} "
                            f"pnl=${live_pnl:+.4f} slip={result.slippage_bps:+.1f}bps"
                        )
                    else:
                        # Sell failed — retry logic
                        retries = pos.get('live_sell_retries', 0) + 1
                        pos['live_sell_failed'] = True
                        pos['live_sell_retries'] = retries
                        logger.error(
                            f"  LIVE SELL FAILED {pair} (attempt {retries}): "
                            f"{result.error}"
                        )
                        if retries >= 3:
                            logger.critical(
                                f"  LIVE SELL FAILED 3x {pair}: MANUAL CLOSE REQUIRED"
                            )
                            tg = _get_tg()
                            if tg:
                                try:
                                    tg.send(
                                        f"🚨 LIVE SELL FAILED 3x\n"
                                        f"Pair: {pair}\n"
                                        f"Qty: {pos.get('live_qty', 0):.6f}\n"
                                        f"MANUAL CLOSE REQUIRED"
                                    )
                                except Exception:
                                    pass
                        # DON'T remove position — retry next cycle
                        save_state(state)
                        continue  # Skip position removal

                # Telegram exit notification
                _tg_exit(pair, trade_rec, state, spread_bps, logger)

                # Remove position
                del state['positions'][pair]

        # ─── Phase 3: Process entries ────────────────────────
        if pair in state['positions']:
            continue  # Already have position in this pair

        if state.get('circuit_breaker_hit', False):
            continue  # Circuit breaker: no new entries

        # Cooldown check (Gap 1 fix: timestamp-based)
        last_exit_t = state['last_exit_time'].get(pair, 0)
        was_stop = state['last_exit_was_stop'].get(pair, False)
        cd_bars = COOLDOWN_AFTER_STOP if was_stop else COOLDOWN_BARS
        bars_since_exit = (last_time - last_exit_t) // 60 if last_exit_t > 0 else 9999
        if bars_since_exit < cd_bars:
            continue

        # Equity check
        if state['equity'] < CAPITAL_PER_TRADE * 0.5:
            continue

        # Run signal function
        try:
            sig = signal_mssb(candles, bar, indicators, ENTRY_PARAMS)
        except Exception as e:
            logger.debug(f"  [{pair}] Signal error: {e}")
            continue

        if sig is None:
            continue

        # Entry fill: apply spread cost (harness.py line 208)
        entry_price = candles[-1]['close']
        spread_fraction = spread_bps / 10000.0
        entry_fill = entry_price * (1 + spread_fraction)
        qty = CAPITAL_PER_TRADE / entry_fill

        state['total_trades'] += 1
        state['positions'][pair] = {
            'pair': pair,
            'entry_price': entry_price,
            'entry_fill': entry_fill,
            'entry_candle_time': last_time,
            'entry_time': check_str,
            'stop_price': sig['stop_price'],
            'target_price': sig['target_price'],
            'time_limit': sig.get('time_limit'),
            'qty': qty,
            'size_usd': CAPITAL_PER_TRADE,
            'spread_at_entry': spread_bps,
            'strength': sig.get('strength', 0),
            'trade_nr': state['total_trades'],
            # Trailing stop state (Gap 2 fix: persisted)
            'highest_since_entry': entry_fill,
            'breakeven_hit': False,
            'breakeven_atr': sig.get('breakeven_atr'),
            'trail_atr': sig.get('trail_atr'),
        }

        rsi_val = indicators['rsi14'][bar] if indicators['rsi14'][bar] is not None else 0
        logger.info(
            f"  ENTRY {pair} @ ${entry_price:.6f} (fill=${entry_fill:.6f}) | "
            f"RSI={rsi_val:.1f} | Str={sig.get('strength', 0):.2f} | "
            f"Spread={spread_bps:.1f}bps | ${CAPITAL_PER_TRADE:.0f}"
        )

        # Telegram entry notification
        _tg_entry(pair, entry_price, spread_bps, rsi_val, sig, state, logger)

        # ─── Live entry mirror ──────────────────────
        if executor and not dry_run:
            pos = state['positions'][pair]
            pos['live_status'] = 'pending'
            pos['live_trade_size'] = live_trade_size
            save_state(state)  # Pre-write marker for crash recovery

            result = executor.buy(pair, live_trade_size, entry_price)
            if result.filled:
                pos['live_fill_price'] = result.fill_price
                pos['live_qty'] = result.fill_qty
                pos['live_order_id'] = result.order_id
                pos['live_status'] = 'open'
                pos['live_slippage_bps'] = result.slippage_bps
                state.setdefault('slippage_log', []).append({
                    'pair': pair, 'side': 'buy',
                    'expected': entry_price,
                    'actual': result.fill_price,
                    'bps': result.slippage_bps,
                    'time': datetime.now(timezone.utc).isoformat(),
                })
                logger.info(
                    f"  LIVE BUY {pair}: fill=${result.fill_price:.6f} "
                    f"qty={result.fill_qty:.6f} slip={result.slippage_bps:+.1f}bps"
                )
            else:
                pos['live_status'] = 'failed'
                logger.warning(
                    f"  LIVE BUY FAILED {pair}: {result.error} "
                    f"— paper entry stands, no live position"
                )

    # ─── Circuit Breaker + Drift Detection ───────────────────
    alerts = _update_metrics_and_check_circuit_breaker(state)
    if alerts:
        for a in alerts:
            logger.warning(f"  ALERT [{a['severity']}] {a['type']}: {a['msg']}")
        _tg_alerts(alerts, state, logger)

    return state


# ─── Circuit Breaker & Drift Detection ──────────────────────

def _update_metrics_and_check_circuit_breaker(state: dict) -> list:
    """Update rolling metrics and check circuit breaker / drift conditions."""
    closed = state['closed_trades']
    if closed == 0:
        return []

    gw = state['gross_wins']
    gl = abs(state['gross_losses'])
    rolling_pf = gw / gl if gl > 0 else 99.0

    alerts = []

    # ─── Circuit Breaker (CRITICAL = halt new entries) ───────

    # R1: PF < 1.0 after 30+ trades
    if closed >= 30 and rolling_pf < CB_PF_FLOOR:
        state['circuit_breaker_hit'] = True
        alerts.append({
            'type': 'CB_PF',
            'severity': 'CRITICAL',
            'msg': f"PF={rolling_pf:.2f} < {CB_PF_FLOOR} after {closed} trades — HALTING entries",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # R2: DD > ceiling
    if state['dd_max'] >= CB_DD_CEILING:
        state['circuit_breaker_hit'] = True
        alerts.append({
            'type': 'CB_DD',
            'severity': 'CRITICAL',
            'msg': f"Max DD={state['dd_max'] * 100:.1f}% >= {CB_DD_CEILING * 100:.0f}% — HALTING entries",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # R3: Consecutive losses
    if state['consecutive_losses'] >= CB_CONSEC_LOSS:
        state['circuit_breaker_hit'] = True
        alerts.append({
            'type': 'CB_CONSEC',
            'severity': 'CRITICAL',
            'msg': f"{state['consecutive_losses']} consecutive losses >= {CB_CONSEC_LOSS} — HALTING entries",
            'time': datetime.now(timezone.utc).isoformat(),
        })
    elif state['consecutive_losses'] >= 5:
        alerts.append({
            'type': 'CONSEC_WARN',
            'severity': 'WARNING',
            'msg': f"{state['consecutive_losses']} consecutive losses",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # ─── Drift Detection (WARNING only) ─────────────────────

    # D1: PF below P5 baseline after 50+ trades
    if closed >= 50 and rolling_pf < BASELINE['boot_p5_pf']:
        alerts.append({
            'type': 'DRIFT_PF',
            'severity': 'WARNING',
            'msg': f"PF={rolling_pf:.2f} below P5 baseline ({BASELINE['boot_p5_pf']}) after {closed} trades",
            'time': datetime.now(timezone.utc).isoformat(),
        })

    # D2: Spread drift — warn if avg live spread > P95 backtest spread
    recent_spreads = [s['spread_bps'] for s in state.get('spread_log', [])[-50:]]
    if len(recent_spreads) >= 20:
        avg_spread = sum(recent_spreads) / len(recent_spreads)
        if avg_spread > 2.97:  # P95 spread from Phase 0
            alerts.append({
                'type': 'DRIFT_SPREAD',
                'severity': 'WARNING',
                'msg': f"Avg live spread={avg_spread:.2f}bps > P95 historical (2.97bps)",
                'time': datetime.now(timezone.utc).isoformat(),
            })

    # Periodic drift checkpoint (every 25 trades)
    if closed > 0 and closed % 25 == 0:
        wr = state['wins'] / closed * 100 if closed > 0 else 0
        checkpoint = {
            'trades': closed,
            'pf': round(rolling_pf, 2),
            'wr': round(wr, 1),
            'dd_max': round(state['dd_max'] * 100, 1),
            'equity': round(state['equity'], 2),
            'time': datetime.now(timezone.utc).isoformat(),
        }
        state.setdefault('drift_checks', []).append(checkpoint)

    if alerts:
        state['alerts'].extend(alerts)
        # Keep alerts trimmed
        if len(state['alerts']) > 200:
            state['alerts'] = state['alerts'][-200:]

    return alerts


# ─── Telegram Integration ───────────────────────────────────

def _get_tg():
    """Get TelegramNotifier instance. Returns None if unavailable."""
    try:
        from telegram_notifier import TelegramNotifier
        return TelegramNotifier()
    except Exception:
        return None


def _tg_entry(pair, price, spread_bps, rsi, sig, state, logger):
    """Send Telegram notification for new entry."""
    tg = _get_tg()
    if not tg:
        return
    try:
        msg = (
            f"Scalp 1m ENTRY\n"
            f"Pair: {pair}\n"
            f"Price: ${price:.6f}\n"
            f"Spread: {spread_bps:.1f}bps\n"
            f"RSI: {rsi:.1f}\n"
            f"Strength: {sig.get('strength', 0):.2f}\n"
            f"Equity: ${state['equity']:.2f}"
        )
        tg.send(msg)
    except Exception as e:
        logger.debug(f"  TG entry notification failed: {e}")


def _tg_exit(pair, trade_rec, state, spread_bps, logger):
    """Send Telegram notification for exit."""
    tg = _get_tg()
    if not tg:
        return
    try:
        pnl = trade_rec['pnl']
        icon = '+' if pnl >= 0 else ''
        msg = (
            f"Scalp 1m EXIT [{trade_rec['exit_type']}]\n"
            f"Pair: {pair}\n"
            f"P&L: ${icon}{pnl:.4f}\n"
            f"Bars held: {trade_rec['bars_held']}\n"
            f"Spread: {spread_bps:.1f}bps\n"
            f"Equity: ${state['equity']:.2f}\n"
            f"Trades: {state['closed_trades']} (W:{state['wins']} L:{state['losses']})"
        )
        tg.send(msg)
    except Exception as e:
        logger.debug(f"  TG exit notification failed: {e}")


def _tg_alerts(alerts, state, logger):
    """Send Telegram notifications for alerts."""
    tg = _get_tg()
    if not tg:
        return
    try:
        for alert in alerts:
            icon = '🚨' if alert['severity'] == 'CRITICAL' else '⚠️'
            msg = (
                f"{icon} Scalp 1m Alert\n"
                f"Type: {alert['type']}\n"
                f"Severity: {alert['severity']}\n"
                f"{alert['msg']}\n\n"
                f"Equity: ${state['equity']:.2f} | DD: {state['dd_current'] * 100:.1f}%"
            )
            tg.send(msg)
    except Exception as e:
        logger.debug(f"  TG alert notification failed: {e}")


def _tg_status(state, logger):
    """Send periodic status update via Telegram."""
    tg = _get_tg()
    if not tg:
        return
    try:
        closed = state['closed_trades']
        gw = state['gross_wins']
        gl = abs(state['gross_losses'])
        pf = gw / gl if gl > 0 else 0
        wr = (state['wins'] / closed * 100) if closed > 0 else 0

        recent_spreads = [s['spread_bps'] for s in state.get('spread_log', [])[-50:]]
        avg_spread = sum(recent_spreads) / len(recent_spreads) if recent_spreads else 0

        msg = (
            f"Scalp 1m Status (MEXC)\n"
            f"Check #{state['checks']} | {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n\n"
            f"Equity: ${state['equity']:.2f}\n"
            f"P&L: ${state['total_pnl']:+.2f}\n"
            f"DD: {state['dd_current'] * 100:.1f}% (max {state['dd_max'] * 100:.1f}%)\n"
            f"Trades: {closed} (W:{state['wins']} L:{state['losses']})\n"
            f"PF: {pf:.2f} | WR: {wr:.1f}%\n"
            f"Avg spread: {avg_spread:.1f}bps\n"
            f"Open: {len(state['positions'])}\n"
        )

        if state['positions']:
            msg += "\nOpen:\n"
            for pair, pos in state['positions'].items():
                bars_held = 'N/A'
                if 'entry_candle_time' in pos:
                    last_t = state['last_candle_time'].get(pair, pos['entry_candle_time'])
                    bars_held = (last_t - pos['entry_candle_time']) // 60
                msg += f"  {pair} @ ${pos['entry_price']:.6f} ({bars_held} bars)\n"

        if state['exit_types']:
            msg += "\nExit types:\n"
            for et, d in state['exit_types'].items():
                msg += f"  {et}: {d['count']}x ${d['pnl']:+.4f}\n"

        cb = state.get('circuit_breaker_hit', False)
        if cb:
            msg += "\n🚨 CIRCUIT BREAKER ACTIVE — no new entries\n"

        tg.send(msg)
    except Exception as e:
        logger.debug(f"  TG status failed: {e}")


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

    recent_spreads = [s['spread_bps'] for s in state.get('spread_log', [])[-50:]]
    avg_spread = sum(recent_spreads) / len(recent_spreads) if recent_spreads else 0

    print(f"\n{'=' * 60}")
    print(f"  PAPER TRADING -- MEXC 1m Scalp FVG Fill (fvg_x2027)")
    print(f"{'=' * 60}")
    print(f"  Signal:          FVG Fill (max_fvg_age=25, fill_depth=0.75, rsi_max=40)")
    print(f"  Exits:           ATR-based (tp=2.5, sl=0.75, tl=15)")
    print(f"  Cost:            Spread-only (0% fees)")
    print(f"  Capital/trade:   ${CAPITAL_PER_TRADE:.0f}")
    print(f"  Started:         {state.get('start_time', 'N/A')}")
    print(f"  Checks:          {state.get('checks', 0)}")
    print(f"  Avg spread:      {avg_spread:.1f}bps")
    print(f"{'=' * 60}")
    print(f"  RESULTS")
    print(f"{'=' * 60}")
    print(f"  Equity:          ${state.get('equity', 0):.2f}")
    print(f"  Total P&L:       ${pnl:+.4f}")
    print(f"  Trades:          {closed} (W:{wins} L:{losses})")
    print(f"  Win rate:        {wr:.1f}%")
    print(f"  Profit Factor:   {pf:.2f}")
    print(f"  Avg P&L/trade:   ${avg:+.4f}")
    print(f"  Max DD:          {state.get('dd_max', 0) * 100:.1f}%")
    print(f"  Current DD:      {state.get('dd_current', 0) * 100:.1f}%")
    print(f"  Consec. losses:  {state.get('max_consecutive_losses', 0)} (max)")
    print(f"  Circuit breaker: {'ACTIVE' if state.get('circuit_breaker_hit') else 'OK'}")
    print(f"{'=' * 60}")

    # Live execution section (if live mode was active)
    if state.get('live_mode'):
        live_trades = state.get('live_trades', 0)
        live_pnl = state.get('live_total_pnl', 0)
        live_size = state.get('live_trade_size', 0)
        slips = state.get('slippage_log', [])
        buy_slips = [s['bps'] for s in slips if s.get('side') == 'buy']
        sell_slips = [s['bps'] for s in slips if s.get('side') == 'sell']
        avg_buy_slip = sum(buy_slips) / len(buy_slips) if buy_slips else 0
        avg_sell_slip = sum(sell_slips) / len(sell_slips) if sell_slips else 0
        paper_pnl = state.get('total_pnl', 0)
        gap_pct = ((paper_pnl - live_pnl) / abs(paper_pnl) * 100) if paper_pnl != 0 else 0

        print(f"  LIVE EXECUTION (real fills)")
        print(f"{'=' * 60}")
        print(f"  Trade size:      ${live_size:.2f}")
        print(f"  Live trades:     {live_trades}")
        print(f"  Live P&L:        ${live_pnl:+.4f}")
        print(f"  Avg slippage:    {avg_buy_slip:+.1f} bps (entry) / {avg_sell_slip:+.1f} bps (exit)")
        print(f"  Paper vs Live:   paper=${paper_pnl:+.4f} live=${live_pnl:+.4f} (gap: {gap_pct:.0f}%)")
        print(f"{'=' * 60}")

    # Baseline comparison
    print(f"  DRIFT DETECTION (vs backtest baseline)")
    print(f"{'=' * 60}")
    print(f"  Backtest PF:     {BASELINE['pf']} (P5={BASELINE['boot_p5_pf']}) @ {BASELINE['spread_bps_backtest']}bps")
    print(f"  Live PF:         {pf:.2f} {'OK' if pf >= BASELINE['boot_p5_pf'] else 'BELOW P5'}")
    print(f"  Live spread:     {avg_spread:.1f}bps (backtest {BASELINE['spread_bps_backtest']}bps)")
    drift = state.get('drift_checks', [])
    if drift:
        print(f"  Checkpoints:     {len(drift)}")
        for dc in drift[-5:]:
            print(f"    @{dc['trades']}t: PF={dc['pf']} WR={dc['wr']}% DD={dc['dd_max']}%")
    print(f"{'=' * 60}")

    # Exit attribution
    exit_types = state.get('exit_types', {})
    if exit_types:
        print(f"  EXIT TYPES")
        print(f"{'=' * 60}")
        for et, d in exit_types.items():
            wr_r = d['wins'] / d['count'] * 100 if d['count'] > 0 else 0
            print(f"    {et}: {d['count']}x | ${d['pnl']:+.4f} | WR {wr_r:.0f}%")
        print(f"{'=' * 60}")

    # Open positions
    positions = state.get('positions', {})
    if positions:
        print(f"  OPEN POSITIONS ({len(positions)})")
        print(f"{'=' * 60}")
        for pair, pos in positions.items():
            bars = 'N/A'
            if 'entry_candle_time' in pos:
                last_t = state['last_candle_time'].get(pair, pos['entry_candle_time'])
                bars = (last_t - pos['entry_candle_time']) // 60
            print(f"    {pair}: ${pos['entry_price']:.6f} | ${pos['size_usd']:.0f} | {bars} bars")
        print(f"{'=' * 60}")

    # Alerts
    alerts = state.get('alerts', [])
    if alerts:
        print(f"\n  ALERTS ({len(alerts)})")
        for a in alerts[-10:]:
            print(f"    [{a['severity']}] {a['type']}: {a['msg']}")

    # Recent trades
    trade_log = state.get('trade_log', [])
    if trade_log:
        print(f"\n  LAST 10 TRADES")
        print(f"{'=' * 60}")
        for t in trade_log[-10:]:
            icon = '+' if t['pnl'] >= 0 else ''
            print(f"    #{t.get('nr', '?')} {t.get('pair', '?')} [{t['exit_type']}] "
                  f"${icon}{t['pnl']:.4f} | {t['bars_held']}bars | "
                  f"spread={t.get('spread_bps', 0):.1f}bps")
    print()


# ─── Dashboard Export ────────────────────────────────────────

def export_dashboard(state: dict):
    """Export monitoring dashboard as JSON."""
    dashboard_file = BASE_DIR / f'dashboard_{TAG}.json'

    closed = state.get('closed_trades', 0)
    gw = state.get('gross_wins', 0)
    gl = abs(state.get('gross_losses', 0))
    recent_spreads = [s['spread_bps'] for s in state.get('spread_log', [])[-50:]]
    avg_spread = sum(recent_spreads) / len(recent_spreads) if recent_spreads else 0

    dashboard = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'config': {
            'signal': 'FVG Fill (fvg_x2027)',
            'exchange': 'MEXC SPOT',
            'cost_model': 'spread-only (0% fees)',
            'capital_per_trade': CAPITAL_PER_TRADE,
            'entry_params': ENTRY_PARAMS,
            'precompute_params': PRECOMPUTE_KWARGS,
        },
        'baseline': BASELINE,
        'metrics': {
            'equity': round(state.get('equity', 0), 2),
            'pnl': round(state.get('total_pnl', 0), 4),
            'trades': closed,
            'wins': state.get('wins', 0),
            'losses': state.get('losses', 0),
            'win_rate': round(state.get('wins', 0) / closed * 100 if closed > 0 else 0, 1),
            'profit_factor': round(gw / gl if gl > 0 else 0, 2),
            'dd_current': round(state.get('dd_current', 0) * 100, 1),
            'dd_max': round(state.get('dd_max', 0) * 100, 1),
            'avg_spread_bps': round(avg_spread, 2),
            'consecutive_losses': state.get('consecutive_losses', 0),
            'max_consecutive_losses': state.get('max_consecutive_losses', 0),
            'circuit_breaker_hit': state.get('circuit_breaker_hit', False),
        },
        'live': {
            'enabled': state.get('live_mode', False),
            'trade_size': state.get('live_trade_size', 0),
            'trades': state.get('live_trades', 0),
            'pnl': round(state.get('live_total_pnl', 0), 6),
            'slippage_entries': len(state.get('slippage_log', [])),
        },
        'positions': state.get('positions', {}),
        'exit_types': state.get('exit_types', {}),
        'drift_checks': state.get('drift_checks', []),
        'alerts': state.get('alerts', [])[-20:],
        'checks': state.get('checks', 0),
        'last_trades': state.get('trade_log', [])[-10:],
    }

    # Atomic write
    tmp = dashboard_file.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(dashboard, f, indent=2, default=str)
    os.replace(tmp, dashboard_file)


# ─── Startup Recovery — orphaned live positions ──────────────

def _recover_orphaned_positions(mexc_client, state: dict, logger):
    """Check for orphaned live positions after crash/restart.

    Handles two cases:
    - 'pending': buy was sent but state wasn't updated → check exchange
    - 'open': position was open → verify balance still held
    """
    for pair, pos in list(state.get('positions', {}).items()):
        ls = pos.get('live_status')

        if ls == 'pending':
            oid = pos.get('live_order_id', '')
            if oid:
                # Check if order filled on exchange
                try:
                    order = mexc_client.fetch_order(oid, pair)
                    if order and order.get('status') == 'closed':
                        pos['live_status'] = 'open'
                        pos['live_fill_price'] = order.get('average', pos.get('entry_fill', 0))
                        pos['live_qty'] = order.get('filled', 0)
                        logger.info(
                            f"  RECOVERED orphaned buy {pair}: "
                            f"fill=${pos['live_fill_price']:.6f} qty={pos['live_qty']:.6f}"
                        )
                    else:
                        pos['live_status'] = 'failed'
                        logger.warning(f"  Orphaned pending {pair}: order not filled, marking failed")
                except Exception as e:
                    pos['live_status'] = 'failed'
                    logger.warning(f"  Orphaned pending {pair}: fetch_order error: {e}")
            else:
                # No order_id → buy never reached exchange
                pos['live_status'] = 'failed'
                logger.warning(f"  Orphaned pending {pair}: no order_id, marking failed")

        elif ls == 'open':
            # Verify we still hold coins on exchange
            try:
                balance = mexc_client.get_balance()
                coin = pair.split('/')[0]
                held = balance.get(coin, 0) if balance else 0
                expected = pos.get('live_qty', 0)
                if held < expected * 0.9:
                    logger.error(
                        f"  BALANCE MISMATCH {pair}: expected {expected:.4f} "
                        f"held {held:.4f} — marking failed"
                    )
                    pos['live_status'] = 'failed'
                else:
                    logger.info(f"  RECOVERED open position {pair}: {held:.4f} {coin} on exchange")
            except Exception as e:
                logger.warning(f"  Balance check failed {pair}: {e} — keeping open status")


# ─── SIGTERM Handler ─────────────────────────────────────────

_shutdown_requested = False


def _sigterm_handler(signum, frame):
    global _shutdown_requested
    _shutdown_requested = True


# ─── Main Loop ──────────────────────────────────────────────

def run_live(mexc_client, pairs: List[str], logger,
             duration_hours: Optional[int] = None, dry_run: bool = False,
             executor=None, live_trade_size: float = 25.0):
    """Main paper trading loop with optional live order mirroring."""
    global _shutdown_requested

    signal.signal(signal.SIGTERM, _sigterm_handler)
    signal.signal(signal.SIGINT, _sigterm_handler)

    state = load_state()

    if state['checks'] == 0:
        state = new_state()
        logger.info("Fresh start -- new state created")

    # Persist live mode settings in state
    if executor:
        state['live_mode'] = True
        state['live_trade_size'] = live_trade_size

    if duration_hours:
        end_time = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        logger.info(f"Paper trading until {end_time.strftime('%Y-%m-%d %H:%M UTC')} ({duration_hours}h)")
    else:
        end_time = None
        logger.info("Paper trading -- infinite (Ctrl+C or SIGTERM to stop)")

    # Startup logging
    if executor:
        logger.info(f"{'=' * 60}")
        logger.info(f"  Mode:            LIVE (real orders!)")
        logger.info(f"  Live trade size: ${live_trade_size:.2f}/trade")
        logger.info(f"  Paper trade size: ${CAPITAL_PER_TRADE:.0f}/trade (signal tracking)")
        logger.info(f"  Max live exposure: ${live_trade_size:.0f} per pair (1 position max)")
        logger.info(f"{'=' * 60}")
    else:
        logger.info(f"  Mode:            PAPER ONLY")

    logger.info(f"Pairs: {pairs}")
    logger.info(f"Signal: FVG Fill (fvg_x2027)")
    logger.info(f"Params: {ENTRY_PARAMS}")
    logger.info(f"Cost: spread-only (0% fees) | Capital: ${CAPITAL_PER_TRADE}/trade")
    logger.info(f"Baseline: PF={BASELINE['pf']} (P5={BASELINE['boot_p5_pf']}) @ {BASELINE['spread_bps_backtest']}bps")
    logger.info(f"Circuit breaker: DD>{CB_DD_CEILING * 100:.0f}% | PF<{CB_PF_FLOOR} after 30t | {CB_CONSEC_LOSS}+ consec losses")

    # ─── Startup Recovery: orphaned live positions ──────────
    if executor:
        _recover_orphaned_positions(mexc_client, state, logger)
        save_state(state)

    # Startup notification
    tg = _get_tg()
    if tg:
        try:
            tg.send(
                f"Scalp 1m Paper Trader Started (MEXC)\n"
                f"Signal: FVG Fill (fvg_x2027)\n"
                f"Pairs: {', '.join(pairs)}\n"
                f"Equity: ${state['equity']:.2f}\n"
                f"Baseline PF: {BASELINE['pf']} (P5={BASELINE['boot_p5_pf']})"
            )
        except Exception:
            pass

    iteration = 0
    while not _shutdown_requested:
        if end_time and datetime.now(timezone.utc) >= end_time:
            logger.info("End time reached!")
            break

        if dry_run and iteration > 0:
            logger.info("Dry run -- one check completed, exiting")
            break

        # Process check
        state = process_check(mexc_client, pairs, state, logger,
                              executor=executor, live_trade_size=live_trade_size,
                              dry_run=dry_run)

        # Save state + dashboard
        save_state(state)
        export_dashboard(state)

        # Telegram status every 60 checks (~1 hour at 65s intervals)
        if state['checks'] % 60 == 0:
            _tg_status(state, logger)

        iteration += 1

        # Sleep until next poll
        if not dry_run and not _shutdown_requested:
            try:
                time.sleep(POLL_INTERVAL_SEC)
            except (KeyboardInterrupt, SystemExit):
                logger.info("\nStopped by signal")
                break

    # Graceful shutdown
    logger.info("Shutting down -- saving final state")
    save_state(state)
    export_dashboard(state)
    print_report(state)
    _tg_status(state, logger)


# ─── Main ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Paper Trade -- MEXC 1m Scalp FVG Fill (fvg_x2027)')
    parser.add_argument('--hours', type=int, default=None,
                        help='Duration in hours (default: infinite)')
    parser.add_argument('--report', action='store_true',
                        help='Show report from existing state')
    parser.add_argument('--dry-run', action='store_true',
                        help='Run one check cycle then exit')
    parser.add_argument('--reset', action='store_true',
                        help='Reset state (fresh start)')
    parser.add_argument('--pairs', type=str, default='XRP/USDT,ETH/USDT',
                        help='Comma-separated pair list (default: XRP/USDT,ETH/USDT)')
    parser.add_argument('--live', action='store_true',
                        help='Execute real orders on MEXC (requires .env credentials)')
    parser.add_argument('--trade-size', type=float, default=25.0,
                        help='USD per live trade (default: $25, paper stays $200)')
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

    # Parse pairs
    pairs = [p.strip() for p in args.pairs.split(',')]
    logger.info(f"Pairs: {pairs}")

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

    # Live mode: init OrderExecutor for real orders
    executor = None
    if args.live:
        from order_executor import OrderExecutor
        executor = OrderExecutor(mexc, mode='live', fee_rate=0.0)
        logger.info("LIVE MODE — OrderExecutor initialized (fee_rate=0.0)")

    # Run
    run_live(mexc, pairs, logger, args.hours, args.dry_run,
             executor=executor, live_trade_size=args.trade_size)


if __name__ == '__main__':
    main()

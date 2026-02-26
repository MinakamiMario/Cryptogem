#!/usr/bin/env python3
"""
Paper Trade — MEXC Maker Execution & Micro-Live Validation
============================================================
Two modes:
  --mode paper : Execution validation for near_ask maker limit orders (fill-rate, slippage)
  --mode micro : MX-MICRO-TP5SL3 alpha/edge validation (TP +5% / SL -3% / TIME 24h)

Paper mode (HF-P2-LIVE-FILL):
  - Fill-rate stability in continuous trading loop
  - Slippage/fees burn under continuous operation
  - Execution path correctness (no stuck positions, no taker incidents)
  - Infrastructure reliability (no API errors, no kill-switch triggers)

Micro mode (MX-MICRO-TP5SL3):
  - Alpha/PnL validation via micro-live on MEXC
  - Separate from HF-P2-LIVE-FILL (fill-rate only) and MEXC-4H-PAPER (4H paper trader)
  - ADR: ADR-MX-001

Strategy: near_ask (ask - spread × 0.10)
Universe: papertrade_universe_v1.json (17 coins, curated from expansion test)
TTL: 120s per order
Order size: $5-15 (configurable)

ADR: HF-038 (paper mode), ADR-MX-001 (micro mode)
Separate from: MEXC-4H-PAPER (trading_bot/paper_mexc_4h.py, ADR-4H-015)

Usage:
    python paper_hf_1h.py                    # Live (infinite)
    python paper_hf_1h.py --hours 168        # 7 days
    python paper_hf_1h.py --dry-run          # 1 cycle, no orders
    python paper_hf_1h.py --report           # Show report from state
"""
import os
import sys
import json
import math
import time
import uuid
import random
import signal
import socket
import logging
import argparse
import urllib.request
from datetime import datetime, timezone
from typing import Optional, Dict, List
from pathlib import Path

# Telegram (optional — fails silently if unavailable)
try:
    from telegram_notifier import TelegramNotifier
except ImportError:
    TelegramNotifier = None

# ─── Path setup ─────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
REPO_ROOT = BASE_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass  # OK in test environments without python-dotenv

# ─── Constants ──────────────────────────────────────────────
TAG = 'hf_1h_paper'
MICRO_TAG = 'mx_micro_tp5sl3'
STATE_FILE = BASE_DIR / f'paper_state_{TAG}.json'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

# Universe file (curated from expansion test)
DEFAULT_UNIVERSE = REPO_ROOT / 'reports' / 'hf' / 'papertrade_universe_v1.json'

# Order params
DEFAULT_ORDER_USD = 5.0
MAX_ORDER_USD = 50.0
MIN_ORDER_USD = 5.0
ORDER_TTL_SECONDS = 120
SPREAD_CAP_BPS = 75.0

# Safety
DUST_CAP_USD = 0.50
MAX_CONSECUTIVE_ERRORS = 3  # legacy — now governed by outage-aware logic
POLL_INTERVAL_SECONDS = 20

# Resilience (outage-aware)
NETWORK_CHECK_TIMEOUT = 5          # seconds for pre-flight check
NETWORK_DOWN_RETRY_INTERVAL = 30   # seconds between retries during outage
NETWORK_DOWN_MAX_HOURS = 2         # hard stop after this many hours of network down
OB_ERROR_PAUSE_SECONDS = 15 * 60   # 15 min pause on orderbook error burst
OB_ERROR_BURST_THRESHOLD = 3       # consecutive OB errors → pause
OB_ERROR_MAX_BURSTS = 3            # max bursts in burst window → hard stop
OB_ERROR_BURST_WINDOW = 2 * 3600   # 2 hour window for burst counting
COIN_COOLDOWN_ERRORS = 3           # errors on same coin → cooldown
COIN_COOLDOWN_SECONDS = 60 * 60    # 1 hour cooldown per coin

# Cycle timing (1H = 3600s)
CYCLE_INTERVAL_SECONDS = 3600

# ─── Micro Mode Constants ────────────────────────────────
MAX_MICRO_POSITIONS = 4           # max 1 per coin
MAX_MICRO_NOTIONAL = 100.0        # total open exposure USD
MAX_MICRO_LOSS = 25.0             # unrealized loss → block new entries
MICRO_MIN_ORDER_USD = 10.0
MICRO_MAX_ORDER_USD = 25.0
MICRO_STALE_HOURS = 24            # warn if position open > 24h
MICRO_DASHBOARD_INTERVAL = 10     # write dashboard every N rounds

# ─── Micro Exit Constants ───────────────────────────────────
MICRO_TP_PCT = 5.0                # take profit % (configurable via --tp)
MICRO_SL_PCT = 3.0                # stop loss %   (configurable via --sl)
MICRO_MAX_HOLD_HOURS = 24         # failsafe time exit
MICRO_COUNTERFACTUAL_HOURS = [12, 24]  # snapshot intervals for counterfactual log
MICRO_EXIT_FEE_BPS = 5.0         # MEXC taker fee for market sell (5bps = 0.05%, verified via API)


# ─── Logging ────────────────────────────────────────────────

def setup_logging(active_tag: str = TAG):
    log_file = LOG_DIR / f"{active_tag}_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ]
    )
    return logging.getLogger(active_tag)


# ─── Telegram Helper ──────────────────────────────────────

def tg_send(tg, text: str, level: str = 'info'):
    """Send telegram message. Fails silently if tg is None or send fails."""
    if tg is None:
        return
    try:
        if level == 'error':
            tg.error(text)
        elif level == 'warning':
            tg.warning(text)
        elif level == 'success':
            tg.success(text)
        elif level == 'status':
            tg.status(text)
        else:
            tg.send(text)
    except Exception:
        pass  # never let TG failure crash the trader


# ─── Exchange Setup ─────────────────────────────────────────

def create_exchange():
    """Create MEXC SPOT exchange via CCXT."""
    import ccxt
    api_key = os.environ.get('MEXC_API_KEY', '')
    secret = os.environ.get('MEXC_SECRET_KEY', '') or os.environ.get('MEXC_SECRET', '')
    if not api_key or not secret:
        raise ValueError("MEXC_API_KEY and MEXC_SECRET must be set in .env")
    exchange = ccxt.mexc({
        'apiKey': api_key,
        'secret': secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'},
    })
    exchange.load_markets()
    return exchange


# ─── Network Pre-flight ───────────────────────────────────

def network_ok() -> bool:
    """Pre-flight check: DNS + HTTPS GET to MEXC API.
    Returns True if network is reachable, False otherwise."""
    # Step 1: DNS resolve
    try:
        socket.setdefaulttimeout(NETWORK_CHECK_TIMEOUT)
        socket.getaddrinfo('api.mexc.com', 443)
    except (socket.gaierror, socket.timeout, OSError):
        return False

    # Step 2: HTTPS GET to MEXC ping endpoint
    try:
        req = urllib.request.Request(
            'https://api.mexc.com/api/v3/ping',
            headers={'User-Agent': 'paper-hf-1h/1.0'}
        )
        with urllib.request.urlopen(req, timeout=NETWORK_CHECK_TIMEOUT) as resp:
            return resp.status == 200
    except Exception:
        return False


def wait_for_network(logger, shutdown_flag: list) -> bool:
    """Block until network is back. Returns True if resumed, False if hard-stop."""
    down_since = time.time()
    max_down = NETWORK_DOWN_MAX_HOURS * 3600

    logger.warning("[NETWORK_DOWN] Network unreachable. Pausing trades, retrying every 30s.")

    while not shutdown_flag[0]:
        elapsed = time.time() - down_since
        if elapsed > max_down:
            logger.error(f"[HARD-STOP] Network down > {NETWORK_DOWN_MAX_HOURS}h. Stopping.")
            return False

        time.sleep(NETWORK_DOWN_RETRY_INTERVAL)

        if network_ok():
            logger.info(f"[NETWORK_UP] Network restored after {elapsed/60:.1f} min. Resuming.")
            return True

        mins = int(elapsed // 60)
        if mins % 5 == 0 and mins > 0:  # log every 5 min
            logger.warning(f"[NETWORK_DOWN] Still down after {mins} min.")

    return False  # shutdown requested


# ─── Universe Loading ───────────────────────────────────────

def load_universe(path: Path) -> List[str]:
    """Load curated coin symbols from universe JSON."""
    with open(path) as f:
        data = json.load(f)
    coins = [c['symbol'] for c in data.get('coins', [])]
    if not coins:
        raise ValueError(f"No coins found in {path}")
    return coins


# ─── State Management ──────────────────────────────────────

def new_state(mode: str = 'paper') -> dict:
    state = {
        'mode': mode,
        'start_time': datetime.now(timezone.utc).isoformat(),
        'total_rounds': 0,
        'filled': 0,
        'partial': 0,
        'missed': 0,
        'errors': 0,
        'taker_incidents': 0,
        'stuck_positions': 0,
        'total_rt_pnl': 0.0,
        'total_flatten_fees': 0.0,
        'slippages': [],
        'consecutive_errors': 0,
        'last_cycle': None,
        'coin_stats': {},
        'rollback_triggered': None,
        'trade_log': [],
    }
    if mode == 'micro':
        state['micro_positions'] = {}     # {symbol: {entry_price, qty, entry_time, order_id, notional}}
        state['micro_closed'] = []        # closed position log
        state['micro_caps_hit'] = 0       # number of times caps blocked entry
        state['micro_new_entries_blocked'] = False
    return state


def load_state(mode: str = 'paper') -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return new_state(mode=mode)


def save_state(state: dict):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)


# ─── Pricing ────────────────────────────────────────────────

def compute_near_ask_price(bid1: float, ask1: float, exchange, symbol: str) -> Optional[float]:
    """Compute near_ask price: ask - spread × 0.10.

    Returns None if price would cross to taker side after rounding.
    """
    spread = ask1 - bid1
    if spread <= 0:
        return None

    raw_price = ask1 - spread * 0.10

    # Apply exchange precision
    try:
        price = float(exchange.price_to_precision(symbol, raw_price))
    except Exception:
        market = exchange.markets.get(symbol, {})
        prec = market.get('precision', {}).get('price')
        if prec and isinstance(prec, int):
            price = round(raw_price, prec)
        else:
            price = raw_price

    # Maker safety guard: price must be strictly below ask
    if price >= ask1:
        # Fallback to bid
        return bid1

    return price


# ─── Quantity ───────────────────────────────────────────────

def compute_quantity(order_usd: float, price: float, exchange, symbol: str) -> float:
    """Compute order quantity with exchange precision."""
    if price <= 0:
        return 0.0
    raw_qty = order_usd / price

    try:
        qty = float(exchange.amount_to_precision(symbol, raw_qty))
    except Exception:
        market = exchange.markets.get(symbol, {})
        prec = market.get('precision', {}).get('amount')
        if prec is not None:
            if isinstance(prec, int):
                qty = math.floor(raw_qty * 10**prec) / 10**prec
            else:
                qty = math.floor(raw_qty / prec) * prec
        else:
            qty = raw_qty

    return qty


# ─── Micro Mode Functions ─────────────────────────────────

def check_micro_caps(state: dict, exchange, logger) -> bool:
    """Check micro mode hard caps. Returns True if new entries are allowed."""
    positions = state.get('micro_positions', {})
    open_count = len(positions)

    # Cap 1: max positions
    if open_count >= MAX_MICRO_POSITIONS:
        logger.info(f"[MICRO_CAP] All {MAX_MICRO_POSITIONS} positions open — blocking new entries")
        state['micro_new_entries_blocked'] = True
        state['micro_caps_hit'] = state.get('micro_caps_hit', 0) + 1
        return False

    # Cap 2: total notional
    total_notional = sum(p.get('notional', 0) for p in positions.values())
    if total_notional >= MAX_MICRO_NOTIONAL:
        logger.info(f"[MICRO_CAP] Notional ${total_notional:.2f} >= ${MAX_MICRO_NOTIONAL} — blocking")
        state['micro_new_entries_blocked'] = True
        state['micro_caps_hit'] = state.get('micro_caps_hit', 0) + 1
        return False

    # Cap 3: unrealized loss check (requires live prices)
    try:
        total_unrealized = 0.0
        for sym, pos in positions.items():
            ob = exchange.fetch_order_book(sym, limit=1)
            if ob.get('bids') and ob['bids'][0]:
                current_bid = float(ob['bids'][0][0])
                unrealized = (current_bid - pos['entry_price']) * pos['qty']
                total_unrealized += unrealized
            time.sleep(0.3)  # rate limit

        if total_unrealized < -MAX_MICRO_LOSS:
            logger.warning(f"[MICRO_CAP] Unrealized loss ${total_unrealized:.2f} exceeds "
                           f"${MAX_MICRO_LOSS} — blocking new entries")
            state['micro_new_entries_blocked'] = True
            state['micro_caps_hit'] = state.get('micro_caps_hit', 0) + 1
            return False
    except Exception as e:
        logger.warning(f"[MICRO_CAP] Could not check unrealized P&L: {e}")
        # On error, allow trading (don't block on monitoring failure)

    state['micro_new_entries_blocked'] = False
    return True


def check_position_staleness(state: dict, logger, tg=None) -> List[str]:
    """Check for stale positions (open > MICRO_STALE_HOURS). Returns list of stale symbols."""
    stale = []
    now = datetime.now(timezone.utc)
    for sym, pos in state.get('micro_positions', {}).items():
        entry_time = datetime.fromisoformat(pos['entry_time'])
        hours_open = (now - entry_time).total_seconds() / 3600
        if hours_open > MICRO_STALE_HOURS:
            stale.append(sym)
            logger.warning(f"[STALE] {sym} open {hours_open:.1f}h (entry ${pos['entry_price']:.6f}, "
                           f"qty={pos['qty']}, notional=${pos['notional']:.2f})")
            tg_send(tg, f"⏰ STALE POSITION\n{sym}: open {hours_open:.1f}h\n"
                        f"Entry: ${pos['entry_price']:.6f}\nNotional: ${pos['notional']:.2f}",
                    level='warning')
    return stale


def compute_micro_unrealized(state: dict, exchange) -> float:
    """Compute total unrealized P&L for micro positions. Returns 0.0 on error."""
    total = 0.0
    for sym, pos in state.get('micro_positions', {}).items():
        try:
            ob = exchange.fetch_order_book(sym, limit=1)
            if ob.get('bids') and ob['bids'][0]:
                current_bid = float(ob['bids'][0][0])
                total += (current_bid - pos['entry_price']) * pos['qty']
            time.sleep(0.3)
        except Exception:
            pass
    return round(total, 4)


def _build_closed_summary(closed: list) -> dict:
    """Build summary statistics for closed micro positions."""
    if not closed:
        return {'count': 0}

    total_net = sum(c.get('net_pnl', 0) for c in closed)
    total_gross = sum(c.get('gross_pnl', 0) for c in closed)
    total_fees = sum(c.get('total_fees', 0) for c in closed)
    wins = sum(1 for c in closed if c.get('net_pnl', 0) > 0)

    by_reason = {}
    for c in closed:
        reason = c.get('exit_reason', '?')
        by_reason.setdefault(reason, {'count': 0, 'net_pnl': 0})
        by_reason[reason]['count'] += 1
        by_reason[reason]['net_pnl'] = round(by_reason[reason]['net_pnl'] + c.get('net_pnl', 0), 4)

    return {
        'count': len(closed),
        'total_net_pnl': round(total_net, 4),
        'total_gross_pnl': round(total_gross, 4),
        'total_fees': round(total_fees, 4),
        'win_rate': round(wins / len(closed), 3) if closed else 0,
        'avg_hold_hours': round(sum(c.get('hours_held', 0) for c in closed) / len(closed), 2),
        'by_exit_reason': by_reason,
        'last_close': closed[-1] if closed else None,
    }


def write_micro_dashboard(state: dict, exchange, mode: str):
    """Write JSON dashboard for micro mode monitoring."""
    if mode != 'micro':
        return

    positions = state.get('micro_positions', {})
    total_notional = sum(p.get('notional', 0) for p in positions.values())

    # Compute unrealized P&L
    unrealized = compute_micro_unrealized(state, exchange)

    total = state.get('filled', 0) + state.get('partial', 0) + state.get('missed', 0)
    fill_rate = state['filled'] / total if total > 0 else 0

    dashboard = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'mode': 'micro',
        'rounds': state.get('total_rounds', 0),
        'fill_rate': round(fill_rate, 3),
        'positions': {
            'count': len(positions),
            'max': MAX_MICRO_POSITIONS,
            'total_notional': round(total_notional, 2),
            'max_notional': MAX_MICRO_NOTIONAL,
            'unrealized_pnl': unrealized,
            'max_loss': MAX_MICRO_LOSS,
            'details': {sym: {
                'entry_price': p['entry_price'],
                'qty': p['qty'],
                'notional': p['notional'],
                'entry_time': p['entry_time'],
            } for sym, p in positions.items()},
        },
        'caps': {
            'entries_blocked': state.get('micro_new_entries_blocked', False),
            'caps_hit_count': state.get('micro_caps_hit', 0),
        },
        'stats': {
            'filled': state.get('filled', 0),
            'missed': state.get('missed', 0),
            'partial': state.get('partial', 0),
            'errors': state.get('errors', 0),
            'taker_incidents': state.get('taker_incidents', 0),
            'stuck_positions': state.get('stuck_positions', 0),
        },
        'exit_config': {
            'tp_pct': MICRO_TP_PCT,
            'sl_pct': MICRO_SL_PCT,
            'max_hold_hours': MICRO_MAX_HOLD_HOURS,
        },
        'closed_summary': _build_closed_summary(state.get('micro_closed', [])),
    }

    dashboard_path = BASE_DIR / f'dashboard_{MICRO_TAG}.json'
    try:
        with open(dashboard_path, 'w') as f:
            json.dump(dashboard, f, indent=2, default=str)
    except Exception:
        pass  # never crash on dashboard write


# ─── Micro Exit Checking ──────────────────────────────────────

def check_micro_exits(state: dict, exchange, logger, tg=None,
                      tp_pct: float = MICRO_TP_PCT,
                      sl_pct: float = MICRO_SL_PCT,
                      max_hold_hours: float = MICRO_MAX_HOLD_HOURS) -> List[dict]:
    """Check all open micro positions for TP/SL/TIME exit triggers.

    For each triggered exit:
      1. Fetch current bid price
      2. Determine exit_reason (TP, SL, TIME)
      3. Execute market sell via safe_sell_back()
      4. Compute actual PnL, fees, slippage
      5. Build counterfactual: what PnL at 12h/24h snapshots
      6. Move to micro_closed with full trade log

    Returns list of close records for Telegram/logging.
    """
    positions = state.get('micro_positions', {})
    if not positions:
        return []

    now = datetime.now(timezone.utc)
    closes = []
    to_remove = []

    for sym, pos in list(positions.items()):
        entry_price = pos['entry_price']
        qty = pos['qty']
        entry_time = datetime.fromisoformat(pos['entry_time'])
        hours_open = (now - entry_time).total_seconds() / 3600

        # Fetch current bid
        try:
            ob = exchange.fetch_order_book(sym, limit=5)
            if not ob.get('bids') or not ob['bids'][0]:
                logger.warning(f"[EXIT_CHECK] {sym}: no bids in orderbook, skipping")
                continue
            current_bid = float(ob['bids'][0][0])
            current_ask = float(ob['asks'][0][0]) if ob.get('asks') and ob['asks'][0] else current_bid
            mid_price = (current_bid + current_ask) / 2
        except Exception as e:
            logger.warning(f"[EXIT_CHECK] {sym}: orderbook fetch failed: {e}")
            time.sleep(0.5)
            continue

        # Compute unrealized %
        pct_change = (current_bid - entry_price) / entry_price * 100 if entry_price > 0 else 0

        # Store price snapshot for counterfactual (append to position)
        snapshots = pos.setdefault('price_snapshots', [])
        snapshots.append({
            'ts': now.isoformat(),
            'hours_open': round(hours_open, 2),
            'bid': current_bid,
            'mid': mid_price,
            'pct_change': round(pct_change, 3),
        })
        # Keep only last 50 snapshots to limit state size
        pos['price_snapshots'] = snapshots[-50:]

        # Determine exit trigger
        exit_reason = None
        if pct_change >= tp_pct:
            exit_reason = 'TP'
        elif pct_change <= -sl_pct:
            exit_reason = 'SL'
        elif hours_open >= max_hold_hours:
            exit_reason = 'TIME'

        if exit_reason is None:
            time.sleep(0.3)  # rate limit between position checks
            continue

        # ── TRIGGERED — execute exit ──
        logger.info(f"[EXIT] {sym} → {exit_reason} | trigger check: "
                    f"bid=${current_bid:.6f} ask=${current_ask:.6f} mid=${mid_price:.6f} | "
                    f"pct_vs_entry={pct_change:+.3f}% (threshold: TP≥+{tp_pct}% SL≤-{sl_pct}%) | "
                    f"open={hours_open:.1f}h (max={max_hold_hours}h)")
        logger.info(f"[EXIT] {sym} entry_order_id={pos.get('order_id', '?')} | "
                    f"entry_price=${entry_price:.8f} | entry_qty={qty} | "
                    f"check_price=bid (${current_bid:.8f})")

        sell_result = safe_sell_back(exchange, sym, qty, entry_price)

        # Compute actual exit price and fees
        actual_sell_price = sell_result.get('sell_price', current_bid)
        actual_sell_qty = sell_result.get('sell_qty', qty)
        sell_fee_cost = sell_result.get('sell_fee_cost', 0)
        sell_order_id = sell_result.get('sell_order_id', '')

        # If sell failed (dust/error), use bid estimate
        sell_method = 'market_sell'
        if sell_result.get('dust_remaining') or sell_result.get('WARNING'):
            actual_sell_price = current_bid
            actual_sell_qty = qty
            sell_fee_cost = current_bid * qty * MICRO_EXIT_FEE_BPS / 10000
            sell_method = 'estimated_bid'

        # Fee model: entry = maker limit (0% MEXC SPOT), exit = market taker (10bps)
        entry_fee = 0.0  # maker 0% on MEXC SPOT
        exit_fee = sell_fee_cost if sell_fee_cost > 0 else (actual_sell_price * actual_sell_qty * MICRO_EXIT_FEE_BPS / 10000)

        # Actual PnL
        gross_pnl = (actual_sell_price - entry_price) * actual_sell_qty
        net_pnl = gross_pnl - entry_fee - exit_fee

        # Slippage: exit vs mid at time of exit
        exit_slip_vs_mid_bps = (actual_sell_price - mid_price) / mid_price * 10000 if mid_price > 0 else 0
        # Slippage: exit vs trigger bid (how much did market sell deviate from bid we saw)
        exit_slip_vs_bid_bps = (actual_sell_price - current_bid) / current_bid * 10000 if current_bid > 0 else 0

        # ── Counterfactual: what PnL would have been at 12h/24h ──
        counterfactual = {}
        for cf_hours in MICRO_COUNTERFACTUAL_HOURS:
            # Find closest snapshot to cf_hours
            cf_snap = None
            min_diff = float('inf')
            for snap in snapshots:
                diff = abs(snap['hours_open'] - cf_hours)
                if diff < min_diff:
                    min_diff = diff
                    cf_snap = snap
            if cf_snap and min_diff < 2.0:  # within 2h tolerance
                cf_bid = cf_snap['bid']
                cf_gross = (cf_bid - entry_price) * qty
                cf_exit_fee = cf_bid * qty * MICRO_EXIT_FEE_BPS / 10000
                cf_net = cf_gross - cf_exit_fee
                counterfactual[f'{cf_hours}h'] = {
                    'bid': cf_bid,
                    'pct_change': cf_snap['pct_change'],
                    'gross_pnl': round(cf_gross, 4),
                    'net_pnl': round(cf_net, 4),
                    'snapshot_hours': cf_snap['hours_open'],
                }
            else:
                counterfactual[f'{cf_hours}h'] = {
                    'status': 'no_snapshot' if not cf_snap else f'nearest_at_{cf_snap["hours_open"]:.1f}h',
                }

        # Compute TP/SL price levels for this position
        tp_price_level = round(entry_price * (1 + tp_pct / 100), 8)
        sl_price_level = round(entry_price * (1 - sl_pct / 100), 8)

        # Build close record
        close_record = {
            'position_id': pos.get('position_id', 'legacy'),
            'symbol': sym,
            'exit_reason': exit_reason,
            # ── Timestamps ──
            'entry_ts': pos['entry_time'],
            'exit_ts': now.isoformat(),
            # ── Entry details ──
            'entry_price_avg': entry_price,
            'entry_order_id': pos.get('order_id', ''),   # mexc_order_id_buy
            'entry_fee_model': 'maker_0bps',
            'entry_fee': round(entry_fee, 6),             # fees_buy
            # ── Exit details ──
            'exit_price_avg': round(actual_sell_price, 8),
            'exit_order_id': sell_order_id,                # mexc_order_id_sell
            'exit_fee_model': f'taker_{MICRO_EXIT_FEE_BPS:.0f}bps',
            'exit_fee': round(exit_fee, 6),                # fees_sell
            'exit_method': sell_method,
            # ── TP/SL levels ──
            'tp_price': tp_price_level,
            'sl_price': sl_price_level,
            'max_hold_hours': max_hold_hours,
            # ── Trigger context ──
            'trigger_price': current_bid,          # price that fired the exit
            'trigger_basis': 'bid',                # bid/ask/last/mid
            'trigger_ask': current_ask,
            'trigger_mid': round(mid_price, 8),
            'trigger_spread_bps': round((current_ask - current_bid) / mid_price * 10000, 2) if mid_price > 0 else 0,
            # ── Trade metrics ──
            'qty': actual_sell_qty,
            'notional_entry': pos.get('notional', 0),
            'notional_exit': round(actual_sell_price * actual_sell_qty, 4),
            'hours_held': round(hours_open, 2),
            'pct_change': round(pct_change, 3),
            'gross_pnl': round(gross_pnl, 4),
            'net_pnl': round(net_pnl, 4),
            'total_fees': round(entry_fee + exit_fee, 6),
            'exit_slip_vs_mid_bps': round(exit_slip_vs_mid_bps, 2),
            'exit_slip_vs_bid_bps': round(exit_slip_vs_bid_bps, 2),
            # ── Sell execution ──
            'sell_result': {
                'order_id': sell_order_id,
                'attempts': sell_result.get('sell_attempts', 0),
                'dust': sell_result.get('dust_remaining', False),
                'warning': sell_result.get('WARNING', ''),
            },
            'counterfactual': counterfactual,
        }

        # ── Sanity checks ──
        sanity = []
        if exit_reason == 'SL' and not (current_bid <= sl_price_level):
            sanity.append(f"FAIL: trigger_bid({current_bid}) > sl_price({sl_price_level})")
        if exit_reason == 'TP' and not (current_bid >= tp_price_level):
            sanity.append(f"FAIL: trigger_bid({current_bid}) < tp_price({tp_price_level})")
        if exit_reason == 'TIME' and hours_open < max_hold_hours:
            sanity.append(f"FAIL: hours_open({hours_open:.2f}) < max({max_hold_hours})")
        if close_record['trigger_basis'] != 'bid':
            sanity.append(f"FAIL: trigger_basis={close_record['trigger_basis']} != bid")
        sanity_ok = len(sanity) == 0
        close_record['sanity_ok'] = sanity_ok
        close_record['sanity_errors'] = sanity if sanity else None

        closes.append(close_record)
        to_remove.append(sym)

        # Log detailed
        sanity_tag = "✅" if sanity_ok else f"❌ {'; '.join(sanity)}"
        logger.info(f"  [SANITY] {sanity_tag}")
        logger.info(f"  [CLOSE] {sym} {exit_reason}: entry=${entry_price:.8f} → "
                    f"exit=${actual_sell_price:.8f} ({pct_change:+.3f}%)")
        logger.info(f"  [CLOSE] Gross=${gross_pnl:.4f} | "
                    f"Fees: buy={entry_fee:.4f}(maker 0%) + sell={exit_fee:.4f}(taker {MICRO_EXIT_FEE_BPS:.0f}bps) = ${entry_fee + exit_fee:.4f} | "
                    f"Net=${net_pnl:.4f}")
        logger.info(f"  [CLOSE] Slip: vs_mid={exit_slip_vs_mid_bps:+.1f}bps vs_bid={exit_slip_vs_bid_bps:+.1f}bps | "
                    f"sell_method={sell_method} sell_order={sell_order_id}")
        for cf_key, cf_val in counterfactual.items():
            if 'net_pnl' in cf_val:
                logger.info(f"  [CF] @{cf_key}: would have been ${cf_val['net_pnl']:.4f} "
                            f"({cf_val['pct_change']:+.2f}%)")
            else:
                logger.info(f"  [CF] @{cf_key}: {cf_val.get('status', 'n/a')}")

        # Telegram alert
        emoji = {'TP': '🎯', 'SL': '🔻', 'TIME': '⏰'}.get(exit_reason, '📤')
        cf_lines = []
        for cf_key, cf_val in counterfactual.items():
            if 'net_pnl' in cf_val:
                cf_lines.append(f"  @{cf_key}: ${cf_val['net_pnl']:.4f} ({cf_val['pct_change']:+.2f}%)")
        cf_text = "\n".join(cf_lines) if cf_lines else "  no snapshots"

        # Compact one-liner for easy debugging
        level_str = {'TP': f'tp {tp_price_level:.4f}', 'SL': f'stop {sl_price_level:.4f}', 'TIME': f'time {hours_open:.1f}h'}
        tg_send(tg, f"{emoji} CLOSE {exit_reason} | {sym}\n"
                     f"entry {entry_price:.4f} | {level_str.get(exit_reason, '')} | "
                     f"trigger bid {current_bid:.4f} | exit {actual_sell_price:.4f}\n"
                     f"fees {entry_fee + exit_fee:.3f} | net {net_pnl:+.4f} | "
                     f"held {hours_open:.1f}h | slip {exit_slip_vs_bid_bps:+.1f}bps\n"
                     f"buy={pos.get('order_id', '?')[:20]}\n"
                     f"sell={sell_order_id[:20]}\n"
                     f"CF: {cf_text}",
                level='success' if net_pnl > 0 else 'warning')

        time.sleep(0.5)  # rate limit between sells

    # Remove closed positions from state
    for sym in to_remove:
        positions.pop(sym, None)

    # Append to closed log (keep last 200)
    closed_log = state.setdefault('micro_closed', [])
    closed_log.extend(closes)
    state['micro_closed'] = closed_log[-200:]

    return closes


# ─── Safe Sell Back ─────────────────────────────────────────

def safe_sell_back(exchange, symbol: str, qty: float, fill_price: float) -> dict:
    """Sell back filled position with retries and dust handling.

    Reuses pattern from live_fill_test._safe_sell_back().
    """
    result = {}
    market_info = exchange.markets.get(symbol, {})

    # Apply precision
    try:
        qty = float(exchange.amount_to_precision(symbol, qty))
    except Exception:
        prec = market_info.get('precision', {}).get('amount')
        if prec is not None:
            if isinstance(prec, int):
                qty = math.floor(qty * 10**prec) / 10**prec
            else:
                qty = math.floor(qty / prec) * prec

    # Check minimums
    min_amount = market_info.get('limits', {}).get('amount', {}).get('min')
    min_cost = market_info.get('limits', {}).get('cost', {}).get('min')
    notional = qty * fill_price

    if qty <= 0:
        result['dust_remaining'] = True
        result['dust_reason'] = 'zero_qty'
        return result

    if (min_amount and qty < min_amount) or \
       (min_cost and notional < min_cost) or \
       notional <= DUST_CAP_USD:
        result['dust_remaining'] = True
        result['dust_notional'] = round(notional, 4)
        result['dust_reason'] = 'below_minimum'
        return result

    # Retry loop
    for attempt in range(3):
        try:
            wait = 0.5 + attempt * 1.5 + random.uniform(0, 0.5)
            time.sleep(wait)
            sell_order = exchange.create_market_sell_order(symbol, qty)
            sell_id = sell_order.get('id', '')
            result['sell_order_id'] = sell_id
            result['sell_attempts'] = attempt + 1

            time.sleep(2.0)
            try:
                sell_status = exchange.fetch_order(sell_id, symbol)
                result['sell_price'] = float(sell_status.get('average', 0) or
                                             sell_status.get('price', 0) or 0)
                result['sell_qty'] = float(sell_status.get('filled', 0) or 0)
                sell_fees = sell_status.get('fee', {})
                if sell_fees and sell_fees.get('cost'):
                    result['sell_fee_cost'] = float(sell_fees['cost'])
            except Exception as e:
                result['sell_check_error'] = str(e)

            return result

        except Exception as e:
            result['sell_error'] = str(e)
            result['sell_attempts'] = attempt + 1

    result['WARNING'] = 'POSITION OPEN — manual close needed!'
    return result


# ─── Single Round ───────────────────────────────────────────

def run_single_round(exchange, symbol: str, order_usd: float, logger,
                     mode: str = 'paper') -> dict:
    """Execute one fill test round: buy limit → wait → sell back (paper) or hold (micro).

    Returns dict with all result fields.
    """
    result = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'symbol': symbol,
        'order_usd': order_usd,
        'strategy': 'near_ask',
        'ttl': ORDER_TTL_SECONDS,
    }

    # 1. Fetch orderbook (with retry)
    ob = None
    ob_error = None
    for attempt in range(3):
        try:
            ob = exchange.fetch_order_book(symbol, limit=5)
            break
        except Exception as e:
            ob_error = str(e)
            if attempt < 2:
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))

    if ob is None:
        result['status'] = 'ERROR_ORDERBOOK'
        result['error'] = ob_error
        return result

    bids = ob.get('bids', [])
    asks = ob.get('asks', [])
    if not bids or not asks:
        result['status'] = 'ERROR_ORDERBOOK'
        result['error'] = 'empty orderbook'
        return result

    bid1, ask1 = float(bids[0][0]), float(asks[0][0])
    spread_bps = (ask1 - bid1) / ((bid1 + ask1) / 2) * 10000
    mid = (bid1 + ask1) / 2

    result['bid1'] = bid1
    result['ask1'] = ask1
    result['spread_bps'] = round(spread_bps, 2)

    # 2. Spread cap check
    if spread_bps > SPREAD_CAP_BPS:
        result['status'] = 'SKIPPED_SPREAD'
        return result

    # 3. Compute price + quantity
    price = compute_near_ask_price(bid1, ask1, exchange, symbol)
    if price is None:
        result['status'] = 'SKIPPED_PRICE'
        return result

    qty = compute_quantity(order_usd, price, exchange, symbol)
    if qty <= 0:
        result['status'] = 'SKIPPED_MIN_SIZE'
        return result

    result['limit_price'] = price
    result['quantity'] = qty
    result['slippage_vs_mid_bps'] = round((price - mid) / mid * 10000, 2)

    # Maker safety: price must be below ask
    result['maker_safe'] = price < ask1

    # 4. Place limit buy
    try:
        order = exchange.create_limit_buy_order(symbol, qty, price)
        order_id = order.get('id', '')
        result['order_id'] = order_id
    except Exception as e:
        result['status'] = 'ERROR_ORDER'
        result['error'] = str(e)
        return result

    # 5. Poll for fill
    start_time = time.time()
    fill_status = 'open'
    fill_qty = 0.0
    fill_price_avg = 0.0
    poll_count = 0

    while time.time() - start_time < ORDER_TTL_SECONDS:
        time.sleep(POLL_INTERVAL_SECONDS)
        poll_count += 1
        try:
            status = exchange.fetch_order(order_id, symbol)
            fill_status = status.get('status', 'open')
            fill_qty = float(status.get('filled', 0) or 0)
            fill_price_avg = float(status.get('average', 0) or status.get('price', 0) or 0)
            if fill_status in ('closed', 'filled'):
                break
        except Exception:
            continue

    elapsed = round(time.time() - start_time, 1)
    result['wait_seconds'] = elapsed
    result['poll_count'] = poll_count

    # 6. Handle result
    if fill_status in ('closed', 'filled') and fill_qty > 0:
        result['status'] = 'FILLED'
        result['fill_qty'] = fill_qty
        result['fill_price'] = fill_price_avg
        result['fill_notional'] = round(fill_qty * fill_price_avg, 4)

        if mode == 'micro':
            # Micro mode: hold position, no sell-back
            result['micro_held'] = True
        else:
            # Paper mode: sell back immediately
            sell_result = safe_sell_back(exchange, symbol, fill_qty, fill_price_avg)
            result.update(sell_result)
            if 'sell_price' in sell_result and fill_price_avg:
                result['roundtrip_pnl'] = round(
                    (sell_result['sell_price'] - fill_price_avg) * fill_qty, 4
                )

    elif fill_qty > 0:
        result['status'] = 'PARTIAL'
        result['fill_qty'] = fill_qty
        result['fill_price'] = fill_price_avg
        result['fill_notional'] = round(fill_qty * fill_price_avg, 4)

        # Cancel remaining
        try:
            exchange.cancel_order(order_id, symbol)
        except Exception:
            pass

        if mode == 'micro':
            # Micro mode: hold partial fill, no sell-back
            result['micro_held'] = True
        else:
            # Paper mode: sell partial back
            sell_result = safe_sell_back(exchange, symbol, fill_qty, fill_price_avg)
            result.update(sell_result)
            if 'sell_price' in sell_result and fill_price_avg:
                result['roundtrip_pnl'] = round(
                    (sell_result['sell_price'] - fill_price_avg) * fill_qty, 4
                )

    else:
        result['status'] = 'MISSED'
        # Cancel unfilled order
        try:
            exchange.cancel_order(order_id, symbol)
        except Exception:
            pass

    return result


# ─── Rollback Check ─────────────────────────────────────────

def check_rollback(state: dict, logger) -> Optional[str]:
    """Check rollback criteria. Returns trigger name or None."""
    # R1: stuck positions
    if state.get('stuck_positions', 0) > 0:
        return 'stuck_position'

    # R2: taker incidents
    if state.get('taker_incidents', 0) > 0:
        return 'taker_incident'

    total = state.get('filled', 0) + state.get('partial', 0) + state.get('missed', 0)

    # R3: flatten fee avg > $0.50
    if total >= 10:
        avg_fee = state.get('total_flatten_fees', 0) / max(1, state['filled'] + state.get('partial', 0))
        if avg_fee > 0.50:
            logger.warning(f"[WARN] Flatten fee avg ${avg_fee:.4f} > $0.50")

    # R4: abnormal slippage
    slips = state.get('slippages', [])
    if len(slips) >= 20:
        avg_slip = sum(slips[-50:]) / len(slips[-50:])
        if avg_slip > 25:
            logger.warning(f"[WARN] Avg slippage {avg_slip:.1f} bps > 25 bps")

    # R5: fill rate < 50% after 50+ trades
    if total >= 50:
        fill_rate = (state['filled'] + state.get('partial', 0)) / total
        if fill_rate < 0.50:
            return 'low_fill_rate'

    # R6: ERROR_ORDERBOOK > 10%
    total_with_errors = total + state.get('errors', 0)
    if total_with_errors >= 20:
        error_rate = state['errors'] / total_with_errors
        if error_rate > 0.10:
            logger.warning(f"[WARN] Error rate {error_rate:.1%} > 10%")

    return None


# ─── Update State ───────────────────────────────────────────

def update_state(state: dict, result: dict, mode: str = 'paper'):
    """Update state with round result."""
    state['total_rounds'] += 1
    state['last_cycle'] = result.get('ts')

    status = result.get('status', '')
    sym = result.get('symbol', '')

    if status == 'FILLED':
        state['filled'] += 1
        state['consecutive_errors'] = 0
    elif status == 'PARTIAL':
        state['partial'] += 1
        state['consecutive_errors'] = 0
    elif status == 'MISSED':
        state['missed'] += 1
        state['consecutive_errors'] = 0
    elif status.startswith('ERROR'):
        state['errors'] += 1
        state['consecutive_errors'] += 1

    # Taker check
    if result.get('maker_safe') is False:
        state['taker_incidents'] += 1

    # Stuck position check
    warn = result.get('WARNING', '')
    if warn.startswith('POSITION OPEN'):
        if not result.get('dust_remaining'):
            state['stuck_positions'] += 1

    # P&L and fees
    rt_pnl = result.get('roundtrip_pnl', 0)
    state['total_rt_pnl'] = round(state.get('total_rt_pnl', 0) + rt_pnl, 4)

    fee = result.get('sell_fee_cost', 0)
    state['total_flatten_fees'] = round(state.get('total_flatten_fees', 0) + fee, 6)

    # Slippage tracking
    slip = result.get('slippage_vs_mid_bps')
    if slip is not None and status in ('FILLED', 'PARTIAL'):
        slips = state.get('slippages', [])
        slips.append(slip)
        # Keep last 200
        state['slippages'] = slips[-200:]

    # Per-coin stats
    if sym:
        cs = state.setdefault('coin_stats', {}).setdefault(sym, {
            'filled': 0, 'partial': 0, 'missed': 0, 'errors': 0,
            'total_rt_pnl': 0.0, 'total_fees': 0.0,
        })
        if status == 'FILLED':
            cs['filled'] += 1
        elif status == 'PARTIAL':
            cs['partial'] += 1
        elif status == 'MISSED':
            cs['missed'] += 1
        elif status.startswith('ERROR'):
            cs['errors'] += 1
        cs['total_rt_pnl'] = round(cs.get('total_rt_pnl', 0) + rt_pnl, 4)
        cs['total_fees'] = round(cs.get('total_fees', 0) + fee, 6)

    # Trade log (keep last 100 for state size)
    log_entry = {
        'ts': result.get('ts'),
        'symbol': sym,
        'status': status,
        'rt_pnl': rt_pnl,
        'slip_bps': slip,
    }
    trade_log = state.setdefault('trade_log', [])
    trade_log.append(log_entry)
    state['trade_log'] = trade_log[-100:]

    # Micro mode: record position on fill
    if mode == 'micro' and result.get('micro_held') and sym:
        positions = state.setdefault('micro_positions', {})
        positions[sym] = {
            'position_id': str(uuid.uuid4())[:12],  # short unique ID for cross-ref
            'entry_price': result.get('fill_price', 0),
            'qty': result.get('fill_qty', 0),
            'entry_time': result.get('ts', datetime.now(timezone.utc).isoformat()),
            'order_id': result.get('order_id', ''),
            'notional': result.get('fill_notional', 0),
            'price_snapshots': [],  # populated by check_micro_exits() each round
        }


# ─── Report ─────────────────────────────────────────────────

def print_report(state: dict):
    """Print summary report from state."""
    total = state.get('filled', 0) + state.get('partial', 0) + state.get('missed', 0)
    touch = state.get('filled', 0) + state.get('partial', 0)
    mode = state.get('mode', 'paper')

    print("\n" + "=" * 60)
    title = "MX-MICRO-TP5SL3 TRADER REPORT" if mode == 'micro' else "HF 1H PAPER TRADER — EXECUTION VALIDATION REPORT"
    print(title)
    print("=" * 60)
    print(f"  Mode:         {mode}")
    print(f"  Start:        {state.get('start_time', '?')}")
    print(f"  Last cycle:   {state.get('last_cycle', '?')}")
    print(f"  Total rounds: {state.get('total_rounds', 0)}")
    print(f"  Actionable:   {total}")
    print(f"  Filled:       {state.get('filled', 0)}")
    print(f"  Partial:      {state.get('partial', 0)}")
    print(f"  Missed:       {state.get('missed', 0)}")
    print(f"  Errors:       {state.get('errors', 0)}")

    if total > 0:
        print(f"\n--- Rates ---")
        print(f"  Touch rate:   {touch / total:.1%}")
        print(f"  Fill rate:    {state['filled'] / total:.1%}")

    print(f"\n--- Safety ---")
    print(f"  Taker incidents:   {state.get('taker_incidents', 0)}")
    print(f"  Stuck positions:   {state.get('stuck_positions', 0)}")
    print(f"  Rollback:          {state.get('rollback_triggered', 'none')}")

    print(f"\n--- Costs ---")
    print(f"  Total RT P&L:      ${state.get('total_rt_pnl', 0):.4f}")
    print(f"  Total flatten fees: ${state.get('total_flatten_fees', 0):.4f}")
    slips = state.get('slippages', [])
    if slips:
        print(f"  Avg slippage:      {sum(slips) / len(slips):+.1f} bps")

    # Per-coin
    coin_stats = state.get('coin_stats', {})
    if coin_stats:
        print(f"\n--- Per-Coin ---")
        for sym in sorted(coin_stats, key=lambda s: coin_stats[s].get('filled', 0), reverse=True):
            cs = coin_stats[sym]
            act = cs.get('filled', 0) + cs.get('partial', 0) + cs.get('missed', 0)
            if act == 0:
                continue
            fr = cs['filled'] / act
            print(f"  {sym:15s} fill={fr:.0%} ({cs['filled']}/{act}) "
                  f"RT=${cs.get('total_rt_pnl', 0):.4f} fees=${cs.get('total_fees', 0):.4f}")

    # Micro positions
    if mode == 'micro':
        positions = state.get('micro_positions', {})
        closed = state.get('micro_closed', [])
        print(f"\n--- Micro Open Positions ---")
        print(f"  Open:         {len(positions)}/{MAX_MICRO_POSITIONS}")
        total_notional = sum(p.get('notional', 0) for p in positions.values())
        print(f"  Notional:     ${total_notional:.2f}/${MAX_MICRO_NOTIONAL:.0f}")
        print(f"  Caps hit:     {state.get('micro_caps_hit', 0)}")
        if positions:
            for sym, pos in positions.items():
                entry_time = datetime.fromisoformat(pos['entry_time'])
                hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
                print(f"    {sym:15s} entry=${pos['entry_price']:.6f} "
                      f"qty={pos['qty']} notional=${pos['notional']:.2f} "
                      f"open={hours:.1f}h")

        # Closed positions analysis
        print(f"\n--- Micro Closed Positions ({len(closed)}) ---")
        if closed:
            total_net = sum(c.get('net_pnl', 0) for c in closed)
            total_gross = sum(c.get('gross_pnl', 0) for c in closed)
            total_fees_paid = sum(c.get('total_fees', 0) for c in closed)
            wins = [c for c in closed if c.get('net_pnl', 0) > 0]
            losses = [c for c in closed if c.get('net_pnl', 0) <= 0]

            # Exit reason breakdown
            by_reason = {}
            for c in closed:
                reason = c.get('exit_reason', '?')
                by_reason.setdefault(reason, []).append(c)

            print(f"  Total Net P&L:  ${total_net:.4f}")
            print(f"  Total Gross:    ${total_gross:.4f}")
            print(f"  Total Fees:     ${total_fees_paid:.4f}")
            print(f"  Win/Loss:       {len(wins)}/{len(losses)} "
                  f"({len(wins)/len(closed)*100:.0f}% WR)" if closed else "")
            print(f"  Avg hold time:  {sum(c.get('hours_held', 0) for c in closed)/len(closed):.1f}h")

            print(f"\n  Exit Reasons:")
            for reason in ['TP', 'SL', 'TIME']:
                trades = by_reason.get(reason, [])
                if trades:
                    reason_pnl = sum(c.get('net_pnl', 0) for c in trades)
                    reason_avg = reason_pnl / len(trades) if trades else 0
                    print(f"    {reason:6s}: {len(trades):3d} trades | "
                          f"Net=${reason_pnl:.4f} | Avg=${reason_avg:.4f}")

            # Last 5 closed trades
            print(f"\n  Last 5 Closes:")
            for c in closed[-5:]:
                cf_summary = ""
                cf = c.get('counterfactual', {})
                for cf_key, cf_val in cf.items():
                    if 'net_pnl' in cf_val:
                        cf_summary += f" | CF@{cf_key}=${cf_val['net_pnl']:.4f}"
                print(f"    {c.get('symbol', '?'):15s} {c.get('exit_reason', '?'):4s} "
                      f"net=${c.get('net_pnl', 0):.4f} "
                      f"{c.get('pct_change', 0):+.2f}% "
                      f"held={c.get('hours_held', 0):.1f}h{cf_summary}")
        else:
            print(f"  No closed positions yet")

    print("=" * 60)


# ─── Main Loop ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='MEXC Paper/Micro Trader (micro = MX-MICRO-TP5SL3)')
    parser.add_argument('--mode', choices=['paper', 'micro'], default='paper',
                        help='Trading mode: paper (roundtrip validation) or micro (live hold)')
    parser.add_argument('--hours', type=float, default=0, help='Run for N hours (0=infinite)')
    parser.add_argument('--order-usd', type=float, default=DEFAULT_ORDER_USD, help='USD per order')
    parser.add_argument('--universe', type=str, default=str(DEFAULT_UNIVERSE), help='Universe JSON')
    parser.add_argument('--dry-run', action='store_true', help='1 cycle, no orders')
    parser.add_argument('--report', action='store_true', help='Print report from state')
    parser.add_argument('--reset-state', action='store_true', help='Reset state and start fresh')
    parser.add_argument('--tp', type=float, default=MICRO_TP_PCT,
                        help=f'Take profit %% for micro mode (default: {MICRO_TP_PCT})')
    parser.add_argument('--sl', type=float, default=MICRO_SL_PCT,
                        help=f'Stop loss %% for micro mode (default: {MICRO_SL_PCT})')
    args = parser.parse_args()

    mode = args.mode
    tp_pct = args.tp
    sl_pct = args.sl

    # Determine state file and active tag based on mode
    global STATE_FILE
    active_tag = TAG
    if mode == 'micro':
        active_tag = MICRO_TAG
        STATE_FILE = BASE_DIR / f'paper_state_{MICRO_TAG}.json'

    # Report mode
    if args.report:
        state = load_state(mode=mode)
        print_report(state)
        return

    logger = setup_logging(active_tag)
    logger.info(f"{'MX-MICRO-TP5SL3' if mode == 'micro' else 'HF 1H Paper'} Trader starting — tag={active_tag} mode={mode}")

    # Telegram (micro mode always, paper mode never)
    tg = None
    if mode == 'micro' and TelegramNotifier is not None:
        try:
            tg = TelegramNotifier()
            logger.info("Telegram notifier initialized")
        except Exception as e:
            logger.warning(f"Telegram init failed (non-fatal): {e}")

    # Load universe
    universe_path = Path(args.universe)
    coins = load_universe(universe_path)
    logger.info(f"Universe: {len(coins)} coins from {universe_path.name}")

    # Validate order size (micro mode has its own range)
    if mode == 'micro':
        order_usd = min(max(args.order_usd, MICRO_MIN_ORDER_USD), MICRO_MAX_ORDER_USD)
    else:
        order_usd = min(max(args.order_usd, MIN_ORDER_USD), MAX_ORDER_USD)

    # State
    if args.reset_state:
        state = new_state(mode=mode)
        save_state(state)
        logger.info("State reset")
    else:
        state = load_state(mode=mode)
        # Ensure micro keys exist on resume
        if mode == 'micro':
            state['mode'] = 'micro'  # always override to match CLI
            state.setdefault('micro_positions', {})
            state.setdefault('micro_closed', [])
            state.setdefault('micro_caps_hit', 0)
            state.setdefault('micro_new_entries_blocked', False)

    # Dry run
    if args.dry_run:
        logger.info(f"[DRY-RUN] Mode: {mode}")
        logger.info(f"[DRY-RUN] Would trade {len(coins)} coins @ ${order_usd}/order")
        for c in coins:
            logger.info(f"  {c}")
        logger.info(f"TTL: {ORDER_TTL_SECONDS}s, spread cap: {SPREAD_CAP_BPS} bps")
        logger.info(f"State: {state.get('total_rounds', 0)} rounds, "
                    f"{state.get('filled', 0)} filled")
        if mode == 'micro':
            positions = state.get('micro_positions', {})
            logger.info(f"Micro positions: {len(positions)}/{MAX_MICRO_POSITIONS}")
            logger.info(f"Micro caps: notional=${MAX_MICRO_NOTIONAL}, "
                        f"loss=${MAX_MICRO_LOSS}, stale={MICRO_STALE_HOURS}h")
            logger.info(f"Micro exits: TP=+{tp_pct}%, SL=-{sl_pct}%, "
                        f"TIME={MICRO_MAX_HOLD_HOURS}h")
        return

    # Create exchange
    exchange = create_exchange()
    logger.info(f"Exchange connected: MEXC SPOT")

    # Fee model verification
    logger.info(f"Fee model: entry=MAKER(0bps) exit=TAKER({MICRO_EXIT_FEE_BPS:.0f}bps)")
    logger.info(f"Exit config: TP=+{tp_pct}% SL=-{sl_pct}% TIME={MICRO_MAX_HOLD_HOURS}h")
    logger.info(f"Exit check: trigger_price=BID (conservative for sell-side)")
    logger.info(f"Sell method: market_sell via safe_sell_back (3 retries)")
    if mode == 'micro':
        # Verify MEXC fee tier if possible
        try:
            fees_info = exchange.fetch_trading_fee(coins[0]) if coins else None
            if fees_info:
                maker_fee = fees_info.get('maker', '?')
                taker_fee = fees_info.get('taker', '?')
                logger.info(f"MEXC fee check ({coins[0]}): maker={maker_fee} taker={taker_fee}")
                if isinstance(taker_fee, (int, float)) and taker_fee * 10000 != MICRO_EXIT_FEE_BPS:
                    logger.warning(f"[FEE_MISMATCH] MEXC taker={taker_fee*10000:.1f}bps vs "
                                   f"model={MICRO_EXIT_FEE_BPS:.1f}bps — update MICRO_EXIT_FEE_BPS!")
        except Exception as e:
            logger.info(f"Fee tier check skipped: {e}")

    # Telegram: start alert
    if mode == 'micro':
        positions = state.get('micro_positions', {})
        tg_send(tg, f"🚀 MX-MICRO-TP5SL3 STARTED\n"
                     f"Coins: {', '.join(coins)}\n"
                     f"Order: ${order_usd}\n"
                     f"TP: +{tp_pct}% | SL: -{sl_pct}% | TIME: {MICRO_MAX_HOLD_HOURS}h\n"
                     f"Positions: {len(positions)}/{MAX_MICRO_POSITIONS}\n"
                     f"Hours: {args.hours or '∞'}",
                level='success')

    # SIGINT handler
    shutdown = [False]
    def handle_sigint(sig, frame):
        logger.info("[SIGINT] Graceful shutdown...")
        shutdown[0] = True
    signal.signal(signal.SIGINT, handle_sigint)

    # SIGHUP handler — hot-reload universe from disk
    def handle_sighup(sig, frame):
        nonlocal coins, coin_idx
        try:
            new_coins = load_universe(universe_path)
            old_count = len(coins)
            coins = new_coins
            coin_idx = 0  # reset round-robin
            logger.info(f"[SIGHUP] Universe reloaded: {old_count} → {len(coins)} coins from {universe_path.name}")
        except Exception as e:
            logger.error(f"[SIGHUP] Failed to reload universe: {e}")
    signal.signal(signal.SIGHUP, handle_sighup)

    # Time limit
    end_time = None
    if args.hours > 0:
        end_time = time.time() + args.hours * 3600
        logger.info(f"Will run for {args.hours}h")

    # Main loop — outage-aware
    coin_idx = 0
    ob_burst_times = []            # timestamps of OB error bursts (for burst counting)
    coin_error_counts = {}         # {symbol: [error_timestamps]} for per-coin cooldown
    coin_cooldowns = {}            # {symbol: cooldown_until_timestamp}
    miss_counter = 0               # for telegram miss alert throttling

    # Clear stale rollback + error counters from previous run (allows clean resume)
    if state.get('rollback_triggered') == 'consecutive_errors':
        logger.info("[RESUME] Clearing stale consecutive_errors rollback from previous run")
        state['rollback_triggered'] = None
        state['consecutive_errors'] = 0
        save_state(state)
    elif state.get('consecutive_errors', 0) > 0:
        logger.info(f"[RESUME] Resetting consecutive_errors from {state['consecutive_errors']} → 0 on restart")
        state['consecutive_errors'] = 0
        save_state(state)

    while not shutdown[0]:
        if end_time and time.time() > end_time:
            logger.info("Time limit reached")
            break

        # ── Pre-flight: network check ──
        if not network_ok():
            resumed = wait_for_network(logger, shutdown)
            if not resumed:
                state['rollback_triggered'] = 'network_down_timeout'
                save_state(state)
                tg_send(tg, "🚨 HARD STOP: Network down timeout", level='error')
                break
            # Re-create exchange after network restore (connections may be stale)
            try:
                exchange = create_exchange()
                logger.info("Exchange reconnected after network restore")
            except Exception as e:
                logger.error(f"Exchange reconnect failed: {e}. Will retry next round.")
                time.sleep(NETWORK_DOWN_RETRY_INTERVAL)
                continue

        # ── Micro mode: check exits on open positions ──
        if mode == 'micro' and state.get('micro_positions'):
            exit_closes = check_micro_exits(
                state, exchange, logger, tg,
                tp_pct=tp_pct, sl_pct=sl_pct,
                max_hold_hours=MICRO_MAX_HOLD_HOURS,
            )
            # Always save: snapshots are recorded even when no exits trigger
            save_state(state)

        # ── Micro mode: cap checks before round ──
        if mode == 'micro':
            if not check_micro_caps(state, exchange, logger):
                # Caps hit — only send TG alert once per 100 rounds to avoid spam
                caps_hit_count = state.get('micro_caps_hit', 0)
                if caps_hit_count == 1 or caps_hit_count % 100 == 0:
                    tg_send(tg, f"🔒 MX-MICRO-TP5SL3 CAP HIT (#{caps_hit_count})\n"
                                 f"Positions: {len(state.get('micro_positions', {}))}/{MAX_MICRO_POSITIONS}\n"
                                 f"Entries blocked.", level='info')
                time.sleep(60)
                continue

            # Check staleness (warn only, TIME exit handled by check_micro_exits)
            check_position_staleness(state, logger, tg)

        # ── Pick coin (round-robin, skip cooldowns + open micro positions) ──
        now_ts = time.time()
        symbol = None
        attempts = 0
        while attempts < len(coins):
            candidate = coins[coin_idx % len(coins)]
            coin_idx += 1
            attempts += 1
            cooldown_until = coin_cooldowns.get(candidate, 0)
            if now_ts < cooldown_until:
                continue  # coin on cooldown

            # Micro mode: skip coins with open positions
            if mode == 'micro' and candidate in state.get('micro_positions', {}):
                continue

            symbol = candidate
            break

        if symbol is None:
            if mode == 'micro' and len(state.get('micro_positions', {})) >= len(coins):
                # All coins have open positions
                logger.info(f"[MICRO] All {len(coins)} coins have open positions. Waiting 60s.")
                time.sleep(60)
                continue
            # All coins on cooldown — wait for shortest cooldown to expire
            if coin_cooldowns:
                min_wait = min(coin_cooldowns.values()) - now_ts
                if min_wait > 0:
                    logger.info(f"[COOLDOWN] All coins on cooldown. Waiting {min_wait:.0f}s.")
                    time.sleep(min(min_wait + 1, 60))
            else:
                time.sleep(5)
            continue

        # ── Run round ──
        logger.info(f"[round {state['total_rounds'] + 1}] {symbol} — ${order_usd} ({mode})")
        result = run_single_round(exchange, symbol, order_usd, logger, mode=mode)

        # Log result
        status = result.get('status', '?')
        spread = result.get('spread_bps', 0)
        slip = result.get('slippage_vs_mid_bps', 0)
        rt_pnl = result.get('roundtrip_pnl', 0)
        logger.info(f"  Status: {status} | Spread: {spread:.1f}bps | "
                    f"Slip: {slip:+.1f}bps | RT P&L: ${rt_pnl:.4f}")

        # Log error details (previously swallowed — see ADR-HF-040)
        if status.startswith('ERROR') and result.get('error'):
            logger.warning(f"  [ERR_DETAIL] {symbol}: {result['error']}")

        # Update state
        update_state(state, result, mode=mode)
        save_state(state)

        # ── Telegram alerts ──
        if mode == 'micro':
            if status == 'FILLED' and result.get('micro_held'):
                pos_info = state.get('micro_positions', {}).get(symbol, {})
                tp_lvl = result.get('fill_price', 0) * (1 + tp_pct / 100)
                sl_lvl = result.get('fill_price', 0) * (1 - sl_pct / 100)
                tg_send(tg, f"✅ FILL {symbol}\n"
                             f"entry {result.get('fill_price', 0):.6f} | "
                             f"qty {result.get('fill_qty', 0)} | ${result.get('fill_notional', 0):.2f}\n"
                             f"TP={tp_lvl:.4f}(+{tp_pct}%) SL={sl_lvl:.4f}(-{sl_pct}%)\n"
                             f"buy={result.get('order_id', '?')[:25]}\n"
                             f"pos={pos_info.get('position_id', '?')} | "
                             f"{len(state.get('micro_positions', {}))}/{MAX_MICRO_POSITIONS}",
                        level='success')
            elif status == 'MISSED':
                miss_counter += 1
                if miss_counter % 50 == 0:
                    tg_send(tg, f"⚠️ MISS #{miss_counter}\n{symbol}\n"
                                 f"Spread: {spread:.1f}bps", level='warning')
            elif status.startswith('ERROR'):
                # Throttled error alert: first error + every 50th per coin
                cs = state.get('coin_stats', {}).get(symbol, {})
                coin_err_count = cs.get('errors', 0)
                if coin_err_count == 1 or coin_err_count % 50 == 0:
                    tg_send(tg, f"🚨 {status} #{coin_err_count} | {symbol}\n"
                                 f"{result.get('error', '?')[:120]}",
                            level='error')

            # Status update every 100 rounds
            if state['total_rounds'] % 100 == 0 and state['total_rounds'] > 0:
                total_acts = state['filled'] + state.get('partial', 0) + state['missed']
                fr = state['filled'] / total_acts if total_acts > 0 else 0
                positions = state.get('micro_positions', {})
                tg_send(tg, f"📊 MX-MICRO-TP5SL3 (round {state['total_rounds']})\n"
                             f"Fill rate: {fr:.1%}\n"
                             f"Positions: {len(positions)}/{MAX_MICRO_POSITIONS}\n"
                             f"Filled: {state['filled']} | Missed: {state['missed']}",
                        level='status')

            # Dashboard write every N rounds
            if state['total_rounds'] % MICRO_DASHBOARD_INTERVAL == 0:
                write_micro_dashboard(state, exchange, mode)

        # ── Hard rollback checks (taker, stuck — always stop) ──
        trigger = check_rollback(state, logger)
        if trigger:
            logger.error(f"[ROLLBACK] Trigger: {trigger}. Stopping.")
            state['rollback_triggered'] = trigger
            save_state(state)
            tg_send(tg, f"🚨 MX-MICRO-TP5SL3 ROLLBACK\nReason: {trigger}\nTrader stopped.",
                    level='error')
            break

        # ── Outage-aware error handling ──
        if status.startswith('ERROR'):
            # Per-coin error tracking (handles ERROR_ORDERBOOK + ERROR_ORDER + any future error types)
            coin_errors = coin_error_counts.setdefault(symbol, [])
            coin_errors.append(now_ts)
            # Keep only errors in last hour
            coin_errors[:] = [t for t in coin_errors if now_ts - t < COIN_COOLDOWN_SECONDS]
            if len(coin_errors) >= COIN_COOLDOWN_ERRORS:
                coin_cooldowns[symbol] = now_ts + COIN_COOLDOWN_SECONDS
                logger.warning(f"[COOLDOWN] {symbol}: {len(coin_errors)} {status} errors in 1h "
                               f"→ blacklisted for {COIN_COOLDOWN_SECONDS // 60} min")
                coin_error_counts[symbol] = []

            # Consecutive error burst detection (multi-coin = exchange/network issue)
            if state['consecutive_errors'] >= OB_ERROR_BURST_THRESHOLD:
                # Check if this is a network issue first
                if not network_ok():
                    resumed = wait_for_network(logger, shutdown)
                    if not resumed:
                        state['rollback_triggered'] = 'network_down_timeout'
                        save_state(state)
                        tg_send(tg, "🚨 HARD STOP: Network down timeout", level='error')
                        break
                    try:
                        exchange = create_exchange()
                        logger.info("Exchange reconnected after network restore")
                    except Exception as e:
                        logger.error(f"Exchange reconnect failed: {e}")
                    state['consecutive_errors'] = 0
                    save_state(state)
                    continue

                # Network OK → exchange-side issue. Pause and count burst.
                ob_burst_times.append(now_ts)
                # Keep only bursts in window
                ob_burst_times[:] = [t for t in ob_burst_times if now_ts - t < OB_ERROR_BURST_WINDOW]

                if len(ob_burst_times) >= OB_ERROR_MAX_BURSTS:
                    logger.error(f"[HARD-STOP] {len(ob_burst_times)} OB error bursts in "
                                 f"{OB_ERROR_BURST_WINDOW//3600}h. Stopping.")
                    state['rollback_triggered'] = 'ob_error_burst_limit'
                    save_state(state)
                    tg_send(tg, f"🚨 HARD STOP: {len(ob_burst_times)} OB error bursts",
                            level='error')
                    break

                pause_min = OB_ERROR_PAUSE_SECONDS // 60
                logger.warning(f"[PAUSE] {state['consecutive_errors']} consecutive OB errors "
                               f"(burst {len(ob_burst_times)}/{OB_ERROR_MAX_BURSTS}). "
                               f"Pausing {pause_min} min.")
                state['consecutive_errors'] = 0
                save_state(state)

                # Sleep in small chunks so SIGINT works
                pause_end = time.time() + OB_ERROR_PAUSE_SECONDS
                while time.time() < pause_end and not shutdown[0]:
                    time.sleep(10)

                if shutdown[0]:
                    break

                logger.info("[RESUME] Pause ended, resuming trading.")
                continue
        else:
            # Non-error status → reset consecutive errors (already done in update_state)
            pass

        # Inter-round delay (avoid rate limits)
        if not shutdown[0]:
            time.sleep(2.0 + random.uniform(0, 1.0))

    # Final dashboard write (micro)
    if mode == 'micro':
        try:
            write_micro_dashboard(state, exchange, mode)
        except Exception:
            pass

    # Final report
    print_report(state)
    logger.info(f"{'MX-MICRO-TP5SL3' if mode == 'micro' else 'Paper'} trader stopped.")
    tg_send(tg, f"🛑 {'MX-MICRO-TP5SL3' if mode == 'micro' else 'HF PAPER'} STOPPED\n"
                 f"Rounds: {state.get('total_rounds', 0)}\n"
                 f"Filled: {state.get('filled', 0)}",
            level='warning')


if __name__ == '__main__':
    main()

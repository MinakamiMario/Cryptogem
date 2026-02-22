#!/usr/bin/env python3
"""
Paper Trade — HF 1H MEXC Maker Execution Validation
=====================================================
Execution validation for near_ask maker limit orders on MEXC SPOT.

This is NOT alpha/PnL validation. Purpose:
  - Fill-rate stability in continuous trading loop
  - Slippage/fees burn under continuous operation
  - Execution path correctness (no stuck positions, no taker incidents)
  - Infrastructure reliability (no API errors, no kill-switch triggers)

Strategy: near_ask (ask - spread × 0.10)
Universe: papertrade_universe_v1.json (17 coins, curated from expansion test)
TTL: 120s per order
Order size: $5-15 (configurable)

ADR: HF-038 Iteration 8 — GO paper trading (execution validation)
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
import random
import signal
import logging
import argparse
from datetime import datetime, timezone
from typing import Optional, Dict, List
from pathlib import Path

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
MAX_CONSECUTIVE_ERRORS = 3
POLL_INTERVAL_SECONDS = 20

# Cycle timing (1H = 3600s)
CYCLE_INTERVAL_SECONDS = 3600


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
    return logging.getLogger(TAG)


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

def new_state() -> dict:
    return {
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


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return new_state()


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

def run_single_round(exchange, symbol: str, order_usd: float, logger) -> dict:
    """Execute one fill test round: buy limit → wait → sell back.

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

        # Sell back immediately
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

        # Sell partial
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

def update_state(state: dict, result: dict):
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


# ─── Report ─────────────────────────────────────────────────

def print_report(state: dict):
    """Print summary report from state."""
    total = state.get('filled', 0) + state.get('partial', 0) + state.get('missed', 0)
    touch = state.get('filled', 0) + state.get('partial', 0)

    print("\n" + "=" * 60)
    print(f"HF 1H PAPER TRADER — EXECUTION VALIDATION REPORT")
    print("=" * 60)
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

    print("=" * 60)


# ─── Main Loop ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='HF 1H MEXC Paper Trader (Execution Validation)')
    parser.add_argument('--hours', type=float, default=0, help='Run for N hours (0=infinite)')
    parser.add_argument('--order-usd', type=float, default=DEFAULT_ORDER_USD, help='USD per order')
    parser.add_argument('--universe', type=str, default=str(DEFAULT_UNIVERSE), help='Universe JSON')
    parser.add_argument('--dry-run', action='store_true', help='1 cycle, no orders')
    parser.add_argument('--report', action='store_true', help='Print report from state')
    parser.add_argument('--reset-state', action='store_true', help='Reset state and start fresh')
    args = parser.parse_args()

    # Report mode
    if args.report:
        state = load_state()
        print_report(state)
        return

    logger = setup_logging()
    logger.info(f"HF 1H Paper Trader starting — tag={TAG}")

    # Load universe
    universe_path = Path(args.universe)
    coins = load_universe(universe_path)
    logger.info(f"Universe: {len(coins)} coins from {universe_path.name}")

    # Validate order size
    order_usd = min(max(args.order_usd, MIN_ORDER_USD), MAX_ORDER_USD)

    # State
    if args.reset_state:
        state = new_state()
        save_state(state)
        logger.info("State reset")
    else:
        state = load_state()

    # Dry run
    if args.dry_run:
        logger.info(f"[DRY-RUN] Would trade {len(coins)} coins @ ${order_usd}/order")
        for c in coins:
            logger.info(f"  {c}")
        logger.info(f"TTL: {ORDER_TTL_SECONDS}s, spread cap: {SPREAD_CAP_BPS} bps")
        logger.info(f"State: {state.get('total_rounds', 0)} rounds, "
                    f"{state.get('filled', 0)} filled")
        return

    # Create exchange
    exchange = create_exchange()
    logger.info(f"Exchange connected: MEXC SPOT")

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

    # Main loop
    coin_idx = 0
    while not shutdown[0]:
        if end_time and time.time() > end_time:
            logger.info("Time limit reached")
            break

        # Pick coin (round-robin)
        symbol = coins[coin_idx % len(coins)]
        coin_idx += 1

        # Run round
        logger.info(f"[round {state['total_rounds'] + 1}] {symbol} — ${order_usd}")
        result = run_single_round(exchange, symbol, order_usd, logger)

        # Log result
        status = result.get('status', '?')
        spread = result.get('spread_bps', 0)
        slip = result.get('slippage_vs_mid_bps', 0)
        rt_pnl = result.get('roundtrip_pnl', 0)
        logger.info(f"  Status: {status} | Spread: {spread:.1f}bps | "
                    f"Slip: {slip:+.1f}bps | RT P&L: ${rt_pnl:.4f}")

        # Update state
        update_state(state, result)
        save_state(state)

        # Check rollback
        trigger = check_rollback(state, logger)
        if trigger:
            logger.error(f"[ROLLBACK] Trigger: {trigger}. Stopping.")
            state['rollback_triggered'] = trigger
            save_state(state)
            break

        # Check consecutive errors
        if state['consecutive_errors'] >= MAX_CONSECUTIVE_ERRORS:
            logger.error(f"[KILL-SWITCH] {MAX_CONSECUTIVE_ERRORS} consecutive errors. Stopping.")
            state['rollback_triggered'] = 'consecutive_errors'
            save_state(state)
            break

        # Inter-round delay (avoid rate limits)
        if not shutdown[0]:
            time.sleep(2.0 + random.uniform(0, 1.0))

    # Final report
    print_report(state)
    logger.info("Paper trader stopped.")


if __name__ == '__main__':
    main()

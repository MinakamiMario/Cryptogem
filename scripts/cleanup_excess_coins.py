#!/usr/bin/env python3
"""
Cleanup excess coins from MEXC wallet.

Sells:
  - ALL non-halal coins (GRT, ES, ALTHEA) — full sell
  - EXCESS halal coins (SUI, ARB, XRP, KAS) — keep only tracked qty

Safe: reads tracked positions from state file, only sells the difference.
"""

import os
import sys
import json
import time
import ccxt
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TRADING_DIR = BASE_DIR / 'trading_bot'

# Load env
env_path = TRADING_DIR / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

# State file
STATE_FILE = TRADING_DIR / 'paper_state_hf_1h_paper_micro.json'

# Non-halal coins to fully sell
HARAM_COINS = ['GRT/USDT', 'ES/USDT', 'ALTHEA/USDT']

# Halal coins (sell only excess above tracked qty)
HALAL_COINS = ['SUI/USDT', 'ARB/USDT', 'XRP/USDT', 'KAS/USDT']


def create_exchange():
    api_key = os.environ.get('MEXC_API_KEY', '')
    secret = os.environ.get('MEXC_SECRET_KEY', '') or os.environ.get('MEXC_SECRET', '')
    if not api_key or not secret:
        raise ValueError("MEXC_API_KEY and MEXC_SECRET must be set")
    return ccxt.mexc({
        'apiKey': api_key,
        'secret': secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'},
    })


def load_tracked_positions():
    """Load tracked qty per symbol from micro state."""
    if not STATE_FILE.exists():
        print(f"[WARN] State file not found: {STATE_FILE}")
        return {}
    state = json.load(open(STATE_FILE))
    positions = state.get('micro_positions', {})
    tracked = {}
    for sym, pos in positions.items():
        tracked[sym] = pos.get('qty', 0)
    return tracked


def get_balances(exchange, symbols):
    """Fetch actual balances for given symbols."""
    balance = exchange.fetch_balance()
    result = {}
    for sym in symbols:
        coin = sym.split('/')[0]
        free = balance.get(coin, {}).get('free', 0) or 0
        total = balance.get(coin, {}).get('total', 0) or 0
        result[sym] = {'free': float(free), 'total': float(total)}
    return result


def market_sell(exchange, symbol, qty, dry_run=False):
    """Market sell with dust handling."""
    try:
        # Get market info for min qty and precision
        market = exchange.market(symbol)
        min_qty = market.get('limits', {}).get('amount', {}).get('min') or 0
        precision = market.get('precision', {}).get('amount')
        if precision is None:
            precision = 4  # safe default

        # Round down to precision
        factor = 10 ** int(precision)
        qty_rounded = int(qty * factor) / factor

        if qty_rounded < min_qty:
            print(f"  [SKIP] {symbol}: qty {qty_rounded} < min {min_qty} (dust)")
            return None

        if dry_run:
            ticker = exchange.fetch_ticker(symbol)
            est_usd = qty_rounded * (ticker.get('bid', 0) or 0)
            print(f"  [DRY] Would sell {qty_rounded} {symbol} ≈ ${est_usd:.2f}")
            return {'dry_run': True, 'qty': qty_rounded, 'est_usd': est_usd}

        print(f"  [SELL] {symbol}: {qty_rounded} @ market...", end=' ', flush=True)
        order = exchange.create_market_sell_order(symbol, qty_rounded)
        filled = order.get('filled') or 0
        cost = order.get('cost') or 0
        avg_price = order.get('average') or order.get('price') or 0
        status = order.get('status', '?')
        # If cost is 0 but we have filled and price, compute it
        if cost == 0 and filled > 0 and avg_price > 0:
            cost = filled * avg_price
        print(f"OK status={status} filled={filled} cost=${cost:.2f}")
        order['_computed_cost'] = cost
        return order

    except Exception as e:
        print(f"  [ERROR] {symbol}: {e}")
        return None


def main():
    dry_run = '--dry-run' in sys.argv or '-n' in sys.argv
    if dry_run:
        print("=== DRY RUN MODE (no actual sells) ===\n")
    else:
        print("=== LIVE CLEANUP — SELLING EXCESS COINS ===\n")

    exchange = create_exchange()
    tracked = load_tracked_positions()

    print("Tracked positions (KEEP):")
    for sym, qty in tracked.items():
        print(f"  {sym}: {qty}")

    all_symbols = HARAM_COINS + HALAL_COINS
    balances = get_balances(exchange, all_symbols)

    total_sold_usd = 0
    results = []

    # 1. Sell ALL haram coins
    print("\n--- Haram coins (SELL ALL) ---")
    for sym in HARAM_COINS:
        bal = balances.get(sym, {})
        free = bal.get('free', 0)
        if free <= 0:
            print(f"  {sym}: no balance, skip")
            continue
        print(f"  {sym}: balance={free}")
        result = market_sell(exchange, sym, free, dry_run=dry_run)
        if result:
            cost = result.get('_computed_cost') or result.get('cost') or result.get('est_usd') or 0
            total_sold_usd += cost
            results.append({'symbol': sym, 'type': 'haram_full', 'qty': free, 'usd': cost})
        time.sleep(0.5)

    # 2. Sell EXCESS halal coins
    print("\n--- Halal coins (SELL EXCESS) ---")
    for sym in HALAL_COINS:
        bal = balances.get(sym, {})
        free = bal.get('free', 0)
        keep = tracked.get(sym, 0)
        excess = free - keep

        if excess <= 0:
            print(f"  {sym}: free={free:.4f}, keep={keep:.4f}, no excess")
            continue

        print(f"  {sym}: free={free:.4f}, keep={keep:.4f}, EXCESS={excess:.4f}")
        result = market_sell(exchange, sym, excess, dry_run=dry_run)
        if result:
            cost = result.get('_computed_cost') or result.get('cost') or result.get('est_usd') or 0
            total_sold_usd += cost
            results.append({'symbol': sym, 'type': 'halal_excess', 'qty': excess, 'usd': cost})
        time.sleep(0.5)

    # Summary
    print(f"\n=== SUMMARY ===")
    print(f"Orders: {len(results)}")
    print(f"Total recovered: ${total_sold_usd:.2f}")
    for r in results:
        print(f"  {r['symbol']:12s} {r['type']:15s} qty={r['qty']:.4f} → ${r['usd']:.2f}")

    if dry_run:
        print(f"\n⚠️  DRY RUN — nothing sold. Run without --dry-run to execute.")


if __name__ == '__main__':
    main()

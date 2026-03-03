#!/usr/bin/env python3
"""
Emergency Panic Sell — Standalone MEXC Position Liquidator
==========================================================
Sells ALL open positions tracked in the live state file.
Independent of live_trader.py — works even if bot is crashed.

IDEMPOTENT: Safe to run multiple times. Checks exchange balance
before selling. Skips positions already sold (dust threshold $1).

Usage:
    python sell_positions_mexc.py                    # Dry run (show what would sell)
    python sell_positions_mexc.py --confirm           # Execute sells
    python sell_positions_mexc.py --confirm --force   # Sell even without state file (uses balance)
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).parent
REPO_ROOT = BASE_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
load_dotenv(BASE_DIR / '.env')

from exchange_manager import MEXCExchangeClient

# ─── Config ────────────────────────────────────────────────
DUST_THRESHOLD_USD = 1.0        # Ignore balances < $1
MAX_RETRIES = 3                 # Retries per sell
RETRY_DELAY_S = 2               # Base delay between retries
STATE_PATTERNS = [               # Where to look for state files
    'state_*_live.json',
]
STABLECOINS = {'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD'}


def find_state_files() -> list[Path]:
    """Find all live state files."""
    files = []
    for pattern in STATE_PATTERNS:
        files.extend(BASE_DIR.glob(pattern))
    return sorted(files)


def load_positions_from_state(state_file: Path) -> list[dict]:
    """Extract open positions from state file."""
    with open(state_file) as f:
        state = json.load(f)
    positions = []
    for pair, pos in state.get('positions', {}).items():
        if pos.get('status') == 'open':
            positions.append({
                'pair': pair,
                'entry_price': pos.get('entry_price', 0),
                'size_usd': pos.get('size_usd', 0),
                'order_id': pos.get('order_id', ''),
                'source': state_file.name,
            })
    return positions


def get_exchange_balances(client: MEXCExchangeClient) -> dict:
    """Get all non-zero balances from exchange."""
    balance = client.get_balance()
    if not balance:
        return {}
    # Filter out zero/tiny balances and stablecoins
    result = {}
    for asset, amount in balance.items():
        if isinstance(amount, (int, float)) and amount > 0 and asset not in STABLECOINS:
            result[asset] = float(amount)
    return result


def estimate_value_usd(client: MEXCExchangeClient, asset: str, amount: float) -> float:
    """Estimate USD value of an asset balance."""
    pair = f"{asset}/USDT"
    try:
        ticker = client.get_ticker(pair)
        if ticker:
            price = ticker.get('last', 0) or ticker.get('close', 0)
            return amount * price
    except Exception:
        pass
    return 0.0


def sell_position(client: MEXCExchangeClient, pair: str, qty: float,
                  confirm: bool = False) -> dict:
    """
    Sell a position with retry logic.
    Returns: {'success': bool, 'order_id': str, 'error': str}
    """
    if not confirm:
        return {'success': True, 'order_id': 'DRY_RUN', 'error': ''}

    # Get precision
    market_info = client.get_market_info(pair)
    if market_info:
        precision = int(market_info.get('amount_precision', 8))
        qty = round(qty, precision)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            order_id = client.place_market_sell(pair, qty)
            if order_id:
                # Poll for fill
                for _ in range(6):  # 30s total
                    time.sleep(5)
                    order = client.fetch_order(order_id, pair)
                    if order and order.get('status') == 'closed':
                        fill_price = order.get('average', 0) or order.get('price', 0)
                        fill_qty = order.get('filled', 0)
                        return {
                            'success': True,
                            'order_id': order_id,
                            'fill_price': fill_price,
                            'fill_qty': fill_qty,
                            'error': '',
                        }
                # Order placed but not confirmed filled
                return {
                    'success': True,
                    'order_id': order_id,
                    'fill_price': 0,
                    'fill_qty': 0,
                    'error': 'placed but fill unconfirmed (check manually)',
                }
            else:
                error = 'place_market_sell returned None'
        except Exception as e:
            error = str(e)

        if attempt < MAX_RETRIES:
            delay = RETRY_DELAY_S * (2 ** (attempt - 1))
            print(f'  ⚠️  Retry {attempt}/{MAX_RETRIES} in {delay}s: {error}')
            time.sleep(delay)

    return {'success': False, 'order_id': '', 'error': error}


def main():
    parser = argparse.ArgumentParser(description='Emergency Panic Sell — MEXC')
    parser.add_argument('--confirm', action='store_true',
                        help='Actually execute sells (default: dry run)')
    parser.add_argument('--force', action='store_true',
                        help='Sell ALL exchange balances (ignore state file)')
    args = parser.parse_args()

    print('='*60)
    print('  🚨 EMERGENCY PANIC SELL — MEXC')
    print(f'  Mode: {"🔴 LIVE SELL" if args.confirm else "🟡 DRY RUN"}')
    print(f'  Time: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}')
    print('='*60)

    # Connect to MEXC
    mexc_key = os.getenv('MEXC_API_KEY', '')
    mexc_secret = os.getenv('MEXC_SECRET_KEY', '') or os.getenv('MEXC_SECRET', '')
    if not mexc_key or not mexc_secret:
        print('❌ MEXC_API_KEY or MEXC_SECRET not set in .env')
        sys.exit(1)

    client = MEXCExchangeClient(api_key=mexc_key, secret=mexc_secret)
    if not client.test_connection():
        print('❌ MEXC connection failed')
        sys.exit(1)
    print('✅ MEXC connected\n')

    # Collect positions to sell
    sell_queue = []

    if args.force:
        # Mode: sell everything on exchange
        print('Mode: --force — scanning ALL exchange balances\n')
        balances = get_exchange_balances(client)
        for asset, amount in sorted(balances.items()):
            pair = f"{asset}/USDT"
            value = estimate_value_usd(client, asset, amount)
            if value >= DUST_THRESHOLD_USD:
                sell_queue.append({
                    'pair': pair,
                    'qty': amount,
                    'value_usd': value,
                    'source': 'exchange_balance',
                })
    else:
        # Mode: sell positions from state files
        state_files = find_state_files()
        if not state_files:
            print('⚠️  No live state files found.')
            print('   Use --force to sell based on exchange balances.')
            return

        for sf in state_files:
            positions = load_positions_from_state(sf)
            if positions:
                print(f'📄 State: {sf.name} — {len(positions)} open position(s)')
                for pos in positions:
                    pair = pos['pair']
                    # Check actual exchange balance
                    asset = pair.split('/')[0]
                    balances = get_exchange_balances(client)
                    actual_qty = balances.get(asset, 0)
                    value = estimate_value_usd(client, asset, actual_qty)

                    if value < DUST_THRESHOLD_USD:
                        print(f'  ⏭️  {pair}: balance ${value:.2f} < dust — already sold?')
                        continue

                    sell_queue.append({
                        'pair': pair,
                        'qty': actual_qty,
                        'value_usd': value,
                        'source': sf.name,
                        'entry_price': pos.get('entry_price', 0),
                    })

    if not sell_queue:
        print('\n✅ Nothing to sell — no positions above dust threshold.')
        return

    # Display sell plan
    total_value = sum(s['value_usd'] for s in sell_queue)
    print(f'\n📋 Sell Queue ({len(sell_queue)} positions, ~${total_value:.2f} total):')
    print(f'   {"Pair":<12} {"Qty":>12} {"Value":>10} {"Source"}')
    print(f'   {"─"*12} {"─"*12} {"─"*10} {"─"*20}')
    for s in sell_queue:
        print(f'   {s["pair"]:<12} {s["qty"]:>12.4f} ${s["value_usd"]:>8.2f} {s["source"]}')

    if not args.confirm:
        print(f'\n🟡 DRY RUN — no sells executed.')
        print(f'   Add --confirm to execute.')
        return

    # Execute sells
    print(f'\n🔴 EXECUTING SELLS...\n')
    results = []
    for s in sell_queue:
        print(f'  Selling {s["pair"]} qty={s["qty"]:.4f} (~${s["value_usd"]:.2f})...')
        result = sell_position(client, s['pair'], s['qty'], confirm=True)
        results.append({**s, **result})

        if result['success']:
            fill_info = ''
            if result.get('fill_price'):
                fill_info = f' @ ${result["fill_price"]:.6f}'
            print(f'    ✅ Sold{fill_info} — order {result["order_id"]}')
            if result.get('error'):
                print(f'    ⚠️  {result["error"]}')
        else:
            print(f'    ❌ FAILED: {result["error"]}')

    # Summary
    n_ok = sum(1 for r in results if r['success'])
    n_fail = len(results) - n_ok
    print(f'\n{"="*60}')
    print(f'  Sold: {n_ok}/{len(results)}' +
          (f' | ❌ Failed: {n_fail}' if n_fail else ''))
    print(f'  Total value: ~${total_value:.2f}')
    if n_fail:
        print(f'\n  ⚠️  MANUAL ACTION NEEDED for failed sells!')
        for r in results:
            if not r['success']:
                print(f'    - {r["pair"]}: {r["error"]}')
    print(f'{"="*60}')

    # Save sell log
    log_path = BASE_DIR / 'logs' / f'panic_sell_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")}.json'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'mode': 'force' if args.force else 'state',
            'results': results,
        }, f, indent=2, default=str)
    print(f'\n📝 Log: {log_path}')


if __name__ == '__main__':
    main()

"""
Generic orderbook snapshot collector — exchange-parametric via ExchangeConfig.

Reuses proven logic from orderbook_collector.py (MEXC) but parameterized:
- Exchange config from exchange_config.py
- Coin selection from universe tiering JSON (fetch_markets-based, no string hacks)
- Fee snapshot + exchange_id in JSONL header record
- Rate limit + backoff + retry

Usage:
    python -m strategies.hf.screening.orderbook_collector_generic --exchange bybit --duration-hours 2.5
    python -m strategies.hf.screening.orderbook_collector_generic --exchange bybit --dry-run
    python -m strategies.hf.screening.orderbook_collector_generic --exchange bybit --quick-test
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Reference coins always included
_REFERENCE_COINS = ["BTC/USD", "ETH/USD"]


# ---------------------------------------------------------------------------
# Coin selection from universe JSON
# ---------------------------------------------------------------------------

def load_coin_selection(
    exchange_id: str,
    universe_label: str = "001",
    seed: int = 42,
    n_per_tier: int = 20,
) -> List[Dict[str, str]]:
    """Select coins for OB collection from universe tiering.

    Selection: 10 alphabetic + 10 random per tier + BTC + ETH = ~42 coins.
    Uses ccxt_symbol from symbol_map (no string-replace).

    Returns: [{"symbol": "ACH/USDT", "internal": "ACH/USD", "tier": "tier1"}, ...]
    """
    path = _PROJECT_ROOT / "reports" / "hf" / f"universe_tiering_{exchange_id}_{universe_label}.json"
    if not path.exists():
        print(f"[collector] Universe not found: {path}")
        print(f"[collector] Run: python -m strategies.hf.screening.universe_builder --exchange {exchange_id}")
        sys.exit(1)

    with open(path) as f:
        universe = json.load(f)

    symbol_map = universe.get("symbol_map", {})
    tier_breakdown = universe.get("tier_breakdown", {})
    result = []
    seen_internal = set()

    half = n_per_tier // 2

    for tier_num, tier_label in [("1", "tier1"), ("2", "tier2")]:
        coins = sorted(tier_breakdown.get(tier_num, {}).get("coins", []))
        first_n = coins[:half]

        remainder = coins[half:]
        rng = random.Random(seed)
        random_n = rng.sample(remainder, min(half, len(remainder)))

        selected = first_n + random_n
        for internal in selected:
            if internal in seen_internal:
                continue
            seen_internal.add(internal)

            info = symbol_map.get(internal, {})
            ccxt_sym = info.get("ccxt_symbol")
            if not ccxt_sym:
                base = internal.split("/")[0]
                ccxt_sym = f"{base}/USDT"

            result.append({
                "symbol": ccxt_sym,
                "internal": internal,
                "tier": tier_label,
            })

    # Reference coins
    for ref in _REFERENCE_COINS:
        if ref not in seen_internal:
            seen_internal.add(ref)
            info = symbol_map.get(ref, {})
            ccxt_sym = info.get("ccxt_symbol")
            if not ccxt_sym:
                base = ref.split("/")[0]
                ccxt_sym = f"{base}/USDT"
            result.append({
                "symbol": ccxt_sym,
                "internal": ref,
                "tier": "tier1",
            })

    return result


# ---------------------------------------------------------------------------
# Slippage computation (identical to orderbook_collector.py)
# ---------------------------------------------------------------------------

def compute_slippage_bps(
    levels: List[List[float]],
    notional_usd: float,
    mid_price: float,
    side: str = "buy",
) -> Optional[float]:
    """Walk the order book to fill notional_usd and compute slippage in bps."""
    if notional_usd <= 0:
        return 0.0
    if mid_price <= 0 or not levels:
        return None

    remaining = notional_usd
    for price, qty in levels:
        if price <= 0 or qty <= 0:
            continue
        level_usd = price * qty
        remaining -= min(remaining, level_usd)
        if remaining <= 0:
            break
    if remaining > 0:
        return None

    total_qty = 0.0
    remaining = notional_usd
    for price, qty in levels:
        if price <= 0 or qty <= 0:
            continue
        level_usd = price * qty
        fill_usd = min(remaining, level_usd)
        total_qty += fill_usd / price
        remaining -= fill_usd
        if remaining <= 0:
            break

    if total_qty <= 0:
        return None

    avg_price = notional_usd / total_qty
    if side == "buy":
        slippage_bps = (avg_price - mid_price) / mid_price * 10_000
    else:
        slippage_bps = (mid_price - avg_price) / mid_price * 10_000
    return round(slippage_bps, 2)


def is_valid_snapshot(bid1, ask1, spread_bps, bid_depth_usd, ask_depth_usd) -> bool:
    """Data quality filters (identical to orderbook_collector.py)."""
    if bid1 >= ask1:
        return False
    if spread_bps > 5000:
        return False
    if bid_depth_usd < 10 or ask_depth_usd < 10:
        return False
    return True


def collect_snapshot(exchange, coin_info: dict) -> Optional[dict]:
    """Fetch orderbook for one coin and compute metrics."""
    symbol = coin_info["symbol"]
    ob = exchange.fetch_order_book(symbol, limit=20)
    bids = ob.get("bids", [])
    asks = ob.get("asks", [])

    if not bids or not asks:
        return None

    bid1 = bids[0][0]
    ask1 = asks[0][0]
    mid = (bid1 + ask1) / 2.0
    if mid <= 0:
        return None

    spread_bps = (ask1 - bid1) / mid * 10_000
    bid_depth_usd = sum(p * q for p, q in bids)
    ask_depth_usd = sum(p * q for p, q in asks)

    if not is_valid_snapshot(bid1, ask1, spread_bps, bid_depth_usd, ask_depth_usd):
        return None

    slippage_200 = compute_slippage_bps(asks, 200.0, mid, "buy")
    slippage_500 = compute_slippage_bps(asks, 500.0, mid, "buy")
    slippage_2000 = compute_slippage_bps(asks, 2000.0, mid, "buy")

    return {
        "ts": int(time.time()),
        "symbol": symbol,
        "internal": coin_info["internal"],
        "tier": coin_info["tier"],
        "bid1": bid1,
        "ask1": ask1,
        "spread_bps": round(spread_bps, 2),
        "mid": round(mid, 8),
        "slippage_200_bps": slippage_200,
        "slippage_500_bps": slippage_500,
        "slippage_2000_bps": slippage_2000,
        "bid_depth_usd": round(bid_depth_usd, 2),
        "ask_depth_usd": round(ask_depth_usd, 2),
        "bids_raw": bids,
        "asks_raw": asks,
    }


# ---------------------------------------------------------------------------
# Main collection loop
# ---------------------------------------------------------------------------

_SHUTDOWN = False


def _signal_handler(signum, frame):
    global _SHUTDOWN
    _SHUTDOWN = True
    print("\n[SIGINT] Graceful shutdown requested, finishing current cycle...")


def run_collector(
    exchange_cfg,
    coins: List[Dict[str, str]],
    output_path: str,
    duration_hours: float = 2.5,
    interval_seconds: float = 10.0,
    fee_snapshot=None,
) -> dict:
    """Run the orderbook collection loop.

    Writes a header record as first line with exchange_id and fee_snapshot.
    """
    global _SHUTDOWN

    exchange = exchange_cfg.create_ccxt_exchange()
    exchange.options["defaultType"] = "spot"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    start_time = time.time()
    end_time = start_time + duration_hours * 3600
    total_snapshots = 0
    total_errors = 0
    skipped_symbols: set = set()
    skipped_logged: set = set()

    print(f"[collector] Starting: {len(coins)} coins, {duration_hours}h, {interval_seconds}s interval")
    print(f"[collector] Exchange: {exchange_cfg.id} | Output: {output_path}")

    signal.signal(signal.SIGINT, _signal_handler)

    with open(output_path, "a") as f:
        # Write header record (first line)
        header = {
            "_header": True,
            "exchange_id": exchange_cfg.id,
            "start_ts": int(start_time),
            "coins": len(coins),
            "interval_s": interval_seconds,
            "duration_h": duration_hours,
        }
        if fee_snapshot:
            header["fee_snapshot"] = fee_snapshot.to_dict()
        f.write(json.dumps(header) + "\n")
        f.flush()

        while time.time() < end_time and not _SHUTDOWN:
            cycle_start = time.time()

            for coin_info in coins:
                if _SHUTDOWN:
                    break
                symbol = coin_info["symbol"]
                if symbol in skipped_symbols:
                    continue

                retries = 0
                max_retries = 3
                backoff = 1.0

                while retries < max_retries:
                    try:
                        snapshot = collect_snapshot(exchange, coin_info)
                        if snapshot is not None:
                            f.write(json.dumps(snapshot) + "\n")
                            total_snapshots += 1
                        break
                    except Exception as e:
                        err_name = type(e).__name__
                        if "BadSymbol" in err_name:
                            skipped_symbols.add(symbol)
                            if symbol not in skipped_logged:
                                print(f"[collector] Symbol not found on {exchange_cfg.id.upper()}: {symbol} -- skipping")
                                skipped_logged.add(symbol)
                            break
                        retries += 1
                        if retries < max_retries:
                            time.sleep(backoff)
                            backoff = min(backoff * 2, 30.0)
                        else:
                            total_errors += 1

                time.sleep(exchange_cfg.politeness_sleep_s)

            f.flush()

            if total_snapshots > 0 and total_snapshots % 200 == 0:
                elapsed = time.time() - start_time
                rate = total_snapshots / elapsed * 3600
                print(
                    f"[collector] {total_snapshots} snapshots | "
                    f"{total_errors} errors | {len(skipped_symbols)} skipped | "
                    f"{elapsed/3600:.1f}h elapsed | {rate:.0f}/hr"
                )

            cycle_elapsed = time.time() - cycle_start
            sleep_time = max(0, interval_seconds - cycle_elapsed)
            if sleep_time > 0 and not _SHUTDOWN:
                time.sleep(sleep_time)

    elapsed_total = time.time() - start_time
    summary = {
        "exchange_id": exchange_cfg.id,
        "total_snapshots": total_snapshots,
        "total_errors": total_errors,
        "skipped_symbols": sorted(skipped_symbols),
        "duration_hours": round(elapsed_total / 3600, 2),
        "coins_monitored": len(coins) - len(skipped_symbols),
        "shutdown_reason": "SIGINT" if _SHUTDOWN else "duration_complete",
    }

    print(f"\n[collector] Done: {total_snapshots} snapshots in {elapsed_total/3600:.2f}h")
    print(f"[collector] Errors: {total_errors}, Skipped: {len(skipped_symbols)}")

    summary_path = output_path.replace(".jsonl", "_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generic orderbook snapshot collector for HF cost analysis"
    )
    parser.add_argument(
        "--duration-hours", type=float, default=2.5,
        help="Collection duration in hours (default: 2.5)"
    )
    parser.add_argument(
        "--interval-seconds", type=float, default=10.0,
        help="Seconds between full collection cycles (default: 10)"
    )
    parser.add_argument(
        "--quick-test", action="store_true",
        help="Quick test: 5 coins, 60 seconds"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List selected coins only, no API calls"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSONL path (default: auto from exchange)"
    )
    parser.add_argument(
        "--universe-label", type=str, default="001",
        help="Universe tiering label (default: 001)"
    )

    from strategies.hf.screening.exchange_config import (
        add_exchange_args, build_fee_snapshot, get_exchange,
    )
    add_exchange_args(parser)

    args = parser.parse_args()
    exchange_cfg = get_exchange(args.exchange)
    fee_snap = build_fee_snapshot(args)

    # Resolve output path
    if args.output:
        output_path = args.output
    else:
        output_path = str(
            _PROJECT_ROOT / "data" / "orderbook_snapshots"
            / f"{exchange_cfg.id}_orderbook_001.jsonl"
        )

    # Load coins from universe
    coins = load_coin_selection(
        exchange_cfg.id, args.universe_label, seed=42,
    )

    if args.dry_run:
        print(f"[dry-run] Exchange: {exchange_cfg.id} | {len(coins)} coins selected:\n")
        for c in coins:
            print(f"  {c['symbol']:20s}  {c['internal']:20s}  {c['tier']}")
        print(f"\nT1: {sum(1 for c in coins if c['tier'] == 'tier1')}")
        print(f"T2: {sum(1 for c in coins if c['tier'] == 'tier2')}")
        return

    if args.quick_test:
        coins = coins[:5]
        args.duration_hours = 60.0 / 3600.0
        print(f"[quick-test] 5 coins, 60s")

    run_collector(
        exchange_cfg=exchange_cfg,
        coins=coins,
        output_path=output_path,
        duration_hours=args.duration_hours,
        interval_seconds=args.interval_seconds,
        fee_snapshot=fee_snap,
    )


if __name__ == "__main__":
    main()

"""
Live fill-rate test for HF 1H MEXC maker strategy.

PROJECT: HF-P2-LIVE-FILL — LIVE fill-rate validation ONLY, NOT paper trading.
Separate from MEXC-4H-PAPER (trading_bot/paper_mexc_4h.py / ADR-4H-015).

Places small ($10-50) maker limit buy orders on MEXC SPOT, measures fill rate,
and compares to fill_model_v3's theoretical predictions.

Motivation (ADR-HF-034, Risk #3):
  "Fill probability at scale: Bar-structure model shows 100% fill for maker
   regimes at these cost levels, but real queue dynamics may reduce fills."

This script validates that assumption with real money.

Design:
  1. Select coins from universe (same T1/T2 sampling as orderbook_collector)
  2. Per round: fetch orderbook, compute limit buy price, place limit buy
  3. Wait TTL (default 60s), check fill status
  4. Cancel if unfilled, sell if filled (recover capital)
  5. Log everything to JSONL + generate summary report
  6. Compare observed fill rate vs fill_model_v3 theoretical prediction

Safety:
  - Max order size: $50 (hard cap)
  - Max open exposure: $50 (hard cap)
  - Max concurrent orders: 1
  - Daily max orders: 50 (configurable)
  - Kill-switch: 3x consecutive API errors, 3x consecutive partials, cancel-fail
  - Emergency: SIGINT cancels all open orders before exit
  - Filled/partial positions are immediately sold back (market sell)

Usage:
    python -m strategies.hf.screening.live_fill_test --dry-run          # no orders, show plan
    python -m strategies.hf.screening.live_fill_test --rounds 5         # 5 test orders
    python -m strategies.hf.screening.live_fill_test --hours 2          # run for 2 hours
    python -m strategies.hf.screening.live_fill_test --report           # generate report from log
    python -m strategies.hf.screening.live_fill_test --checkpoint       # mid-run checkpoint analysis
    python -m strategies.hf.screening.live_fill_test --classify         # fillability tier classification
    python -m strategies.hf.screening.live_fill_test --rounds 50 --coin-filter reports/hf/fillable_universe_v1.json

Requires in .env:
    MEXC_API_KEY=your_key
    MEXC_SECRET=your_secret   (or MEXC_SECRET_KEY)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Paths (timestamped RUN_ID prevents log mixing across runs)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_UNIVERSE_PATH = _PROJECT_ROOT / "reports" / "hf" / "universe_tiering_001.json"
_RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
_DEFAULT_LOG = _PROJECT_ROOT / "reports" / "hf" / f"live_fill_test_{_RUN_ID}.jsonl"

# ---------------------------------------------------------------------------
# Safety constants
# ---------------------------------------------------------------------------

MAX_ORDER_USD = 50.0          # Hard cap per order
MIN_ORDER_USD = 5.0           # MEXC minimum
DEFAULT_ORDER_USD = 15.0      # Default order size
MAX_EXPOSURE_USD = 50.0       # Max open exposure at any time (hard cap)
MAX_TOTAL_RISK_USD = 500.0    # Max cumulative capital deployed (for long runs)
ORDER_TTL_SECONDS = 60.0      # Time to wait for fill before cancel
ROUND_PAUSE_SECONDS = 30.0    # Pause between rounds
MAX_SPREAD_BPS = 200.0        # Skip coins with spread > 200bps (2%)
DAILY_MAX_ORDERS = 50         # Max orders per 24h period
MAX_CONSECUTIVE_ERRORS = 3    # Kill-switch: consecutive API errors
MAX_CONSECUTIVE_PARTIALS = 3  # Kill-switch: consecutive partial fills
DUST_CAP_USD = 0.50           # Positions ≤ $0.50 are dust — not fatal, skip sell

# ---------------------------------------------------------------------------
# Coin selection (reuses orderbook_collector logic)
# ---------------------------------------------------------------------------

# NOTE: BTC/USDT and ETH/USDT return "symbol not support api" on MEXC spot API.
# HF strategy targets altcoins anyway, so no reference coins forced.
_REFERENCE_COINS: list = []


def _internal_to_ccxt(internal: str) -> str:
    return internal.replace("/USD", "/USDT")


def load_fill_test_coins(
    n_coins: int = 10,
    seed: int = 42,
    tiers: Tuple[str, ...] = ("1", "2"),
) -> List[Dict[str, str]]:
    """Select coins for fill testing from universe tiering.

    Picks n_coins randomly (seeded) from T1+T2, always includes BTC and ETH.
    """
    with open(_UNIVERSE_PATH, "r") as f:
        universe = json.load(f)

    tier_breakdown = universe["tier_breakdown"]
    all_coins = []
    for tier_num in tiers:
        for c in tier_breakdown.get(tier_num, {}).get("coins", []):
            all_coins.append((c, f"tier{tier_num}"))

    rng = random.Random(seed)
    rng.shuffle(all_coins)

    # Always include BTC and ETH at the front
    selected = []
    seen = set()
    for ref in _REFERENCE_COINS:
        if ref not in seen:
            seen.add(ref)
            selected.append({"symbol": _internal_to_ccxt(ref), "internal": ref, "tier": "tier1"})

    for internal, tier in all_coins:
        if internal not in seen and len(selected) < n_coins:
            seen.add(internal)
            selected.append({"symbol": _internal_to_ccxt(internal), "internal": internal, "tier": tier})

    return selected


# ---------------------------------------------------------------------------
# Fill model v3 theoretical prediction
# ---------------------------------------------------------------------------

def theoretical_fill_prob(
    low: float, high: float, limit_price: float, queue_factor: float = 0.7
) -> float:
    """Replicate fill_model_v3.bar_structure_fill_probability for comparison."""
    if low > limit_price:
        return 0.0
    bar_range = high - low
    if bar_range <= 0:
        return queue_factor
    penetration = (limit_price - low) / bar_range
    return queue_factor * min(1.0, penetration * 2.0)


# ---------------------------------------------------------------------------
# Pre-flight market validation
# ---------------------------------------------------------------------------

def _validate_coins_against_markets(
    exchange, coins: List[Dict[str, str]]
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """Filter coins that don't exist or aren't active on exchange.

    Uses exchange.markets dict (populated by load_markets()).
    Returns (valid_coins, invalid_coins).
    """
    valid, invalid = [], []
    for coin in coins:
        market = exchange.markets.get(coin["symbol"])
        if not market or not market.get("active", False):
            invalid.append(coin)
        else:
            valid.append(coin)
    return valid, invalid


# ---------------------------------------------------------------------------
# Checkpoint decision logic
# ---------------------------------------------------------------------------

def checkpoint_decision(touch_rate: float) -> str:
    """Return checkpoint decision based on actionable touch rate.

    touch_rate = (FILLED + PARTIAL) / actionable  [PRIMARY KPI]

    < 0.40  → RECONFIGURE (pricing/TTL must change)
    0.40-0.50 → WATCH (more data + activity filter needed)
    >= 0.50  → GO (proceed to paper trading)
    """
    if touch_rate < 0.40:
        return "RECONFIGURE"
    elif touch_rate < 0.50:
        return "WATCH"
    else:
        return "GO"


# ---------------------------------------------------------------------------
# Core fill test logic
# ---------------------------------------------------------------------------

_SHUTDOWN = False
_OPEN_ORDERS: List[dict] = []  # Track for emergency cleanup


def _signal_handler(signum, frame):
    global _SHUTDOWN
    _SHUTDOWN = True
    print("\n[SIGINT] Graceful shutdown — cancelling open orders...")


def _get_exchange():
    """Create authenticated CCXT MEXC exchange instance."""
    try:
        import ccxt
    except ImportError:
        raise ImportError("ccxt not installed. Run: pip install ccxt")

    api_key = os.getenv("MEXC_API_KEY", "")
    secret = os.getenv("MEXC_SECRET", "") or os.getenv("MEXC_SECRET_KEY", "")

    if not api_key or not secret:
        raise ValueError(
            "MEXC_API_KEY and MEXC_SECRET (or MEXC_SECRET_KEY) must be set in .env"
        )

    exchange = ccxt.mexc({
        "apiKey": api_key,
        "secret": secret,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    exchange.load_markets()
    return exchange


def _compute_limit_price(bid1: float, ask1: float, strategy: str = "near_bid") -> float:
    """Compute limit buy price based on strategy.

    Exact formulas (spread = ask1 - bid1):
      - 'below_bid': bid1 - spread * 0.50  (most passive, 50% below best bid)
      - 'near_bid':  bid1 + spread * 0.10  (slightly above bid, 10% into the spread)
      - 'mid':       (bid1 + ask1) / 2.0   (exact midpoint of best bid/ask)
      - 'near_ask':  ask1 - spread * 0.10  (most aggressive maker, 10% below ask)

    Example (bid=100.00, ask=100.20, spread=0.20):
      - below_bid:  99.90
      - near_bid:  100.02
      - mid:       100.10
      - near_ask:  100.18

    All strategies ensure we stay ON the bid side (maker, not taker).
    """
    mid = (bid1 + ask1) / 2.0
    spread = ask1 - bid1

    if strategy == "near_bid":
        # Place slightly above best bid — aggressive maker
        tick = spread * 0.1  # 10% of spread above bid
        return bid1 + tick
    elif strategy == "mid":
        return mid
    elif strategy == "below_bid":
        return bid1 - spread * 0.5
    elif strategy == "near_ask":
        # Place just below best ask — most aggressive maker
        tick = spread * 0.1  # 10% of spread below ask
        return ask1 - tick
    else:
        return bid1


def _compute_quantity(price: float, notional_usd: float, market_info: dict) -> Optional[float]:
    """Compute order quantity respecting exchange precision and minimums.

    Returns None if order would be below exchange minimums.
    """
    if price <= 0:
        return None

    raw_qty = notional_usd / price

    # Get precision from market info
    amount_precision = market_info.get("precision", {}).get("amount")
    min_amount = market_info.get("limits", {}).get("amount", {}).get("min")
    min_cost = market_info.get("limits", {}).get("cost", {}).get("min")

    # Apply precision
    if amount_precision is not None:
        if isinstance(amount_precision, int):
            raw_qty = round(raw_qty, amount_precision)
        else:
            # Some exchanges use step size
            raw_qty = math.floor(raw_qty / amount_precision) * amount_precision

    # Check minimums
    if min_amount and raw_qty < min_amount:
        return None
    if min_cost and raw_qty * price < min_cost:
        return None

    return raw_qty


def _safe_sell_back(exchange, symbol: str, qty: float, fill_price: float) -> dict:
    """Sell back filled/partial position with retries and dust handling.

    Uses CCXT amount_to_precision() for exchange-correct rounding.
    Pre-checks minimums to detect dust positions that cannot be sold.
    Retries up to 3x with exponential backoff + jitter.

    Returns dict with sell result fields (sell_price, sell_qty, sell_fee_cost, etc).
    If position is dust or all retries fail, sets WARNING or dust_remaining accordingly.
    """
    result: dict = {}
    market_info = exchange.markets.get(symbol, {})

    # 1. Apply CCXT amount precision (exchange-correct, replaces manual floor)
    try:
        qty = float(exchange.amount_to_precision(symbol, qty))
    except Exception:
        # Fallback: manual precision from market_info (same as _compute_quantity)
        amount_precision = market_info.get("precision", {}).get("amount")
        if amount_precision is not None:
            if isinstance(amount_precision, int):
                qty = math.floor(qty * 10**amount_precision) / 10**amount_precision
            else:
                qty = math.floor(qty / amount_precision) * amount_precision

    # 2. Pre-check minimums — if below, this is dust
    min_amount = market_info.get("limits", {}).get("amount", {}).get("min")
    min_cost = market_info.get("limits", {}).get("cost", {}).get("min")
    estimated_notional = qty * fill_price

    if qty <= 0:
        result["dust_remaining"] = True
        result["dust_notional"] = 0.0
        result["dust_reason"] = "zero_qty_after_precision"
        return result

    if (min_amount and qty < min_amount) or \
       (min_cost and estimated_notional < min_cost) or \
       estimated_notional <= DUST_CAP_USD:
        result["dust_remaining"] = True
        result["dust_notional"] = round(estimated_notional, 4)
        result["dust_reason"] = (
            "below_min_amount" if min_amount and qty < min_amount
            else "below_min_cost" if min_cost and estimated_notional < min_cost
            else "below_dust_cap"
        )
        return result

    # 3. Retry loop (3 attempts, exponential backoff + jitter)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            wait = 0.5 + attempt * 1.5 + random.uniform(0, 0.5)
            time.sleep(wait)
            sell_order = exchange.create_market_sell_order(symbol, qty)
            sell_id = sell_order.get("id", "")
            result["sell_order_id"] = sell_id
            result["sell_attempts"] = attempt + 1

            # Check execution
            time.sleep(2.0)
            try:
                sell_status = exchange.fetch_order(sell_id, symbol)
                sell_price = float(
                    sell_status.get("average", 0)
                    or sell_status.get("price", 0) or 0
                )
                sell_qty = float(sell_status.get("filled", 0) or 0)
                result["sell_price"] = sell_price
                result["sell_qty"] = sell_qty
                result["sell_notional"] = round(sell_qty * sell_price, 4)
                result["sell_status"] = sell_status.get("status", "unknown")
                sell_fees_raw = sell_status.get("fee", {})
                if sell_fees_raw and sell_fees_raw.get("cost"):
                    result["sell_fee_cost"] = float(sell_fees_raw["cost"])
                    result["sell_fee_currency"] = sell_fees_raw.get("currency", "")
            except Exception as e:
                result["sell_check_error"] = str(e)

            return result  # Success — exit retry loop

        except Exception as e:
            result["sell_error"] = str(e)
            result["sell_attempts"] = attempt + 1
            if attempt < max_retries - 1:
                continue

    # All retries failed — position open
    result["WARNING"] = "POSITION OPEN — manual close needed!"
    return result


def run_single_fill_test(
    exchange,
    coin_info: dict,
    order_usd: float = DEFAULT_ORDER_USD,
    ttl_seconds: float = ORDER_TTL_SECONDS,
    price_strategy: str = "near_bid",
    max_spread_bps: float = MAX_SPREAD_BPS,
) -> dict:
    """Execute one fill test: place limit buy, wait, check, cancel/sell.

    Returns a result dict with all timing and fill information.
    """
    symbol = coin_info["symbol"]
    result = {
        "ts": int(time.time()),
        "ts_iso": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "internal": coin_info["internal"],
        "tier": coin_info["tier"],
        "order_usd": order_usd,
        "price_strategy": price_strategy,
        "ttl_seconds": ttl_seconds,
    }

    # 1. Fetch orderbook (with retries + backoff)
    ob = None
    ob_error = None
    for ob_attempt in range(3):
        try:
            ob = exchange.fetch_order_book(symbol, limit=5)
            break
        except Exception as e:
            ob_error = str(e)
            if ob_attempt < 2:
                jitter = random.uniform(0, 0.5)
                time.sleep((2 ** ob_attempt) + jitter)  # ~1s, ~2s

    if ob is None:
        result["status"] = "ERROR_ORDERBOOK"
        result["error"] = ob_error
        result["ob_retries"] = 3
        # Classify error type for audit
        err_lower = (ob_error or "").lower()
        if "timeout" in err_lower or "rate" in err_lower or "429" in err_lower:
            result["error_type"] = "transient"
        elif "not found" in err_lower or "not support" in err_lower:
            result["error_type"] = "permanent"
        else:
            result["error_type"] = "unknown"
        return result

    if ob_attempt > 0:
        result["ob_retries"] = ob_attempt + 1

    bids = ob.get("bids", [])
    asks = ob.get("asks", [])

    if not bids or not asks:
        result["status"] = "ERROR_EMPTY_BOOK"
        return result

    bid1, ask1 = bids[0][0], asks[0][0]
    mid = (bid1 + ask1) / 2.0
    spread_bps = (ask1 - bid1) / mid * 10_000 if mid > 0 else 0

    result["bid1"] = bid1
    result["ask1"] = ask1
    result["mid"] = mid
    result["spread_bps"] = round(spread_bps, 2)

    # Safety: skip extreme spreads
    if spread_bps > max_spread_bps:
        result["status"] = "SKIPPED_SPREAD"
        return result

    # 2. Compute limit price
    limit_price = _compute_limit_price(bid1, ask1, price_strategy)
    result["limit_price"] = limit_price

    # Verify we're on maker side (below ask)
    if limit_price >= ask1:
        # Would cross the spread -> taker. Adjust to bid.
        limit_price = bid1
        result["limit_price"] = limit_price
        result["price_adjusted"] = True

    # 3. Compute quantity
    market_info = exchange.markets.get(symbol, {})
    qty = _compute_quantity(limit_price, order_usd, market_info)

    if qty is None or qty <= 0:
        result["status"] = "SKIPPED_MIN_SIZE"
        return result

    result["quantity"] = qty
    result["actual_notional"] = round(qty * limit_price, 4)

    # Apply exchange price precision
    price_precision = market_info.get("precision", {}).get("price")
    if price_precision is not None:
        if isinstance(price_precision, int):
            limit_price = round(limit_price, price_precision)
        result["limit_price_rounded"] = limit_price

    # Post-rounding maker safety: rounding can push price to ask -> taker
    if limit_price >= ask1:
        limit_price = bid1
        result["maker_safe_after_rounding"] = False
        result["WARNING"] = "Price rounding crossed spread — adjusted to bid"
    else:
        result["maker_safe_after_rounding"] = True

    # 4. Place limit buy order
    place_time = time.time()
    try:
        order = exchange.create_limit_buy_order(symbol, qty, limit_price)
    except Exception as e:
        result["status"] = "ERROR_PLACE"
        result["error"] = str(e)
        return result

    order_id = order.get("id", "")
    result["order_id"] = order_id
    result["place_ts"] = place_time

    # Track for emergency cleanup
    _OPEN_ORDERS.append({"order_id": order_id, "symbol": symbol})

    # 5. Wait and poll for fill
    filled = False
    fill_qty = 0.0
    fill_price = 0.0
    checks = 0
    poll_interval = min(10.0, ttl_seconds / 6)  # Check ~6 times during TTL

    while time.time() - place_time < ttl_seconds and not _SHUTDOWN:
        time.sleep(poll_interval)
        checks += 1

        try:
            status = exchange.fetch_order(order_id, symbol)
        except Exception as e:
            result["poll_error"] = str(e)
            continue

        order_status = status.get("status", "")
        fill_qty = float(status.get("filled", 0) or 0)
        fill_price = float(status.get("average", 0) or status.get("price", 0) or 0)

        if order_status == "closed":
            # Fully filled
            filled = True
            break
        elif order_status == "canceled" or order_status == "cancelled":
            # Externally cancelled
            result["status"] = "EXTERNALLY_CANCELLED"
            _OPEN_ORDERS[:] = [o for o in _OPEN_ORDERS if o["order_id"] != order_id]
            return result

    fill_time = time.time()
    result["wait_seconds"] = round(fill_time - place_time, 2)
    result["poll_checks"] = checks

    # 6. Cancel if not filled
    if not filled:
        try:
            exchange.cancel_order(order_id, symbol)
            result["cancelled"] = True
        except Exception as e:
            # May already be filled between last check and cancel
            result["cancel_error"] = str(e)
            # Re-check status
            try:
                status = exchange.fetch_order(order_id, symbol)
                if status.get("status") == "closed":
                    filled = True
                    fill_qty = float(status.get("filled", 0) or 0)
                    fill_price = float(status.get("average", 0) or status.get("price", 0) or 0)
            except Exception:
                pass

    # Remove from open orders tracker
    _OPEN_ORDERS[:] = [o for o in _OPEN_ORDERS if o["order_id"] != order_id]

    # Record fill result
    if filled and fill_qty > 0:
        result["status"] = "FILLED"
        result["fill_qty"] = fill_qty
        result["fill_price"] = fill_price
        result["fill_notional"] = round(fill_qty * fill_price, 4)

        # Slippage vs mid: how far fill deviated from mid at order time
        if mid > 0:
            result["slippage_vs_mid_bps"] = round(
                (fill_price - mid) / mid * 10_000, 2
            )  # Negative = filled below mid (good for buyer)

        # 7. Sell back immediately (centralized with retries + dust handling)
        sell_result = _safe_sell_back(exchange, symbol, fill_qty, fill_price)
        result.update(sell_result)
        if "sell_price" in sell_result and fill_price:
            result["roundtrip_pnl"] = round(
                (sell_result["sell_price"] - fill_price) * fill_qty, 4
            )
    elif fill_qty > 0:
        # Partial fill — always flatten immediately
        result["status"] = "PARTIAL"
        result["fill_qty"] = fill_qty
        result["fill_price"] = fill_price
        result["fill_notional"] = round(fill_qty * fill_price, 4)

        if mid > 0:
            result["slippage_vs_mid_bps"] = round(
                (fill_price - mid) / mid * 10_000, 2
            )

        # Sell partial fill (centralized with retries + dust handling)
        sell_result = _safe_sell_back(exchange, symbol, fill_qty, fill_price)
        result.update(sell_result)
        if "sell_price" in sell_result and fill_price:
            result["roundtrip_pnl"] = round(
                (sell_result["sell_price"] - fill_price) * fill_qty, 4
            )
    else:
        result["status"] = "MISSED"

    # 8. Theoretical fill prediction (for comparison)
    # We use the current bar's high/low as proxy (not perfect, but indicative)
    result["theoretical_fill_prob"] = round(
        theoretical_fill_prob(
            low=min(bid1, limit_price * 0.999),  # Approximate: bid is near low
            high=ask1,
            limit_price=limit_price,
            queue_factor=0.7,
        ), 4
    )

    return result


# ---------------------------------------------------------------------------
# Emergency cleanup
# ---------------------------------------------------------------------------

def _emergency_cancel_all(exchange):
    """Cancel all tracked open orders. Called on SIGINT."""
    for o in list(_OPEN_ORDERS):
        try:
            exchange.cancel_order(o["order_id"], o["symbol"])
            print(f"  Cancelled: {o['order_id']} ({o['symbol']})")
        except Exception as e:
            print(f"  Cancel failed for {o['order_id']}: {e}")
    _OPEN_ORDERS.clear()


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_fill_test(
    n_rounds: int = 10,
    order_usd: float = DEFAULT_ORDER_USD,
    ttl_seconds: float = ORDER_TTL_SECONDS,
    price_strategy: str = "near_bid",
    max_total_risk: float = MAX_TOTAL_RISK_USD,
    n_coins: int = 10,
    output_path: str = str(_DEFAULT_LOG),
    hours: Optional[float] = None,
    seed: int = 42,
    daily_max_orders: int = DAILY_MAX_ORDERS,
    kill_partials: int = MAX_CONSECUTIVE_PARTIALS,
    spread_cap: float = MAX_SPREAD_BPS,
    coins_override: Optional[List[Dict[str, str]]] = None,
) -> dict:
    """Run the full fill-rate test.

    Either runs n_rounds fixed rounds, or runs for `hours` duration (whichever
    comes first). Includes kill-switch for safety.
    """
    global _SHUTDOWN

    signal.signal(signal.SIGINT, _signal_handler)

    # Load .env (check project root first, then trading_bot/)
    for env_candidate in [_PROJECT_ROOT / ".env", _PROJECT_ROOT / "trading_bot" / ".env"]:
        if env_candidate.exists():
            for line in env_candidate.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    exchange = _get_exchange()

    if coins_override is not None:
        coins = coins_override
        print(f"[fill-test] Using coin filter: {len(coins)} coins from external list")
    else:
        coins = load_fill_test_coins(n_coins=n_coins, seed=seed)

    # Pre-flight: filter coins not available on exchange
    coins, invalid_coins = _validate_coins_against_markets(exchange, coins)
    if invalid_coins:
        print(f"[fill-test] {len(invalid_coins)} invalid symbols removed:")
        for c in invalid_coins:
            print(f"  ✗ {c['symbol']} ({c['tier']})")
    if not coins:
        print("[fill-test] ERROR: no valid coins remaining after market validation")
        return {}

    print(f"[fill-test] {len(coins)} valid coins, {n_rounds} rounds, ${order_usd}/order")
    print(f"[fill-test] Strategy: {price_strategy}, TTL: {ttl_seconds}s")
    print(f"[fill-test] Max exposure (concurrent): ${order_usd} (1 order at a time)")
    print(f"[fill-test] Max risk (cumulative budget): ${max_total_risk}")
    print(f"[fill-test] Daily max: {daily_max_orders}")
    print(f"[fill-test] Spread cap: {spread_cap} bps")
    partials_label = str(kill_partials) if kill_partials > 0 else "disabled"
    print(f"[fill-test] Kill-switch: {MAX_CONSECUTIVE_ERRORS} errors, "
          f"{partials_label} partials")
    print(f"[fill-test] Run ID: {_RUN_ID}")
    print(f"[fill-test] Output: {output_path}")

    # Ensure output dir
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    start_time = time.time()
    end_time = start_time + (hours * 3600) if hours else float("inf")
    total_deployed = 0.0
    results = []
    coin_idx = 0

    # Kill-switch counters
    consecutive_errors = 0
    consecutive_partials = 0
    daily_order_count = 0
    daily_reset_time = start_time + 86400  # Reset counter every 24h

    with open(output_path, "a") as f:
        for round_num in range(1, n_rounds + 1):
            if _SHUTDOWN:
                break
            if time.time() > end_time:
                print(f"[fill-test] Duration limit reached ({hours}h)")
                break
            if total_deployed + order_usd > max_total_risk:
                print(f"[fill-test] Risk limit reached "
                      f"(${total_deployed:.0f}/${max_total_risk:.0f})")
                break

            # Daily order cap (reset every 24h)
            if time.time() > daily_reset_time:
                daily_order_count = 0
                daily_reset_time = time.time() + 86400
                print(f"[fill-test] Daily counter reset")
            if daily_order_count >= daily_max_orders:
                wait_secs = daily_reset_time - time.time()
                print(f"[fill-test] Daily cap reached ({daily_max_orders}), "
                      f"sleeping {wait_secs/60:.0f}min until reset")
                # Sleep in chunks so SIGINT can interrupt
                while time.time() < daily_reset_time and not _SHUTDOWN:
                    time.sleep(min(60, daily_reset_time - time.time()))
                if _SHUTDOWN:
                    break
                daily_order_count = 0
                daily_reset_time = time.time() + 86400

            # Round-robin through coins
            coin = coins[coin_idx % len(coins)]
            coin_idx += 1

            print(
                f"\n[round {round_num}/{n_rounds}] "
                f"{coin['symbol']} ({coin['tier']}) — ${order_usd}"
            )

            result = run_single_fill_test(
                exchange=exchange,
                coin_info=coin,
                order_usd=order_usd,
                ttl_seconds=ttl_seconds,
                price_strategy=price_strategy,
                max_spread_bps=spread_cap,
            )

            result["round"] = round_num
            results.append(result)
            daily_order_count += 1

            # Log to file
            f.write(json.dumps(result) + "\n")
            f.flush()

            status = result.get("status", "UNKNOWN")
            rt_pnl = result.get("roundtrip_pnl", 0)
            spread = result.get("spread_bps", 0)

            print(f"  Status: {status} | Spread: {spread:.1f}bps", end="")
            if status == "FILLED":
                slip = result.get("slippage_vs_mid_bps", 0)
                print(f" | Fill: ${result.get('fill_notional', 0):.2f} "
                      f"| Slip: {slip:+.1f}bps | RT P&L: ${rt_pnl:.4f}")
                total_deployed += order_usd
                consecutive_errors = 0
                consecutive_partials = 0
            elif status == "PARTIAL":
                print(f" | Partial: {result.get('fill_qty', 0)}")
                total_deployed += result.get("fill_notional", order_usd)
                consecutive_errors = 0
                consecutive_partials += 1
            elif status == "MISSED":
                print(f" | MISSED")
                consecutive_errors = 0
                consecutive_partials = 0
            elif status.startswith("SKIPPED"):
                print(f" | {status}")
                consecutive_errors = 0
                consecutive_partials = 0
                daily_order_count -= 1  # Don't count skips against daily cap
            else:
                # ERROR status
                print(f" | {result.get('error', '')[:60]}")
                consecutive_errors += 1
                daily_order_count -= 1  # Don't count errors against daily cap

            # --- Kill-switch checks ---
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"\n[KILL-SWITCH] {consecutive_errors} consecutive API errors. "
                      f"Stopping.")
                result["kill_switch"] = "consecutive_errors"
                break

            if kill_partials > 0 and consecutive_partials >= kill_partials:
                print(f"\n[KILL-SWITCH] {consecutive_partials} consecutive partial "
                      f"fills. Stopping.")
                result["kill_switch"] = "consecutive_partials"
                break

            # Kill-switch: flatten-fail — only if exposure > dust cap after retries
            warn = result.get("WARNING", "")
            if warn.startswith("POSITION OPEN") or warn.startswith("PARTIAL POSITION OPEN"):
                open_notional = result.get("fill_notional", 0)
                if result.get("dust_remaining"):
                    print(f"  [DUST] ${result.get('dust_notional', 0):.4f} "
                          f"({result.get('dust_reason', '?')}). Continuing.")
                elif open_notional > DUST_CAP_USD:
                    print(f"\n[KILL-SWITCH] Open position ${open_notional:.2f} > "
                          f"dust cap ${DUST_CAP_USD}. Stopping.")
                    result["kill_switch"] = "flatten_failed"
                    break
                else:
                    print(f"  [DUST] ${open_notional:.4f} <= "
                          f"${DUST_CAP_USD}. Continuing.")
                    result["dust_remaining"] = True

            # --- Stop-early checkpoint at round 100 (expansion runs only) ---
            if round_num == 100 and len(coins) > 4:
                _ACTIONABLE = {"FILLED", "PARTIAL", "MISSED"}
                coin_touch: dict = {}
                for r in results:
                    s = r.get("symbol", "")
                    st = r.get("status", "")
                    if st in _ACTIONABLE:
                        if s not in coin_touch:
                            coin_touch[s] = {"n": 0, "touch": 0}
                        coin_touch[s]["n"] += 1
                        if st in ("FILLED", "PARTIAL"):
                            coin_touch[s]["touch"] += 1
                promising = sum(
                    1 for v in coin_touch.values()
                    if v["n"] >= 3 and v["touch"] / v["n"] >= 0.40
                )
                print(f"\n[CHECKPOINT 100] {promising} coins with touch >= 40% "
                      f"(gate: >= 3)")
                for sym, v in sorted(
                    coin_touch.items(),
                    key=lambda x: -x[1]["touch"] / max(x[1]["n"], 1),
                ):
                    tr = v["touch"] / v["n"] if v["n"] else 0
                    print(f"  {sym:15s} {v['touch']}/{v['n']} ({tr:.0%})")
                if promising < 3:
                    print("[STOP-EARLY] < 3 promising coins. "
                          "Stopping for reconfig.")
                    break

            # Pause between rounds
            if round_num < n_rounds and not _SHUTDOWN:
                time.sleep(ROUND_PAUSE_SECONDS)

    # Emergency cleanup
    if _OPEN_ORDERS:
        _emergency_cancel_all(exchange)

    # Generate summary
    summary = _generate_summary(results)
    summary["total_deployed_usd"] = round(total_deployed, 2)
    summary["duration_minutes"] = round((time.time() - start_time) / 60, 1)
    summary["daily_orders_placed"] = daily_order_count
    summary["kill_switch_triggered"] = results[-1].get("kill_switch") if results else None

    # Write summary
    report_path = output_path.replace(".jsonl", "_summary.json")
    with open(report_path, "w") as f:
        json.dump(summary, f, indent=2)

    _print_summary(summary)
    return summary


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple:
    """Wilson score interval for binomial proportion (95% CI by default).

    Returns (lower, upper) bounds. No continuity correction.
    """
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z ** 2 / n
    centre = p + z ** 2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2))
    return (round((centre - margin) / denom, 4), round((centre + margin) / denom, 4))


def _generate_summary(results: List[dict]) -> dict:
    """Generate summary statistics from test results."""
    total = len(results)
    if total == 0:
        return {"total": 0}

    filled = [r for r in results if r.get("status") == "FILLED"]
    partial = [r for r in results if r.get("status") == "PARTIAL"]
    missed = [r for r in results if r.get("status") == "MISSED"]
    skipped = [r for r in results if r.get("status", "").startswith("SKIPPED")]
    errors = [r for r in results if r.get("status", "").startswith("ERROR")]
    cancelled = [r for r in results if r.get("cancelled", False)]

    # Taker incidents: orders where rounding or pre-rounding pushed price to ask
    taker_incidents = sum(
        1 for r in results
        if r.get("maker_safe_after_rounding") is False or r.get("price_adjusted")
    )

    # Dust positions: sells skipped because position was below minimums/dust cap
    dust_positions = sum(1 for r in results if r.get("dust_remaining"))

    # Actionable orders = total - skipped - errors
    actionable = total - len(skipped) - len(errors)

    touch_rate = (len(filled) + len(partial)) / actionable if actionable > 0 else 0.0
    fill_rate = len(filled) / actionable if actionable > 0 else 0.0
    partial_rate = len(partial) / actionable if actionable > 0 else 0.0
    timeout_rate = len(missed) / actionable if actionable > 0 else 0.0
    cancelled_rate = len(cancelled) / actionable if actionable > 0 else 0.0

    # Roundtrip P&L
    rt_pnls = [r.get("roundtrip_pnl", 0) for r in (filled + partial)
               if "roundtrip_pnl" in r]
    total_rt_pnl = sum(rt_pnls)

    # Wait times for fills
    fill_wait_times = [r.get("wait_seconds", 0) for r in filled]
    avg_fill_wait = sum(fill_wait_times) / len(fill_wait_times) if fill_wait_times else 0

    # Spread statistics
    spreads = [r.get("spread_bps", 0) for r in results if "spread_bps" in r]
    avg_spread = sum(spreads) / len(spreads) if spreads else 0

    # Slippage vs mid (fills + partials only)
    slippages = [r.get("slippage_vs_mid_bps", 0) for r in (filled + partial)
                 if "slippage_vs_mid_bps" in r]
    avg_slippage = sum(slippages) / len(slippages) if slippages else 0

    # Flatten fees (sell-side taker fees = measurement overhead, NOT part of maker fill model)
    flatten_fees = sum(
        r.get("sell_fee_cost", 0) for r in (filled + partial)
        if "sell_fee_cost" in r
    )

    # Theoretical comparison
    theo_probs = [r.get("theoretical_fill_prob", 0) for r in results
                  if "theoretical_fill_prob" in r and r.get("status") in ("FILLED", "MISSED", "PARTIAL")]
    avg_theo_prob = sum(theo_probs) / len(theo_probs) if theo_probs else 0

    # Per-tier breakdown
    tier_stats = {}
    for tier in ("tier1", "tier2"):
        tier_results = [r for r in results if r.get("tier") == tier]
        tier_actionable = [r for r in tier_results if r.get("status") in ("FILLED", "MISSED", "PARTIAL")]
        tier_filled = [r for r in tier_actionable if r.get("status") == "FILLED"]
        tier_partial = [r for r in tier_actionable if r.get("status") == "PARTIAL"]
        tier_waits = [r.get("wait_seconds", 0) for r in tier_filled]
        tier_stats[tier] = {
            "total": len(tier_results),
            "actionable": len(tier_actionable),
            "filled": len(tier_filled),
            "partial": len(tier_partial),
            "touch_rate": round((len(tier_filled) + len(tier_partial)) / len(tier_actionable), 4) if tier_actionable else 0.0,
            "fill_rate": round(len(tier_filled) / len(tier_actionable), 4) if tier_actionable else 0.0,
            "avg_wait_seconds": round(sum(tier_waits) / len(tier_waits), 1) if tier_waits else 0,
        }

    # Per-coin breakdown
    coin_stats: Dict[str, dict] = {}
    for r in results:
        sym = r.get("symbol", "")
        if not sym:
            continue
        if sym not in coin_stats:
            coin_stats[sym] = {
                "tier": r.get("tier", ""),
                "total": 0, "filled": 0, "partial": 0, "missed": 0,
                "skipped": 0, "errors": 0,
                "fill_waits": [], "spreads": [], "slippages": [], "flatten_fees": [],
            }
        cs = coin_stats[sym]
        cs["total"] += 1
        st = r.get("status", "")
        if st == "FILLED":
            cs["filled"] += 1
            if "wait_seconds" in r:
                cs["fill_waits"].append(r["wait_seconds"])
            if "slippage_vs_mid_bps" in r:
                cs["slippages"].append(r["slippage_vs_mid_bps"])
        elif st == "PARTIAL":
            cs["partial"] += 1
        elif st == "MISSED":
            cs["missed"] += 1
        elif st.startswith("SKIPPED"):
            cs["skipped"] += 1
        elif st.startswith("ERROR"):
            cs["errors"] += 1
        if "spread_bps" in r:
            cs["spreads"].append(r["spread_bps"])
        if st in ("FILLED", "PARTIAL") and "sell_fee_cost" in r:
            cs["flatten_fees"].append(r["sell_fee_cost"])

    # Collapse lists into aggregates
    coin_summary = {}
    for sym, cs in coin_stats.items():
        act = cs["filled"] + cs["partial"] + cs["missed"]
        coin_summary[sym] = {
            "tier": cs["tier"],
            "total": cs["total"],
            "actionable": act,
            "filled": cs["filled"],
            "partial": cs["partial"],
            "missed": cs["missed"],
            "touch_rate": round((cs["filled"] + cs["partial"]) / act, 4) if act > 0 else 0.0,
            "fill_rate": round(cs["filled"] / act, 4) if act > 0 else 0.0,
            "avg_spread_bps": round(sum(cs["spreads"]) / len(cs["spreads"]), 2) if cs["spreads"] else 0,
            "avg_wait_seconds": round(sum(cs["fill_waits"]) / len(cs["fill_waits"]), 1) if cs["fill_waits"] else 0,
            "avg_slippage_bps": round(sum(cs["slippages"]) / len(cs["slippages"]), 2) if cs["slippages"] else 0,
            "total_flatten_fees": round(sum(cs["flatten_fees"]), 6) if cs["flatten_fees"] else 0,
            "partial_rate": round(cs["partial"] / act, 4) if act > 0 else 0.0,
        }
        # Add Wilson CI for touch and fill rates
        touch_count = cs["filled"] + cs["partial"]
        t_lo, t_hi = wilson_ci(touch_count, act)
        f_lo, f_hi = wilson_ci(cs["filled"], act)
        coin_summary[sym]["touch_ci_lower"] = t_lo
        coin_summary[sym]["touch_ci_upper"] = t_hi
        coin_summary[sym]["fill_ci_lower"] = f_lo
        coin_summary[sym]["fill_ci_upper"] = f_hi

    return {
        "total_rounds": total,
        "actionable": actionable,
        "filled": len(filled),
        "partial": len(partial),
        "missed": len(missed),
        "skipped": len(skipped),
        "errors": len(errors),
        "cancelled": len(cancelled),
        "touch_rate": round(touch_rate, 4),
        "fill_rate": round(fill_rate, 4),
        "partial_rate": round(partial_rate, 4),
        "timeout_rate": round(timeout_rate, 4),
        "cancelled_rate": round(cancelled_rate, 4),
        "avg_fill_wait_seconds": round(avg_fill_wait, 1),
        "avg_spread_bps": round(avg_spread, 2),
        "avg_slippage_vs_mid_bps": round(avg_slippage, 2),
        "total_flatten_fees_paid": round(flatten_fees, 6),
        "flatten_fees_note": "Sell-side taker fees are measurement overhead, not part of maker fill model",
        "total_roundtrip_pnl": round(total_rt_pnl, 4),
        "avg_roundtrip_pnl": round(total_rt_pnl / len(filled), 4) if filled else 0,
        "theoretical_avg_fill_prob": round(avg_theo_prob, 4),
        "model_vs_reality_delta": round(touch_rate - avg_theo_prob, 4) if theo_probs else None,
        "taker_incidents": taker_incidents,
        "dust_positions": dust_positions,
        "touch_ci_lower": wilson_ci(len(filled) + len(partial), actionable)[0] if actionable > 0 else 0.0,
        "touch_ci_upper": wilson_ci(len(filled) + len(partial), actionable)[1] if actionable > 0 else 0.0,
        "fill_ci_lower": wilson_ci(len(filled), actionable)[0] if actionable > 0 else 0.0,
        "fill_ci_upper": wilson_ci(len(filled), actionable)[1] if actionable > 0 else 0.0,
        "tier_breakdown": tier_stats,
        "coin_breakdown": coin_summary,
    }


def _print_summary(summary: dict):
    """Print human-readable summary."""
    print("\n" + "=" * 70)
    print("LIVE FILL-RATE TEST SUMMARY")
    print("=" * 70)
    print(f"  Rounds:       {summary['total_rounds']}")
    print(f"  Actionable:   {summary['actionable']}")
    print(f"  Filled:       {summary['filled']}")
    print(f"  Partial:      {summary['partial']}")
    print(f"  Missed:       {summary['missed']}")
    print(f"  Skipped:      {summary['skipped']}")
    print(f"  Errors:       {summary['errors']}")
    print(f"  Cancelled:    {summary.get('cancelled', 0)}")
    print(f"  Duration:     {summary.get('duration_minutes', '?')} min")
    ks = summary.get("kill_switch_triggered")
    if ks:
        print(f"  Kill-switch:  {ks}")

    print()
    print("--- Rates ---")
    t_lo = summary.get('touch_ci_lower', 0)
    t_hi = summary.get('touch_ci_upper', 0)
    f_lo = summary.get('fill_ci_lower', 0)
    f_hi = summary.get('fill_ci_upper', 0)
    print(f"  Touch rate:     {summary.get('touch_rate', 0):.1%}  95%CI [{t_lo:.1%}, {t_hi:.1%}]  (PRIMARY)")
    print(f"  Fill rate:      {summary['fill_rate']:.1%}  95%CI [{f_lo:.1%}, {f_hi:.1%}]  (secondary)")
    print(f"  Partial rate:   {summary['partial_rate']:.1%}")
    print(f"  Timeout rate:   {summary['timeout_rate']:.1%}")
    print(f"  Cancelled %:    {summary['cancelled_rate']:.1%}")

    print()
    print("--- Timing ---")
    print(f"  Avg fill wait:  {summary['avg_fill_wait_seconds']:.0f}s")

    print()
    print("--- Costs ---")
    print(f"  Avg spread:           {summary['avg_spread_bps']:.1f} bps")
    print(f"  Avg slippage vs mid:  {summary['avg_slippage_vs_mid_bps']:+.1f} bps")
    print(f"  Flatten fees (overhead): ${summary['total_flatten_fees_paid']:.4f}  "
          f"(sell-side taker, NOT maker model)")
    print(f"  Total RT P&L:         ${summary['total_roundtrip_pnl']:.4f}")
    print(f"  Avg RT P&L:           ${summary.get('avg_roundtrip_pnl', 0):.4f}")
    print(f"  Total deployed:       ${summary.get('total_deployed_usd', 0):.0f}")
    print(f"  Taker incidents:      {summary.get('taker_incidents', 0)}")
    print(f"  Dust positions:       {summary.get('dust_positions', 0)}")

    print()
    print("--- Model Comparison ---")
    print(f"  Theoretical avg fill prob: {summary['theoretical_avg_fill_prob']:.1%}")
    delta = summary.get('model_vs_reality_delta')
    if delta is not None:
        sign = "+" if delta >= 0 else ""
        print(f"  Model vs Reality delta:    {sign}{delta:.1%}")

    print()
    print("--- Tier Breakdown ---")
    for tier, stats in summary.get("tier_breakdown", {}).items():
        if stats["total"] > 0:
            print(f"  {tier}: {stats['filled']}/{stats['actionable']} filled "
                  f"({stats['fill_rate']:.0%}) | partial: {stats.get('partial', 0)} "
                  f"| avg wait: {stats.get('avg_wait_seconds', 0):.0f}s")

    print()
    print("--- Per-Coin Breakdown ---")
    coin_stats = summary.get("coin_breakdown", {})
    if coin_stats:
        # Sort by fill_rate descending
        for sym in sorted(coin_stats, key=lambda s: coin_stats[s]["fill_rate"], reverse=True):
            cs = coin_stats[sym]
            if cs["total"] == 0:
                continue
            ci_lo = cs.get('touch_ci_lower', 0)
            ci_hi = cs.get('touch_ci_upper', 0)
            print(f"  {sym:20s} {cs['tier']:7s} | "
                  f"{cs['filled']}/{cs['actionable']} fill "
                  f"({cs['fill_rate']:.0%}) | "
                  f"touch: {cs.get('touch_rate', 0):.0%} [{ci_lo:.0%}-{ci_hi:.0%}] | "
                  f"spread: {cs['avg_spread_bps']:.1f}bps | "
                  f"wait: {cs['avg_wait_seconds']:.0f}s | "
                  f"slip: {cs['avg_slippage_bps']:+.1f}bps | "
                  f"fees: ${cs.get('total_flatten_fees', 0):.4f}")

    print("=" * 70)


# ---------------------------------------------------------------------------
# Report generator (from existing log)
# ---------------------------------------------------------------------------

def generate_report(log_path: str) -> dict:
    """Generate report from existing JSONL log file."""
    results = []
    with open(log_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))

    summary = _generate_summary(results)
    _print_summary(summary)

    report_path = log_path.replace(".jsonl", "_summary.json")
    with open(report_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nReport saved to: {report_path}")
    return summary


# ---------------------------------------------------------------------------
# Checkpoint analyzer (mid-run diagnostics)
# ---------------------------------------------------------------------------

def checkpoint_report(log_path: str) -> dict:
    """Generate compact checkpoint report from JSONL log (mid-run).

    Reads existing log, computes actionable fill-rate excluding invalid
    symbols (ERROR_ORDERBOOK) and extreme spreads (SKIPPED_SPREAD),
    and returns a decision: RECONFIGURE / WATCH / CONTINUE.
    """
    results = []
    with open(log_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))

    if not results:
        print("[checkpoint] No data in log file.")
        return {"decision": "NO_DATA", "total_rounds": 0}

    # Classify rounds
    invalid_symbols = []
    extreme_spread = []
    filled = []
    missed = []
    other = []

    for r in results:
        st = r.get("status", "")
        sym = r.get("symbol", "?")
        if st == "ERROR_ORDERBOOK":
            invalid_symbols.append(sym)
        elif st == "SKIPPED_SPREAD":
            extreme_spread.append({
                "symbol": sym,
                "spread_bps": r.get("spread_bps", 0),
            })
        elif st == "FILLED":
            filled.append(r)
        elif st == "MISSED":
            missed.append(r)
        else:
            other.append(r)

    total = len(results)
    n_invalid = len(invalid_symbols)
    n_extreme = len(extreme_spread)
    n_filled = len(filled)
    n_missed = len(missed)
    n_partial = len([o for o in other if o.get("status") == "PARTIAL"])
    actionable = n_filled + n_missed + n_partial
    valid_rounds = total - n_invalid - n_extreme

    touch_rate = (n_filled + n_partial) / actionable if actionable > 0 else 0.0
    fill_rate = n_filled / actionable if actionable > 0 else 0.0
    decision = checkpoint_decision(touch_rate)

    # Avg spread on actionable rounds
    spreads = [r.get("spread_bps", 0) for r in filled + missed if r.get("spread_bps", 0) > 0]
    avg_spread = sum(spreads) / len(spreads) if spreads else 0.0

    # Model delta (vs touch_rate, primary KPI)
    theo_probs = [r.get("theoretical_fill_prob", 0) for r in filled + missed if "theoretical_fill_prob" in r]
    avg_theo = sum(theo_probs) / len(theo_probs) if theo_probs else 0.0
    model_delta = (touch_rate - avg_theo) if theo_probs else None

    # Unique invalid symbols
    unique_invalid = sorted(set(invalid_symbols))
    unique_extreme = sorted(set(e["symbol"] for e in extreme_spread))

    # Print compact checkpoint
    print()
    print(f"=== CHECKPOINT ({total} rounds) ===")
    print(f"  Valid rounds:   {valid_rounds}  (excl {n_invalid} invalid, {n_extreme} extreme_spread)")
    print(f"  Filled:         {n_filled:3d}")
    print(f"  Partial:        {n_partial:3d}")
    print(f"  Missed:         {n_missed:3d}")
    print(f"  Touch rate:     {touch_rate:.1%}  (PRIMARY: filled+partial / actionable)")
    print(f"  Fill rate:      {fill_rate:.1%}  (secondary: filled-only)")
    if unique_invalid:
        print(f"  Invalid coins:  {', '.join(unique_invalid)}")
    if unique_extreme:
        extreme_detail = ", ".join(
            f"{e['symbol']} ({e['spread_bps']:.0f}bps)"
            for e in extreme_spread[:5]
        )
        print(f"  Extreme spread: {extreme_detail}")
    print(f"  Avg spread:     {avg_spread:.1f} bps")
    if model_delta is not None:
        print(f"  Model delta:    {model_delta:+.1%}")
    print(f"  → DECISION: {decision} (touch_rate {touch_rate:.1%}"
          f" {'<' if touch_rate < 0.40 else ('<' if touch_rate < 0.50 else '≥')} "
          f"{'40%' if touch_rate < 0.40 else ('50%' if touch_rate < 0.50 else '50%')})")
    print()

    return {
        "total_rounds": total,
        "valid_rounds": valid_rounds,
        "actionable": actionable,
        "filled": n_filled,
        "partial": n_partial,
        "missed": n_missed,
        "touch_rate": round(touch_rate, 4),
        "fill_rate": round(fill_rate, 4),
        "avg_spread_bps": round(avg_spread, 2),
        "model_delta": round(model_delta, 4) if model_delta is not None else None,
        "invalid_symbols": unique_invalid,
        "extreme_spread_coins": unique_extreme,
        "decision": decision,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Live fill-rate test for MEXC maker limit orders"
    )
    parser.add_argument(
        "--rounds", type=int, default=300,
        help="Number of test rounds (default: 300 for statistical significance)"
    )
    parser.add_argument(
        "--order-usd", type=float, default=DEFAULT_ORDER_USD,
        help=f"Order size in USD (default: ${DEFAULT_ORDER_USD}, max: ${MAX_ORDER_USD})"
    )
    parser.add_argument(
        "--ttl", type=float, default=ORDER_TTL_SECONDS,
        help=f"Order TTL in seconds (default: {ORDER_TTL_SECONDS})"
    )
    parser.add_argument(
        "--strategy", choices=["near_bid", "mid", "below_bid", "near_ask"], default="near_bid",
        help="Limit price placement strategy (default: near_bid)"
    )
    parser.add_argument(
        "--max-risk", type=float, default=MAX_TOTAL_RISK_USD,
        help=f"Max total capital at risk (default: ${MAX_TOTAL_RISK_USD})"
    )
    parser.add_argument(
        "--coins", type=int, default=10,
        help="Number of coins to cycle through (default: 10)"
    )
    parser.add_argument(
        "--hours", type=float, default=None,
        help="Run for N hours (alternative to --rounds)"
    )
    parser.add_argument(
        "--output", type=str, default=str(_DEFAULT_LOG),
        help="Output JSONL path (default: timestamped reports/hf/live_fill_test_YYYYMMDD_HHMMSS.jsonl)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show plan without placing orders"
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Generate report from existing log file (use --output to specify log)"
    )
    parser.add_argument(
        "--checkpoint", action="store_true",
        help="Run checkpoint analysis on existing log (actionable fill-rate + decision)"
    )
    parser.add_argument(
        "--classify", action="store_true",
        help="Run fillability classification on existing log (tier A/B/C assignment)"
    )
    parser.add_argument(
        "--coin-filter", type=str, default=None,
        help="Path to fillable_universe JSON — use only filtered coins instead of random selection"
    )
    parser.add_argument(
        "--coin-filter-tiers", type=str, default="a",
        help="Which tiers to include from coin-filter: 'a', 'ab', 'abc' (default: 'a')"
    )
    parser.add_argument(
        "--daily-max", type=int, default=DAILY_MAX_ORDERS,
        help=f"Max orders per 24h period (default: {DAILY_MAX_ORDERS})"
    )
    parser.add_argument(
        "--kill-partials", type=int, default=MAX_CONSECUTIVE_PARTIALS,
        help=f"Kill-switch: max consecutive partials before stop (0=disable, default: {MAX_CONSECUTIVE_PARTIALS})"
    )
    parser.add_argument(
        "--spread-cap", type=float, default=MAX_SPREAD_BPS,
        help=f"Max spread in bps before SKIPPED_SPREAD (default: {MAX_SPREAD_BPS})"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for coin selection (default: 42)"
    )

    args = parser.parse_args()

    # Safety: cap order size
    if args.order_usd > MAX_ORDER_USD:
        print(f"[safety] Order size capped at ${MAX_ORDER_USD} (was ${args.order_usd})")
        args.order_usd = MAX_ORDER_USD
    if args.order_usd < MIN_ORDER_USD:
        print(f"[safety] Order size raised to ${MIN_ORDER_USD} minimum")
        args.order_usd = MIN_ORDER_USD

    if args.classify:
        from strategies.hf.screening.fillability_classifier import (
            classify_coins,
            print_classification,
            save_classification,
        )
        result = classify_coins(args.output)
        print_classification(result)
        # Save to reports/hf/fillable_universe_v1.json
        out_dir = Path(args.output).parent
        universe_path = str(out_dir / "fillable_universe_v1.json")
        save_classification(result, universe_path)
        print(f"Classification saved to: {universe_path}")
        return

    if args.checkpoint:
        checkpoint_report(args.output)
        return

    if args.report:
        generate_report(args.output)
        return

    if args.dry_run:
        if args.coin_filter:
            from strategies.hf.screening.fillability_classifier import load_coins_by_tiers
            tiers = tuple(args.coin_filter_tiers.lower())
            coins = load_coins_by_tiers(args.coin_filter, tiers=tiers)
            tier_label = "+".join(t.upper() for t in tiers)
            print(f"[dry-run] Coin filter: {len(coins)} Tier {tier_label} coins")
        else:
            coins = load_fill_test_coins(n_coins=args.coins, seed=args.seed)

        # Graceful online market validation
        validation_mode = "offline"
        invalid_coins = []
        try:
            # Load .env for exchange credentials
            for env_candidate in [_PROJECT_ROOT / ".env", _PROJECT_ROOT / "trading_bot" / ".env"]:
                if env_candidate.exists():
                    for line in env_candidate.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip())
            exchange = _get_exchange()
            coins, invalid_coins = _validate_coins_against_markets(exchange, coins)
            validation_mode = "online"
        except Exception as e:
            print(f"  [!] Market validation unavailable: {e}")

        est_hours = args.rounds * (args.ttl + ROUND_PAUSE_SECONDS) / 3600
        print(f"\n[dry-run] Fill Test Plan")
        print(f"  Rounds: {args.rounds}")
        print(f"  Order size: ${args.order_usd}")
        print(f"  TTL: {args.ttl}s")
        print(f"  Strategy: {args.strategy}")
        print(f"  Max exposure (concurrent): ${args.order_usd} (1 order at a time)")
        print(f"  Max risk (cumulative budget): ${args.max_risk}")
        print(f"  Daily max orders: {args.daily_max}")
        kp_label = str(args.kill_partials) if args.kill_partials > 0 else "disabled"
        print(f"  Kill-switch: {MAX_CONSECUTIVE_ERRORS} errors, "
              f"{kp_label} partials")
        print(f"  Spread cap: {args.spread_cap} bps")
        print(f"  Run ID: {_RUN_ID}")
        print(f"  Output: {args.output}")
        print(f"  Validation: {validation_mode}")
        if invalid_coins:
            sample = invalid_coins[:5]
            print(f"  Invalid symbols filtered: {len(invalid_coins)}")
            print(f"  Sample invalid: {[c['symbol'] for c in sample]}")
        print(f"  Coins ({len(coins)}):")
        for c in coins:
            print(f"    {c['symbol']:20s}  {c['tier']}")
        print(f"\n  Max capital needed: ${min(args.rounds * args.order_usd, args.max_risk):.0f}")
        print(f"  Estimated duration: {est_hours:.1f}h ({est_hours*60:.0f} min)")
        if args.rounds > args.daily_max:
            days_needed = math.ceil(args.rounds / args.daily_max)
            print(f"  Days needed (daily cap): {days_needed}")
        return

    # Load coin filter if provided
    coins_override = None
    if args.coin_filter:
        from strategies.hf.screening.fillability_classifier import load_coins_by_tiers
        tiers = tuple(args.coin_filter_tiers.lower())
        coins_override = load_coins_by_tiers(args.coin_filter, tiers=tiers)
        if not coins_override:
            print(f"[error] No coins found in tiers {tiers} from {args.coin_filter}")
            return
        tier_label = "+".join(t.upper() for t in tiers)
        print(f"[fill-test] Coin filter: {len(coins_override)} Tier {tier_label} coins "
              f"from {args.coin_filter}")

    # Run the test
    run_fill_test(
        n_rounds=args.rounds,
        order_usd=args.order_usd,
        ttl_seconds=args.ttl,
        price_strategy=args.strategy,
        max_total_risk=args.max_risk,
        n_coins=args.coins,
        output_path=args.output,
        hours=args.hours,
        seed=args.seed,
        daily_max_orders=args.daily_max,
        kill_partials=args.kill_partials,
        spread_cap=args.spread_cap,
        coins_override=coins_override,
    )


if __name__ == "__main__":
    main()

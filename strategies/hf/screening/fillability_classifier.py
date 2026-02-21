"""
Fillable Universe Classifier for HF-P2-LIVE-FILL.

Reads JSONL from live_fill_test.py, computes per-coin fillability metrics,
and assigns coins to tiers:
  - Tier A (Fillable):   touch_rate >= 0.50 AND n_actionable >= 30
  - Tier B (Marginal):   0.25 <= touch_rate < 0.50
  - Tier C (Unfillable): touch_rate < 0.25 OR n_actionable < 10

Error classification:
  - INVALID_SYMBOL:  coin that ALWAYS gets ERROR_ORDERBOOK (100% of appearances)
  - TRANSIENT_ERROR: sporadic ERROR_ORDERBOOK / ERROR_PLACE / ERROR_EMPTY_BOOK
  - EXTREME_SPREAD:  SKIPPED_SPREAD (not counted in actionable)

See ADR-HF-038 Iteration 4.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Tier thresholds
# ---------------------------------------------------------------------------

TIER_A_TOUCH_RATE = 0.50
TIER_B_TOUCH_RATE = 0.25
TIER_A_MIN_ACTIONABLE = 30

# Statuses that count as "actionable" (order was placed, result observed)
_ACTIONABLE_STATUSES = {"FILLED", "MISSED", "PARTIAL"}

# Statuses that are errors (transient)
_ERROR_STATUSES = {"ERROR_ORDERBOOK", "ERROR_PLACE", "ERROR_EMPTY_BOOK"}

# Statuses excluded from actionable AND error_rate
_EXCLUDED_STATUSES = {"SKIPPED_SPREAD", "SKIPPED_MIN_SIZE"}


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------

def classify_coins(log_path: str) -> dict:
    """Read JSONL, compute per-coin fillability, assign tiers.

    Args:
        log_path: Path to JSONL file from live_fill_test.py.

    Returns:
        {
            "tier_a": [{"symbol": ..., "touch_rate": ..., ...}],
            "tier_b": [...],
            "tier_c": [...],
            "invalid_symbols": [...],
            "summary": {
                "n_a": int, "n_b": int, "n_c": int,
                "n_invalid": int,
                "tier_a_touch_rate": float,
                "total_rounds": int,
            },
            "log_path": str,
        }
    """
    records = _read_jsonl(log_path)
    if not records:
        return {
            "tier_a": [], "tier_b": [], "tier_c": [],
            "invalid_symbols": [],
            "summary": {
                "n_a": 0, "n_b": 0, "n_c": 0, "n_invalid": 0,
                "tier_a_touch_rate": 0.0, "total_rounds": 0,
            },
            "log_path": log_path,
        }

    # Group records by symbol
    by_coin: Dict[str, List[dict]] = defaultdict(list)
    for r in records:
        sym = r.get("symbol", "UNKNOWN")
        by_coin[sym].append(r)

    # Step 1: Identify INVALID_SYMBOL coins (100% ERROR_ORDERBOOK)
    invalid_symbols = []
    valid_coins: Dict[str, List[dict]] = {}

    for sym, coin_records in by_coin.items():
        n_error_ob = sum(
            1 for r in coin_records if r.get("status") == "ERROR_ORDERBOOK"
        )
        if n_error_ob == len(coin_records):
            # Every single appearance is ERROR_ORDERBOOK → invalid symbol
            invalid_symbols.append(sym)
        else:
            valid_coins[sym] = coin_records

    # Step 2: Compute per-coin metrics for valid coins
    coin_metrics = []
    for sym, coin_records in valid_coins.items():
        metrics = _compute_coin_metrics(sym, coin_records)
        coin_metrics.append(metrics)

    # Step 3: Assign tiers
    tier_a = []
    tier_b = []
    tier_c = []

    for m in coin_metrics:
        if m["n_actionable"] < TIER_A_MIN_ACTIONABLE:
            tier_c.append(m)
        elif m["touch_rate"] >= TIER_A_TOUCH_RATE:
            tier_a.append(m)
        elif m["touch_rate"] >= TIER_B_TOUCH_RATE:
            tier_b.append(m)
        else:
            tier_c.append(m)

    # Sort each tier by touch_rate descending
    tier_a.sort(key=lambda x: x["touch_rate"], reverse=True)
    tier_b.sort(key=lambda x: x["touch_rate"], reverse=True)
    tier_c.sort(key=lambda x: x["touch_rate"], reverse=True)

    # Tier A aggregate touch_rate
    tier_a_actionable = sum(m["n_actionable"] for m in tier_a)
    tier_a_touches = sum(m["n_fills"] + m["n_partials"] for m in tier_a)
    tier_a_touch_rate = (
        tier_a_touches / tier_a_actionable if tier_a_actionable > 0 else 0.0
    )

    return {
        "tier_a": tier_a,
        "tier_b": tier_b,
        "tier_c": tier_c,
        "invalid_symbols": sorted(invalid_symbols),
        "summary": {
            "n_a": len(tier_a),
            "n_b": len(tier_b),
            "n_c": len(tier_c),
            "n_invalid": len(invalid_symbols),
            "tier_a_touch_rate": round(tier_a_touch_rate, 4),
            "total_rounds": len(records),
        },
        "log_path": log_path,
    }


def _compute_coin_metrics(symbol: str, records: List[dict]) -> dict:
    """Compute fillability metrics for a single coin."""
    n_fills = 0
    n_partials = 0
    n_misses = 0
    n_errors = 0
    n_excluded = 0
    wait_times: List[float] = []

    for r in records:
        st = r.get("status", "")
        if st == "FILLED":
            n_fills += 1
            if "wait_seconds" in r:
                wait_times.append(r["wait_seconds"])
        elif st == "PARTIAL":
            n_partials += 1
            if "wait_seconds" in r:
                wait_times.append(r["wait_seconds"])
        elif st == "MISSED":
            n_misses += 1
        elif st in _ERROR_STATUSES:
            n_errors += 1
        elif st in _EXCLUDED_STATUSES:
            n_excluded += 1

    n_actionable = n_fills + n_partials + n_misses
    touch_rate = (
        (n_fills + n_partials) / n_actionable if n_actionable > 0 else 0.0
    )
    full_fill_rate = n_fills / n_actionable if n_actionable > 0 else 0.0
    avg_wait_s = sum(wait_times) / len(wait_times) if wait_times else 0.0

    # Error rate: transient errors / total non-excluded rounds
    total_non_excluded = len(records) - n_excluded
    error_rate = n_errors / total_non_excluded if total_non_excluded > 0 else 0.0

    return {
        "symbol": symbol,
        "touch_rate": round(touch_rate, 4),
        "full_fill_rate": round(full_fill_rate, 4),
        "avg_wait_s": round(avg_wait_s, 2),
        "n_actionable": n_actionable,
        "n_fills": n_fills,
        "n_partials": n_partials,
        "n_misses": n_misses,
        "n_errors": n_errors,
        "n_excluded": n_excluded,
        "n_total": len(records),
        "error_rate": round(error_rate, 4),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_classification(result: dict) -> None:
    """Print compact fillability classification report."""
    s = result["summary"]
    print()
    print(f"=== FILLABILITY CLASSIFICATION ({s['total_rounds']} rounds) ===")
    print()

    # Invalid symbols
    if result["invalid_symbols"]:
        print(f"  INVALID SYMBOLS ({s['n_invalid']}): "
              f"{', '.join(result['invalid_symbols'])}")
        print()

    # Tier A
    print(f"  TIER A — Fillable ({s['n_a']} coins, "
          f"aggregate touch_rate={s['tier_a_touch_rate']:.1%})")
    if result["tier_a"]:
        print(f"    {'Symbol':<16s} {'Touch%':>7s} {'Fill%':>7s} "
              f"{'N':>4s} {'AvgWait':>8s} {'Err%':>6s}")
        for m in result["tier_a"]:
            print(f"    {m['symbol']:<16s} {m['touch_rate']:>6.1%} "
                  f"{m['full_fill_rate']:>6.1%} {m['n_actionable']:>4d} "
                  f"{m['avg_wait_s']:>7.1f}s {m['error_rate']:>5.1%}")
    else:
        print("    (none)")
    print()

    # Tier B
    print(f"  TIER B — Marginal ({s['n_b']} coins)")
    if result["tier_b"]:
        print(f"    {'Symbol':<16s} {'Touch%':>7s} {'Fill%':>7s} "
              f"{'N':>4s} {'AvgWait':>8s} {'Err%':>6s}")
        for m in result["tier_b"]:
            print(f"    {m['symbol']:<16s} {m['touch_rate']:>6.1%} "
                  f"{m['full_fill_rate']:>6.1%} {m['n_actionable']:>4d} "
                  f"{m['avg_wait_s']:>7.1f}s {m['error_rate']:>5.1%}")
    else:
        print("    (none)")
    print()

    # Tier C
    print(f"  TIER C — Unfillable ({s['n_c']} coins)")
    if result["tier_c"]:
        print(f"    {'Symbol':<16s} {'Touch%':>7s} {'Fill%':>7s} "
              f"{'N':>4s} {'Reason':>12s}")
        for m in result["tier_c"]:
            reason = ("low_n" if m["n_actionable"] < TIER_A_MIN_ACTIONABLE
                      else "low_touch")
            print(f"    {m['symbol']:<16s} {m['touch_rate']:>6.1%} "
                  f"{m['full_fill_rate']:>6.1%} {m['n_actionable']:>4d} "
                  f"{reason:>12s}")
    else:
        print("    (none)")
    print()

    # GO gate
    go = s["tier_a_touch_rate"] >= TIER_A_TOUCH_RATE
    print(f"  GO GATE: tier_a_touch_rate={s['tier_a_touch_rate']:.1%} "
          f"{'≥' if go else '<'} {TIER_A_TOUCH_RATE:.0%} → "
          f"{'GO ✓' if go else 'NO-GO ✗'}")
    print()


def save_classification(result: dict, output_path: str) -> str:
    """Save classification result to JSON file.

    Returns the path written to.
    """
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    return output_path


def load_tier_a_coins(filter_path: str) -> List[Dict[str, str]]:
    """Load Tier A coins from classification JSON for use as coin filter.

    Returns list of dicts compatible with live_fill_test coin format:
        [{"symbol": "VINE/USDT", "tier": "tier_a"}, ...]
    """
    return load_coins_by_tiers(filter_path, tiers=("a",))


def load_coins_by_tiers(
    filter_path: str,
    tiers: tuple = ("a",),
) -> List[Dict[str, str]]:
    """Load coins from specified tiers of classification JSON.

    Args:
        filter_path: Path to fillable_universe JSON.
        tiers: Tuple of tier letters to include, e.g. ("a",) or ("a", "b").

    Returns list of dicts compatible with live_fill_test coin format:
        [{"symbol": "VINE/USDT", "tier": "tier_a"}, ...]
    """
    with open(filter_path, "r") as f:
        data = json.load(f)

    coins = []
    tier_map = {"a": "tier_a", "b": "tier_b", "c": "tier_c"}
    for t in tiers:
        key = tier_map.get(t, f"tier_{t}")
        for m in data.get(key, []):
            sym = m["symbol"]
            # Derive internal symbol (VINE/USDT → VINE/USD) for live_fill_test compat
            internal = sym.replace("/USDT", "/USD") if "/USDT" in sym else sym
            coins.append({
                "symbol": sym,
                "internal": internal,
                "tier": key,
            })
    return coins


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_jsonl(path: str) -> List[dict]:
    """Read JSONL file into list of dicts."""
    records = []
    p = Path(path)
    if not p.exists():
        return records
    with open(p, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records

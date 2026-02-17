"""
Exchange universe builder — discovers tradeable coins and builds tier assignments.

Uses CCXT fetch_markets() + fetch_tickers() for proper symbol mapping.
No string-replace hacks: everything driven by market metadata.

Output schema is compatible with existing universe_tiering_001.json:
{
    "exchange": "bybit",
    "generated_at": "2026-02-16T...",
    "fee_snapshot": {...},
    "filters": {...},
    "tier_breakdown": {
        "1": {"coins": ["ACH/USD", ...], "count": 96},
        "2": {"coins": ["ADA/USD", ...], "count": 199}
    },
    "excluded": {"coins": [...], "count": ...},
    "symbol_map": {"ACH/USD": {"ccxt_symbol": "ACH/USDT", ...}, ...}
}

Usage:
    python -m strategies.hf.screening.universe_builder --exchange bybit
    python -m strategies.hf.screening.universe_builder --exchange okx --min-volume 100000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "reports" / "hf"


# ---------------------------------------------------------------------------
# Market discovery
# ---------------------------------------------------------------------------

def fetch_spot_markets(exchange_cfg) -> List[dict]:
    """Fetch all active SPOT markets for an exchange.

    Returns list of normalized market dicts:
    [
        {
            "ccxt_symbol": "ACH/USDT",
            "internal_symbol": "ACH/USD",
            "base": "ACH",
            "quote": "USDT",
            "active": True,
            "spot": True,
            "market_id": "ACHUSDT",  # exchange native ID
        },
        ...
    ]
    """
    exchange = exchange_cfg.create_ccxt_exchange()
    markets = exchange.load_markets()

    result = []
    for symbol, mkt in markets.items():
        # Filter: spot only, active, correct quote currency
        if mkt.get("type") != "spot":
            continue
        if not mkt.get("active", True):
            continue
        if mkt.get("quote") != exchange_cfg.quote_currency:
            continue

        base = mkt["base"]
        internal = f"{base}/USD"  # Our canonical format

        result.append({
            "ccxt_symbol": symbol,
            "internal_symbol": internal,
            "base": base,
            "quote": mkt["quote"],
            "active": True,
            "spot": True,
            "market_id": mkt.get("id", symbol),
        })

    print(f"[universe] {exchange_cfg.id}: {len(result)} active SPOT/{exchange_cfg.quote_currency} pairs found")
    return result


# ---------------------------------------------------------------------------
# Volume fetching
# ---------------------------------------------------------------------------

def fetch_volumes(exchange_cfg, markets: List[dict]) -> Dict[str, float]:
    """Fetch 24h USD volume for all markets.

    Returns: {internal_symbol: volume_usd_24h}
    """
    exchange = exchange_cfg.create_ccxt_exchange()

    # Try bulk fetch first (much faster)
    # Some exchanges (Bybit) return derivatives by default — force spot
    volumes = {}
    try:
        exchange.options["defaultType"] = "spot"
        tickers = exchange.fetch_tickers()
        for mkt in markets:
            ticker = tickers.get(mkt["ccxt_symbol"])
            if ticker:
                vol = ticker.get("quoteVolume") or 0.0
                volumes[mkt["internal_symbol"]] = vol
        print(f"[universe] Fetched volumes via bulk tickers: {len(volumes)} coins")
        return volumes
    except Exception as e:
        print(f"[universe] Bulk ticker fetch failed ({e}), falling back to per-coin...")

    # Fallback: per-coin fetch (slow but universal)
    for i, mkt in enumerate(markets):
        try:
            ticker = exchange.fetch_ticker(mkt["ccxt_symbol"])
            vol = ticker.get("quoteVolume") or 0.0
            volumes[mkt["internal_symbol"]] = vol
        except Exception:
            volumes[mkt["internal_symbol"]] = 0.0

        if (i + 1) % 50 == 0:
            print(f"[universe] Volume fetch progress: {i+1}/{len(markets)}")
        time.sleep(exchange_cfg.politeness_sleep_s)

    print(f"[universe] Fetched volumes per-coin: {len(volumes)} coins")
    return volumes


# ---------------------------------------------------------------------------
# Tiering
# ---------------------------------------------------------------------------

def _percentile(values: List[float], pct: int) -> float:
    """Compute percentile from sorted list."""
    if not values:
        return 0.0
    n = len(values)
    idx = min(int(n * pct / 100), n - 1)
    return values[idx]


def build_tiering(
    markets: List[dict],
    volumes: Dict[str, float],
    min_volume_usd: float = 8300.0,
    p75_tier1: bool = True,
) -> dict:
    """Assign tiers based on volume percentiles.

    Tier 1 (Liquid):   volume >= P75, zero_vol not checked (no candle data yet)
    Tier 2 (Mid):      volume >= P25 (or min_volume_usd)
    Tier 3 (Illiquid): below T2 → EXCLUDED

    Args:
        markets: from fetch_spot_markets()
        volumes: from fetch_volumes()
        min_volume_usd: minimum 24h volume to include (default: ~P25 from MEXC)
        p75_tier1: if True, use P75 for T1 cutoff; else use min_volume * 10

    Returns:
        Tier breakdown dict (compatible with universe_tiering_001.json schema)
    """
    # Filter by minimum volume
    eligible = []
    for mkt in markets:
        vol = volumes.get(mkt["internal_symbol"], 0.0)
        if vol >= min_volume_usd:
            eligible.append((mkt, vol))

    if not eligible:
        print(f"[universe] WARNING: 0 coins above min volume ${min_volume_usd}")
        return {
            "tier_breakdown": {
                "1": {"coins": [], "count": 0},
                "2": {"coins": [], "count": 0},
            },
            "excluded": {"coins": [], "count": 0},
            "symbol_map": {},
            "volume_stats": {"total_eligible": 0, "min_volume_usd": min_volume_usd},
        }

    # Sort by volume descending
    eligible.sort(key=lambda x: x[1], reverse=True)
    all_vols = sorted([v for _, v in eligible])

    # Compute P75 cutoff for T1
    p75_val = _percentile(all_vols, 75)
    print(f"[universe] {len(eligible)} coins above min vol ${min_volume_usd:.0f}")
    print(f"[universe] Volume P25=${_percentile(all_vols, 25):.0f} P50=${_percentile(all_vols, 50):.0f} P75=${p75_val:.0f}")

    t1_coins = []
    t2_coins = []
    excluded_coins = []
    symbol_map = {}

    for mkt, vol in eligible:
        internal = mkt["internal_symbol"]
        symbol_map[internal] = {
            "ccxt_symbol": mkt["ccxt_symbol"],
            "market_id": mkt["market_id"],
            "base": mkt["base"],
            "quote": mkt["quote"],
            "volume_usd_24h": round(vol, 2),
        }

        if vol >= p75_val:
            t1_coins.append(internal)
        else:
            t2_coins.append(internal)

    # Sort alphabetically within tiers for deterministic ordering
    t1_coins.sort()
    t2_coins.sort()

    print(f"[universe] Tier 1 (Liquid): {len(t1_coins)} coins (vol >= ${p75_val:.0f})")
    print(f"[universe] Tier 2 (Mid):    {len(t2_coins)} coins")

    return {
        "tier_breakdown": {
            "1": {"coins": t1_coins, "count": len(t1_coins)},
            "2": {"coins": t2_coins, "count": len(t2_coins)},
        },
        "excluded": {"coins": excluded_coins, "count": len(excluded_coins)},
        "symbol_map": symbol_map,
        "volume_stats": {
            "p25": round(_percentile(all_vols, 25), 2),
            "p50": round(_percentile(all_vols, 50), 2),
            "p75": round(p75_val, 2),
            "min_volume_usd": min_volume_usd,
            "total_eligible": len(eligible),
        },
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def save_universe(
    tiering: dict,
    exchange_cfg,
    fee_snapshot=None,
    output_dir: str = None,
    label: str = "001",
) -> str:
    """Save universe tiering to JSON file.

    Output: reports/hf/universe_tiering_{exchange}_001.json
    """
    if output_dir is None:
        output_dir = str(_DEFAULT_OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)

    output = {
        "exchange": exchange_cfg.id,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **tiering,
    }
    if fee_snapshot:
        output["fee_snapshot"] = fee_snapshot.to_dict()

    path = os.path.join(output_dir, f"universe_tiering_{exchange_cfg.id}_{label}.json")
    with open(path, "w") as f:
        json.dump(output, f, indent=2)

    t1 = tiering["tier_breakdown"]["1"]["count"]
    t2 = tiering["tier_breakdown"]["2"]["count"]
    print(f"[universe] Saved: {path} (T1={t1}, T2={t2}, total={t1+t2})")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build exchange-specific coin universe with tier assignments"
    )
    parser.add_argument(
        "--min-volume", type=float, default=8300.0,
        help="Minimum 24h USD volume for inclusion (default: 8300)"
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(_DEFAULT_OUTPUT_DIR),
        help=f"Output directory (default: {_DEFAULT_OUTPUT_DIR})"
    )
    parser.add_argument(
        "--label", type=str, default="001",
        help="Output label (default: 001)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show market count only, no volume fetch or output"
    )

    from strategies.hf.screening.exchange_config import (
        add_exchange_args, build_fee_snapshot, get_exchange,
    )
    add_exchange_args(parser)

    args = parser.parse_args()
    exchange_cfg = get_exchange(args.exchange)
    fee_snap = build_fee_snapshot(args)

    print(f"[universe] Exchange: {exchange_cfg.id} ({exchange_cfg.ccxt_id})")
    print(f"[universe] Fees: maker={fee_snap.maker_fee_bps}bps taker={fee_snap.taker_fee_bps}bps")

    # Step 1: Discover markets
    markets = fetch_spot_markets(exchange_cfg)

    if args.dry_run:
        print(f"\n[dry-run] {len(markets)} SPOT/{exchange_cfg.quote_currency} markets found")
        for m in markets[:20]:
            print(f"  {m['internal_symbol']:20s} -> {m['ccxt_symbol']:20s} ({m['market_id']})")
        if len(markets) > 20:
            print(f"  ... and {len(markets) - 20} more")
        return

    # Step 2: Fetch volumes
    volumes = fetch_volumes(exchange_cfg, markets)

    # Step 3: Build tiering
    tiering = build_tiering(markets, volumes, min_volume_usd=args.min_volume)

    # Step 4: Save
    path = save_universe(
        tiering=tiering,
        exchange_cfg=exchange_cfg,
        fee_snapshot=fee_snap,
        output_dir=args.output_dir,
        label=args.label,
    )


if __name__ == "__main__":
    main()

"""
Generic 1H OHLCV candle downloader via CCXT.

Downloads candles for all coins in a universe tiering JSON.
Uses ccxt_symbol from symbol_map (no string-replace hacks).
Writes per-coin JSON files + merged cache + coverage report.

Usage:
    python -m strategies.hf.screening.candle_downloader --exchange bybit
    python -m strategies.hf.screening.candle_downloader --exchange bybit --since 2025-06-01 --bars 721
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Universe loading
# ---------------------------------------------------------------------------

def load_universe(exchange_id: str, label: str = "001") -> dict:
    """Load universe tiering JSON for an exchange."""
    path = _PROJECT_ROOT / "reports" / "hf" / f"universe_tiering_{exchange_id}_{label}.json"
    if not path.exists():
        print(f"[candles] Universe file not found: {path}")
        print(f"[candles] Run: python -m strategies.hf.screening.universe_builder --exchange {exchange_id}")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def get_download_list(universe: dict) -> List[dict]:
    """Build list of coins to download with ccxt_symbol from symbol_map.

    Returns: [{"internal": "ACH/USD", "ccxt_symbol": "ACH/USDT", "tier": "tier1"}, ...]
    """
    symbol_map = universe.get("symbol_map", {})
    result = []
    for tier_num, tier_label in [("1", "tier1"), ("2", "tier2")]:
        coins = universe.get("tier_breakdown", {}).get(tier_num, {}).get("coins", [])
        for internal in coins:
            info = symbol_map.get(internal, {})
            ccxt_sym = info.get("ccxt_symbol")
            if not ccxt_sym:
                # Fallback: construct from internal (less reliable)
                base = internal.split("/")[0]
                ccxt_sym = f"{base}/USDT"
            result.append({
                "internal": internal,
                "ccxt_symbol": ccxt_sym,
                "tier": tier_label,
            })
    return result


# ---------------------------------------------------------------------------
# Candle download
# ---------------------------------------------------------------------------

def download_candles(
    exchange_cfg,
    coins: List[dict],
    since_ms: int,
    max_bars: int = 721,
    output_dir: str = None,
) -> dict:
    """Download 1H candles for all coins.

    Args:
        exchange_cfg: ExchangeConfig instance
        coins: from get_download_list()
        since_ms: start timestamp in milliseconds
        max_bars: maximum bars to fetch per coin
        output_dir: per-coin output directory

    Returns:
        Coverage stats dict
    """
    exchange = exchange_cfg.create_ccxt_exchange()
    exchange.options["defaultType"] = "spot"

    if output_dir is None:
        output_dir = str(_PROJECT_ROOT / "data" / "cache_parts_hf" / "1h" / exchange_cfg.id)
    os.makedirs(output_dir, exist_ok=True)

    stats = {
        "total": len(coins),
        "success": 0,
        "failed": 0,
        "skipped_existing": 0,
        "coverage": [],
    }

    for i, coin in enumerate(coins):
        internal = coin["internal"]
        ccxt_sym = coin["ccxt_symbol"]
        safe_name = internal.replace("/", "_")
        out_path = os.path.join(output_dir, f"{safe_name}.json")

        # Skip if already downloaded (resume support)
        if os.path.exists(out_path):
            try:
                with open(out_path) as f:
                    existing = json.load(f)
                if len(existing) >= max_bars * 0.9:
                    stats["skipped_existing"] += 1
                    stats["coverage"].append({
                        "internal": internal, "bars": len(existing),
                        "status": "cached",
                    })
                    continue
            except (json.JSONDecodeError, KeyError):
                pass  # Re-download

        # Fetch with pagination
        all_candles = []
        fetch_since = since_ms
        retries = 0

        while len(all_candles) < max_bars and retries < 5:
            try:
                ohlcv = exchange.fetch_ohlcv(
                    ccxt_sym, "1h", since=fetch_since,
                    limit=min(500, max_bars - len(all_candles)),
                )
                if not ohlcv:
                    break

                for row in ohlcv:
                    all_candles.append({
                        "timestamp": row[0],
                        "open": row[1],
                        "high": row[2],
                        "low": row[3],
                        "close": row[4],
                        "volume": row[5],
                    })

                # Next page: last timestamp + 1h
                fetch_since = ohlcv[-1][0] + 3600_000
                if len(ohlcv) < 100:
                    break  # No more data

                time.sleep(exchange_cfg.politeness_sleep_s)
                retries = 0

            except Exception as e:
                retries += 1
                if retries >= 5:
                    print(f"[candles] FAILED {ccxt_sym}: {e}")
                    stats["failed"] += 1
                    stats["coverage"].append({
                        "internal": internal, "bars": len(all_candles),
                        "status": "failed", "error": str(e),
                    })
                    break
                time.sleep(1.0 * retries)

        if retries < 5 and all_candles:
            # Deduplicate by timestamp
            seen_ts = set()
            deduped = []
            for c in all_candles:
                if c["timestamp"] not in seen_ts:
                    seen_ts.add(c["timestamp"])
                    deduped.append(c)
            all_candles = sorted(deduped, key=lambda x: x["timestamp"])

            # Trim to max_bars
            if len(all_candles) > max_bars:
                all_candles = all_candles[-max_bars:]

            with open(out_path, "w") as f:
                json.dump(all_candles, f)

            stats["success"] += 1
            stats["coverage"].append({
                "internal": internal, "bars": len(all_candles),
                "status": "ok",
                "first_ts": all_candles[0]["timestamp"],
                "last_ts": all_candles[-1]["timestamp"],
            })
        elif not all_candles and retries < 5:
            stats["failed"] += 1
            stats["coverage"].append({
                "internal": internal, "bars": 0, "status": "no_data",
            })

        if (i + 1) % 25 == 0:
            print(
                f"[candles] Progress: {i+1}/{len(coins)} | "
                f"OK={stats['success']} Failed={stats['failed']} "
                f"Cached={stats['skipped_existing']}"
            )

    return stats


# ---------------------------------------------------------------------------
# Merge into single cache file
# ---------------------------------------------------------------------------

def merge_cache(exchange_id: str, parts_dir: str = None) -> str:
    """Merge per-coin JSON files into one candle_cache_1h_{exchange}.json.

    Returns path to merged file.
    """
    if parts_dir is None:
        parts_dir = str(_PROJECT_ROOT / "data" / "cache_parts_hf" / "1h" / exchange_id)

    merged = {}
    for fname in sorted(os.listdir(parts_dir)):
        if not fname.endswith(".json") or fname == "manifest.json":
            continue
        internal = fname.replace(".json", "").replace("_", "/")
        fpath = os.path.join(parts_dir, fname)
        try:
            with open(fpath) as f:
                candles = json.load(f)
            if candles:
                merged[internal] = candles
        except (json.JSONDecodeError, IOError):
            pass

    out_path = str(_PROJECT_ROOT / "data" / f"candle_cache_1h_{exchange_id}.json")
    with open(out_path, "w") as f:
        json.dump(merged, f)

    total_bars = sum(len(v) for v in merged.values())
    print(f"[candles] Merged: {len(merged)} coins, {total_bars} total bars -> {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------

def print_coverage(stats: dict, exchange_id: str):
    """Print coverage summary."""
    coverage = stats.get("coverage", [])
    if not coverage:
        return

    bars_list = [c["bars"] for c in coverage if c.get("bars", 0) > 0]
    failed = [c for c in coverage if c["status"] in ("failed", "no_data")]

    print(f"\n--- Coverage Report ({exchange_id}) ---")
    print(f"  Total coins: {stats['total']}")
    print(f"  Success:     {stats['success']}")
    print(f"  Failed:      {stats['failed']}")
    print(f"  Cached:      {stats['skipped_existing']}")

    if bars_list:
        bars_list.sort()
        n = len(bars_list)
        print(f"  Bars: min={bars_list[0]} median={bars_list[n//2]} max={bars_list[-1]}")
        low_coverage = [c for c in coverage if 0 < c.get("bars", 0) < 500]
        if low_coverage:
            print(f"  Low coverage (<500 bars): {len(low_coverage)} coins")

    if failed:
        print(f"  Failed coins:")
        for c in failed[:10]:
            print(f"    {c['internal']}: {c.get('error', c['status'])}")

    # Save coverage report
    report_path = _PROJECT_ROOT / "reports" / "hf" / f"candle_coverage_{exchange_id}_001.json"
    os.makedirs(report_path.parent, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"  Report: {report_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download 1H candles for an exchange universe via CCXT"
    )
    parser.add_argument(
        "--since", type=str, default="2025-06-01",
        help="Start date for candle download (default: 2025-06-01)"
    )
    parser.add_argument(
        "--bars", type=int, default=721,
        help="Maximum bars per coin (default: 721)"
    )
    parser.add_argument(
        "--universe-label", type=str, default="001",
        help="Universe tiering label (default: 001)"
    )
    parser.add_argument(
        "--skip-merge", action="store_true",
        help="Skip merged cache creation"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show download plan only"
    )

    from strategies.hf.screening.exchange_config import add_exchange_args, get_exchange
    add_exchange_args(parser)

    args = parser.parse_args()
    exchange_cfg = get_exchange(args.exchange)

    print(f"[candles] Exchange: {exchange_cfg.id}")
    print(f"[candles] Since: {args.since} | Max bars: {args.bars}")

    # Load universe
    universe = load_universe(exchange_cfg.id, args.universe_label)
    coins = get_download_list(universe)
    print(f"[candles] Coins to download: {len(coins)}")

    if args.dry_run:
        for c in coins[:20]:
            print(f"  {c['internal']:20s} -> {c['ccxt_symbol']:20s} ({c['tier']})")
        if len(coins) > 20:
            print(f"  ... and {len(coins) - 20} more")
        return

    # Parse since date
    since_dt = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    since_ms = int(since_dt.timestamp() * 1000)

    # Download
    stats = download_candles(
        exchange_cfg=exchange_cfg,
        coins=coins,
        since_ms=since_ms,
        max_bars=args.bars,
    )

    # Coverage report
    print_coverage(stats, exchange_cfg.id)

    # Merge
    if not args.skip_merge:
        merge_cache(exchange_cfg.id)


if __name__ == "__main__":
    main()

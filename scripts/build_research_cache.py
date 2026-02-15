#!/usr/bin/env python3
"""
build_research_cache.py — Resumable, incremental cache builder for Cryptogem.

Fetches 4H OHLC candles from Kraken (USD pairs) and MEXC (USDT pairs),
saves per-coin JSON artifacts, and merges into one research cache.

Usage:
    python3 scripts/build_research_cache.py                        # resume, fetch all
    python3 scripts/build_research_cache.py --max-coins 200        # batch of 200
    python3 scripts/build_research_cache.py --max-runtime-seconds 300  # 5 min max
    python3 scripts/build_research_cache.py --force-rediscover     # re-discover pairs
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

AMS = ZoneInfo("Europe/Amsterdam")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PARTS_DIR = DATA_DIR / "cache_parts"
MANIFEST_PATH = DATA_DIR / "manifest.json"
FINAL_CACHE = DATA_DIR / "candle_cache_research_all.json"

RATE_LIMIT_KRAKEN = 1.1   # seconds between Kraken requests
RATE_LIMIT_MEXC = 0.3      # seconds between MEXC requests
MAX_RETRIES = 3
MIN_CANDLES = 30

# Kraken base name normalization
BASE_MAP = {
    "XBT": "BTC",
    "XETH": "ETH",
    "XDG": "DOGE",
    "XETC": "ETC",
    "XMLN": "MLN",
    "XREP": "REP",
    "XXLM": "XLM",
    "XXMR": "XMR",
    "XXRP": "XRP",
    "XZEC": "ZEC",
    "XLTC": "LTC",
}

# Exclude stablecoins, fiat, wrapped tokens
EXCLUDE_BASES = {
    # Stablecoins
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP", "GUSD", "FRAX",
    "LUSD", "SUSD", "MIM", "UST", "USTC", "USDD", "PYUSD", "FDUSD",
    "EURC", "EURT", "EURS",
    # Fiat
    "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "KRW", "CNY",
    # Wrapped
    "WBTC", "WETH", "WBNB", "WMATIC", "WAVAX", "WSOL", "WSTETH",
    "STETH", "CBETH", "RETH", "BETH",
}

EXCLUDE_QUOTES_KRAKEN = {"EUR", "GBP", "JPY", "CAD", "AUD", "CHF"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    tmp.replace(path)


def save_json_pretty(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    tmp.replace(path)


def now_ts():
    return int(time.time())


def now_ams_str():
    return datetime.now(AMS).strftime("%Y-%m-%d %H:%M CET")


def exponential_backoff(attempt: int) -> float:
    """Return sleep seconds for retry attempt (0-indexed)."""
    return min(2 ** (attempt + 1), 30)


# ---------------------------------------------------------------------------
# Exchange discovery
# ---------------------------------------------------------------------------

def discover_kraken_pairs() -> list[dict]:
    """
    Fetch active USD pairs from Kraken public API.
    Returns list of {symbol: 'BTC/USD', kraken_name: 'XXBTZUSD', exchange: 'kraken'}
    """
    import urllib.request

    url = "https://api.kraken.com/0/public/AssetPairs"
    req = urllib.request.Request(url, headers={"User-Agent": "CryptogemBot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())

    if data.get("error"):
        print(f"  [WARN] Kraken API errors: {data['error']}")

    pairs = []
    result = data.get("result", {})

    for kraken_name, info in result.items():
        # Skip darkpool pairs
        if kraken_name.startswith(".") or ".d" in kraken_name.lower():
            continue

        # Must be active
        if info.get("status") != "online":
            continue

        # Use wsname for clean base/quote extraction when available
        wsname = info.get("wsname", "")
        if wsname and "/" in wsname:
            base_raw, quote_raw = wsname.split("/", 1)
        else:
            # Fallback: use base and quote fields
            base_raw = info.get("base", "")
            quote_raw = info.get("quote", "")

        # Only USD quote pairs
        quote_norm = quote_raw.upper().strip()
        if quote_norm not in ("USD", "ZUSD"):
            continue

        # Normalize base
        base_norm = base_raw.upper().strip()
        # Remove leading X or Z from Kraken's internal naming
        base_norm = BASE_MAP.get(base_norm, base_norm)

        # Exclude stablecoins, fiat, wrapped
        if base_norm in EXCLUDE_BASES:
            continue

        symbol = f"{base_norm}/USD"
        pairs.append({
            "symbol": symbol,
            "kraken_name": kraken_name,
            "exchange": "kraken",
        })

    # Deduplicate by symbol (keep first occurrence)
    seen = set()
    unique = []
    for p in pairs:
        if p["symbol"] not in seen:
            seen.add(p["symbol"])
            unique.append(p)

    return unique


def discover_mexc_pairs() -> list[dict]:
    """
    Fetch active USDT spot pairs from MEXC via ccxt.
    Returns list of {symbol: 'BTC/USD', mexc_symbol: 'BTC/USDT', exchange: 'mexc'}
    """
    import ccxt

    exchange = ccxt.mexc({"enableRateLimit": True})
    markets = exchange.load_markets()

    pairs = []
    for mkt_symbol, mkt in markets.items():
        if mkt.get("type") != "spot":
            continue
        if not mkt.get("active", True):
            continue
        if mkt.get("quote") != "USDT":
            continue

        base = mkt.get("base", "").upper()
        if base in EXCLUDE_BASES:
            continue

        # Normalize to BASE/USD
        symbol = f"{base}/USD"
        pairs.append({
            "symbol": symbol,
            "mexc_symbol": mkt_symbol,  # e.g. 'BTC/USDT'
            "exchange": "mexc",
        })

    return pairs


def discover_all_pairs(force: bool = False) -> dict:
    """
    Discover pairs from both exchanges.
    Returns dict keyed by symbol: {symbol, exchange, kraken_name/mexc_symbol}
    Priority: Kraken first, MEXC for coins not on Kraken.
    """
    print("[DISCOVER] Fetching Kraken pairs...")
    kraken_pairs = discover_kraken_pairs()
    print(f"  Found {len(kraken_pairs)} Kraken USD pairs")

    print("[DISCOVER] Fetching MEXC pairs...")
    mexc_pairs = discover_mexc_pairs()
    print(f"  Found {len(mexc_pairs)} MEXC USDT pairs")

    # Merge: Kraken takes priority
    universe = {}
    for p in kraken_pairs:
        universe[p["symbol"]] = p
    for p in mexc_pairs:
        if p["symbol"] not in universe:
            universe[p["symbol"]] = p

    print(f"  Combined universe: {len(universe)} unique coins")
    return universe


# ---------------------------------------------------------------------------
# OHLC fetching
# ---------------------------------------------------------------------------

def fetch_kraken_ohlc(kraken_name: str) -> list[dict]:
    """Fetch 4H candles from Kraken. Returns list of candle dicts."""
    import urllib.request

    url = f"https://api.kraken.com/0/public/OHLC?pair={kraken_name}&interval=240"
    req = urllib.request.Request(url, headers={"User-Agent": "CryptogemBot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())

    if data.get("error") and len(data["error"]) > 0:
        raise RuntimeError(f"Kraken API error: {data['error']}")

    result = data.get("result", {})
    # The result has the pair data under the kraken_name key (and a 'last' key)
    candles_raw = None
    for key, val in result.items():
        if key == "last":
            continue
        if isinstance(val, list):
            candles_raw = val
            break

    if not candles_raw:
        return []

    candles = []
    for c in candles_raw:
        # [time, open, high, low, close, vwap, volume, count]
        candles.append({
            "time": int(c[0]),
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "vwap": float(c[5]),
            "volume": float(c[6]),
            "count": int(c[7]),
        })

    return candles


def fetch_mexc_ohlc(mexc_symbol: str) -> list[dict]:
    """Fetch 4H candles from MEXC via ccxt. Returns list of candle dicts."""
    import ccxt

    exchange = ccxt.mexc({"enableRateLimit": True})
    ohlcv = exchange.fetch_ohlcv(mexc_symbol, "4h", limit=720)

    candles = []
    for c in ohlcv:
        # [timestamp_ms, open, high, low, close, volume]
        candles.append({
            "time": int(c[0] / 1000),
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "vwap": 0.0,
            "volume": float(c[5]),
            "count": 0,
        })

    return candles


# ---------------------------------------------------------------------------
# Manifest management
# ---------------------------------------------------------------------------

def load_manifest() -> dict:
    return load_json(MANIFEST_PATH, {})


def save_manifest(manifest: dict):
    save_json(MANIFEST_PATH, manifest)


def init_manifest_entry(symbol: str, exchange: str, extra: dict = None) -> dict:
    entry = {
        "exchange": exchange,
        "status": "pending",
        "retries": 0,
        "bars": 0,
        "timestamp": 0,
    }
    if extra:
        entry.update(extra)
    return entry


# ---------------------------------------------------------------------------
# Core fetch logic
# ---------------------------------------------------------------------------

def fetch_and_save_coin(symbol: str, manifest_entry: dict) -> tuple[str, int]:
    """
    Fetch OHLC for one coin, save to per-coin JSON.
    Returns (status, bar_count).
    """
    exchange = manifest_entry["exchange"]
    kraken_name = manifest_entry.get("kraken_name", "")
    mexc_symbol = manifest_entry.get("mexc_symbol", "")

    if exchange == "kraken":
        candles = fetch_kraken_ohlc(kraken_name)
    elif exchange == "mexc":
        candles = fetch_mexc_ohlc(mexc_symbol)
    else:
        raise ValueError(f"Unknown exchange: {exchange}")

    if len(candles) < MIN_CANDLES:
        return "fail", len(candles)

    # Save per-coin file
    exchange_dir = PARTS_DIR / exchange
    safe_name = symbol.replace("/", "_")
    coin_path = exchange_dir / f"{safe_name}.json"
    save_json(coin_path, candles)

    return "done", len(candles)


def process_coin(symbol: str, manifest: dict) -> str:
    """
    Process a single coin with retry logic.
    Updates manifest in-place. Returns final status.
    """
    entry = manifest[symbol]
    exchange = entry["exchange"]
    attempt = entry.get("retries", 0)

    while attempt < MAX_RETRIES:
        try:
            status, bars = fetch_and_save_coin(symbol, entry)
            entry["status"] = status
            entry["bars"] = bars
            entry["timestamp"] = now_ts()
            entry["retries"] = attempt
            save_manifest(manifest)

            if status == "done":
                return "done"
            else:
                # Too few candles — won't improve with retry
                entry["status"] = "fail"
                entry["fail_reason"] = f"only {bars} candles (min {MIN_CANDLES})"
                save_manifest(manifest)
                return "fail"

        except Exception as e:
            attempt += 1
            entry["retries"] = attempt
            entry["last_error"] = str(e)[:200]

            if attempt < MAX_RETRIES:
                wait = exponential_backoff(attempt)
                print(f"    Retry {attempt}/{MAX_RETRIES} for {symbol} in {wait:.0f}s — {e}")
                time.sleep(wait)
            else:
                entry["status"] = "fail"
                entry["timestamp"] = now_ts()
                entry["fail_reason"] = str(e)[:200]
                save_manifest(manifest)
                return "fail"

    return "fail"


# ---------------------------------------------------------------------------
# Merge all per-coin JSONs into final cache
# ---------------------------------------------------------------------------

def merge_cache(manifest: dict):
    """Merge all 'done' per-coin JSONs into one final cache file."""
    print("\n[MERGE] Building final cache...")

    cache = {
        "_timestamp": now_ts(),
        "_date": now_ams_str(),
        "_universe": "research_all",
        "_sources": ["kraken", "mexc"],
        "_coins": 0,
    }

    done_count = 0
    for symbol, entry in sorted(manifest.items()):
        if entry.get("status") != "done":
            continue

        exchange = entry["exchange"]
        safe_name = symbol.replace("/", "_")
        coin_path = PARTS_DIR / exchange / f"{safe_name}.json"

        if not coin_path.exists():
            print(f"  [WARN] Missing file for {symbol}: {coin_path}")
            continue

        candles = load_json(coin_path, [])
        if len(candles) < MIN_CANDLES:
            continue

        cache[symbol] = candles
        done_count += 1

    cache["_coins"] = done_count
    print(f"  Merged {done_count} coins into {FINAL_CACHE.name}")

    save_json(FINAL_CACHE, cache)
    print(f"  File size: {FINAL_CACHE.stat().st_size / (1024*1024):.1f} MB")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run(args):
    start_time = time.time()

    # Ensure directories exist
    (PARTS_DIR / "kraken").mkdir(parents=True, exist_ok=True)
    (PARTS_DIR / "mexc").mkdir(parents=True, exist_ok=True)

    # Load or create manifest
    manifest = load_manifest()

    # Discover pairs if needed
    needs_discovery = (
        args.force_rediscover
        or len(manifest) == 0
    )

    if needs_discovery:
        universe = discover_all_pairs(force=args.force_rediscover)

        # Update manifest with new pairs (don't overwrite existing done/fail entries
        # unless force-rediscover)
        for symbol, pair_info in universe.items():
            if symbol not in manifest or args.force_rediscover:
                extra = {}
                if pair_info["exchange"] == "kraken":
                    extra["kraken_name"] = pair_info.get("kraken_name", "")
                elif pair_info["exchange"] == "mexc":
                    extra["mexc_symbol"] = pair_info.get("mexc_symbol", "")
                manifest[symbol] = init_manifest_entry(
                    symbol, pair_info["exchange"], extra
                )
            elif manifest[symbol].get("status") == "fail" and args.force_rediscover:
                # Reset failed entries on force-rediscover
                manifest[symbol]["status"] = "pending"
                manifest[symbol]["retries"] = 0

        save_manifest(manifest)
        print(f"  Manifest updated: {len(manifest)} total symbols")

    # Collect pending coins
    pending = [
        sym for sym, entry in manifest.items()
        if entry.get("status") == "pending"
    ]

    if args.max_coins and args.max_coins > 0:
        pending = pending[:args.max_coins]

    total_pending = len(pending)
    if total_pending == 0:
        print("\n[INFO] No pending coins to fetch.")
    else:
        print(f"\n[FETCH] Processing {total_pending} pending coins...")

    done_this_run = 0
    fail_this_run = 0
    skip_this_run = 0

    for i, symbol in enumerate(pending):
        # Check runtime limit
        if args.max_runtime_seconds and args.max_runtime_seconds > 0:
            elapsed = time.time() - start_time
            if elapsed >= args.max_runtime_seconds:
                print(f"\n[TIMEOUT] Reached {args.max_runtime_seconds}s limit after {i} coins.")
                break

        entry = manifest[symbol]
        exchange = entry["exchange"]
        pct = (i + 1) / total_pending * 100

        print(f"  [{i+1}/{total_pending}] ({pct:.0f}%) {symbol} ({exchange})...", end=" ", flush=True)

        status = process_coin(symbol, manifest)

        if status == "done":
            bars = entry.get("bars", 0)
            print(f"OK ({bars} bars)")
            done_this_run += 1
        else:
            reason = entry.get("fail_reason", "unknown")
            print(f"FAIL ({reason})")
            fail_this_run += 1

        # Rate limiting
        if exchange == "kraken":
            time.sleep(RATE_LIMIT_KRAKEN)
        elif exchange == "mexc":
            time.sleep(RATE_LIMIT_MEXC)

    # Final summary
    all_done = sum(1 for e in manifest.values() if e.get("status") == "done")
    all_fail = sum(1 for e in manifest.values() if e.get("status") == "fail")
    all_pending = sum(1 for e in manifest.values() if e.get("status") == "pending")

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"[SUMMARY] Elapsed: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  This run:  done={done_this_run}  fail={fail_this_run}")
    print(f"  Overall:   done={all_done}  fail={all_fail}  pending={all_pending}  total={len(manifest)}")
    print(f"{'='*60}")

    # Merge into final cache
    if all_done > 0:
        merge_cache(manifest)

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Resumable, incremental research cache builder for Cryptogem"
    )
    parser.add_argument(
        "--max-coins", type=int, default=0,
        help="Max new coins to fetch per run (0 = unlimited)"
    )
    parser.add_argument(
        "--max-runtime-seconds", type=int, default=0,
        help="Stop gracefully after N seconds (0 = unlimited)"
    )
    parser.add_argument(
        "--force-rediscover", action="store_true",
        help="Re-discover exchange pairs (reset pending/fail)"
    )
    args = parser.parse_args()

    try:
        sys.exit(run(args))
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Saving manifest and exiting...")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FATAL] {e}")
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()

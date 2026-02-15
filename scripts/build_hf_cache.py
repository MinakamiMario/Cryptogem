#!/usr/bin/env python3
"""
build_hf_cache.py — Paginated 1H/15m candle fetcher for HF research.

Fetches OHLC candles from Kraken (USD pairs) and MEXC (USDT pairs)
with pagination to cover 120+ days of history. Resumable via manifest.

Usage:
    python3 scripts/build_hf_cache.py --timeframe 1h
    python3 scripts/build_hf_cache.py --timeframe 15m
    python3 scripts/build_hf_cache.py --timeframe 1h --max-coins 50
    python3 scripts/build_hf_cache.py --timeframe 1h --max-runtime-seconds 600
    python3 scripts/build_hf_cache.py --timeframe 1h --force-rediscover

Outputs:
    data/candle_cache_1h.json   (or candle_cache_15m.json)
    data/manifest_hf_1h.json    (runtime, gitignored)
    reports/hf/data_manifest_1h.json  (committed snapshot)
"""

import argparse
import json
import os
import shutil
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
PARTS_DIR_BASE = DATA_DIR / "cache_parts_hf"
REPORTS_DIR = ROOT / "reports" / "hf"

RATE_LIMIT_KRAKEN = 1.1   # seconds between Kraken requests
RATE_LIMIT_MEXC = 0.3      # seconds between MEXC requests
MAX_RETRIES = 3
MIN_CANDLES = 30

# Kraken: max 720 candles per call
KRAKEN_MAX_CANDLES = 720

# Timeframe configs
TF_CONFIG = {
    "1h": {
        "kraken_interval": 60,       # minutes
        "mexc_timeframe": "1h",
        "interval_seconds": 3600,
        "target_days": 120,
        "expected_bars": 2880,       # 120 * 24
        "calls_needed": 4,           # ceil(2880 / 720)
        "cache_file": "candle_cache_1h.json",
        "manifest_file": "manifest_hf_1h.json",
    },
    "15m": {
        "kraken_interval": 15,       # minutes
        "mexc_timeframe": "15m",
        "interval_seconds": 900,
        "target_days": 120,
        "expected_bars": 11520,      # 120 * 24 * 4
        "calls_needed": 16,          # ceil(11520 / 720)
        "cache_file": "candle_cache_15m.json",
        "manifest_file": "manifest_hf_15m.json",
    },
}

# Reuse from build_research_cache.py
BASE_MAP = {
    "XBT": "BTC", "XETH": "ETH", "XDG": "DOGE", "XETC": "ETC",
    "XMLN": "MLN", "XREP": "REP", "XXLM": "XLM", "XXMR": "XMR",
    "XXRP": "XRP", "XZEC": "ZEC", "XLTC": "LTC",
}

EXCLUDE_BASES = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP", "GUSD", "FRAX",
    "LUSD", "SUSD", "MIM", "UST", "USTC", "USDD", "PYUSD", "FDUSD",
    "EURC", "EURT", "EURS",
    "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "KRW", "CNY",
    "WBTC", "WETH", "WBNB", "WMATIC", "WAVAX", "WSOL", "WSTETH",
    "STETH", "CBETH", "RETH", "BETH",
}


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
    return min(2 ** (attempt + 1), 30)


# ---------------------------------------------------------------------------
# Exchange discovery (reused from build_research_cache.py)
# ---------------------------------------------------------------------------

def discover_kraken_pairs() -> list:
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
        if kraken_name.startswith(".") or ".d" in kraken_name.lower():
            continue
        if info.get("status") != "online":
            continue
        wsname = info.get("wsname", "")
        if wsname and "/" in wsname:
            base_raw, quote_raw = wsname.split("/", 1)
        else:
            base_raw = info.get("base", "")
            quote_raw = info.get("quote", "")
        quote_norm = quote_raw.upper().strip()
        if quote_norm not in ("USD", "ZUSD"):
            continue
        base_norm = base_raw.upper().strip()
        base_norm = BASE_MAP.get(base_norm, base_norm)
        if base_norm in EXCLUDE_BASES:
            continue
        symbol = f"{base_norm}/USD"
        pairs.append({"symbol": symbol, "kraken_name": kraken_name, "exchange": "kraken"})
    seen = set()
    unique = []
    for p in pairs:
        if p["symbol"] not in seen:
            seen.add(p["symbol"])
            unique.append(p)
    return unique


def discover_mexc_pairs() -> list:
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
        symbol = f"{base}/USD"
        pairs.append({"symbol": symbol, "mexc_symbol": mkt_symbol, "exchange": "mexc"})
    return pairs


def discover_all_pairs() -> dict:
    print("[DISCOVER] Fetching Kraken pairs...")
    kraken_pairs = discover_kraken_pairs()
    print(f"  Found {len(kraken_pairs)} Kraken USD pairs")
    print("[DISCOVER] Fetching MEXC pairs...")
    mexc_pairs = discover_mexc_pairs()
    print(f"  Found {len(mexc_pairs)} MEXC USDT pairs")
    universe = {}
    for p in kraken_pairs:
        universe[p["symbol"]] = p
    for p in mexc_pairs:
        if p["symbol"] not in universe:
            universe[p["symbol"]] = p
    print(f"  Combined universe: {len(universe)} unique coins")
    return universe


# ---------------------------------------------------------------------------
# Paginated OHLC fetching
# ---------------------------------------------------------------------------

def fetch_kraken_ohlc_paginated(kraken_name: str, tf_cfg: dict) -> list:
    """
    Fetch candles from Kraken with pagination.
    Kraken returns max 720 candles/call. Use `since` param to paginate.
    """
    import urllib.request

    interval = tf_cfg["kraken_interval"]
    target_bars = tf_cfg["expected_bars"]
    interval_sec = tf_cfg["interval_seconds"]

    # Start from (target_days + 5) days ago to have margin
    since_ts = now_ts() - (tf_cfg["target_days"] + 5) * 86400

    all_candles = []
    seen_ts = set()
    calls = 0
    max_calls = tf_cfg["calls_needed"] + 2  # margin

    while calls < max_calls:
        url = (
            f"https://api.kraken.com/0/public/OHLC"
            f"?pair={kraken_name}&interval={interval}&since={since_ts}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "CryptogemBot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())

        if data.get("error") and len(data["error"]) > 0:
            raise RuntimeError(f"Kraken API error: {data['error']}")

        result = data.get("result", {})
        candles_raw = None
        last_ts = None
        for key, val in result.items():
            if key == "last":
                last_ts = val
                continue
            if isinstance(val, list):
                candles_raw = val

        if not candles_raw:
            break

        new_count = 0
        for c in candles_raw:
            ts = int(c[0])
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
            all_candles.append({
                "time": ts,
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "vwap": float(c[5]),
                "volume": float(c[6]),
                "count": int(c[7]),
            })
            new_count += 1

        calls += 1

        # If we got fewer than 720 new candles, we've reached the end
        if new_count < 700:
            break

        # Advance since to last timestamp
        if last_ts:
            since_ts = int(last_ts)
        elif all_candles:
            since_ts = max(c["time"] for c in all_candles)
        else:
            break

        # Rate limit
        time.sleep(RATE_LIMIT_KRAKEN)

    # Sort by timestamp
    all_candles.sort(key=lambda c: c["time"])
    return all_candles


def fetch_mexc_ohlc_paginated(mexc_symbol: str, tf_cfg: dict) -> list:
    """
    Fetch candles from MEXC with pagination via ccxt.
    MEXC returns max 1000 candles/call.
    """
    import ccxt

    exchange = ccxt.mexc({"enableRateLimit": True})
    timeframe = tf_cfg["mexc_timeframe"]
    interval_ms = tf_cfg["interval_seconds"] * 1000
    target_bars = tf_cfg["expected_bars"]

    # Start from (target_days + 5) days ago
    since_ms = (now_ts() - (tf_cfg["target_days"] + 5) * 86400) * 1000

    all_candles = []
    seen_ts = set()
    max_calls = (target_bars // 1000) + 3

    for _ in range(max_calls):
        try:
            ohlcv = exchange.fetch_ohlcv(mexc_symbol, timeframe, since=since_ms, limit=1000)
        except Exception:
            break

        if not ohlcv:
            break

        new_count = 0
        for c in ohlcv:
            ts = int(c[0] / 1000)
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
            all_candles.append({
                "time": ts,
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "vwap": 0.0,
                "volume": float(c[5]),
                "count": 0,
            })
            new_count += 1

        if new_count < 900:
            break

        # Advance since to last candle + 1 interval
        last_ts_ms = max(c[0] for c in ohlcv)
        since_ms = last_ts_ms + interval_ms

        time.sleep(RATE_LIMIT_MEXC)

    all_candles.sort(key=lambda c: c["time"])
    return all_candles


# ---------------------------------------------------------------------------
# Manifest management
# ---------------------------------------------------------------------------

def manifest_path(tf: str) -> Path:
    return DATA_DIR / TF_CONFIG[tf]["manifest_file"]


def load_manifest(tf: str) -> dict:
    return load_json(manifest_path(tf), {})


def save_manifest_file(tf: str, manifest: dict):
    save_json(manifest_path(tf), manifest)


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

def fetch_and_save_coin(symbol: str, manifest_entry: dict, tf: str) -> tuple:
    """Fetch paginated OHLC for one coin, save to per-coin JSON."""
    exchange = manifest_entry["exchange"]
    tf_cfg = TF_CONFIG[tf]

    parts_dir = PARTS_DIR_BASE / tf / exchange
    parts_dir.mkdir(parents=True, exist_ok=True)

    if exchange == "kraken":
        kraken_name = manifest_entry.get("kraken_name", "")
        candles = fetch_kraken_ohlc_paginated(kraken_name, tf_cfg)
    elif exchange == "mexc":
        mexc_symbol = manifest_entry.get("mexc_symbol", "")
        candles = fetch_mexc_ohlc_paginated(mexc_symbol, tf_cfg)
    else:
        raise ValueError(f"Unknown exchange: {exchange}")

    if len(candles) < MIN_CANDLES:
        return "fail", len(candles)

    safe_name = symbol.replace("/", "_")
    coin_path = parts_dir / f"{safe_name}.json"
    save_json(coin_path, candles)

    return "done", len(candles)


def process_coin(symbol: str, manifest: dict, tf: str) -> str:
    """Process a single coin with retry logic."""
    entry = manifest[symbol]
    attempt = entry.get("retries", 0)

    while attempt < MAX_RETRIES:
        try:
            status, bars = fetch_and_save_coin(symbol, entry, tf)
            entry["status"] = status
            entry["bars"] = bars
            entry["timestamp"] = now_ts()
            entry["retries"] = attempt
            save_manifest_file(tf, manifest)

            if status == "done":
                return "done"
            else:
                entry["status"] = "fail"
                entry["fail_reason"] = f"only {bars} candles (min {MIN_CANDLES})"
                save_manifest_file(tf, manifest)
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
                save_manifest_file(tf, manifest)
                return "fail"

    return "fail"


# ---------------------------------------------------------------------------
# Merge all per-coin JSONs into final cache
# ---------------------------------------------------------------------------

def merge_cache(manifest: dict, tf: str):
    """Merge all 'done' per-coin JSONs into one final cache file."""
    print("\n[MERGE] Building final cache...")

    tf_cfg = TF_CONFIG[tf]
    cache_path = DATA_DIR / tf_cfg["cache_file"]

    cache = {
        "_timestamp": now_ts(),
        "_date": now_ams_str(),
        "_universe": f"hf_{tf}_research",
        "_sources": ["kraken", "mexc"],
        "_timeframe": tf,
        "_interval_seconds": tf_cfg["interval_seconds"],
        "_coins": 0,
    }

    done_count = 0
    for symbol, entry in sorted(manifest.items()):
        if entry.get("status") != "done":
            continue

        exchange = entry["exchange"]
        safe_name = symbol.replace("/", "_")
        coin_path = PARTS_DIR_BASE / tf / exchange / f"{safe_name}.json"

        if not coin_path.exists():
            print(f"  [WARN] Missing file for {symbol}: {coin_path}")
            continue

        candles = load_json(coin_path, [])
        if len(candles) < MIN_CANDLES:
            continue

        cache[symbol] = candles
        done_count += 1

    cache["_coins"] = done_count
    print(f"  Merged {done_count} coins into {cache_path.name}")

    save_json(cache_path, cache)
    size_mb = cache_path.stat().st_size / (1024 * 1024)
    print(f"  File size: {size_mb:.1f} MB")


# ---------------------------------------------------------------------------
# Snapshot manifest to reports/hf/
# ---------------------------------------------------------------------------

def snapshot_manifest(tf: str, manifest: dict):
    """Copy manifest to reports/hf/data_manifest_{tf}.json for git commit."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = REPORTS_DIR / f"data_manifest_{tf}.json"

    # Build clean snapshot with summary
    all_done = sum(1 for e in manifest.values() if e.get("status") == "done")
    all_fail = sum(1 for e in manifest.values() if e.get("status") == "fail")
    all_pending = sum(1 for e in manifest.values() if e.get("status") == "pending")

    snapshot = {
        "_timestamp": now_ts(),
        "_date": now_ams_str(),
        "_timeframe": tf,
        "_summary": {
            "total": len(manifest),
            "done": all_done,
            "fail": all_fail,
            "pending": all_pending,
            "coverage_pct": round(100 * all_done / len(manifest), 1) if manifest else 0,
        },
        "coins": {},
    }

    for symbol, entry in sorted(manifest.items()):
        snapshot["coins"][symbol] = {
            "exchange": entry.get("exchange"),
            "status": entry.get("status"),
            "bars": entry.get("bars", 0),
        }

    save_json_pretty(snapshot_path, snapshot)
    print(f"\n[SNAPSHOT] Manifest saved to {snapshot_path}")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run(args):
    start_time = time.time()
    tf = args.timeframe
    tf_cfg = TF_CONFIG[tf]

    print(f"=== HF Cache Builder (timeframe={tf}) ===")
    print(f"  Interval: {tf_cfg['interval_seconds']}s ({tf_cfg['kraken_interval']}m)")
    print(f"  Target: ~{tf_cfg['expected_bars']} bars ({tf_cfg['target_days']} days)")
    print(f"  Kraken calls/coin: ~{tf_cfg['calls_needed']}")
    print()

    # Ensure directories
    for exch in ["kraken", "mexc"]:
        (PARTS_DIR_BASE / tf / exch).mkdir(parents=True, exist_ok=True)

    # Load or create manifest
    manifest = load_manifest(tf)

    # Discover pairs if needed
    needs_discovery = args.force_rediscover or len(manifest) == 0
    if needs_discovery:
        universe = discover_all_pairs()
        for symbol, pair_info in universe.items():
            if symbol not in manifest or args.force_rediscover:
                extra = {}
                if pair_info["exchange"] == "kraken":
                    extra["kraken_name"] = pair_info.get("kraken_name", "")
                elif pair_info["exchange"] == "mexc":
                    extra["mexc_symbol"] = pair_info.get("mexc_symbol", "")
                manifest[symbol] = init_manifest_entry(symbol, pair_info["exchange"], extra)
            elif manifest[symbol].get("status") == "fail" and args.force_rediscover:
                manifest[symbol]["status"] = "pending"
                manifest[symbol]["retries"] = 0

        save_manifest_file(tf, manifest)
        print(f"  Manifest updated: {len(manifest)} total symbols")

    # Collect pending coins
    pending = [sym for sym, entry in manifest.items() if entry.get("status") == "pending"]
    if args.max_coins and args.max_coins > 0:
        pending = pending[:args.max_coins]

    total_pending = len(pending)
    if total_pending == 0:
        print("\n[INFO] No pending coins to fetch.")
    else:
        print(f"\n[FETCH] Processing {total_pending} pending coins...")

    done_this_run = 0
    fail_this_run = 0

    for i, symbol in enumerate(pending):
        # Runtime limit
        if args.max_runtime_seconds and args.max_runtime_seconds > 0:
            elapsed = time.time() - start_time
            if elapsed >= args.max_runtime_seconds:
                print(f"\n[TIMEOUT] Reached {args.max_runtime_seconds}s limit after {i} coins.")
                break

        entry = manifest[symbol]
        exchange = entry["exchange"]
        pct = (i + 1) / total_pending * 100

        print(f"  [{i+1}/{total_pending}] ({pct:.0f}%) {symbol} ({exchange})...", end=" ", flush=True)

        status = process_coin(symbol, manifest, tf)

        if status == "done":
            bars = entry.get("bars", 0)
            print(f"OK ({bars} bars)")
            done_this_run += 1
        else:
            reason = entry.get("fail_reason", "unknown")
            print(f"FAIL ({reason})")
            fail_this_run += 1

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
        merge_cache(manifest, tf)

    # Snapshot manifest to reports/hf/ (for git commit)
    snapshot_manifest(tf, manifest)

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Paginated 1H/15m candle fetcher for HF research"
    )
    parser.add_argument(
        "--timeframe", "-tf", choices=["1h", "15m"], required=True,
        help="Timeframe to fetch (1h or 15m)"
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

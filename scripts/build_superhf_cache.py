#!/usr/bin/env python3
"""
build_superhf_cache.py — Download 15m + 1H MEXC candles for SuperHF research.

MEXC-only, top 200 coins by 24h volume, 120 days of history.
Outputs to ~/CryptogemData/derived/candle_cache/mexc/15m/ and /1h/

Usage:
    python3 scripts/build_superhf_cache.py                # Full run (15m + 1H)
    python3 scripts/build_superhf_cache.py --tf 15m       # 15m only
    python3 scripts/build_superhf_cache.py --tf 1h        # 1H only
    python3 scripts/build_superhf_cache.py --max-coins 50 # Limit coins
    python3 scripts/build_superhf_cache.py --max-runtime 1800  # 30 min limit
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
ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("DATA_ROOT", Path.home() / "CryptogemData"))

RATE_LIMIT = 0.35  # seconds between MEXC requests
MAX_RETRIES = 3
MIN_CANDLES = 100   # minimum usable bars

TF_CONFIG = {
    "15m": {
        "mexc_timeframe": "15m",
        "interval_seconds": 900,
        "target_days": 120,
        "expected_bars": 11520,     # 120 * 24 * 4
    },
    "1h": {
        "mexc_timeframe": "1h",
        "interval_seconds": 3600,
        "target_days": 120,
        "expected_bars": 2880,      # 120 * 24
    },
}

EXCLUDE_BASES = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP", "GUSD", "FRAX",
    "LUSD", "SUSD", "MIM", "UST", "USTC", "USDD", "PYUSD", "FDUSD",
    "EURC", "EURT", "EURS",
    "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "KRW", "CNY",
    "WBTC", "WETH", "WBNB", "WMATIC", "WAVAX", "WSOL", "WSTETH",
    "STETH", "CBETH", "RETH", "BETH",
}


def now_ts():
    return int(time.time())


def now_ams_str():
    return datetime.now(AMS).strftime("%Y-%m-%d %H:%M CET")


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


def load_json(path: Path, default=None):
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return default if default is not None else {}


# ---------------------------------------------------------------------------
# MEXC coin discovery — top 200 by volume
# ---------------------------------------------------------------------------

def discover_mexc_top200() -> list[dict]:
    """Discover top 200 MEXC SPOT USDT pairs by 24h volume."""
    import ccxt
    exchange = ccxt.mexc({"enableRateLimit": True})
    markets = exchange.load_markets()

    # Fetch tickers for volume ranking
    print("[DISCOVER] Fetching MEXC tickers for volume ranking...")
    tickers = exchange.fetch_tickers()

    pairs = []
    for symbol, mkt in markets.items():
        if mkt.get("type") != "spot" or not mkt.get("active", True):
            continue
        if mkt.get("quote") != "USDT":
            continue
        base = mkt.get("base", "").upper()
        if base in EXCLUDE_BASES:
            continue

        # Get 24h quote volume
        ticker = tickers.get(symbol, {})
        quote_vol = ticker.get("quoteVolume", 0) or 0

        pairs.append({
            "symbol": f"{base}/USD",
            "mexc_symbol": symbol,
            "base": base,
            "quote_volume_24h": float(quote_vol),
        })

    # Sort by volume descending, take top 200
    pairs.sort(key=lambda x: x["quote_volume_24h"], reverse=True)
    top200 = pairs[:200]

    print(f"  Found {len(pairs)} total MEXC USDT pairs")
    print(f"  Top 200 by volume selected")
    if top200:
        print(f"  Volume range: ${top200[0]['quote_volume_24h']:,.0f} — ${top200[-1]['quote_volume_24h']:,.0f}")

    return top200


# ---------------------------------------------------------------------------
# MEXC candle fetching with pagination
# ---------------------------------------------------------------------------

def fetch_mexc_ohlc(mexc_symbol: str, tf_cfg: dict) -> list[dict]:
    """Fetch paginated candles from MEXC via CCXT.

    MEXC returns max ~500 bars per call (not 1000).
    Pagination: advance `since` to last timestamp + interval.
    Stop when: no new candles, or target bars reached, or max calls.
    """
    import ccxt
    exchange = ccxt.mexc({"enableRateLimit": True})

    timeframe = tf_cfg["mexc_timeframe"]
    interval_ms = tf_cfg["interval_seconds"] * 1000
    target_bars = tf_cfg["expected_bars"]

    since_ms = (now_ts() - (tf_cfg["target_days"] + 5) * 86400) * 1000

    all_candles = []
    seen_ts = set()
    max_calls = (target_bars // 400) + 5  # ~500 per call, need target/400 calls + margin

    for call_num in range(max_calls):
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

        # Stop if no new data returned
        if new_count == 0:
            break

        # Stop if we have enough bars
        if len(all_candles) >= target_bars:
            break

        # Advance since to last timestamp + 1 interval
        last_ts_ms = max(c[0] for c in ohlcv)
        since_ms = last_ts_ms + interval_ms
        time.sleep(RATE_LIMIT)

    all_candles.sort(key=lambda c: c["time"])
    return all_candles


# ---------------------------------------------------------------------------
# Aggregation: 15m → 1H
# ---------------------------------------------------------------------------

def aggregate_15m_to_1h(candles_15m: list[dict]) -> list[dict]:
    """Aggregate 15m candles into 1H candles."""
    from collections import defaultdict

    buckets = defaultdict(list)
    for c in candles_15m:
        # Round down to 1H boundary
        hour_ts = (c["time"] // 3600) * 3600
        buckets[hour_ts].append(c)

    candles_1h = []
    for hour_ts in sorted(buckets.keys()):
        bars = buckets[hour_ts]
        if len(bars) < 3:  # need at least 3 of 4 15m bars
            continue
        candles_1h.append({
            "time": hour_ts,
            "open": bars[0]["open"],
            "high": max(b["high"] for b in bars),
            "low": min(b["low"] for b in bars),
            "close": bars[-1]["close"],
            "vwap": 0.0,
            "volume": sum(b["volume"] for b in bars),
            "count": sum(b.get("count", 0) for b in bars),
        })
    return candles_1h


# ---------------------------------------------------------------------------
# Core download pipeline
# ---------------------------------------------------------------------------

def download_timeframe(coins: list[dict], tf: str, manifest: dict,
                        max_runtime: int = 0, parts_dir: Path = None) -> dict:
    """Download candles for all coins for one timeframe."""
    tf_cfg = TF_CONFIG[tf]
    start = time.time()
    done = 0
    fail = 0

    for i, coin in enumerate(coins):
        if max_runtime > 0 and (time.time() - start) >= max_runtime:
            print(f"\n[TIMEOUT] Reached {max_runtime}s limit after {i} coins.")
            break

        symbol = coin["symbol"]
        mexc_sym = coin["mexc_symbol"]

        # Skip already done
        if symbol in manifest and manifest[symbol].get("status") == "done":
            done += 1
            continue

        pct = (i + 1) / len(coins) * 100
        print(f"  [{i+1}/{len(coins)}] ({pct:.0f}%) {symbol} ({tf})...", end=" ", flush=True)

        for attempt in range(MAX_RETRIES):
            try:
                candles = fetch_mexc_ohlc(mexc_sym, tf_cfg)

                if len(candles) < MIN_CANDLES:
                    manifest[symbol] = {"status": "fail", "bars": len(candles),
                                         "reason": f"only {len(candles)} bars"}
                    print(f"FAIL ({len(candles)} bars)")
                    fail += 1
                    break

                # Save per-coin file
                safe_name = symbol.replace("/", "_")
                coin_path = parts_dir / f"{safe_name}.json"
                save_json(coin_path, candles)

                manifest[symbol] = {"status": "done", "bars": len(candles),
                                     "mexc_symbol": mexc_sym,
                                     "quote_volume_24h": coin.get("quote_volume_24h", 0)}
                print(f"OK ({len(candles)} bars)")
                done += 1
                break

            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    wait = min(2 ** (attempt + 2), 30)
                    print(f"retry {attempt+1}...", end=" ", flush=True)
                    time.sleep(wait)
                else:
                    manifest[symbol] = {"status": "fail", "reason": str(e)[:200]}
                    print(f"FAIL ({e})")
                    fail += 1

    elapsed = time.time() - start
    print(f"\n  [{tf}] Done={done} Fail={fail} Time={elapsed:.0f}s")
    return manifest


def merge_cache(manifest: dict, parts_dir: Path, output_path: Path, tf: str):
    """Merge per-coin JSONs into one cache file."""
    print(f"\n[MERGE] Building {output_path.name}...")

    cache = {
        "_timestamp": now_ts(),
        "_date": now_ams_str(),
        "_universe": f"superhf_mexc_{tf}_top200",
        "_sources": ["mexc"],
        "_timeframe": tf,
        "_interval_seconds": TF_CONFIG[tf]["interval_seconds"],
        "_coins": 0,
    }

    coin_count = 0
    for symbol, entry in sorted(manifest.items()):
        if entry.get("status") != "done":
            continue
        safe_name = symbol.replace("/", "_")
        coin_path = parts_dir / f"{safe_name}.json"
        if not coin_path.exists():
            continue

        candles = load_json(coin_path, [])
        if len(candles) < MIN_CANDLES:
            continue

        cache[symbol] = candles
        coin_count += 1

    cache["_coins"] = coin_count
    save_json(output_path, cache)
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"  Merged {coin_count} coins → {output_path.name} ({size_mb:.1f} MB)")
    return coin_count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(args):
    start = time.time()
    timeframes = [args.tf] if args.tf else ["15m", "1h"]

    print(f"=== SuperHF Cache Builder (MEXC top 200) ===")
    print(f"  Timeframes: {timeframes}")
    print(f"  Target: 120 days history")
    print()

    # Discover top 200 coins
    manifest_path = DATA_ROOT / "derived" / "candle_cache" / "mexc" / "superhf_manifest.json"
    manifest = load_json(manifest_path, {})

    if not manifest.get("_coins_list") or args.force_rediscover:
        coins = discover_mexc_top200()
        manifest["_coins_list"] = coins
        manifest["_discovered_at"] = now_ams_str()
        save_json_pretty(manifest_path, manifest)
    else:
        coins = manifest["_coins_list"]
        print(f"[CACHED] Using {len(coins)} previously discovered coins")

    if args.max_coins > 0:
        coins = coins[:args.max_coins]

    # Download each timeframe
    for tf in timeframes:
        parts_dir = DATA_ROOT / "derived" / "candle_cache" / "mexc" / tf / "parts_superhf"
        parts_dir.mkdir(parents=True, exist_ok=True)

        tf_manifest_key = f"_manifest_{tf}"
        tf_manifest = manifest.get(tf_manifest_key, {})

        max_rt = args.max_runtime // len(timeframes) if args.max_runtime > 0 else 0
        tf_manifest = download_timeframe(coins, tf, tf_manifest, max_rt, parts_dir)

        manifest[tf_manifest_key] = tf_manifest
        save_json_pretty(manifest_path, manifest)

        # Merge into final cache
        output_path = DATA_ROOT / "derived" / "candle_cache" / "mexc" / tf / f"candle_cache_{tf}_mexc_superhf.json"
        merge_cache(tf_manifest, parts_dir, output_path, tf)

    # If we downloaded 15m but not 1h, aggregate 15m → 1h
    if "15m" in timeframes and "1h" not in timeframes:
        print("\n[AGGREGATE] Generating 1H from 15m candles...")
        cache_15m_path = DATA_ROOT / "derived" / "candle_cache" / "mexc" / "15m" / "candle_cache_15m_mexc_superhf.json"
        if cache_15m_path.exists():
            cache_15m = load_json(cache_15m_path)
            cache_1h = {
                "_timestamp": now_ts(),
                "_date": now_ams_str(),
                "_universe": "superhf_mexc_1h_aggregated",
                "_sources": ["mexc_15m_aggregated"],
                "_timeframe": "1h",
                "_interval_seconds": 3600,
                "_coins": 0,
            }
            agg_count = 0
            for key, val in cache_15m.items():
                if key.startswith("_"):
                    continue
                candles_1h = aggregate_15m_to_1h(val)
                if len(candles_1h) >= 50:
                    cache_1h[key] = candles_1h
                    agg_count += 1
            cache_1h["_coins"] = agg_count

            output_1h = DATA_ROOT / "derived" / "candle_cache" / "mexc" / "1h" / "candle_cache_1h_mexc_superhf.json"
            save_json(output_1h, cache_1h)
            size_mb = output_1h.stat().st_size / (1024 * 1024)
            print(f"  Aggregated {agg_count} coins → {output_1h.name} ({size_mb:.1f} MB)")

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"[DONE] Total elapsed: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="SuperHF MEXC candle downloader")
    parser.add_argument("--tf", choices=["15m", "1h"], default=None,
                        help="Single timeframe (default: both)")
    parser.add_argument("--max-coins", type=int, default=0,
                        help="Max coins (0=all 200)")
    parser.add_argument("--max-runtime", type=int, default=0,
                        help="Max runtime seconds (0=unlimited)")
    parser.add_argument("--force-rediscover", action="store_true",
                        help="Re-discover coins (ignore cached list)")
    args = parser.parse_args()

    try:
        run(args)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED]")
        sys.exit(1)
    except Exception as e:
        print(f"\n[FATAL] {e}")
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()

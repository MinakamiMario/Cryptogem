#!/usr/bin/env python3
"""
fetch_missing_tier.py - Fetch missing T1+T2 coins for HF 1H dataset.
Targets only the ~181 missing tier coins (K-Z alphabetically).
Uses same Kraken OHLC logic as build_hf_cache.py.
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PARTS_DIR = DATA_DIR / "cache_parts_hf" / "1h" / "kraken"
MANIFEST_PATH = DATA_DIR / "manifest_hf_1h.json"
TIERING_PATH = ROOT / "reports" / "hf" / "universe_tiering_001.json"

RATE_LIMIT = 1.1
MAX_RETRIES = 3
MIN_CANDLES = 30
KRAKEN_INTERVAL = 60
TARGET_DAYS = 120
MAX_CALLS = 6


def now_ts():
    return int(time.time())


def fetch_kraken_ohlc(kraken_name):
    since_ts = now_ts() - (TARGET_DAYS + 5) * 86400
    all_candles = []
    seen_ts = set()
    calls = 0

    while calls < MAX_CALLS:
        url = (
            f"https://api.kraken.com/0/public/OHLC"
            f"?pair={kraken_name}&interval={KRAKEN_INTERVAL}&since={since_ts}"
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
        if new_count < 700:
            break

        if last_ts:
            since_ts = int(last_ts)
        elif all_candles:
            since_ts = max(c["time"] for c in all_candles)
        else:
            break

        time.sleep(RATE_LIMIT)

    all_candles.sort(key=lambda c: c["time"])
    return all_candles


def main():
    with open(TIERING_PATH) as f:
        tiering = json.load(f)
    t1 = set(tiering["tier_breakdown"]["1"]["coins"])
    t2 = set(tiering["tier_breakdown"]["2"]["coins"])
    tier_coins = t1 | t2

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    existing_files = set(os.listdir(PARTS_DIR))
    missing = []
    for c in sorted(tier_coins):
        fname = c.replace("/", "_") + ".json"
        if fname not in existing_files:
            entry = manifest.get(c, {})
            kraken_name = entry.get("kraken_name", "")
            if not kraken_name:
                base = c.split("/")[0]
                kraken_name = base + "USD"
            tier = 1 if c in t1 else 2
            missing.append({"symbol": c, "kraken_name": kraken_name, "tier": tier})

    total = len(missing)
    print(f"=== Fetching {total} missing tier coins (T1+T2) ===")
    print()

    done = 0
    fail = 0
    start = time.time()

    for i, coin in enumerate(missing):
        symbol = coin["symbol"]
        kraken_name = coin["kraken_name"]
        tier = coin["tier"]
        pct = (i + 1) / total * 100
        elapsed = time.time() - start
        eta = (elapsed / max(i, 1)) * (total - i) if i > 0 else 0

        print(f"  [{i+1}/{total}] ({pct:.0f}%) T{tier} {symbol} ({kraken_name}) ETA:{eta/60:.0f}m ...",
              end=" ", flush=True)

        retries = 0
        while retries < MAX_RETRIES:
            try:
                candles = fetch_kraken_ohlc(kraken_name)
                if len(candles) < MIN_CANDLES:
                    print(f"SKIP (only {len(candles)} bars)")
                    if symbol in manifest:
                        manifest[symbol]["status"] = "fail"
                        manifest[symbol]["bars"] = len(candles)
                        manifest[symbol]["timestamp"] = now_ts()
                        manifest[symbol]["fail_reason"] = f"only {len(candles)} candles"
                    break

                safe_name = symbol.replace("/", "_")
                coin_path = PARTS_DIR / f"{safe_name}.json"
                with open(coin_path, "w") as f:
                    json.dump(candles, f)

                if symbol not in manifest:
                    manifest[symbol] = {
                        "exchange": "kraken",
                        "status": "done",
                        "retries": 0,
                        "bars": len(candles),
                        "timestamp": now_ts(),
                        "kraken_name": kraken_name,
                    }
                else:
                    manifest[symbol]["status"] = "done"
                    manifest[symbol]["bars"] = len(candles)
                    manifest[symbol]["timestamp"] = now_ts()
                    manifest[symbol]["retries"] = retries

                print(f"OK ({len(candles)} bars)")
                done += 1
                break

            except Exception as e:
                retries += 1
                if retries < MAX_RETRIES:
                    wait = 2 ** retries + 1
                    print(f"\n    Retry {retries}/{MAX_RETRIES} in {wait}s -- {e}")
                    time.sleep(wait)
                else:
                    print(f"FAIL ({e})")
                    if symbol in manifest:
                        manifest[symbol]["status"] = "fail"
                        manifest[symbol]["timestamp"] = now_ts()
                        manifest[symbol]["fail_reason"] = str(e)[:200]
                    fail += 1

        if (i + 1) % 10 == 0 or i == total - 1:
            with open(MANIFEST_PATH, "w") as f:
                json.dump(manifest, f, indent=2)

        time.sleep(RATE_LIMIT)

    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)

    elapsed = time.time() - start
    print()
    print("=" * 60)
    print(f"[DONE] {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  Downloaded: {done}  Failed: {fail}  Skipped: {total - done - fail}")

    existing_after = set(os.listdir(PARTS_DIR))
    t1_have = sum(1 for c in t1 if c.replace("/","_") + ".json" in existing_after)
    t2_have = sum(1 for c in t2 if c.replace("/","_") + ".json" in existing_after)
    print()
    print(f"  T1 coverage: {t1_have}/{len(t1)} ({t1_have/len(t1)*100:.1f}%)")
    print(f"  T2 coverage: {t2_have}/{len(t2)} ({t2_have/len(t2)*100:.1f}%)")
    print(f"  Total parts: {len(existing_after)}")
    print("=" * 60)


if __name__ == "__main__":
    main()

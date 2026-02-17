#!/usr/bin/env python3
"""Build MEXC 4H universe -- top coins with sufficient 4H history.

Pipeline:
  1. MEXC exchangeInfo API -> active USDT spot pairs
  2. MEXC ticker/24hr API -> 24h quote volume for ranking
  3. CryptoCompare histohour -> 4H bar count per coin (rate-limited)
  4. Filter >= 2160 bars (360 days), sort by volume, take top 200
  5. Save to strategies/4h/mexc_universe_4h.json

Usage:
    python3 scripts/build_mexc_universe.py
    python3 scripts/build_mexc_universe.py --max-coins 100
    python3 scripts/build_mexc_universe.py --min-bars 1000
"""

import json
import time
import argparse
import urllib.request
import urllib.error
import sys
from datetime import datetime, timezone
from pathlib import Path

# -- Config -------------------------------------------------------------------
MIN_BARS_DEFAULT = 2160     # 360 days x 6 bars/day
MAX_COINS_DEFAULT = 200     # Top N by volume
RATE_LIMIT_S = 1.2          # Between CryptoCompare calls
AGGREGATE = 4               # 4H bars
HISTO_LIMIT = 2000          # Max bars per CC page

MEXC_INFO_URL = "https://api.mexc.com/api/v3/exchangeInfo"
MEXC_TICKER_URL = "https://api.mexc.com/api/v3/ticker/24hr"

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "strategies" / "4h" / "mexc_universe_4h.json"
)

STABLES = {
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD",
    "PYUSD", "UST", "USDP", "USDE", "USD1", "USDF",
}


# -- Helpers ------------------------------------------------------------------
def fetch_json(url, retries=3, timeout=30):
    """Fetch JSON with retries and exponential backoff."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "CryptogemBot/1.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            if attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                print("  WARN: retry {}/{} in {}s ({})".format(
                    attempt + 1, retries, wait, e
                ))
                time.sleep(wait)
            else:
                raise


def bars_to_days(bars):
    return bars * AGGREGATE // 24


# -- Step 1: Get active USDT pairs from MEXC ---------------------------------
def fetch_mexc_pairs():
    """Get active USDT spot pairs from MEXC exchangeInfo."""
    print("[1/5] Fetching MEXC exchangeInfo...")
    data = fetch_json(MEXC_INFO_URL)
    symbols = data.get("symbols", [])
    print("  Total symbols: {}".format(len(symbols)))

    pairs = []
    for s in symbols:
        base = s.get("baseAsset", "")
        quote = s.get("quoteAsset", "")
        status = s.get("status", "")
        spot = s.get("isSpotTradingAllowed", False)
        if quote != "USDT":
            continue
        if status != "1":
            continue
        if not spot:
            continue
        if base in STABLES:
            continue
        pairs.append(base)

    print("  Active USDT spot pairs: {}".format(len(pairs)))
    return pairs


# -- Step 2: Get 24h volumes from MEXC ---------------------------------------
def fetch_mexc_volumes(pairs):
    """Get 24h quote volumes from MEXC ticker API."""
    print("[2/5] Fetching MEXC 24h ticker volumes...")
    data = fetch_json(MEXC_TICKER_URL, timeout=60)

    vol_map = {}
    for t in data:
        sym = t.get("symbol", "")
        if sym.endswith("USDT"):
            base = sym[:-4]
            try:
                vol = float(t.get("quoteVolume", 0))
            except (ValueError, TypeError):
                vol = 0.0
            vol_map[base] = vol

    # Merge volumes into pair list
    result = []
    for base in pairs:
        result.append({
            "sym": base,
            "volume_24h": vol_map.get(base, 0.0),
        })

    # Sort by volume descending
    result.sort(key=lambda r: r["volume_24h"], reverse=True)

    top5 = result[:5]
    print("  Volumes loaded for {}/{} pairs".format(
        sum(1 for r in result if r["volume_24h"] > 0), len(result)
    ))
    print("  Top 5 by volume: {}".format(
        ", ".join("{} (${:,.0f})".format(r["sym"], r["volume_24h"]) for r in top5)
    ))
    return result


# -- Step 3: Check 4H bar counts via CryptoCompare ---------------------------
def check_bar_count(sym, min_bars):
    """Check if coin has >= min_bars of 4H data on CryptoCompare/MEXC.

    Strategy: CryptoCompare histohour with aggregate=4 returns max ~500 bars/page.
    To check for 360+ days we need to look back in time.

    Method: 2 API calls
      1. Recent page → get actual bar count (up to 500) + latest timestamp
      2. Old page (toTs = now - min_bars*4h) → check if data exists that far back

    Returns (estimated_bars, has_enough_history) or (None, False) on failure.
    """
    import time as _time

    # Call 1: recent data (latest 500 bars)
    url_recent = (
        "https://min-api.cryptocompare.com/data/v2/histohour"
        "?fsym={}&tsym=USDT&limit=2000&aggregate=4&e=MEXC"
        "&extraParams=CryptogemBot"
    ).format(sym)
    try:
        data = fetch_json(url_recent)
    except Exception:
        return None, False
    if data.get("Response") == "Error":
        return None, False
    bars = data.get("Data", {}).get("Data", [])
    if not bars:
        return 0, False

    # Count real bars (skip leading zero-volume padding)
    found_start = False
    recent_count = 0
    first_real_ts = None
    for b in bars:
        if not found_start:
            if b.get("volumeto", 0) > 0 or b.get("volumefrom", 0) > 0:
                found_start = True
                recent_count = 1
                first_real_ts = b["time"]
        else:
            recent_count += 1

    if recent_count < 10:
        return recent_count, False

    # If recent page already has enough bars, done
    if recent_count >= min_bars:
        return recent_count, True

    # Optimization: if we got < 450 recent bars, coin is too young — skip 2nd call
    if recent_count < 450:
        return recent_count, False

    # Call 2: check if data exists ~min_bars * 4h ago
    _time.sleep(RATE_LIMIT_S)
    target_ts = int(_time.time()) - (min_bars * 4 * 3600)
    # Fetch a small window around the target time
    url_old = (
        "https://min-api.cryptocompare.com/data/v2/histohour"
        "?fsym={}&tsym=USDT&limit=10&aggregate=4&e=MEXC"
        "&toTs={}&extraParams=CryptogemBot"
    ).format(sym, target_ts + 10 * 4 * 3600)  # offset to get bars around target
    try:
        data_old = fetch_json(url_old)
    except Exception:
        return recent_count, False
    if data_old.get("Response") == "Error":
        return recent_count, False
    old_bars = data_old.get("Data", {}).get("Data", [])
    if not old_bars:
        return recent_count, False

    # Check if any of these old bars have volume
    has_old_data = any(
        (b.get("volumeto", 0) > 0 or b.get("volumefrom", 0) > 0)
        for b in old_bars
    )

    if has_old_data:
        # Estimate total bars from time span
        latest_ts = bars[-1]["time"]
        oldest_vol_ts = None
        for b in old_bars:
            if b.get("volumeto", 0) > 0 or b.get("volumefrom", 0) > 0:
                oldest_vol_ts = b["time"]
                break
        if oldest_vol_ts:
            span_seconds = latest_ts - oldest_vol_ts
            estimated_bars = span_seconds // (4 * 3600)
            return estimated_bars, estimated_bars >= min_bars
        return min_bars, True  # conservative: if old data exists, assume enough

    return recent_count, False


def check_all_bars(pairs, min_bars, max_coins=200):
    """Check 4H bar counts for all pairs with rate limiting.

    Early stops once we have enough passing coins (max_coins + 50% buffer)
    since pairs are sorted by volume descending.
    """
    n = len(pairs)
    # Optimistic: ~60% need 2 calls, ~40% bail after 1
    est_min = n * RATE_LIMIT_S * 1.4 / 60
    early_stop_target = int(max_coins * 1.5)  # 50% buffer for safety
    print("")
    print("[3/5] Checking 4H bars for {} coins (early stop at {} passes)...".format(
        n, early_stop_target
    ))
    print("")

    results = []
    pass_count = 0
    skip_count = 0
    fail_count = 0
    consecutive_fails = 0
    t0 = time.time()

    for i, p in enumerate(pairs):
        sym = p["sym"]
        bars, has_enough = check_bar_count(sym, min_bars)
        elapsed = time.time() - t0
        avg_per = elapsed / max(1, i + 1)
        eta = (n - i - 1) * avg_per / 60

        if bars is not None and bars > 0:
            days = bars_to_days(bars)
            consecutive_fails = 0
            if has_enough:
                tag = "PASS"
                pass_count += 1
            else:
                tag = "skip"
                skip_count += 1
            print("  [{:4d}/{}] {:12s} ~{:5d} bars ({:4d}d) [{}]  {:.0f}s ETA {:.1f}m  ({} pass)".format(
                i + 1, n, sym, bars, days, tag, elapsed, eta, pass_count
            ))
            results.append({
                "sym": sym,
                "bars": bars,
                "days": days,
                "volume_24h": p["volume_24h"],
            })
        else:
            fail_count += 1
            consecutive_fails += 1
            print("  [{:4d}/{}] {:12s}    -- no data --      {:.0f}s ETA {:.1f}m".format(
                i + 1, n, sym, elapsed, eta
            ))

        # Early stop: enough passes collected (sorted by volume, so best coins first)
        if pass_count >= early_stop_target:
            print("\n  EARLY STOP: {} passes >= {} target (checked {}/{})".format(
                pass_count, early_stop_target, i + 1, n
            ))
            break

        if i < n - 1:
            time.sleep(RATE_LIMIT_S)

    print("")
    print("  Done: {} pass, {} skip, {} no-data (checked {}/{})".format(
        pass_count, skip_count, fail_count, min(i + 1, n), n
    ))
    return results


# -- Step 4: Filter, sort, select --------------------------------------------
def filter_and_rank(results, min_bars, max_coins):
    print("")
    print("[4/5] Filtering and ranking...")
    passing = [r for r in results if r["bars"] >= min_bars]
    print("  {}/{} coins >= {} bars ({} days)".format(
        len(passing), len(results), min_bars, bars_to_days(min_bars)
    ))

    # Already sorted by volume from step 2, but re-sort passing subset
    has_vol = any(r["volume_24h"] > 0 for r in passing)
    if has_vol:
        passing.sort(key=lambda r: r["volume_24h"], reverse=True)
        print("  Sorted by 24h quote volume (descending)")
    else:
        passing.sort(key=lambda r: r["sym"])
        print("  Sorted alphabetically (no volume data)")

    selected = passing[:max_coins]
    print("  Selected top {} coins".format(len(selected)))
    return selected


# -- Step 5: Save output -----------------------------------------------------
def save_universe(selected, min_bars, max_coins):
    print("")
    print("[5/5] Saving to {}...".format(OUTPUT_PATH))

    # Internal format: "BTC" -> "BTC/USD"
    coins = ["{}/USD".format(r["sym"]) for r in selected]
    coin_stats = {}
    for r in selected:
        key = "{}/USD".format(r["sym"])
        coin_stats[key] = {"bars": r["bars"], "days": r["days"]}

    output = {
        "version": "v1",
        "exchange": "mexc",
        "quote_currency": "USDT",
        "internal_format": "SYM/USD",
        "n_coins": len(coins),
        "min_bars": min_bars,
        "min_days": bars_to_days(min_bars),
        "max_coins": max_coins,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "coins": coins,
        "coin_stats": coin_stats,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print("  Saved {} coins to {}".format(len(coins), OUTPUT_PATH.name))


# -- Main ---------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Build MEXC 4H universe")
    parser.add_argument("--min-bars", type=int, default=MIN_BARS_DEFAULT,
                        help="Minimum 4H bars required (default: 2160 = 360d)")
    parser.add_argument("--max-coins", type=int, default=MAX_COINS_DEFAULT,
                        help="Max coins to include (default: 200)")
    args = parser.parse_args()

    min_bars = args.min_bars
    max_coins = args.max_coins

    print("=" * 70)
    print("MEXC 4H Universe Builder")
    print("  Min bars: {} ({} days)".format(min_bars, bars_to_days(min_bars)))
    print("  Max coins: {}".format(max_coins))
    print("  Source: MEXC API (pairs) + CryptoCompare (bar counts)")
    print("=" * 70)

    # Step 1: Active pairs from MEXC
    pairs = fetch_mexc_pairs()
    if not pairs:
        print("ERROR: No pairs found.")
        sys.exit(1)

    # Step 2: 24h volumes from MEXC
    ranked = fetch_mexc_volumes(pairs)

    # Step 3: Bar counts from CryptoCompare (rate-limited, early stop)
    results = check_all_bars(ranked, min_bars, max_coins)

    # Step 4: Filter and rank
    selected = filter_and_rank(results, min_bars, max_coins)
    if not selected:
        print("")
        print("ERROR: No coins passed the filter.")
        sys.exit(1)

    # Step 5: Save
    save_universe(selected, min_bars, max_coins)

    # Summary
    print("")
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    bc = [r["bars"] for r in selected]
    print("  Coins: {}".format(len(selected)))
    print("  Bar range: {} - {} bars".format(min(bc), max(bc)))
    print("  Day range: {} - {} days".format(
        bars_to_days(min(bc)), bars_to_days(max(bc))
    ))
    print("  Top 10: {}".format(
        ", ".join(r["sym"] for r in selected[:10])
    ))
    print("  Output: {}".format(OUTPUT_PATH))
    elapsed_total = time.time()
    print("=" * 70)


if __name__ == "__main__":
    main()

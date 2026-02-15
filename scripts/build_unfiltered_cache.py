#!/usr/bin/env python3
"""
Build Unfiltered Candle Cache — Kraken + MEXC, no halal filter.
Only excludes stablecoins, fiat, and wrapped tokens (technical reasons).
Keeps: memecoins, yield, lending, gambling — alles wat tradeable is.

Sources:
  - Kraken: ~600 USD pairs via public AssetPairs API
  - MEXC: ~1900 USDT pairs via ccxt (adds coins not on Kraken)

Normalization:
  - All pairs normalized to BASE/USD format
  - MEXC USDT pairs -> BASE/USD (backtest treats as equivalent)
  - Dedup: if coin on both exchanges, Kraken data wins (4H candles, vwap)

Usage:
  python3 scripts/build_unfiltered_cache.py                          # Kraken + MEXC
  python3 scripts/build_unfiltered_cache.py --kraken-only             # Kraken only
  python3 scripts/build_unfiltered_cache.py --output data/custom.json
"""
import sys
import json
import time
import urllib.request
import logging
from pathlib import Path
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

AMS = ZoneInfo('Europe/Amsterdam')
ROOT = Path(__file__).parent.parent
DEFAULT_OUTPUT = ROOT / 'data' / 'candle_cache_unfiltered.json'

# Only exclude things technically unsuitable for spot trading
TECHNICAL_EXCLUDES = {
    # Stablecoins & fiat — no volatility
    'USDT', 'USDC', 'DAI', 'TUSD', 'BUSD', 'GUSD', 'PAX', 'USDP',
    'FRAX', 'LUSD', 'SUSD', 'UST', 'PYUSD', 'FDUSD', 'EURC', 'EURT',
    'USD1', 'USDD', 'USDE', 'USDG', 'USDQ', 'USDR', 'USDS', 'USDUC',
    'RLUSD', 'AUSD',
    # Fiat currencies
    'EUR', 'GBP', 'AUD', 'CAD', 'JPY', 'CHF', 'NZD',
    'EURQ', 'EURR', 'EUROP', 'TGBP', 'AUDX',
    # Wrapped / pegged — track underlying
    'WBTC', 'WETH', 'STETH', 'RETH', 'CBETH', 'WSTETH', 'MSOL',
    'JITOSOL', 'BNSOL', 'CMETH', 'METH', 'LSETH', 'LSSOL', 'TBTC',
    'WAXL',
}

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('build_cache')

BASE_MAP = {
    'XBT': 'BTC', 'XETH': 'ETH', 'XDG': 'DOGE', 'XETC': 'ETC',
    'XMLN': 'MLN', 'XREP': 'REP', 'XXLM': 'XLM', 'XXMR': 'XMR',
    'XXRP': 'XRP', 'XZEC': 'ZEC', 'XLTC': 'LTC',
}


# ============================================================
# KRAKEN
# ============================================================
def discover_kraken_pairs():
    """Get ALL active USD spot pairs from Kraken (minimal filtering)."""
    url = 'https://api.kraken.com/0/public/AssetPairs'
    req = urllib.request.Request(url, headers={'User-Agent': 'CryptogemBot/1.0'})
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())

    result = data.get('result', {})
    discovered = {}
    skipped = 0

    for kraken_name, info in result.items():
        if '.d' in kraken_name:
            continue
        if info.get('status', 'online') != 'online':
            continue
        if info.get('quote', '') not in ('ZUSD', 'USD'):
            continue

        base = info.get('base', '')
        clean = base
        if clean.startswith('X') and len(clean) > 3:
            clean = clean[1:]
        if clean.startswith('Z') and len(clean) > 3:
            clean = clean[1:]
        standard = BASE_MAP.get(clean, clean)

        wsname = info.get('wsname', '')
        if wsname and '/USD' in wsname:
            ws_base = wsname.split('/')[0]
            if ws_base:
                standard = ws_base

        if standard.upper() in TECHNICAL_EXCLUDES:
            skipped += 1
            continue

        discovered[f"{standard}/USD"] = kraken_name

    logger.info(f"  Kraken: {len(discovered)} USD pairs (skipped {skipped} technical)")
    return discovered


def fetch_kraken_ohlc(kraken_name, interval=240, retries=3):
    """Fetch OHLC from Kraken public API."""
    url = f'https://api.kraken.com/0/public/OHLC?pair={kraken_name}&interval={interval}'
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'CryptogemBot/1.0'})
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read())
            if data.get('error') and any('EGeneral' not in e for e in data['error']):
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return None
            for key, candles in data.get('result', {}).items():
                if key == 'last':
                    continue
                return [{
                    'time': int(c[0]), 'open': float(c[1]), 'high': float(c[2]),
                    'low': float(c[3]), 'close': float(c[4]), 'vwap': float(c[5]),
                    'volume': float(c[6]), 'count': int(c[7]),
                } for c in candles]
            return None
        except Exception:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return None
    return None


# ============================================================
# MEXC (via ccxt)
# ============================================================
def discover_mexc_pairs():
    """Get USDT spot pairs from MEXC, return as BASE/USD."""
    try:
        import ccxt
    except ImportError:
        logger.warning("  MEXC: ccxt niet gevonden (pip install ccxt), skip")
        return {}

    exchange = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
    exchange.load_markets()

    discovered = {}
    skipped = 0
    for symbol, market in exchange.markets.items():
        if not market.get('spot') or not market.get('active'):
            continue
        if market.get('quote') != 'USDT':
            continue
        base = market.get('base', '')
        if base.upper() in TECHNICAL_EXCLUDES:
            skipped += 1
            continue
        # Normalize to BASE/USD
        discovered[f"{base}/USD"] = symbol  # symbol is like "BTC/USDT"

    logger.info(f"  MEXC: {len(discovered)} USDT pairs (skipped {skipped} technical)")
    return discovered


def fetch_mexc_ohlc(ccxt_symbol, retries=2):
    """Fetch OHLC from MEXC via ccxt."""
    try:
        import ccxt
        exchange = ccxt.mexc({'enableRateLimit': True})
        ohlcv = exchange.fetch_ohlcv(ccxt_symbol, '4h', limit=720)
        if not ohlcv or len(ohlcv) < 30:
            return None
        return [{
            'time': int(c[0] / 1000), 'open': float(c[1]), 'high': float(c[2]),
            'low': float(c[3]), 'close': float(c[4]), 'vwap': 0.0,
            'volume': float(c[5]), 'count': 0,
        } for c in ohlcv]
    except Exception:
        return None


# ============================================================
# MAIN
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description='Build unfiltered candle cache (Kraken + MEXC)')
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--kraken-only', action='store_true',
                        help='Only download from Kraken (skip MEXC)')
    parser.add_argument('--mexc-top', type=int, default=200,
                        help='Max number of MEXC-only coins to add (default: 200)')
    parser.add_argument('--append-mexc', action='store_true',
                        help='Load existing cache and only add MEXC coins (skip Kraken download)')
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(AMS)
    logger.info(f"{'='*65}")
    logger.info(f"  BUILD UNFILTERED CACHE (Kraken + MEXC)")
    logger.info(f"  {now.strftime('%Y-%m-%d %H:%M %Z')}")
    logger.info(f"  Excludes: stablecoins, fiat, wrapped only")
    logger.info(f"  Keeps: memecoins, yield, lending, gambling, alles")
    logger.info(f"{'='*65}")

    # === Phase 1: Kraken ===
    dl = 0
    if args.append_mexc and output_path.exists():
        logger.info("\nPhase 1: Loading existing cache (--append-mexc)...")
        with open(output_path) as f:
            cache = json.load(f)
        dl = len([k for k, v in cache.items() if isinstance(v, list)])
        logger.info(f"  Loaded {dl} coins from existing cache")
        if 'kraken' not in cache.get('_sources', []):
            cache.setdefault('_sources', []).append('kraken')
    else:
        logger.info("\nPhase 1: Kraken discovery...")
        kraken_pairs = discover_kraken_pairs()
        kraken_coins = sorted(kraken_pairs.keys())

        cache = {
            '_timestamp': time.time(),
            '_date': now.strftime('%Y-%m-%d %H:%M %Z'),
            '_universe': 'unfiltered',
            '_sources': ['kraken'],
        }

        logger.info(f"\nDownloading Kraken candles ({len(kraken_coins)} coins)...")
        errs = 0
        for i, pair in enumerate(kraken_coins):
            candles = fetch_kraken_ohlc(kraken_pairs[pair])
            if candles and len(candles) >= 30:
                cache[pair] = candles
                dl += 1
            else:
                errs += 1
            if (i + 1) % 50 == 0:
                logger.info(f"  [{i+1}/{len(kraken_coins)}] {dl} OK, {errs} fail")
            time.sleep(1.1)  # Kraken rate limit
        logger.info(f"  Kraken: {dl} coins downloaded, {errs} failed")

    # === Phase 2: MEXC (only coins NOT already from Kraken) ===
    mexc_added = 0
    if not args.kraken_only:
        logger.info(f"\nPhase 2: MEXC discovery...")
        mexc_pairs = discover_mexc_pairs()
        # Only coins not yet in cache
        mexc_only = sorted(p for p in mexc_pairs if p not in cache)
        mexc_to_fetch = mexc_only[:args.mexc_top]
        logger.info(f"  MEXC-only coins (not on Kraken): {len(mexc_only)}")
        logger.info(f"  Fetching top {len(mexc_to_fetch)} MEXC-only coins...")
        cache['_sources'].append('mexc')

        for i, pair in enumerate(mexc_to_fetch):
            ccxt_symbol = mexc_pairs[pair]
            candles = fetch_mexc_ohlc(ccxt_symbol)
            if candles and len(candles) >= 30:
                cache[pair] = candles
                mexc_added += 1
            if (i + 1) % 25 == 0:
                logger.info(f"  [{i+1}/{len(mexc_to_fetch)}] {mexc_added} added")
            time.sleep(0.3)  # MEXC rate limit is generous
        logger.info(f"  MEXC: {mexc_added} new coins added")

    # Final
    coin_count = len([k for k, v in cache.items() if isinstance(v, list)])
    cache['_coins'] = coin_count

    with open(output_path, 'w') as f:
        json.dump(cache, f)

    size_mb = output_path.stat().st_size / 1024 / 1024
    logger.info(f"\n{'='*65}")
    logger.info(f"  Total: {coin_count} coins (Kraken {dl} + MEXC {mexc_added})")
    logger.info(f"  Output: {output_path} ({size_mb:.1f} MB)")
    logger.info(f"  Done.")


if __name__ == '__main__':
    main()

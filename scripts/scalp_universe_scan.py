#!/usr/bin/env python3
"""Scan MEXC for coins suitable for 1m FVG scalp strategy.

Requirements:
  - Halal (no riba/gambling/derivatives)
  - Tight spread (≤5 bps — strategy breakeven is 4.8 bps)
  - Sufficient 24h volume (≥$50K for execution)
  - MEXC spot enabled

Measures live spread + depth for top candidates.
"""
import json, urllib.request, time, sys

# Known haram coins (from our classification)
KNOWN_HARAM = {
    'AAVE', 'COMP', 'MKR', 'DOGE', 'SHIB', 'PEPE', 'FLOKI', 'WIF', 'BONK',
    'TRUMP', 'MELANIA', 'BRETT', 'POPCAT', 'NEIRO', 'TURBO', 'SPX', 'MOODENG',
    'MOG', 'PNUT', 'GOAT', 'FARTCOIN', 'VINE', 'ANIME', 'TST', 'BERA',
    'SYRUP', 'KERNEL', 'SKY', 'PENDLE', 'GHST', 'MIRROR', 'YFI', 'SUSHI',
    'CAKE', 'JUP', 'SNX', 'CRV', 'CVX', 'FXS', 'SPELL', 'ALPACA',
    'LQTY', 'MORPHO', 'UMA', 'PERP', 'DRIFT', 'DYDX', 'GMX', 'GNS',
    'VRTX', 'KAVA', 'IDEX', 'T',
    # Meme / zero utility
    'KET', 'SUNDOG', 'CAT', 'MYRO', 'BOME', 'SLERF',
    # Lending/yield
    'BLUAI', 'RIVER', 'HIFI', 'WING', 'CREAM',
}

# Known halal coins (already verified)
KNOWN_HALAL = {
    'XRP', 'ETH', 'BTC', 'SOL', 'ADA', 'DOT', 'SUI', 'TON', 'NEAR', 'ALGO',
    'SEI', 'APT', 'ATOM', 'HBAR', 'FIL', 'AR', 'RENDER', 'GRT', 'IMX', 'OP',
    'ENS', 'LTC', 'XMR', 'BAT', 'ZRO', 'TRAC', 'AXS',
    'EDU', 'SC', 'QTUM', 'ANKR', 'LRC', 'SONIC', 'RARI', 'COOKIE',
    'ASTER', 'MOVR', 'H', 'SAHARA', 'GUN', 'STRK', 'B2', 'FF', 'ACH', 'OPEN',
    'VET', 'IOTA', 'NEO', 'ZIL', 'ONE', 'ROSE', 'KAS',
    # Infrastructure/utility
    'LINK', 'AVAX', 'MATIC', 'POL', 'ARB', 'MANA', 'SAND', 'AXS', 'ICP',
    'FTM', 'CELO', 'EGLD', 'FLOW', 'THETA', 'TFUEL', 'KDA', 'KLAY',
    'WAVES', 'ZEC', 'DASH', 'ETC', 'BCH', 'XLM', 'EOS', 'TRX',
    'DENT', 'HOT', 'CELR', 'CKB', 'CTXC', 'RLC', 'NKN',
    'STORJ', 'MASK', 'API3', 'BAND', 'TLM', 'ALICE', 'GALA',
    'CHZ', 'ENJ', 'RNDR', 'AUDIO', 'LPT', 'SUPER', 'YGG',
    'AGLD', 'GMT', 'STX', 'CFX', 'ASTR', 'GLMR',
}

print("=" * 100)
print("SCALP UNIVERSE SCAN — MEXC SPOT")
print("Finding halal coins with tight spreads for 1m FVG scalp")
print("=" * 100)
print()

# Step 1: Get all MEXC symbols
url = 'https://api.mexc.com/api/v3/exchangeInfo'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
resp = urllib.request.urlopen(req, timeout=30)
exchange_info = json.loads(resp.read())

usdt_pairs = {}
for s in exchange_info.get('symbols', []):
    if s.get('quoteAsset') == 'USDT' and s.get('isSpotTradingAllowed', False):
        base = s.get('baseAsset', '')
        usdt_pairs[base] = s.get('symbol', '')

print(f"MEXC USDT spot pairs: {len(usdt_pairs)}")

# Step 2: Get 24h volume
url2 = 'https://api.mexc.com/api/v3/ticker/24hr'
req2 = urllib.request.Request(url2, headers={'User-Agent': 'Mozilla/5.0'})
resp2 = urllib.request.urlopen(req2, timeout=30)
tickers = json.loads(resp2.read())

volume_map = {}
for t in tickers:
    sym = t.get('symbol', '')
    if sym.endswith('USDT'):
        base = sym.replace('USDT', '')
        vol = float(t.get('quoteVolume', 0) or 0)
        price = float(t.get('lastPrice', 0) or 0)
        if vol >= 50000 and price > 0:  # Min $50K daily volume
            volume_map[base] = {'volume': vol, 'price': price}

print(f"Coins with ≥$50K 24h volume: {len(volume_map)}")

# Step 3: Filter halal candidates
candidates = []
for base, data in volume_map.items():
    if base in KNOWN_HARAM:
        continue
    if base in usdt_pairs:
        halal_status = 'VERIFIED' if base in KNOWN_HALAL else 'UNVERIFIED'
        candidates.append({
            'symbol': base,
            'pair': f"{base}USDT",
            'volume': data['volume'],
            'price': data['price'],
            'halal': halal_status,
        })

# Sort by volume
candidates.sort(key=lambda x: x['volume'], reverse=True)
print(f"Non-haram candidates with volume: {len(candidates)}")
print(f"  Verified halal: {sum(1 for c in candidates if c['halal'] == 'VERIFIED')}")
print(f"  Unverified: {sum(1 for c in candidates if c['halal'] == 'UNVERIFIED')}")

# Step 4: Check live spread for top candidates (by volume)
# Take top 80 by volume
top_candidates = candidates[:80]
print(f"\nChecking live spread for top {len(top_candidates)} by volume...")
print()

results = []
for i, cand in enumerate(top_candidates):
    try:
        url3 = f"https://api.mexc.com/api/v3/depth?symbol={cand['pair']}&limit=5"
        req3 = urllib.request.Request(url3, headers={'User-Agent': 'Mozilla/5.0'})
        resp3 = urllib.request.urlopen(req3, timeout=10)
        ob = json.loads(resp3.read())

        bids = ob.get('bids', [])
        asks = ob.get('asks', [])

        if bids and asks:
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            mid = (best_bid + best_ask) / 2
            spread_bps = (best_ask - best_bid) / mid * 10000

            # Depth within 10bps of mid
            bid_depth = sum(float(b[0]) * float(b[1]) for b in bids[:5])
            ask_depth = sum(float(a[0]) * float(a[1]) for a in asks[:5])
            min_depth = min(bid_depth, ask_depth)

            cand['spread_bps'] = spread_bps
            cand['depth'] = min_depth
            results.append(cand)

        if (i + 1) % 20 == 0:
            print(f"  Checked {i+1}/{len(top_candidates)}...")

        time.sleep(0.15)  # Rate limit

    except Exception as e:
        pass

# Sort by spread
results.sort(key=lambda x: x['spread_bps'])

# Show results
print()
print("=" * 100)
print(f"{'Coin':<10} {'Halal':<12} {'Price':>12} {'24h Vol':>14} {'Spread':>8} {'Depth':>12} {'Scalp?':>8}")
print("-" * 100)

scalp_go = []
scalp_maybe = []
for r in results:
    spread = r['spread_bps']
    depth = r['depth']
    vol = r['volume']

    # Scalp suitability: spread ≤3 bps (well under 4.8 breakeven) AND depth ≥$1K
    if spread <= 3.0 and depth >= 1000:
        verdict = 'GO'
        scalp_go.append(r)
    elif spread <= 5.0 and depth >= 500:
        verdict = 'MAYBE'
        scalp_maybe.append(r)
    else:
        verdict = 'NO'

    if spread <= 8.0:  # Only show coins with spread ≤8 bps
        print(f"{r['symbol']:<10} {r['halal']:<12} ${r['price']:>11.6f} ${vol:>13,.0f} {spread:>6.1f}bp ${depth:>10,.0f} {verdict:>8}")

print()
print("=" * 100)
print("SCALP UNIVERSE SUMMARY")
print("=" * 100)
print(f"\n  GO (spread ≤3bps, depth ≥$1K):    {len(scalp_go)} coins")
for c in scalp_go:
    print(f"    {c['symbol']:<10} spread={c['spread_bps']:.1f}bp  depth=${c['depth']:,.0f}  vol=${c['volume']:,.0f}  [{c['halal']}]")

print(f"\n  MAYBE (spread ≤5bps, depth ≥$500): {len(scalp_maybe)} coins")
for c in scalp_maybe:
    print(f"    {c['symbol']:<10} spread={c['spread_bps']:.1f}bp  depth=${c['depth']:,.0f}  vol=${c['volume']:,.0f}  [{c['halal']}]")

print(f"\n  Current scalp coins: XRP (0.35bp), ETH (0.02bp)")
print(f"  Strategy breakeven spread: 4.8 bps")
print(f"  Recommended max spread: 3.0 bps (62% margin)")

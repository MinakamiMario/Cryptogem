#!/usr/bin/env python3
"""QC4: Survivorship bias check — do all 19 QC1-PASS coins still trade on MEXC?"""
import json, urllib.request, time

QC1_PASS = ['RARI', 'XMR', 'COOKIE', 'BAT', 'ASTER', 'LTC', 'MOVR', 'H', 'ZRO',
            'TRAC', 'SAHARA', 'GUN', 'STRK', 'B2', 'GMT', 'FF', 'AXS', 'ACH', 'OPEN']

CURRENT_HALAL = ['EDU', 'CTSI', 'AIOZ', 'SC', 'QTUM', 'ANKR', 'LRC', 'SONIC',
                 'ADA', 'DOT', 'SUI', 'TON', 'IMX', 'RENDER', 'FIL', 'HBAR',
                 'KAS', 'OP', 'ENS', 'AR', 'ATOM', 'APT', 'GRT', 'ALGO',
                 'NEAR', 'SEI', 'SOL', 'XRP']

print("=" * 80)
print("QC4: SURVIVORSHIP BIAS CHECK — MEXC SPOT AVAILABILITY")
print("=" * 80)
print()

# Fetch all MEXC spot symbols
url = 'https://api.mexc.com/api/v3/exchangeInfo'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
resp = urllib.request.urlopen(req, timeout=30)
exchange_info = json.loads(resp.read())

active_symbols = set()
symbol_details = {}
for s in exchange_info.get('symbols', []):
    sym = s.get('symbol', '')
    status = s.get('status', '')
    base = s.get('baseAsset', '')
    quote = s.get('quoteAsset', '')
    if quote == 'USDT':
        active_symbols.add(base)
        symbol_details[base] = {
            'symbol': sym,
            'status': status,
            'isSpotTradingAllowed': s.get('isSpotTradingAllowed', False),
        }

print(f"Total USDT pairs on MEXC: {len(active_symbols)}")
print()

# Check 24h ticker for volume
url2 = 'https://api.mexc.com/api/v3/ticker/24hr'
req2 = urllib.request.Request(url2, headers={'User-Agent': 'Mozilla/5.0'})
resp2 = urllib.request.urlopen(req2, timeout=30)
tickers = json.loads(resp2.read())

ticker_map = {}
for t in tickers:
    sym = t.get('symbol', '')
    if sym.endswith('USDT'):
        base = sym[:-4]
        ticker_map[base] = {
            'price': float(t.get('lastPrice', 0)),
            'volume_usd': float(t.get('quoteVolume', 0)),
            'trades': int(t.get('count', 0) or 0),
            'change_pct': float(t.get('priceChangePercent', 0) or 0),
        }

print(f"{'Coin':<10} {'Listed?':>8} {'Status':>10} {'SpotOK':>7} {'Price':>12} {'24h Vol':>14} {'Verdict':>10}")
print("-" * 80)

qc1_results = {}
for coin in QC1_PASS:
    listed = coin in active_symbols
    status = symbol_details.get(coin, {}).get('status', 'N/A')
    spot_ok = symbol_details.get(coin, {}).get('isSpotTradingAllowed', False)
    ticker = ticker_map.get(coin, {})
    price = ticker.get('price', 0)
    vol = ticker.get('volume_usd', 0)
    trades = ticker.get('trades', 0)

    if not listed:
        verdict = 'DELISTED'
    elif status not in ('ENABLED', '1'):
        verdict = 'SUSPENDED'
    elif not spot_ok:
        verdict = 'NO_SPOT'
    elif vol < 1000:
        verdict = 'DEAD'
    elif vol < 10000:
        verdict = 'LOW_VOL'
    else:
        verdict = 'ACTIVE'

    qc1_results[coin] = verdict
    print(f"{coin:<10} {'YES' if listed else 'NO':>8} {status:>10} {'YES' if spot_ok else 'NO':>7} ${price:>11.6f} ${vol:>13,.0f} {verdict:>10}")

print()
print("=" * 80)
print("CURRENT HALAL COINS")
print("=" * 80)
print(f"{'Coin':<10} {'Listed?':>8} {'Status':>10} {'SpotOK':>7} {'Price':>12} {'24h Vol':>14} {'Verdict':>10}")
print("-" * 80)

halal_results = {}
for coin in CURRENT_HALAL:
    listed = coin in active_symbols
    status = symbol_details.get(coin, {}).get('status', 'N/A')
    spot_ok = symbol_details.get(coin, {}).get('isSpotTradingAllowed', False)
    ticker = ticker_map.get(coin, {})
    price = ticker.get('price', 0)
    vol = ticker.get('volume_usd', 0)

    if not listed:
        verdict = 'DELISTED'
    elif status not in ('ENABLED', '1'):
        verdict = 'SUSPENDED'
    elif not spot_ok:
        verdict = 'NO_SPOT'
    elif vol < 1000:
        verdict = 'DEAD'
    elif vol < 10000:
        verdict = 'LOW_VOL'
    else:
        verdict = 'ACTIVE'

    halal_results[coin] = verdict
    print(f"{coin:<10} {'YES' if listed else 'NO':>8} {status:>10} {'YES' if spot_ok else 'NO':>7} ${price:>11.6f} ${vol:>13,.0f} {verdict:>10}")

# Summary
print()
print("=" * 80)
print("QC4 SUMMARY")
print("=" * 80)

qc1_active = sum(1 for v in qc1_results.values() if v == 'ACTIVE')
qc1_issues = {c: v for c, v in qc1_results.items() if v != 'ACTIVE'}
halal_active = sum(1 for v in halal_results.values() if v == 'ACTIVE')
halal_issues = {c: v for c, v in halal_results.items() if v != 'ACTIVE'}

print(f"\nQC1 PASS coins: {qc1_active}/{len(QC1_PASS)} ACTIVE")
if qc1_issues:
    print(f"  Issues: {qc1_issues}")

print(f"\nCurrent halal: {halal_active}/{len(CURRENT_HALAL)} ACTIVE")
if halal_issues:
    print(f"  Issues: {halal_issues}")

if qc1_active == len(QC1_PASS):
    print(f"\nVERDICT: QC4 PASS — all {len(QC1_PASS)} coins actively trading on MEXC")
elif qc1_active >= len(QC1_PASS) * 0.85:
    print(f"\nVERDICT: QC4 CONDITIONAL — {len(QC1_PASS) - qc1_active} coins have issues, remove from candidate list")
else:
    print(f"\nVERDICT: QC4 FAIL — too many coins with trading issues")

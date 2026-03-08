#!/usr/bin/env python3
"""
Collect 90 days of 1m candles from Binance (public API, no keys needed).
Saves to ~/CryptogemData/scalp/1m/binance/{COIN}_USDT_1m.json

Binance has much deeper 1m history than MEXC (months vs 30d).
Used for temporal validation only — not for live trading decisions.
"""
import sys, json, time
from pathlib import Path
from datetime import datetime, timezone

import ccxt

DATA_DIR = Path.home() / 'CryptogemData' / 'scalp' / '1m' / 'binance'
COINS = ['XRP', 'BTC', 'ETH', 'SUI']
DAYS = 90
BARS_PER_REQUEST = 1000  # Binance allows up to 1000
RATE_LIMIT_S = 0.3       # Binance is more generous with rate limits


def collect(exchange, pair: str, days: int) -> list[dict]:
    now_ts = int(time.time())
    start_ts = (now_ts - days * 86400) * 1000  # ms
    all_candles = {}
    cursor = start_ts
    page = 0
    total_expected = days * 24 * 60

    print(f'  Collecting {pair} ({days}d, ~{total_expected:,} bars)')

    while cursor < now_ts * 1000:
        page += 1
        try:
            ohlcv = exchange.fetch_ohlcv(pair, '1m', since=cursor, limit=BARS_PER_REQUEST)
        except Exception as e:
            print(f'    [WARN] Page {page}: {e}, retrying...')
            time.sleep(2)
            try:
                ohlcv = exchange.fetch_ohlcv(pair, '1m', since=cursor, limit=BARS_PER_REQUEST)
            except Exception as e2:
                print(f'    [ERROR] Page {page} failed: {e2}')
                cursor += BARS_PER_REQUEST * 60 * 1000
                continue

        if not ohlcv:
            cursor += BARS_PER_REQUEST * 60 * 1000
            continue

        for c in ohlcv:
            ts = int(c[0] / 1000)
            all_candles[ts] = {
                'time': ts,
                'open': float(c[1]),
                'high': float(c[2]),
                'low': float(c[3]),
                'close': float(c[4]),
                'volume': float(c[5]),
            }

        cursor = ohlcv[-1][0] + 60 * 1000

        if page % 20 == 0:
            pct = min(100, len(all_candles) / total_expected * 100)
            print(f'    Page {page}: {len(all_candles):,} bars ({pct:.0f}%)')

        time.sleep(RATE_LIMIT_S)

    candles = sorted(all_candles.values(), key=lambda c: c['time'])
    return candles


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ex = ccxt.binance({'enableRateLimit': True})

    print(f'Collecting {DAYS}d 1m candles from Binance for: {", ".join(COINS)}')
    print(f'Output: {DATA_DIR}')
    print()

    for coin in COINS:
        pair = f'{coin}/USDT'
        t0 = time.time()
        candles = collect(ex, pair, DAYS)
        elapsed = time.time() - t0

        if not candles:
            print(f'  {coin}: NO DATA')
            continue

        first_dt = datetime.fromtimestamp(candles[0]['time'], tz=timezone.utc)
        last_dt = datetime.fromtimestamp(candles[-1]['time'], tz=timezone.utc)
        span = (last_dt - first_dt).total_seconds() / 86400

        filepath = DATA_DIR / f'{coin}_USDT_1m.json'
        with open(filepath, 'w') as f:
            json.dump(candles, f)
        size_mb = filepath.stat().st_size / (1024 * 1024)

        print(f'  {coin}: {len(candles):,} bars, {first_dt:%Y-%m-%d} → {last_dt:%Y-%m-%d} '
              f'({span:.0f}d), {size_mb:.1f}MB, {elapsed:.0f}s')

    print('\n[DONE]')


if __name__ == '__main__':
    main()

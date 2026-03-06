"""Check if profitable micro-caps have enough liquidity for real trading."""
import sys, statistics
sys.path.insert(0, '/Users/oussama/Cryptogem/scripts')
from _ms018_helper import load_data, bt_coin, coin_symbol

data, coins = load_data()

results = []
for coin in coins:
    bars = data[coin]
    closes = [b['close'] for b in bars]
    volumes = [b['volume'] for b in bars]
    avg_vol_usd = statistics.mean([v*c for v, c in zip(volumes[-100:], closes[-100:])])
    try:
        res = bt_coin(data, coin)
        if res.trades > 0 and res.pnl > 0:
            results.append({
                'sym': coin_symbol(coin), 'pnl': res.pnl,
                'vol': avg_vol_usd, 'trades': res.trades
            })
    except:
        pass

results.sort(key=lambda x: -x['pnl'])

print(f'Profitable coins: {len(results)}')
daily_3k = [r for r in results if r['vol'] * 6 > 3000]
daily_500 = [r for r in results if r['vol'] * 6 > 500]
print(f'Daily vol > $3K: {len(daily_3k)} coins')
print(f'Daily vol > $500: {len(daily_500)} coins')
print(f'Daily vol < $500 (untradeable): {len(results) - len(daily_500)} coins')

print(f'\n=== BY DAILY VOLUME BUCKET ===')
for label, lo, hi in [
    ('< $500/day', 0, 83),
    ('$500-$5K', 83, 833),
    ('$5K-$50K', 833, 8333),
    ('$50K-$500K', 8333, 83333),
    ('> $500K', 83333, 1e12),
]:
    bucket = [r for r in results if lo <= r['vol'] * 6 < hi]
    if bucket:
        pnl = sum(r['pnl'] for r in bucket)
        avg_t = statistics.mean([r['trades'] for r in bucket])
        print(f'  {label:15s}: {len(bucket):3d} coins, PnL=${pnl:+,.0f}, avg trades={avg_t:.1f}')

# Realistic: enough volume + enough trades
realistic = [r for r in results if r['vol'] * 6 > 3000 and r['trades'] >= 4]
print(f'\n=== REALISTIC CANDIDATES (vol>$3K/day, trades>=4) ===')
print(f'Count: {len(realistic)}, PnL=${sum(r["pnl"] for r in realistic):+,.0f}')
for r in realistic[:20]:
    print(f'  {r["sym"]:12s} PnL=${r["pnl"]:+,.0f}, {r["trades"]} trades, daily=${r["vol"]*6:,.0f}')

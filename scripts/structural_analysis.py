"""Structural characteristics analysis: do profitable coins have different traits?"""
import sys, statistics
sys.path.insert(0, '/Users/oussama/Cryptogem/scripts')
from _ms018_helper import load_data, bt_coin, coin_symbol

data, coins_list = load_data()

coin_data = {}
for coin in coins_list:
    bars = data[coin]
    closes = [b['close'] if isinstance(b, dict) else b[4] for b in bars]
    highs = [b['high'] if isinstance(b, dict) else b[2] for b in bars]
    lows = [b['low'] if isinstance(b, dict) else b[3] for b in bars]
    volumes = [b['volume'] if isinstance(b, dict) else b[5] for b in bars]

    avg_price = statistics.mean(closes[-100:])
    trs = []
    for i in range(-100, -1):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    atr_pct = (statistics.mean(trs[-14:]) / avg_price * 100) if avg_price > 0 else 0
    avg_vol_usd = statistics.mean([v*c for v, c in zip(volumes[-100:], closes[-100:])])
    spreads = [(h-l)/c if c > 0 else 0 for h, l, c in zip(highs[-100:], lows[-100:], closes[-100:])]
    avg_spread_pct = statistics.mean(spreads) * 100
    returns = [(closes[i]-closes[i-1])/closes[i-1] if closes[i-1] > 0 else 0 for i in range(-99, 0)]
    volatility = statistics.stdev(returns) * 100 if len(returns) > 1 else 0

    try:
        res = bt_coin(data, coin)
        if res.trades > 0:
            coin_data[coin] = {
                'pnl': res.pnl, 'trades': res.trades, 'pf': res.pf,
                'atr_pct': atr_pct, 'avg_vol_usd': avg_vol_usd,
                'avg_spread_pct': avg_spread_pct, 'price_level': avg_price,
                'volatility': volatility,
            }
    except:
        pass

winners = {c: v for c, v in coin_data.items() if v['pnl'] > 0}
losers = {c: v for c, v in coin_data.items() if v['pnl'] <= 0}
print(f'Total: {len(coin_data)} | Winners: {len(winners)} | Losers: {len(losers)}')

metrics = ['atr_pct', 'avg_vol_usd', 'avg_spread_pct', 'price_level', 'volatility']
labels = ['ATR %', 'Avg Vol USD', 'Avg Spread %', 'Avg Price', 'Volatility %']

print(f'\n=== STRUCTURAL DIFFERENCES: WINNERS vs LOSERS ===')
print(f'{"Metric":20s} {"Winners":>15s} {"Losers":>15s} {"Ratio":>10s} {"Significant?":>15s}')
print('-' * 80)

structural_diffs = 0
for metric, label in zip(metrics, labels):
    wv = [v[metric] for v in winners.values() if v[metric] > 0]
    lv = [v[metric] for v in losers.values() if v[metric] > 0]
    if wv and lv:
        wm, lm = statistics.mean(wv), statistics.mean(lv)
        ratio = wm / lm if lm > 0 else float('inf')
        if ratio > 1.5 or ratio < 0.67:
            sig = f'YES ({ratio:.1f}x)'; structural_diffs += 1
        elif ratio > 1.25 or ratio < 0.8:
            sig = '~ MAYBE'
        else:
            sig = 'Similar'
        if metric == 'avg_vol_usd':
            print(f'{label:20s} {wm:>15,.0f} {lm:>15,.0f} {ratio:>10.2f}x {sig:>15s}')
        else:
            print(f'{label:20s} {wm:>15.3f} {lm:>15.3f} {ratio:>10.2f}x {sig:>15s}')

for qname, qmetric in [('VOLUME', 'avg_vol_usd'), ('VOLATILITY', 'volatility'), ('PRICE', 'price_level')]:
    print(f'\n=== PROFITABILITY BY {qname} QUARTILE ===')
    s = sorted([(c, v[qmetric], v['pnl']) for c, v in coin_data.items()], key=lambda x: x[1])
    qs = len(s) // 4
    for qi in range(4):
        start, end = qi*qs, (qi+1)*qs if qi < 3 else len(s)
        q = s[start:end]
        pnl = sum(c[2] for c in q)
        w = len([c for c in q if c[2] > 0])
        if qmetric == 'avg_vol_usd':
            rng = f'${q[0][1]:,.0f} - ${q[-1][1]:,.0f}'
        elif qmetric == 'price_level':
            rng = f'${q[0][1]:.4f} - ${q[-1][1]:.2f}'
        else:
            rng = f'{q[0][1]:.2f}% - {q[-1][1]:.2f}%'
        print(f'  Q{qi+1} ({rng}): PnL=${pnl:+,.0f}, {w}/{len(q)} profitable')

print(f'\n=== STRUCTURAL VERDICT ===')
if structural_diffs >= 2:
    print(f'  {structural_diffs} significant differences -> Edge is STRUCTURAL')
else:
    print(f'  Only {structural_diffs} differences -> Edge may be COINCIDENTAL')

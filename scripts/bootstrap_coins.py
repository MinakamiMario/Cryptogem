"""Bootstrap significance test: is halal coin selection better than random?"""
import sys, random, statistics
sys.path.insert(0, '/Users/oussama/Cryptogem/scripts')
from _ms018_helper import load_data, bt_coin, coin_symbol, load_halal

data, coins_list = load_data()

print('Computing per-coin PnL...')
coin_pnl = {}
for coin in coins_list:
    try:
        res = bt_coin(data, coin)
        if res.trades > 0:
            coin_pnl[coin] = res.pnl
    except:
        pass

print(f'Coins with trades: {len(coin_pnl)}')
print(f'Full universe PnL: ${sum(coin_pnl.values()):+,.0f}')

halal = load_halal()
halal_in_data = set()
for sym in halal:
    for coin in coin_pnl:
        if coin_symbol(coin) == sym:
            halal_in_data.add(coin)
            break

halal_pnl = sum(coin_pnl.get(c, 0) for c in halal_in_data)
hc = len(halal_in_data)
print(f'\nHalal whitelist: {len(halal)} symbols, {hc} in dataset')
print(f'Halal PnL: ${halal_pnl:+,.0f}')

N = 5000
random.seed(42)
all_coins = list(coin_pnl.keys())
rand_pnls = sorted([sum(coin_pnl[c] for c in random.sample(all_coins, min(hc, len(all_coins)))) for _ in range(N)])

beats = len([p for p in rand_pnls if p >= halal_pnl])
pctile = 100 * (1 - beats / N)

print(f'\n=== BOOTSTRAP ({N} random selections of {hc} coins) ===')
print(f'Halal PnL:     ${halal_pnl:+,.0f}')
print(f'Random mean:   ${statistics.mean(rand_pnls):+,.0f}')
print(f'Random median: ${statistics.median(rand_pnls):+,.0f}')
print(f'Random P5:     ${rand_pnls[int(N*0.05)]:+,.0f}')
print(f'Random P95:    ${rand_pnls[int(N*0.95)]:+,.0f}')
print(f'\n>= halal: {beats}/{N} ({100*beats/N:.1f}%)')
print(f'Percentile: {pctile:.1f}th')

best_n = sum(v for _, v in sorted(coin_pnl.items(), key=lambda x: -x[1])[:hc])
full = sum(coin_pnl.values())
all_prof = {c: p for c, p in coin_pnl.items() if p > 0}

print(f'\n=== STRATEGIES COMPARED ===')
print(f'  Full ({len(coin_pnl)}):      ${full:+,.0f}')
print(f'  Halal ({hc}):          ${halal_pnl:+,.0f}')
print(f'  Random {hc} (avg):      ${statistics.mean(rand_pnls):+,.0f}')
print(f'  Best {hc} (oracle):     ${best_n:+,.0f}')
print(f'  All profitable ({len(all_prof)}): ${sum(all_prof.values()):+,.0f}')

# Top-N stability across halves
min_bars = min(len(data[c]) for c in coins_list)
mid = min_bars // 2
fh, sh = {}, {}
for coin in coin_pnl:
    for store, s, e in [(fh, 0, mid), (sh, mid, min_bars)]:
        try:
            r = bt_coin(data, coin, start=s, end=e)
            if r.trades > 0: store[coin] = r.pnl
        except:
            pass

ft = set(c for c, _ in sorted(fh.items(), key=lambda x: -x[1])[:hc])
st = set(c for c, _ in sorted(sh.items(), key=lambda x: -x[1])[:hc])
ov = ft & st
print(f'\n=== TOP-{hc} STABILITY ===')
print(f'  Overlap: {len(ov)}/{hc} in BOTH halves')
print(f'  Stability: {100*len(ov)/hc:.0f}%')

print(f'\n=== VERDICT ===')
if pctile >= 90:
    print(f'  {pctile:.0f}th percentile -> Coin selection has REAL value')
elif pctile >= 60:
    print(f'  {pctile:.0f}th percentile -> MARGINAL, partly coincidental')
else:
    print(f'  {pctile:.0f}th percentile -> NOT better than random = OVERFITTING')

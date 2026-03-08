"""Temporal stability analysis for ms_018 per-coin profitability.
Split data into 3 windows, check which coins flip between profitable/unprofitable."""
import sys
sys.path.insert(0, '/Users/oussama/Cryptogem/scripts')
from _ms018_helper import load_data, bt_coin, coin_symbol, load_halal

data, coins_list = load_data()
min_bars = min(len(data[c]) for c in coins_list)
print(f'Total coins: {len(coins_list)}, min bars: {min_bars}')

ws = min_bars // 3
windows = [(0, ws), (ws, 2*ws), (2*ws, min_bars)]
print(f'Window size: ~{ws} bars (~{ws*4/24:.0f} days)')

results_by_window = {0: {}, 1: {}, 2: {}}
for coin in coins_list:
    for wi, (s, e) in enumerate(windows):
        try:
            res = bt_coin(data, coin, start=s, end=e)
            if res.trades > 0:
                results_by_window[wi][coin] = {'pnl': res.pnl, 'trades': res.trades, 'pf': res.pf}
        except:
            pass

print(f'\n=== COINS WITH TRADES PER WINDOW ===')
for wi in range(3):
    r = results_by_window[wi]
    p = len([c for c in r if r[c]['pnl'] > 0])
    print(f'Window {wi+1}: {len(r)} coins traded, {p} profitable, {len(r)-p} unprofitable')

all_traded = set()
for wi in range(3):
    all_traded |= set(results_by_window[wi].keys())

consistent_winners, consistent_losers, flippers = [], [], []
for coin in sorted(all_traded):
    wr = []
    for wi in range(3):
        if coin in results_by_window[wi]:
            wr.append(('W' if results_by_window[wi][coin]['pnl'] > 0 else 'L', results_by_window[wi][coin]['pnl']))
        else:
            wr.append(('N', 0))
    signs = [w[0] for w in wr if w[0] != 'N']
    if len(signs) >= 2:
        if all(s == 'W' for s in signs):
            consistent_winners.append((coin, wr))
        elif all(s == 'L' for s in signs):
            consistent_losers.append((coin, wr))
        else:
            flippers.append((coin, wr))

total = len(consistent_winners) + len(consistent_losers) + len(flippers)
print(f'\n=== CONSISTENCY ANALYSIS (coins in >=2 windows) ===')
print(f'Consistent winners: {len(consistent_winners)}')
print(f'Consistent losers:  {len(consistent_losers)}')
print(f'Flippers:           {len(flippers)}')
print(f'Flipper rate: {len(flippers)}/{total} = {100*len(flippers)/total:.1f}%')

halal = load_halal()
removed = {'BTC','ETH','SOL','APT','NEAR','SEI','AVAX','EGLD','XTZ','ALGO','FLOW',
           'POL','ARB','XRP','XLM','LINK','GRT','ATOM','INJ','TIA','FET','TAO','ICP','KAVA'}
new_coins = {'EDU','CTSI','AIOZ','LRC','ENS','ANKR','SC'}

def show(group, coins_set, label):
    for coin, wr in group:
        sym = coin_symbol(coin)
        if sym in coins_set:
            pat = ' | '.join([f'{w[0]}(${w[1]:+.0f})' for w in wr])
            print(f'  {sym:12s} {pat}  {label}')

print(f'\n=== REMOVED HALAL — Consistently bad? ===')
show(sorted(consistent_losers, key=lambda x: sum(w[1] for w in x[1])), removed, 'CONSISTENT LOSER')
show(flippers, removed, 'FLIPPER')

print(f'\n=== KEPT HALAL — Consistent winners? ===')
show(sorted(consistent_winners, key=lambda x: -sum(w[1] for w in x[1])), halal, 'CONSISTENT WINNER')
show(flippers, halal, 'FLIPPER')

print(f'\n=== NEW HALAL — Consistency check ===')
show(consistent_winners, new_coins, 'CONSISTENT WINNER')
show(flippers, new_coins, 'FLIPPER')
show(consistent_losers, new_coins, 'CONSISTENT LOSER')

print(f'\n=== PORTFOLIO-LEVEL STABILITY ===')
for wi in range(3):
    r = results_by_window[wi]
    pnl = sum(v['pnl'] for v in r.values())
    trades = sum(v['trades'] for v in r.values())
    p = len([c for c in r if r[c]['pnl'] > 0])
    print(f'Window {wi+1}: PnL=${pnl:+,.0f}, {trades} trades, {p}/{len(r)} profitable')

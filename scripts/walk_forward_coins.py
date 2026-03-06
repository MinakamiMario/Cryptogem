"""Walk-forward test: does selecting profitable coins IS predict OOS profitability?"""
import sys
sys.path.insert(0, '/Users/oussama/Cryptogem/scripts')
from _ms018_helper import load_data, bt_coin

data, coins_list = load_data()
min_bars = min(len(data[c]) for c in coins_list)

def run_split(name, is_s, is_e, oos_s, oos_e):
    print(f'\n{"="*60}')
    print(f'{name}')
    print(f'IS: bars {is_s}-{is_e} ({(is_e-is_s)*4/24:.0f}d) | OOS: bars {oos_s}-{oos_e} ({(oos_e-oos_s)*4/24:.0f}d)')
    print(f'{"="*60}')

    is_res, oos_res = {}, {}
    for coin in coins_list:
        for store, s, e in [(is_res, is_s, is_e), (oos_res, oos_s, oos_e)]:
            try:
                r = bt_coin(data, coin, start=s, end=e)
                if r.trades > 0:
                    store[coin] = {'pnl': r.pnl, 'trades': r.trades}
            except:
                pass

    is_win = set(c for c in is_res if is_res[c]['pnl'] > 0)
    is_lose = set(c for c in is_res if is_res[c]['pnl'] <= 0)
    print(f'IS: {len(is_res)} coins, {len(is_win)} winners, {len(is_lose)} losers')
    print(f'IS Total PnL: ${sum(v["pnl"] for v in is_res.values()):+,.0f}')

    win_oos = {c: oos_res[c] for c in is_win if c in oos_res}
    lose_oos = {c: oos_res[c] for c in is_lose if c in oos_res}

    still_w = len([c for c in win_oos if win_oos[c]['pnl'] > 0])
    win_pnl = sum(v['pnl'] for v in win_oos.values())
    print(f'\nIS Winners -> OOS:')
    print(f'  Still profitable: {still_w}/{len(win_oos)} ({100*still_w/max(1,len(win_oos)):.1f}%)')
    print(f'  OOS PnL (IS winners only): ${win_pnl:+,.0f}')

    flip_w = len([c for c in lose_oos if lose_oos[c]['pnl'] > 0])
    lose_pnl = sum(v['pnl'] for v in lose_oos.values())
    print(f'\nIS Losers -> OOS:')
    print(f'  Flipped to profit: {flip_w}/{len(lose_oos)} ({100*flip_w/max(1,len(lose_oos)):.1f}%)')
    print(f'  OOS PnL (IS losers only): ${lose_pnl:+,.0f}')

    all_oos = sum(v['pnl'] for v in oos_res.values())
    print(f'\nIS winners OOS=${win_pnl:+,.0f} vs IS losers OOS=${lose_pnl:+,.0f} vs All OOS=${all_oos:+,.0f}')

    if win_pnl > 0:
        print(f'  -> IS winners STILL profitable OOS = predictive value')
    else:
        print(f'  -> IS winners UNPROFITABLE OOS = OVERFITTING')

    return win_pnl

s70 = int(min_bars * 0.7)
s50 = min_bars // 2

results = []
results.append(('70/30 forward', run_split('70/30 FORWARD', 0, s70, s70, min_bars)))
results.append(('30/70 reverse', run_split('30/70 REVERSE', s70, min_bars, 0, s70)))
results.append(('50/50 split', run_split('50/50 SPLIT', 0, s50, s50, min_bars)))

print(f'\n{"="*60}')
print(f'WALK-FORWARD VERDICT')
print(f'{"="*60}')
passed = 0
for name, pnl in results:
    s = 'PASS' if pnl > 0 else 'FAIL'
    print(f'  {name}: ${pnl:+,.0f} {s}')
    if pnl > 0: passed += 1

print(f'\nCoin selection predictive power: {passed}/3 tests pass')
if passed >= 2:
    print('CONCLUSION: Coin selection has REAL signal - not pure overfitting')
elif passed == 1:
    print('CONCLUSION: WEAK evidence - coin selection is MARGINAL')
else:
    print('CONCLUSION: Coin selection is OVERFITTING - profitable set rotates')

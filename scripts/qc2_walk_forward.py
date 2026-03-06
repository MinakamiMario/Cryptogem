#!/usr/bin/env python3
"""QC2: Walk-forward validation on 19 QC1-PASS halal coins."""
import sys, json, importlib
sys.path.insert(0, '/Users/oussama/Cryptogem')
from strategies.ms.hypotheses import signal_structure_shift_pullback
from strategies.ms.indicators import precompute_ms_indicators
engine = importlib.import_module('strategies.4h.sprint3.engine')
run_backtest = engine.run_backtest

PARAMS = {
    'max_bos_age': 15, 'pullback_pct': 0.382, 'max_pullback_bars': 6,
    'max_stop_pct': 15.0, 'time_max_bars': 15,
    'rsi_recovery': True, 'rsi_rec_target': 45.0, 'rsi_rec_min_bars': 2,
}
MEXC_FEE = 0.001

# 19 coins that passed QC1 (spread <=25bps AND depth >= $500)
QC1_PASS = ['RARI', 'XMR', 'COOKIE', 'BAT', 'ASTER', 'LTC', 'MOVR', 'H', 'ZRO',
            'TRAC', 'SAHARA', 'GUN', 'STRK', 'B2', 'GMT', 'FF', 'AXS', 'ACH', 'OPEN']

# Also test current halal micro/mid winners for comparison
CURRENT_HALAL_MICROMID = ['EDU', 'CTSI', 'AIOZ', 'SC', 'QTUM', 'ANKR', 'LRC', 'SONIC']

# Load data
data_resolver = importlib.import_module('strategies.4h.data_resolver')
dataset_path = data_resolver.resolve_dataset('4h_default')
with open(dataset_path) as f:
    raw = json.load(f)
data = {k: v for k, v in raw.items() if not k.startswith('_') and isinstance(v, list)}

# Map symbols to dataset keys
def find_key(symbol):
    for k in data:
        if k.split('/')[0] == symbol:
            return k
    return None

# Get all available coins from both sets
test_coins = {}
for s in QC1_PASS + CURRENT_HALAL_MICROMID:
    k = find_key(s)
    if k and len(data[k]) >= 360:
        test_coins[s] = k

print(f"Testing {len(test_coins)} coins in walk-forward")
print(f"QC1 PASS found: {sum(1 for s in QC1_PASS if s in test_coins)}/{len(QC1_PASS)}")
print(f"Current halal found: {sum(1 for s in CURRENT_HALAL_MICROMID if s in test_coins)}/{len(CURRENT_HALAL_MICROMID)}")
print()

# Get total bars
all_keys = list(test_coins.values())
min_bars = min(len(data[k]) for k in all_keys)
print(f"Min bars across test coins: {min_bars}")

# Walk-forward: 70% IS / 30% OOS
split_bar = int(min_bars * 0.7)
print(f"Split bar: {split_bar} (IS: 0-{split_bar}, OOS: {split_bar}-{min_bars})")
print()

# Run IS and OOS backtests per coin
results = {}
for symbol, key in test_coins.items():
    bars = data[key]

    # IS period
    is_bars = bars[:split_bar]
    is_single = {key: is_bars}
    is_ind = precompute_ms_indicators(is_single, [key])
    is_res = run_backtest(is_single, [key], signal_structure_shift_pullback, PARAMS, is_ind,
                          fee=MEXC_FEE, initial_capital=10000, max_pos=1)

    # OOS period
    oos_bars = bars[split_bar:]
    oos_single = {key: oos_bars}
    oos_ind = precompute_ms_indicators(oos_single, [key])
    oos_res = run_backtest(oos_single, [key], signal_structure_shift_pullback, PARAMS, oos_ind,
                           fee=MEXC_FEE, initial_capital=10000, max_pos=1)

    # Full period
    full_single = {key: bars}
    full_ind = precompute_ms_indicators(full_single, [key])
    full_res = run_backtest(full_single, [key], signal_structure_shift_pullback, PARAMS, full_ind,
                            fee=MEXC_FEE, initial_capital=10000, max_pos=1)

    group = 'QC1_PASS' if symbol in QC1_PASS else 'CURRENT_HALAL'

    # Handle trades field
    def get_trade_count(res):
        t = res.trades
        if isinstance(t, list):
            return len(t)
        return t

    results[symbol] = {
        'group': group,
        'is_pnl': is_res.pnl, 'is_trades': get_trade_count(is_res),
        'oos_pnl': oos_res.pnl, 'oos_trades': get_trade_count(oos_res),
        'full_pnl': full_res.pnl, 'full_trades': get_trade_count(full_res),
        'is_profitable': is_res.pnl > 0,
        'oos_profitable': oos_res.pnl > 0,
    }

# Analysis
print("=" * 90)
print("WALK-FORWARD RESULTS: 70% IS / 30% OOS")
print("=" * 90)
print(f"{'Coin':<10} {'Group':<15} {'IS PnL':>10} {'IS Tr':>6} {'OOS PnL':>10} {'OOS Tr':>7} {'Full PnL':>10} {'Verdict':>10}")
print("-" * 90)

for symbol in sorted(results, key=lambda s: (results[s]['group'], -results[s]['oos_pnl'])):
    r = results[symbol]
    verdict = "PASS" if r['is_profitable'] and r['oos_profitable'] else \
              "IS_ONLY" if r['is_profitable'] and not r['oos_profitable'] else \
              "OOS_ONLY" if not r['is_profitable'] and r['oos_profitable'] else "FAIL"

    print(f"{symbol:<10} {r['group']:<15} ${r['is_pnl']:>+9.0f} {r['is_trades']:>6} ${r['oos_pnl']:>+9.0f} {r['oos_trades']:>7} ${r['full_pnl']:>+9.0f} {verdict:>10}")

# Summary statistics
print()
print("=" * 90)
print("SUMMARY BY GROUP")
print("=" * 90)

for group in ['QC1_PASS', 'CURRENT_HALAL']:
    coins = {s: r for s, r in results.items() if r['group'] == group}
    if not coins:
        continue

    n = len(coins)
    is_winners = sum(1 for r in coins.values() if r['is_profitable'])
    oos_winners = sum(1 for r in coins.values() if r['oos_profitable'])
    pass_both = sum(1 for r in coins.values() if r['is_profitable'] and r['oos_profitable'])
    is_total = sum(r['is_pnl'] for r in coins.values())
    oos_total = sum(r['oos_pnl'] for r in coins.values())
    full_total = sum(r['full_pnl'] for r in coins.values())

    print(f"\n{group} ({n} coins):")
    print(f"  IS winners:    {is_winners}/{n} ({100*is_winners/n:.0f}%)")
    print(f"  OOS winners:   {oos_winners}/{n} ({100*oos_winners/n:.0f}%)")
    print(f"  PASS (both):   {pass_both}/{n} ({100*pass_both/n:.0f}%)")
    print(f"  IS total PnL:  ${is_total:+,.0f}")
    print(f"  OOS total PnL: ${oos_total:+,.0f}")
    print(f"  Full PnL:      ${full_total:+,.0f}")

    # Predictive value
    is_win_coins = [s for s, r in coins.items() if r['is_profitable']]
    if is_win_coins:
        still_oos = sum(1 for s in is_win_coins if coins[s]['oos_profitable'])
        print(f"  Predictive value: {still_oos}/{len(is_win_coins)} IS winners stay OOS profitable ({100*still_oos/len(is_win_coins):.0f}%)")

    is_lose_coins = [s for s, r in coins.items() if not r['is_profitable']]
    if is_lose_coins:
        flipped_oos = sum(1 for s in is_lose_coins if coins[s]['oos_profitable'])
        print(f"  Flipper check: {flipped_oos}/{len(is_lose_coins)} IS losers flip to OOS winners ({100*flipped_oos/len(is_lose_coins):.0f}%)")

# Combined verdict
print()
print("=" * 90)
print("COMBINED WALK-FORWARD VERDICT")
print("=" * 90)

qc1_coins = {s: r for s, r in results.items() if r['group'] == 'QC1_PASS'}
qc1_pass_both = sum(1 for r in qc1_coins.values() if r['is_profitable'] and r['oos_profitable'])
qc1_oos_total = sum(r['oos_pnl'] for r in qc1_coins.values())
qc1_n = len(qc1_coins)

print(f"QC1_PASS coins: {qc1_pass_both}/{qc1_n} pass walk-forward ({100*qc1_pass_both/qc1_n:.0f}%)")
print(f"QC1_PASS OOS total PnL: ${qc1_oos_total:+,.0f}")

if qc1_oos_total > 0 and qc1_n > 0 and qc1_pass_both / qc1_n >= 0.4:
    print("\nVERDICT: QC2 PASS — expanded set shows walk-forward predictive value")
elif qc1_oos_total > 0:
    print("\nVERDICT: QC2 CONDITIONAL — positive OOS but low pass rate")
else:
    print("\nVERDICT: QC2 FAIL — expanded set does not survive walk-forward")

#!/usr/bin/env python3
"""Large-cap vs micro-cap structural analysis + parameter sweep on ms_018."""
import json, sys, importlib
sys.path.insert(0, '/Users/oussama/Cryptogem')

from strategies.ms.hypotheses import signal_structure_shift_pullback
from strategies.ms.indicators import precompute_ms_indicators

engine = importlib.import_module('strategies.4h.sprint3.engine')
run_backtest = engine.run_backtest
data_resolver = importlib.import_module('strategies.4h.data_resolver')

# Load Kraken 4H data
dataset_path = data_resolver.resolve_dataset('4h_default')
with open(dataset_path) as f:
    raw = json.load(f)
data = {k: v for k, v in raw.items()
        if not k.startswith('_') and isinstance(v, list) and len(v) >= 360}

# Define coin groups
LARGE_CAPS = ['ADA/USD', 'DOT/USD', 'SUI/USD', 'SOL/USD', 'XRP/USD', 'NEAR/USD',
              'AVAX/USD', 'ATOM/USD', 'LINK/USD', 'APT/USD']
KNOWN_WINNERS = ['EDU/USD', 'SC/USD', 'QTUM/USD', 'ANKR/USD', 'LRC/USD']

large = [c for c in LARGE_CAPS if c in data]
winners = [c for c in KNOWN_WINNERS if c in data]

MEXC_FEE = 0.001

# Default ms_018 params
DEFAULT = {
    'max_bos_age': 15, 'pullback_pct': 0.382, 'max_pullback_bars': 6,
    'max_stop_pct': 15.0, 'time_max_bars': 15,
    'rsi_recovery': True, 'rsi_rec_target': 45.0, 'rsi_rec_min_bars': 2,
}

# Large-cap friendly param variants
VARIANTS = {
    'default':          DEFAULT.copy(),
    'shallow_pb':       {**DEFAULT, 'pullback_pct': 0.20, 'max_pullback_bars': 10},
    'wider_bos':        {**DEFAULT, 'max_bos_age': 25, 'pullback_pct': 0.25, 'max_pullback_bars': 12},
    'low_rsi':          {**DEFAULT, 'pullback_pct': 0.25, 'rsi_rec_target': 40.0, 'max_pullback_bars': 10},
    'aggressive':       {**DEFAULT, 'pullback_pct': 0.15, 'max_bos_age': 30, 'max_pullback_bars': 15, 'rsi_rec_target': 38.0},
    'very_shallow':     {**DEFAULT, 'pullback_pct': 0.10, 'max_bos_age': 20, 'max_pullback_bars': 15},
}


def bt_group(coins, params):
    """Backtest a group of coins."""
    indicators = precompute_ms_indicators(data, coins)
    res = run_backtest(data, coins, signal_structure_shift_pullback, params, indicators,
                       fee=MEXC_FEE, initial_capital=10000, max_pos=1)
    return res


print("=" * 80)
print("MS-018 LARGE-CAP PARAMETER EXPERIMENT")
print(f"Large-caps: {len(large)} coins | Known winners: {len(winners)} coins")
print("=" * 80)

for vname, params in VARIANTS.items():
    res_l = bt_group(large, params)
    res_w = bt_group(winners, params)

    print(f"\n--- {vname} (pb={params['pullback_pct']}, bos={params['max_bos_age']}, "
          f"pb_bars={params['max_pullback_bars']}, rsi={params['rsi_rec_target']}) ---")
    print(f"  LARGE  ({len(large):2}): trades={res_l.trades:3}, PF={res_l.pf:.2f}, PnL=${res_l.pnl:+8,.0f}, DD={res_l.dd:5.1f}%")
    print(f"  WINNER ({len(winners):2}): trades={res_w.trades:3}, PF={res_w.pf:.2f}, PnL=${res_w.pnl:+8,.0f}, DD={res_w.dd:5.1f}%")


print("\n" + "=" * 80)
print("PER-COIN BREAKDOWN — all variants")
print("=" * 80)

all_coins = large + winners
for coin in all_coins:
    single = {coin: data[coin]}
    tag = "LARGE" if coin in large else "WINNER"
    results = []
    for vname, params in VARIANTS.items():
        ind = precompute_ms_indicators(single, [coin])
        res = run_backtest(single, [coin], signal_structure_shift_pullback, params, ind,
                           fee=MEXC_FEE, initial_capital=10000, max_pos=1)
        results.append((vname, res.trades, res.pf, res.pnl))

    print(f"\n  [{tag:6}] {coin}")
    for vname, t, pf, pnl in results:
        if t > 0:
            print(f"    {vname:16} trades={t:3}, PF={pf:.2f}, PnL=${pnl:+,.0f}")
        else:
            print(f"    {vname:16} NO TRADES")

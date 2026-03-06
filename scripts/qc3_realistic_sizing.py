#!/usr/bin/env python3
"""QC3: Realistic sizing backtest — $500/trade, max_pos=2, combined portfolio."""
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

QC1_PASS = ['RARI', 'XMR', 'COOKIE', 'BAT', 'ASTER', 'LTC', 'MOVR', 'H', 'ZRO',
            'TRAC', 'SAHARA', 'GUN', 'STRK', 'B2', 'GMT', 'FF', 'AXS', 'ACH', 'OPEN']

CURRENT_HALAL_MICROMID = ['EDU', 'CTSI', 'AIOZ', 'SC', 'QTUM', 'ANKR', 'LRC', 'SONIC']

# Load data
data_resolver = importlib.import_module('strategies.4h.data_resolver')
dataset_path = data_resolver.resolve_dataset('4h_default')
with open(dataset_path) as f:
    raw = json.load(f)
data = {k: v for k, v in raw.items() if not k.startswith('_') and isinstance(v, list)}

def find_key(symbol):
    for k in data:
        if k.split('/')[0] == symbol:
            return k
    return None

# Build coin sets
qc1_keys = []
for s in QC1_PASS:
    k = find_key(s)
    if k and len(data[k]) >= 360:
        qc1_keys.append(k)

current_keys = []
for s in CURRENT_HALAL_MICROMID:
    k = find_key(s)
    if k and len(data[k]) >= 360:
        current_keys.append(k)

# Combined = QC1 PASS + current halal micro/mid
combined_keys = list(set(qc1_keys + current_keys))

print("=" * 80)
print("QC3: REALISTIC SIZING BACKTEST")
print("=" * 80)
print()

# Test configurations
configs = [
    ("QC1 PASS (19 coins)", qc1_keys),
    ("Current Halal Micro/Mid (8)", current_keys),
    ("Combined (all)", combined_keys),
]

# Test with different sizing
sizing_configs = [
    # (initial_capital, max_pos, label)
    (2000, 3, "Default ($2K, max_pos=3)"),
    (5000, 2, "Conservative ($5K, max_pos=2)"),
    (10000, 3, "Standard ($10K, max_pos=3)"),
    (500, 1, "Minimal ($500, max_pos=1)"),
]

for label, coins in configs:
    print(f"\n{'='*80}")
    print(f"PORTFOLIO: {label} — {len(coins)} coins")
    print(f"{'='*80}")
    print(f"{'Sizing':<30} {'PF':>6} {'Trades':>7} {'PnL':>12} {'DD%':>8} {'WR%':>6}")
    print("-" * 75)

    for capital, max_pos, size_label in sizing_configs:
        # Build subset
        subset = {k: data[k] for k in coins}
        indicators = precompute_ms_indicators(subset, coins)

        res = run_backtest(subset, coins, signal_structure_shift_pullback, PARAMS, indicators,
                           fee=MEXC_FEE, initial_capital=capital, max_pos=max_pos)

        trades = len(res.trades) if isinstance(res.trades, list) else res.trades
        pf = res.pf if hasattr(res, 'pf') else 0
        wr = res.wr if hasattr(res, 'wr') else 0
        dd = res.dd if hasattr(res, 'dd') else 0

        print(f"{size_label:<30} {pf:>6.2f} {trades:>7} ${res.pnl:>+11,.0f} {dd:>7.1f}% {wr:>5.1f}%")

# Detailed trade analysis for recommended config
print()
print("=" * 80)
print("DETAILED: Combined portfolio, $5K capital, max_pos=2")
print("=" * 80)

subset = {k: data[k] for k in combined_keys}
indicators = precompute_ms_indicators(subset, combined_keys)
res = run_backtest(subset, combined_keys, signal_structure_shift_pullback, PARAMS, indicators,
                   fee=MEXC_FEE, initial_capital=5000, max_pos=2)

trades = res.trades if isinstance(res.trades, list) else []
if trades:
    # Analyze exit classes
    exit_classes = {}
    for t in trades:
        ec = t.get('exit_class', t.get('exit_reason', 'unknown'))
        if ec not in exit_classes:
            exit_classes[ec] = {'count': 0, 'pnl': 0}
        exit_classes[ec]['count'] += 1
        exit_classes[ec]['pnl'] += t.get('pnl', 0)

    print(f"\nExit Class Decomposition:")
    print(f"{'Exit Class':<25} {'Count':>7} {'PnL':>12} {'Avg PnL':>10}")
    print("-" * 60)
    for ec in sorted(exit_classes, key=lambda x: exit_classes[x]['pnl'], reverse=True):
        d = exit_classes[ec]
        avg = d['pnl'] / d['count'] if d['count'] > 0 else 0
        print(f"{ec:<25} {d['count']:>7} ${d['pnl']:>+11,.0f} ${avg:>+9,.0f}")

    # Per-coin analysis
    coin_stats = {}
    for t in trades:
        coin = t.get('coin', t.get('symbol', 'unknown'))
        if coin not in coin_stats:
            coin_stats[coin] = {'count': 0, 'pnl': 0}
        coin_stats[coin]['count'] += 1
        coin_stats[coin]['pnl'] += t.get('pnl', 0)

    print(f"\nPer-Coin Breakdown (top 10 by PnL):")
    print(f"{'Coin':<20} {'Trades':>7} {'PnL':>12}")
    print("-" * 45)
    for coin in sorted(coin_stats, key=lambda x: coin_stats[x]['pnl'], reverse=True)[:10]:
        d = coin_stats[coin]
        sym = coin.split('/')[0]
        print(f"{sym:<20} {d['count']:>7} ${d['pnl']:>+11,.0f}")

    print(f"\nBottom 5 by PnL:")
    for coin in sorted(coin_stats, key=lambda x: coin_stats[x]['pnl'])[:5]:
        d = coin_stats[coin]
        sym = coin.split('/')[0]
        print(f"{sym:<20} {d['count']:>7} ${d['pnl']:>+11,.0f}")

# Final summary
print()
print("=" * 80)
print("QC3 VERDICT")
print("=" * 80)

# Use $5K, max_pos=2 as recommended
subset = {k: data[k] for k in combined_keys}
indicators = precompute_ms_indicators(subset, combined_keys)
res = run_backtest(subset, combined_keys, signal_structure_shift_pullback, PARAMS, indicators,
                   fee=MEXC_FEE, initial_capital=5000, max_pos=2)

pf = res.pf if hasattr(res, 'pf') else 0
dd = res.dd if hasattr(res, 'dd') else 0
trades_n = len(res.trades) if isinstance(res.trades, list) else res.trades

print(f"Combined portfolio ({len(combined_keys)} coins), $5K, max_pos=2:")
print(f"  PF: {pf:.2f}")
print(f"  DD: {dd:.1f}%")
print(f"  Trades: {trades_n}")
print(f"  PnL: ${res.pnl:+,.0f}")

if pf >= 1.5 and dd <= 30:
    print("\nVERDICT: QC3 PASS — realistic sizing maintains strong performance")
elif pf >= 1.2 and dd <= 40:
    print("\nVERDICT: QC3 CONDITIONAL — acceptable but drawdown needs monitoring")
else:
    print("\nVERDICT: QC3 FAIL — performance degrades with realistic sizing")

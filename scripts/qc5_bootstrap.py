#!/usr/bin/env python3
"""QC5: Bootstrap significance — 19 QC1-PASS coins vs random 19."""
import sys, json, importlib, random
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

# Load data
data_resolver = importlib.import_module('strategies.4h.data_resolver')
dataset_path = data_resolver.resolve_dataset('4h_default')
with open(dataset_path) as f:
    raw = json.load(f)
data = {k: v for k, v in raw.items() if not k.startswith('_') and isinstance(v, list)}
all_coins = [c for c in data if len(data[c]) >= 360]
print(f"Universe: {len(all_coins)} coins with >=360 bars")

# Map QC1 PASS to dataset keys
def find_key(symbol):
    for k in data:
        if k.split('/')[0] == symbol:
            return k
    return None

qc1_keys = []
for s in QC1_PASS:
    k = find_key(s)
    if k and k in all_coins:
        qc1_keys.append(k)

print(f"QC1 PASS in dataset: {len(qc1_keys)}/{len(QC1_PASS)}")
N = len(qc1_keys)

# Pre-compute all coin PnLs (once)
print("Pre-computing all coin backtests...")
coin_pnls = {}
for i, coin in enumerate(all_coins):
    if (i + 1) % 50 == 0:
        print(f"  {i+1}/{len(all_coins)}...")
    single = {coin: data[coin]}
    ind = precompute_ms_indicators(single, [coin])
    res = run_backtest(single, [coin], signal_structure_shift_pullback, PARAMS, ind,
                       fee=MEXC_FEE, initial_capital=10000, max_pos=1)
    coin_pnls[coin] = res.pnl

print(f"Done. {sum(1 for v in coin_pnls.values() if v > 0)}/{len(coin_pnls)} coins profitable")

# QC1 PASS portfolio PnL
qc1_pnl = sum(coin_pnls[k] for k in qc1_keys)
print(f"\nQC1 PASS portfolio PnL: ${qc1_pnl:+,.0f}")

# Bootstrap: 5000 random selections of N coins
N_BOOT = 5000
random.seed(42)
random_pnls = []
for _ in range(N_BOOT):
    sample = random.sample(all_coins, N)
    pnl = sum(coin_pnls[c] for c in sample)
    random_pnls.append(pnl)

random_pnls.sort()
mean_random = sum(random_pnls) / len(random_pnls)
median_random = random_pnls[len(random_pnls) // 2]

# Percentile of QC1 PASS
rank = sum(1 for p in random_pnls if p <= qc1_pnl)
percentile = 100 * rank / N_BOOT

# Oracle best-N
sorted_coins = sorted(all_coins, key=lambda c: coin_pnls[c], reverse=True)
oracle_pnl = sum(coin_pnls[c] for c in sorted_coins[:N])

print()
print("=" * 80)
print(f"QC5: BOOTSTRAP SIGNIFICANCE — {N} coins, {N_BOOT} iterations")
print("=" * 80)
print(f"  QC1 PASS PnL:     ${qc1_pnl:+,.0f}")
print(f"  Random mean:       ${mean_random:+,.0f}")
print(f"  Random median:     ${median_random:+,.0f}")
print(f"  Random P5:         ${random_pnls[int(N_BOOT*0.05)]:+,.0f}")
print(f"  Random P95:        ${random_pnls[int(N_BOOT*0.95)]:+,.0f}")
print(f"  Percentile:        {percentile:.1f}th")
print(f"  Oracle best-{N}:    ${oracle_pnl:+,.0f}")
print(f"  Capture ratio:     {100*qc1_pnl/oracle_pnl:.1f}%" if oracle_pnl > 0 else "  Capture ratio: N/A")
print(f"  vs random mean:    {qc1_pnl/mean_random:.1f}x" if mean_random != 0 else "  vs random mean: N/A")

# Distribution analysis
print()
print("Distribution of random portfolios:")
buckets = [0, 10, 25, 50, 75, 90, 100]
for b in buckets:
    idx = min(int(N_BOOT * b / 100), N_BOOT - 1)
    print(f"  P{b:>3}: ${random_pnls[idx]:+,.0f}")

# Verdict
print()
if percentile >= 90:
    print("VERDICT: QC5 PASS — QC1 PASS set is HIGHLY significant (>90th percentile)")
elif percentile >= 75:
    print("VERDICT: QC5 PASS — QC1 PASS set is significant (>75th percentile)")
elif percentile >= 60:
    print("VERDICT: QC5 CONDITIONAL — marginally better than random (>60th percentile)")
else:
    print("VERDICT: QC5 FAIL — QC1 PASS set is NOT significantly better than random")

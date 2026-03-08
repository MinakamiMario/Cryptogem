#!/usr/bin/env python3
"""MS-018 Strategy Integrity Evaluation — answers: is this a real edge or survivorship bias?

4 tests:
1. Blind portfolio: all 444 coins, no selection
2. Per-coin distribution: what % profitable?
3. Walk-forward: 70/30 split, do IS winners stay profitable OOS?
4. Random benchmark: 1000 trials of 24 random coins vs halal set
"""
import json, sys, random, importlib, time
from collections import Counter

sys.path.insert(0, '/Users/oussama/Cryptogem')

from strategies.ms.hypotheses import signal_structure_shift_pullback
from strategies.ms.indicators import precompute_ms_indicators

engine = importlib.import_module('strategies.4h.sprint3.engine')
run_backtest = engine.run_backtest

MEXC_FEE = 0.001
DATASET = '/Users/oussama/CryptogemData/derived/candle_cache/mexc/4h/candle_cache_4h_mexc_v2.json'

DEFAULT_PARAMS = {
    'max_bos_age': 15, 'pullback_pct': 0.382, 'max_pullback_bars': 6,
    'max_stop_pct': 15.0, 'time_max_bars': 15,
    'rsi_recovery': True, 'rsi_rec_target': 45.0, 'rsi_rec_min_bars': 2,
}

# Current halal set
HALAL_SET = [
    'ACH/USDT', 'H/USDT', 'XMR/USDT', 'GUN/USDT', 'BAT/USDT', 'LTC/USDT',
    'ASTER/USDT', 'EDU/USDT', 'FF/USDT', 'SAHARA/USDT', 'ANKR/USDT',
    'LRC/USDT', 'STRK/USDT', 'ZRO/USDT', 'COOKIE/USDT', 'AXS/USDT',
]

print("Loading MEXC 4H dataset...", flush=True)
t0 = time.time()
with open(DATASET) as f:
    raw = json.load(f)
data = {k: v for k, v in raw.items()
        if not k.startswith('_') and isinstance(v, list) and len(v) >= 360}
print(f"  Loaded {len(data)} coins in {time.time()-t0:.1f}s\n", flush=True)


def bt_single(coin_data, coins, params=None):
    """Backtest a set of coins. Returns BacktestResult."""
    if params is None:
        params = DEFAULT_PARAMS
    indicators = precompute_ms_indicators(coin_data, coins)
    return run_backtest(coin_data, coins, signal_structure_shift_pullback,
                        params, indicators, fee=MEXC_FEE,
                        initial_capital=10000, max_pos=1)


def bt_per_coin(coins, params=None):
    """Backtest each coin individually. Returns list of (coin, trades, pf, pnl)."""
    results = []
    for i, coin in enumerate(coins):
        if coin not in data:
            continue
        single = {coin: data[coin]}
        try:
            res = bt_single(single, [coin], params)
            results.append((coin, res.trades, res.pf, res.pnl))
        except Exception as e:
            results.append((coin, 0, 0.0, 0.0))
        if (i + 1) % 50 == 0:
            print(f"    ... {i+1}/{len(coins)} coins done", flush=True)
    return results


# ════════════════════════════════════════════════════════════════
# TEST 1: Blind Portfolio — alle 444 coins, geen selectie
# ════════════════════════════════════════════════════════════════
print("=" * 70)
print("TEST 1: BLIND PORTFOLIO — all coins, no selection")
print("=" * 70, flush=True)

all_coins = list(data.keys())
t1 = time.time()
blind_res = bt_single(data, all_coins)
print(f"  Coins:  {len(all_coins)}")
print(f"  Trades: {blind_res.trades}")
print(f"  PF:     {blind_res.pf:.2f}")
print(f"  PnL:    ${blind_res.pnl:+,.0f}")
print(f"  WR:     {blind_res.wr:.1f}%")
print(f"  DD:     {blind_res.dd:.1f}%")
print(f"  Time:   {time.time()-t1:.1f}s\n", flush=True)


# ════════════════════════════════════════════════════════════════
# TEST 2: Per-Coin Distribution
# ════════════════════════════════════════════════════════════════
print("=" * 70)
print("TEST 2: PER-COIN DISTRIBUTION")
print("=" * 70, flush=True)

t2 = time.time()
per_coin = bt_per_coin(all_coins)
print(f"  Time: {time.time()-t2:.1f}s\n", flush=True)

# Filter coins with trades
active = [(c, t, pf, pnl) for c, t, pf, pnl in per_coin if t >= 2]
profitable = [(c, t, pf, pnl) for c, t, pf, pnl in active if pnl > 0]
strong = [(c, t, pf, pnl) for c, t, pf, pnl in active if pf > 1.3]
losing = [(c, t, pf, pnl) for c, t, pf, pnl in active if pnl < 0]

print(f"  Total coins with ≥2 trades: {len(active)}")
print(f"  Profitable (PnL > 0):       {len(profitable)} ({100*len(profitable)/max(len(active),1):.1f}%)")
print(f"  Strong (PF > 1.3):          {len(strong)} ({100*len(strong)/max(len(active),1):.1f}%)")
print(f"  Losing (PnL < 0):           {len(losing)} ({100*len(losing)/max(len(active),1):.1f}%)")

# PnL distribution
pnls = sorted([pnl for _, _, _, pnl in active])
if pnls:
    import statistics
    print(f"\n  PnL distribution:")
    print(f"    Min:    ${pnls[0]:+,.0f}")
    print(f"    P10:    ${pnls[int(len(pnls)*0.1)]:+,.0f}")
    print(f"    P25:    ${pnls[int(len(pnls)*0.25)]:+,.0f}")
    print(f"    Median: ${pnls[len(pnls)//2]:+,.0f}")
    print(f"    P75:    ${pnls[int(len(pnls)*0.75)]:+,.0f}")
    print(f"    P90:    ${pnls[int(len(pnls)*0.9)]:+,.0f}")
    print(f"    Max:    ${pnls[-1]:+,.0f}")
    print(f"    Mean:   ${statistics.mean(pnls):+,.0f}")
    total_pnl = sum(pnls)
    print(f"    SUM:    ${total_pnl:+,.0f}")

# PF distribution
pfs = sorted([pf for _, _, pf, _ in active if pf < 100])  # exclude inf
if pfs:
    print(f"\n  PF distribution (excl inf):")
    print(f"    Min:    {pfs[0]:.2f}")
    print(f"    P25:    {pfs[int(len(pfs)*0.25)]:.2f}")
    print(f"    Median: {pfs[len(pfs)//2]:.2f}")
    print(f"    P75:    {pfs[int(len(pfs)*0.75)]:.2f}")
    print(f"    Max:    {pfs[-1]:.2f}")

# Trade count distribution
trade_counts = [t for _, t, _, _ in active]
if trade_counts:
    print(f"\n  Trade count distribution:")
    print(f"    Min:    {min(trade_counts)}")
    print(f"    Median: {sorted(trade_counts)[len(trade_counts)//2]}")
    print(f"    Max:    {max(trade_counts)}")
    print(f"    Total:  {sum(trade_counts)}")

print(flush=True)


# ════════════════════════════════════════════════════════════════
# TEST 3: Walk-Forward (70/30) op ALLE coins
# ════════════════════════════════════════════════════════════════
print("=" * 70)
print("TEST 3: WALK-FORWARD — 70% IS / 30% OOS per coin")
print("=" * 70, flush=True)

t3 = time.time()
wf_results = []
coins_tested = 0

for coin in all_coins:
    bars = data[coin]
    n = len(bars)
    if n < 360:
        continue
    split = int(n * 0.7)
    is_bars = bars[:split]
    oos_bars = bars[split:]

    if len(is_bars) < 200 or len(oos_bars) < 50:
        continue

    is_data = {coin: is_bars}
    oos_data = {coin: oos_bars}

    try:
        is_res = bt_single(is_data, [coin])
        oos_res = bt_single(oos_data, [coin])
        if is_res.trades >= 2:
            wf_results.append({
                'coin': coin,
                'is_trades': is_res.trades, 'is_pf': is_res.pf, 'is_pnl': is_res.pnl,
                'oos_trades': oos_res.trades, 'oos_pf': oos_res.pf, 'oos_pnl': oos_res.pnl,
            })
    except:
        pass

    coins_tested += 1
    if coins_tested % 50 == 0:
        print(f"    ... {coins_tested} coins done", flush=True)

print(f"  Coins tested: {coins_tested}")
print(f"  Coins with IS trades: {len(wf_results)}")
print(f"  Time: {time.time()-t3:.1f}s\n", flush=True)

# Analyze WF results
is_winners = [r for r in wf_results if r['is_pf'] > 1.0]
is_strong = [r for r in wf_results if r['is_pf'] > 1.3]

# Key question: do IS winners stay profitable OOS?
oos_still_profitable = [r for r in is_winners if r['oos_pnl'] > 0]
oos_still_strong = [r for r in is_strong if r['oos_pf'] > 1.0]

print(f"  IS winners (PF>1.0):           {len(is_winners)}")
print(f"  IS strong (PF>1.3):            {len(is_strong)}")
print(f"  IS winners → OOS profitable:   {len(oos_still_profitable)}/{len(is_winners)} ({100*len(oos_still_profitable)/max(len(is_winners),1):.1f}%)")
print(f"  IS strong → OOS profitable:    {len(oos_still_strong)}/{len(is_strong)} ({100*len(oos_still_strong)/max(len(is_strong),1):.1f}%)")

# Aggregate: if we traded ALL IS winners OOS
if is_winners:
    oos_pnls = [r['oos_pnl'] for r in is_winners]
    oos_profits = sum(p for p in oos_pnls if p > 0)
    oos_losses = sum(p for p in oos_pnls if p < 0)
    agg_pf = oos_profits / abs(oos_losses) if oos_losses != 0 else float('inf')
    print(f"\n  Aggregate OOS (all IS winners):")
    print(f"    Coins:    {len(is_winners)}")
    print(f"    OOS PnL:  ${sum(oos_pnls):+,.0f}")
    print(f"    OOS PF:   {agg_pf:.2f}")

if is_strong:
    oos_pnls_s = [r['oos_pnl'] for r in is_strong]
    oos_prof_s = sum(p for p in oos_pnls_s if p > 0)
    oos_loss_s = sum(p for p in oos_pnls_s if p < 0)
    agg_pf_s = oos_prof_s / abs(oos_loss_s) if oos_loss_s != 0 else float('inf')
    print(f"\n  Aggregate OOS (IS strong PF>1.3):")
    print(f"    Coins:    {len(is_strong)}")
    print(f"    OOS PnL:  ${sum(oos_pnls_s):+,.0f}")
    print(f"    OOS PF:   {agg_pf_s:.2f}")

# Degradation analysis
if is_winners:
    degradations = []
    for r in is_winners:
        if r['oos_trades'] >= 1 and r['is_pf'] > 0:
            deg = (r['oos_pf'] - r['is_pf']) / r['is_pf'] * 100 if r['is_pf'] < 100 else 0
            degradations.append(deg)
    if degradations:
        print(f"\n  PF Degradation IS → OOS:")
        print(f"    Avg: {statistics.mean(degradations):+.1f}%")
        print(f"    Median: {sorted(degradations)[len(degradations)//2]:+.1f}%")

print(flush=True)


# ════════════════════════════════════════════════════════════════
# TEST 4: Random Selection Benchmark (500 trials)
# ════════════════════════════════════════════════════════════════
print("=" * 70)
print("TEST 4: RANDOM BENCHMARK — 500 trials of 24 random coins")
print("=" * 70, flush=True)

t4 = time.time()
random.seed(42)
N_TRIALS = 500
N_COINS = 24

# Pre-compute per-coin PnL for speed (reuse TEST 2 results)
coin_pnl_map = {c: pnl for c, _, _, pnl in per_coin if _ >= 1}  # at least 1 trade
eligible_coins = [c for c in coin_pnl_map.keys()]

random_pnls = []
random_pfs = []

for trial in range(N_TRIALS):
    sample = random.sample(eligible_coins, min(N_COINS, len(eligible_coins)))
    trial_pnl = sum(coin_pnl_map.get(c, 0) for c in sample)
    random_pnls.append(trial_pnl)
    if (trial + 1) % 100 == 0:
        print(f"    ... {trial+1}/{N_TRIALS} trials done", flush=True)

# Halal set PnL for comparison
halal_pnl = sum(coin_pnl_map.get(c, 0) for c in HALAL_SET if c in coin_pnl_map)
halal_in_data = [c for c in HALAL_SET if c in coin_pnl_map]

random_pnls_sorted = sorted(random_pnls)
halal_rank = sum(1 for p in random_pnls if p < halal_pnl)

print(f"\n  Eligible coins: {len(eligible_coins)}")
print(f"  Halal coins in data: {len(halal_in_data)}/{len(HALAL_SET)}")
print(f"\n  Halal set PnL:    ${halal_pnl:+,.0f}")
print(f"  Random mean PnL:  ${statistics.mean(random_pnls):+,.0f}")
print(f"  Random median PnL: ${random_pnls_sorted[len(random_pnls_sorted)//2]:+,.0f}")
print(f"  Random P5 PnL:    ${random_pnls_sorted[int(len(random_pnls_sorted)*0.05)]:+,.0f}")
print(f"  Random P95 PnL:   ${random_pnls_sorted[int(len(random_pnls_sorted)*0.95)]:+,.0f}")
print(f"\n  Halal set rank:   {halal_rank}/{N_TRIALS} ({100*halal_rank/N_TRIALS:.1f}th percentile)")
print(f"  Halal beats random: {100*halal_rank/N_TRIALS:.1f}% of random portfolios")
print(f"  Time: {time.time()-t4:.1f}s\n", flush=True)


# ════════════════════════════════════════════════════════════════
# VERDICT
# ════════════════════════════════════════════════════════════════
print("=" * 70)
print("STRATEGY INTEGRITY VERDICT")
print("=" * 70)

verdicts = []

# Test 1 verdict
if blind_res.pf > 1.0:
    verdicts.append(("TEST 1 — Blind Portfolio", "PASS", f"PF={blind_res.pf:.2f} > 1.0"))
else:
    verdicts.append(("TEST 1 — Blind Portfolio", "FAIL", f"PF={blind_res.pf:.2f} < 1.0 — no aggregate edge"))

# Test 2 verdict
pct_profitable = 100 * len(profitable) / max(len(active), 1)
if pct_profitable > 50:
    verdicts.append(("TEST 2 — Per-Coin Distribution", "PASS", f"{pct_profitable:.0f}% profitable (majority)"))
elif pct_profitable > 30:
    verdicts.append(("TEST 2 — Per-Coin Distribution", "MARGINAL", f"{pct_profitable:.0f}% profitable (minority but sizeable)"))
else:
    verdicts.append(("TEST 2 — Per-Coin Distribution", "FAIL", f"{pct_profitable:.0f}% profitable (too few)"))

# Test 3 verdict
if is_winners:
    oos_rate = 100 * len(oos_still_profitable) / len(is_winners)
    if oos_rate > 60:
        verdicts.append(("TEST 3 — Walk-Forward", "PASS", f"{oos_rate:.0f}% IS winners stay profitable OOS"))
    elif oos_rate > 40:
        verdicts.append(("TEST 3 — Walk-Forward", "MARGINAL", f"{oos_rate:.0f}% IS winners stay profitable OOS"))
    else:
        verdicts.append(("TEST 3 — Walk-Forward", "FAIL", f"{oos_rate:.0f}% IS winners profitable OOS (poor persistence)"))

# Test 4 verdict
halal_pctile = 100 * halal_rank / N_TRIALS
if halal_pctile > 80:
    verdicts.append(("TEST 4 — Random Benchmark", "PASS", f"Halal set at {halal_pctile:.0f}th percentile"))
elif halal_pctile > 60:
    verdicts.append(("TEST 4 — Random Benchmark", "MARGINAL", f"Halal set at {halal_pctile:.0f}th percentile"))
else:
    verdicts.append(("TEST 4 — Random Benchmark", "FAIL", f"Halal set at {halal_pctile:.0f}th percentile (not better than random)"))

passes = sum(1 for _, v, _ in verdicts if v == 'PASS')
marginals = sum(1 for _, v, _ in verdicts if v == 'MARGINAL')
fails = sum(1 for _, v, _ in verdicts if v == 'FAIL')

for name, verdict, detail in verdicts:
    icon = '✅' if verdict == 'PASS' else '⚠️' if verdict == 'MARGINAL' else '❌'
    print(f"  {icon} {name}: {verdict} — {detail}")

print(f"\n  Overall: {passes} PASS / {marginals} MARGINAL / {fails} FAIL")

if passes >= 3:
    print("\n  🟢 CONCLUSIE: ms_018 heeft een REËEL EDGE — coin selectie verbetert het, maar de basis werkt")
elif passes >= 2 and marginals >= 1:
    print("\n  🟡 CONCLUSIE: ms_018 heeft een ZWAK EDGE — werkt op subset, coin selectie is ESSENTIEEL")
elif passes >= 1:
    print("\n  🟠 CONCLUSIE: ms_018 is MARGINAAL — mogelijk survivorship bias, hoge risico")
else:
    print("\n  🔴 CONCLUSIE: ms_018 heeft GEEN BETROUWBAAR EDGE — survivorship bias bevestigd")

print(f"\n  Totale runtime: {time.time()-t0:.0f}s")
print(flush=True)

#!/usr/bin/env python3
"""
Diagnostic: Run Bybit validation on ONLY coins that also exist in MEXC universe.
Purpose: Distinguish "universe mismatch" from "exchange microstructure" as root cause.

Creates a filtered Bybit candle cache and tiering, then invokes the runner.
"""
import json
import sys
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent

# --- Load MEXC universe (T1+T2) ---
mexc_path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
with open(mexc_path) as f:
    mexc = json.load(f)

mexc_bases = set()
for tier_num in ('1', '2'):
    for coin in mexc.get('tier_breakdown', {}).get(tier_num, {}).get('coins', []):
        mexc_bases.add(coin.split('/')[0])
print(f"MEXC T1+T2 base currencies: {len(mexc_bases)}")

# --- Load Bybit universe ---
bybit_tier_path = ROOT / 'reports' / 'hf' / 'universe_tiering_bybit_001.json'
with open(bybit_tier_path) as f:
    bybit_tier = json.load(f)

# --- Load Bybit candle cache ---
bybit_candle_path = ROOT / 'data' / 'candle_cache_1h_bybit.json'
with open(bybit_candle_path) as f:
    bybit_candles = json.load(f)

# --- Compute intersection ---
intersection_bases = set()
for coin in bybit_candles.keys():
    base = coin.split('/')[0]
    if base in mexc_bases:
        intersection_bases.add(base)
print(f"Intersection base currencies: {len(intersection_bases)}")

# --- Filter Bybit candle cache ---
filtered_candles = {}
for coin, bars in bybit_candles.items():
    base = coin.split('/')[0]
    if base in intersection_bases:
        filtered_candles[coin] = bars
print(f"Filtered Bybit candle cache: {len(filtered_candles)} coins")

# --- Write filtered cache ---
filtered_cache_path = ROOT / 'data' / 'candle_cache_1h_bybit_intersection.json'
with open(filtered_cache_path, 'w') as f:
    json.dump(filtered_candles, f)
print(f"Wrote: {filtered_cache_path}")

# --- Filter Bybit tiering ---
filtered_tier = json.loads(json.dumps(bybit_tier))  # deep copy
for tier_num in ('1', '2'):
    coins = filtered_tier.get('tier_breakdown', {}).get(tier_num, {}).get('coins', [])
    filtered = [c for c in coins if c.split('/')[0] in intersection_bases]
    filtered_tier['tier_breakdown'][tier_num]['coins'] = filtered
    filtered_tier['tier_breakdown'][tier_num]['count'] = len(filtered)
    print(f"  T{tier_num}: {len(coins)} -> {len(filtered)} coins")

filtered_tier_path = ROOT / 'reports' / 'hf' / 'universe_tiering_bybit_intersection_001.json'
with open(filtered_tier_path, 'w') as f:
    json.dump(filtered_tier, f, indent=2)
print(f"Wrote: {filtered_tier_path}")

# --- Now run the validation ---
print("\n" + "=" * 70)
print("Running intersection diagnostic: Bybit with MEXC-overlap coins only")
print("=" * 70)

# Import and run directly to avoid subprocess complexity
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.run_multi_exchange_validation import (
    load_candle_cache_exchange, load_universe_tiering_exchange,
    build_tier_coins, load_excluded_coins, analyze_combination, build_md,
    get_half_spread_for_fill,
    CONFIGS, REGIMES_TO_TEST, SIZES, BARS_PER_WEEK, BARS_PER_DAY,
)
from strategies.hf.screening.harness import precompute_base_indicators
from strategies.hf.screening.indicators_extended import extend_indicators, get_feature_coverage
from strategies.hf.screening.market_context import precompute_market_context
from strategies.hf.screening.costs_mexc_v2 import register_regime, COST_REGIMES
from strategies.hf.screening.fill_model_v3 import full_fill_model_v3
from strategies.hf.screening.exchange_config import get_exchange, FeeSnapshot
import time, subprocess

exchange_cfg = get_exchange('bybit')
fee_snap = FeeSnapshot(
    exchange_id='bybit',
    maker_fee_bps=10.0,
    taker_fee_bps=10.0,
    region='EU',
    account_tier='regular',
    source='diagnostic intersection run',
)

# Load OB regimes
ob_report_path = ROOT / 'reports' / 'hf' / 'bybit_orderbook_costs_001.json'
with open(ob_report_path) as f:
    ob_report = json.load(f)
measured_regimes = ob_report.get('regimes', {})
for name, regime in measured_regimes.items():
    if name in REGIMES_TO_TEST:
        register_regime(name, regime)
        print(f"  Registered: {name} -> T1={regime['tier1']['total_per_side_bps']}bps T2={regime['tier2']['total_per_side_bps']}bps")

# Use filtered data
data = filtered_candles
available_coins = set(data.keys())

tier_coins_full = build_tier_coins(filtered_tier, available_coins)
tier_coins = tier_coins_full  # no exclusions

n_t1 = len(tier_coins['tier1'])
n_t2 = len(tier_coins['tier2'])
n_total = n_t1 + n_t2
print(f"[Universe] T1({n_t1}) + T2({n_t2}) = {n_total} coins (intersection only)")

# Precompute
print('[Indicators] Precomputing base indicators...')
tier_indicators = {}
for tier_name, coins in tier_coins.items():
    if coins:
        t_ind = time.time()
        tier_indicators[tier_name] = precompute_base_indicators(data, coins)
        print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

print('[Indicators] Extending with VWAP fields...')
for tier_name, coins in tier_coins.items():
    if coins and tier_name in tier_indicators:
        extend_indicators(data, coins, tier_indicators[tier_name])
        cov = get_feature_coverage(tier_indicators[tier_name], coins)
        print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% ({cov["vwap_available"]}/{cov["total_coins"]})')

# Market context
print('[Market Context] Precomputing...')
all_coins = list(set(tier_coins.get('tier1', []) + tier_coins.get('tier2', [])))
for btc in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
    if btc in available_coins and btc not in all_coins:
        all_coins.append(btc)
market_context = precompute_market_context(data, all_coins)

# Inject __coin__
for tier_name, ind_dict in tier_indicators.items():
    for coin in ind_dict:
        ind_dict[coin]['__coin__'] = coin

# Estimate bars
total_bars = 0
for tier_name, coins in tier_coins.items():
    indicators = tier_indicators.get(tier_name, {})
    for coin in coins:
        n = indicators.get(coin, {}).get('n', 0)
        if n > total_bars:
            total_bars = n
total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0
print(f'[Data] total_bars={total_bars}, total_weeks={total_weeks:.1f}')

t1_indicators = tier_indicators.get('tier1', {})
t2_indicators = tier_indicators.get('tier2', {})
t1_coins = tier_coins['tier1']
t2_coins = tier_coins['tier2']

# Run combinations
all_results = []
combo_idx = 0
t0 = time.time()

for config_name, config_params in CONFIGS.items():
    for regime_name in REGIMES_TO_TEST:
        for size in SIZES:
            combo_idx += 1
            print(f"\n--- Combo {combo_idx}/24: {config_name}/{regime_name}/${size} ---")
            regime = COST_REGIMES[regime_name]
            result = analyze_combination(
                config_name=config_name,
                config_params=config_params,
                regime_name=regime_name,
                regime=regime,
                size=size,
                data=data,
                t1_coins=t1_coins,
                t2_coins=t2_coins,
                t1_indicators=t1_indicators,
                t2_indicators=t2_indicators,
                market_ctx=market_context,
                total_bars=total_bars,
                distributions=ob_report.get('distributions', {}),
                skip_fill_model=False,
            )
            all_results.append(result)

            # Quick summary
            m = result.get('metrics', {})
            g = result.get('gates', {})
            n_pass = sum(1 for v in g.values() if v.get('pass', False))
            print(f"  Trades={m.get('total_trades', 0)} PF={m.get('profit_factor', 0):.3f} "
                  f"Exp/Wk=${m.get('exp_per_week', 0):.2f} Gates={n_pass}/7")

elapsed = time.time() - t0
print(f"\n{'='*70}")
print(f"INTERSECTION DIAGNOSTIC COMPLETE ({elapsed:.1f}s)")
print(f"{'='*70}")

# Summary
pass_count = 0
for r in all_results:
    g = r.get('gates', {})
    if all(v.get('pass', False) for v in g.values()):
        pass_count += 1

print(f"\nResults: {pass_count}/24 pass ALL STRICT gates")
print(f"Universe: {n_total} coins (intersection of MEXC {len(mexc_bases)} × Bybit {len(bybit_candles)})")

# Show best combo
best = max(all_results, key=lambda x: x.get('metrics', {}).get('profit_factor', 0))
bm = best.get('metrics', {})
bg = best.get('gates', {})
bn_pass = sum(1 for v in bg.values() if v.get('pass', False))
print(f"\nBest combo: {best['config']}/{best['regime']}/{best['size']}")
print(f"  Trades={bm.get('total_trades', 0)} PF={bm.get('profit_factor', 0):.3f} "
      f"Exp/Wk=${bm.get('exp_per_week', 0):.2f} DD={bm.get('max_dd_pct', 0):.1f}% "
      f"WF={bm.get('wf_folds_positive', 0)}/5 Gates={bn_pass}/7")

# Save results
try:
    commit = subprocess.check_output(
        ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
    ).decode().strip()
except Exception:
    commit = 'unknown'

report = {
    'diagnostic': 'intersection_mexc_bybit',
    'date': time.strftime('%Y-%m-%d %H:%M'),
    'commit': commit,
    'mexc_bases': len(mexc_bases),
    'bybit_total': len(bybit_candles),
    'intersection': n_total,
    'intersection_t1': n_t1,
    'intersection_t2': n_t2,
    'total_bars': total_bars,
    'total_weeks': total_weeks,
    'fee_snapshot': {
        'exchange_id': fee_snap.exchange_id,
        'maker_fee_bps': fee_snap.maker_fee_bps,
        'taker_fee_bps': fee_snap.taker_fee_bps,
    },
    'pass_count': pass_count,
    'total_combos': 24,
    'results': all_results,
}

out_path = ROOT / 'reports' / 'hf' / 'diagnostic_intersection_bybit_mexc.json'
with open(out_path, 'w') as f:
    json.dump(report, f, indent=2, default=str)
print(f"\nReport: {out_path}")

# Also print scoreboard
print(f"\n{'='*70}")
print("SCOREBOARD (Intersection)")
print(f"{'='*70}")
print(f"{'Config':<6} {'Regime':<25} {'Size':>5} {'Tr':>4} {'PF':>6} {'Exp/Wk':>8} {'DD%':>5} {'WF':>4} {'Gates':>5}")
for r in all_results:
    m = r.get('metrics', {})
    g = r.get('gates', {})
    n_pass = sum(1 for v in g.values() if v.get('pass', False))
    print(f"{r['config']:<6} {r['regime']:<25} ${r['size']:>4} "
          f"{m.get('total_trades', 0):>4} {m.get('profit_factor', 0):>6.3f} "
          f"${m.get('exp_per_week', 0):>7.2f} {m.get('max_dd_pct', 0):>5.1f} "
          f"{m.get('wf_folds_positive', 0):>2}/5 {n_pass:>3}/7")

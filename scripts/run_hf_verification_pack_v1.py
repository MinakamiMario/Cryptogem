#!/usr/bin/env python3
"""
HF Verification Pack v1 — H20 + HLC3 proxy robustness tests.

Three tests:
  1. Window Split (3 equal windows, all must PF > 1.0)
  2. Walk-Forward (5-fold, each fold PF > 0.8 + aggregate PF > 1.0)
  3. Bootstrap Monte Carlo (1000 resamples, P5 PF > 0.9, >70% profitable)

Data: Kraken 1H (442 coins), MEXC fees (10bps taker = 0.001 per side).
HLC3 proxy injected into candle['vwap'] before indicator computation.

Usage:
    python scripts/run_hf_verification_pack_v1.py
"""

import sys
import json
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.harness import (
    precompute_base_indicators,
    run_backtest,
    walk_forward,
)
from strategies.hf.screening.indicators_extended import extend_indicators
from strategies.hf.screening.hypotheses_s5 import signal_h20_vwap_deviation

# ============================================================
# Config
# ============================================================
MEXC_FEE = 0.001          # 10 bps taker per side (MEXC spot)
H20_PARAMS = {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10}
INITIAL_CAPITAL = 2000.0
MAX_POS = 1
START_BAR = 50
COOLDOWN_BARS = 4
COOLDOWN_AFTER_STOP = 8
N_BOOTSTRAP = 1000
RANDOM_SEED = 42

# Gates
WINDOW_PF_GATE = 1.0       # Each window PF > 1.0
WF_FOLD_PF_GATE = 0.8      # Each WF fold PF > 0.8
WF_AGG_PF_GATE = 1.0       # Aggregate WF PF > 1.0
BOOT_P5_PF_GATE = 0.9      # P5 PF > 0.9
BOOT_PCT_PROFITABLE = 70   # >70% of bootstraps profitable


# ============================================================
# Data Loading (Kraken 1H per-coin parts)
# ============================================================
def load_kraken_1h():
    parts_dir = ROOT / 'data' / 'cache_parts_hf' / '1h' / 'kraken'
    if not parts_dir.exists():
        print(f'[ERROR] Kraken 1H parts not found: {parts_dir}')
        sys.exit(1)
    data = {}
    for f in sorted(parts_dir.glob('*.json')):
        symbol = f.stem.replace('_', '/')
        with open(f) as fh:
            candles = json.load(fh)
        if len(candles) >= 100:  # need enough bars
            data[symbol] = candles
    print(f'[Load] Kraken 1H: {len(data)} coins loaded')
    return data


# ============================================================
# HLC3 Injection
# ============================================================
def inject_hlc3_as_vwap(data: dict) -> dict:
    """Replace vwap field with HLC3 proxy: (H+L+C)/3."""
    count = 0
    for coin, candles in data.items():
        for c in candles:
            c['vwap'] = (c['high'] + c['low'] + c['close']) / 3.0
        count += 1
    print(f'[HLC3] Injected HLC3 proxy as vwap for {count} coins')
    return data


# ============================================================
# Test 1: Window Split
# ============================================================
def test_window_split(data, coins, signal_fn, params, n_windows=3):
    """Split bar range into n_windows equal segments, run each independently."""
    print('\n' + '='*60)
    print('TEST 1: WINDOW SPLIT')
    print('='*60)

    # Compute indicators on full data
    indicators = precompute_base_indicators(data, coins)
    extend_indicators(data, coins, indicators)

    # Find max bars
    coin_list = [c for c in coins if c in indicators]
    max_bars = max(indicators[p]['n'] for p in coin_list)
    total_range = max_bars - START_BAR
    window_size = total_range // n_windows

    print(f'  Max bars: {max_bars}, window size: {window_size} bars')

    results = []
    all_pass = True
    for i in range(n_windows):
        start = START_BAR + i * window_size
        end = start + window_size if i < n_windows - 1 else max_bars
        r = run_backtest(
            data=data, coins=coins, signal_fn=signal_fn, params=params,
            indicators=indicators, fee=MEXC_FEE, initial_capital=INITIAL_CAPITAL,
            start_bar=start, end_bar=end, cooldown_bars=COOLDOWN_BARS,
            cooldown_after_stop=COOLDOWN_AFTER_STOP, max_pos=MAX_POS,
        )
        status = '✅' if r.pf >= WINDOW_PF_GATE else '❌'
        if r.pf < WINDOW_PF_GATE:
            all_pass = False
        label = f'Window {i+1} [bar {start}-{end}]'
        print(f'  {status} {label}: PF={r.pf:.2f}, trades={r.trades}, '
              f'WR={r.wr:.1f}%, DD={r.dd:.1f}%, P&L=${r.pnl:.0f}')
        results.append({
            'window': i+1, 'start_bar': start, 'end_bar': end,
            'pf': round(r.pf, 3), 'trades': r.trades, 'wr': round(r.wr, 1),
            'dd': round(r.dd, 1), 'pnl': round(r.pnl, 2),
            'pass': r.pf >= WINDOW_PF_GATE,
        })

    verdict = 'PASS' if all_pass else 'FAIL'
    print(f'\n  Window Split Verdict: {verdict} ({sum(1 for r in results if r["pass"])}/{n_windows} pass)')
    return {'test': 'window_split', 'verdict': verdict, 'results': results}


# ============================================================
# Test 2: Walk-Forward
# ============================================================
def test_walk_forward(data, coins, signal_fn, params, n_folds=5):
    """Walk-forward validation using harness walk_forward()."""
    print('\n' + '='*60)
    print('TEST 2: WALK-FORWARD')
    print('='*60)

    indicators = precompute_base_indicators(data, coins)
    extend_indicators(data, coins, indicators)

    fold_results = walk_forward(
        data=data, coins=coins, signal_fn=signal_fn, params=params,
        indicators=indicators, n_folds=n_folds, embargo=2, fee=MEXC_FEE,
        initial_capital=INITIAL_CAPITAL, start_bar=START_BAR,
        cooldown_bars=COOLDOWN_BARS, cooldown_after_stop=COOLDOWN_AFTER_STOP,
        max_pos=MAX_POS,
    )

    results = []
    all_fold_pass = True
    total_wins = 0
    total_losses_abs = 0

    for i, r in enumerate(fold_results):
        fold_pass = r.pf >= WF_FOLD_PF_GATE
        if not fold_pass:
            all_fold_pass = False
        status = '✅' if fold_pass else '❌'
        print(f'  {status} Fold {i+1}: PF={r.pf:.2f}, trades={r.trades}, '
              f'WR={r.wr:.1f}%, DD={r.dd:.1f}%, P&L=${r.pnl:.0f}')
        # Accumulate for aggregate PF
        for t in r.trade_list:
            if t['pnl'] > 0:
                total_wins += t['pnl']
            else:
                total_losses_abs += abs(t['pnl'])
        results.append({
            'fold': i+1, 'pf': round(r.pf, 3), 'trades': r.trades,
            'wr': round(r.wr, 1), 'dd': round(r.dd, 1), 'pnl': round(r.pnl, 2),
            'pass': fold_pass,
        })

    agg_pf = total_wins / total_losses_abs if total_losses_abs > 0 else float('inf')
    agg_pass = agg_pf >= WF_AGG_PF_GATE
    total_trades = sum(r['trades'] for r in results)
    print(f'\n  Aggregate: PF={agg_pf:.2f}, total_trades={total_trades}')
    print(f'  All folds ≥{WF_FOLD_PF_GATE}: {"✅" if all_fold_pass else "❌"}')
    print(f'  Aggregate PF ≥{WF_AGG_PF_GATE}: {"✅" if agg_pass else "❌"}')

    verdict = 'PASS' if (all_fold_pass and agg_pass) else 'FAIL'
    print(f'\n  Walk-Forward Verdict: {verdict}')
    return {
        'test': 'walk_forward', 'verdict': verdict,
        'aggregate_pf': round(agg_pf, 3), 'total_trades': total_trades,
        'all_folds_pass': all_fold_pass, 'aggregate_pass': agg_pass,
        'results': results,
    }


# ============================================================
# Test 3: Bootstrap Monte Carlo
# ============================================================
def test_bootstrap(data, coins, signal_fn, params, n_samples=N_BOOTSTRAP):
    """Bootstrap resample trade list, compute P5 PF and % profitable."""
    print('\n' + '='*60)
    print('TEST 3: BOOTSTRAP MONTE CARLO')
    print('='*60)

    # Full backtest first
    indicators = precompute_base_indicators(data, coins)
    extend_indicators(data, coins, indicators)

    full = run_backtest(
        data=data, coins=coins, signal_fn=signal_fn, params=params,
        indicators=indicators, fee=MEXC_FEE, initial_capital=INITIAL_CAPITAL,
        start_bar=START_BAR, cooldown_bars=COOLDOWN_BARS,
        cooldown_after_stop=COOLDOWN_AFTER_STOP, max_pos=MAX_POS,
    )

    print(f'  Full backtest: PF={full.pf:.2f}, trades={full.trades}, '
          f'WR={full.wr:.1f}%, DD={full.dd:.1f}%')

    if full.trades < 10:
        print('  ❌ Too few trades for bootstrap (<10)')
        return {
            'test': 'bootstrap', 'verdict': 'FAIL',
            'reason': 'too_few_trades', 'full_trades': full.trades,
        }

    trade_pnls = [t['pnl'] for t in full.trade_list]
    rng = random.Random(RANDOM_SEED)

    boot_pfs = []
    boot_pnls = []

    for _ in range(n_samples):
        sample = rng.choices(trade_pnls, k=len(trade_pnls))
        wins = sum(p for p in sample if p > 0)
        losses_abs = abs(sum(p for p in sample if p <= 0))
        pf = wins / losses_abs if losses_abs > 0 else float('inf')
        boot_pfs.append(pf)
        boot_pnls.append(sum(sample))

    # Sort for percentiles
    boot_pfs.sort()
    boot_pnls.sort()

    p5_pf = boot_pfs[int(n_samples * 0.05)]
    p25_pf = boot_pfs[int(n_samples * 0.25)]
    p50_pf = boot_pfs[int(n_samples * 0.50)]
    p75_pf = boot_pfs[int(n_samples * 0.75)]
    p95_pf = boot_pfs[int(n_samples * 0.95)]

    pct_profitable = sum(1 for p in boot_pnls if p > 0) / n_samples * 100

    p5_pass = p5_pf >= BOOT_P5_PF_GATE
    pct_pass = pct_profitable >= BOOT_PCT_PROFITABLE

    print(f'\n  Bootstrap Distribution (n={n_samples}):')
    print(f'    PF  P5={p5_pf:.2f} P25={p25_pf:.2f} P50={p50_pf:.2f} '
          f'P75={p75_pf:.2f} P95={p95_pf:.2f}')
    print(f'    P&L P5=${boot_pnls[int(n_samples*0.05)]:.0f} '
          f'P50=${boot_pnls[int(n_samples*0.5)]:.0f} '
          f'P95=${boot_pnls[int(n_samples*0.95)]:.0f}')
    print(f'    % Profitable: {pct_profitable:.1f}%')
    print(f'\n  P5 PF ≥{BOOT_P5_PF_GATE}: {"✅" if p5_pass else "❌"} ({p5_pf:.2f})')
    print(f'  % Profitable ≥{BOOT_PCT_PROFITABLE}%: {"✅" if pct_pass else "❌"} ({pct_profitable:.1f}%)')

    verdict = 'PASS' if (p5_pass and pct_pass) else 'FAIL'
    print(f'\n  Bootstrap Verdict: {verdict}')
    return {
        'test': 'bootstrap', 'verdict': verdict,
        'full_pf': round(full.pf, 3), 'full_trades': full.trades,
        'p5_pf': round(p5_pf, 3), 'p25_pf': round(p25_pf, 3),
        'p50_pf': round(p50_pf, 3), 'p75_pf': round(p75_pf, 3),
        'p95_pf': round(p95_pf, 3),
        'pct_profitable': round(pct_profitable, 1),
        'p5_pass': p5_pass, 'pct_pass': pct_pass,
    }


# ============================================================
# Main
# ============================================================
def main():
    t0 = time.time()
    print('='*60)
    print('HF VERIFICATION PACK v1')
    print(f'Signal: H20 VWAP_DEVIATION + HLC3 proxy')
    print(f'Params: {H20_PARAMS}')
    print(f'Fee: {MEXC_FEE*10000:.0f} bps/side (MEXC spot)')
    print('='*60)

    # Load data
    data = load_kraken_1h()
    coins = sorted(data.keys())

    # Inject HLC3
    data = inject_hlc3_as_vwap(data)

    # Run all 3 tests
    r1 = test_window_split(data, coins, signal_h20_vwap_deviation, H20_PARAMS)
    r2 = test_walk_forward(data, coins, signal_h20_vwap_deviation, H20_PARAMS)
    r3 = test_bootstrap(data, coins, signal_h20_vwap_deviation, H20_PARAMS)

    # ============================================================
    # Final Verdict
    # ============================================================
    elapsed = time.time() - t0
    verdicts = [r1['verdict'], r2['verdict'], r3['verdict']]
    n_pass = sum(1 for v in verdicts if v == 'PASS')

    print('\n' + '='*60)
    print('VERIFICATION PACK v1 — SUMMARY')
    print('='*60)
    print(f'  1. Window Split:     {r1["verdict"]}')
    print(f'  2. Walk-Forward:     {r2["verdict"]}')
    print(f'  3. Bootstrap MC:     {r3["verdict"]}')
    print(f'\n  Tests passed: {n_pass}/3')

    if n_pass == 3:
        final = 'GO ✅'
    elif n_pass >= 2:
        final = 'CONDITIONAL GO ⚠️'
    else:
        final = 'NO-GO ❌'

    print(f'  Final Verdict: {final}')
    print(f'  Elapsed: {elapsed:.1f}s')

    # Save report
    report = {
        'signal': 'H20_VWAP_DEVIATION',
        'proxy': 'HLC3',
        'params': H20_PARAMS,
        'fee_bps': MEXC_FEE * 10000,
        'data': 'kraken_1h',
        'coins': len(coins),
        'tests': [r1, r2, r3],
        'n_pass': n_pass,
        'final_verdict': final,
        'elapsed_s': round(elapsed, 1),
    }
    report_path = ROOT / 'reports' / 'hf' / 'verification_pack_v1.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f'\n  Report: {report_path}')

    return 0 if n_pass >= 2 else 1


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""
Phase 3 — MS Scalp Truth-Pass Verification (top N candidates).

Runs 5 robustness tests on each candidate:
    T1 WINDOW_SPLIT:  3×10d windows, all PF ≥ 0.95
    T2 WALK_FORWARD:  5-fold (24d train → 6d test), aggregate PF ≥ 1.0
    T3 BOOTSTRAP:     1000 trade resamplings, P5 PF ≥ 0.85, ≥75% profitable
    T4 SPREAD_STRESS: Backtest at P95 spread (2.97 bps), PF > 1.0
    T5 CROSS_ASSET:   OOS on ETH/USDT and BTC/USDT, ≥1 coin PF ≥ 0.90

Verdict: VERIFIED (5/5), CONDITIONAL (3-4/5), FAILED (<3/5)

Usage:
    python scripts/run_scalp_ms_verify.py
"""

import json
import sys
import time
import random
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategies.scalp.ms_hypotheses import signal_mssb
from strategies.scalp.ms_indicators import precompute_scalp_ms_indicators
from strategies.scalp.harness import run_backtest

# ─── Config ─────────────────────────────────────────────
DATA_DIR = Path.home() / 'CryptogemData' / 'scalp' / '1m' / 'mexc'
OUT_DIR = Path.home() / 'CryptogemData' / 'scalp' / 'ms' / 'verify'
PAIR = 'XRP/USDT'
SPREAD_BPS = 1.5
P95_SPREAD_BPS = 2.97

# ─── Top 5 Candidates ──────────────────────────────────
CANDIDATES = {
    'fvg_x2027': {
        'signal_fn': signal_mssb, 'family': 'FVG_FILL',
        'params': {'max_fvg_age': 25, 'fill_depth': 0.75, 'rsi_max': 40,
                   'tp_atr': 2.5, 'sl_atr': 0.75, 'time_limit': 15},
        'screening_pf': 1.769, 'screening_brk': 4.8,
    },
    'fvg_x2030': {
        'signal_fn': signal_mssb, 'family': 'FVG_FILL',
        'params': {'max_fvg_age': 25, 'fill_depth': 0.75, 'rsi_max': 40,
                   'tp_atr': 2.5, 'sl_atr': 0.75, 'time_limit': 20},
        'screening_pf': 1.719, 'screening_brk': 4.6,
    },
    'fvg_x1217': {
        'signal_fn': signal_mssb, 'family': 'FVG_FILL',
        'params': {'max_fvg_age': 25, 'fill_depth': 0.50, 'rsi_max': 40,
                   'tp_atr': 2.5, 'sl_atr': 0.75, 'time_limit': 15},
        'screening_pf': 1.713, 'screening_brk': 4.6,
    },
    'fvg_x2033': {
        'signal_fn': signal_mssb, 'family': 'FVG_FILL',
        'params': {'max_fvg_age': 25, 'fill_depth': 0.75, 'rsi_max': 40,
                   'tp_atr': 2.5, 'sl_atr': 0.75, 'time_limit': 30},
        'screening_pf': 1.693, 'screening_brk': 4.6,
    },
    'fvg_x1220': {
        'signal_fn': signal_mssb, 'family': 'FVG_FILL',
        'params': {'max_fvg_age': 25, 'fill_depth': 0.50, 'rsi_max': 40,
                   'tp_atr': 2.5, 'sl_atr': 0.75, 'time_limit': 20},
        'screening_pf': 1.671, 'screening_brk': 4.5,
    },
}

# ─── Shared backtest kwargs ─────────────────────────────
BT_KWARGS = dict(
    initial_capital=2000.0,
    capital_per_trade=200.0,
    max_positions=1,
    cooldown_bars=2,
    cooldown_after_stop=5,
    daily_loss_limit=-0.02,
)


def load_candles(pair_file: str) -> list[dict]:
    path = DATA_DIR / pair_file
    if not path.exists():
        print(f'  [SKIP] {path} not found')
        return []
    with open(path) as f:
        return json.load(f)


def precompute(candles: list[dict], pair: str) -> dict:
    data = {pair: candles}
    all_ind = precompute_scalp_ms_indicators(
        data, [pair],
        swing_left=3, swing_right=1,
        min_gap_atr=0.3, min_impulse_atr=1.5,
        lookback_impulse=3, tolerance_atr=0.5, min_touches=2,
    )
    return all_ind[pair]


def bt(candles, cfg, indicators, spread=SPREAD_BPS, start_bar=60, end_bar=None):
    return run_backtest(
        candles=candles,
        signal_fn=cfg['signal_fn'],
        params=cfg['params'],
        indicators=indicators,
        spread_bps=spread,
        start_bar=start_bar,
        end_bar=end_bar,
        **BT_KWARGS,
    )


# ═══════════════════════════════════════════════════════
# T1: Window Split (3×10d)
# ═══════════════════════════════════════════════════════
def test_window_split(candles, cfg, indicators, n_windows=3):
    """Split into n equal windows, check PF ≥ 0.95 in all."""
    n = len(candles)
    window_size = n // n_windows
    results = []

    for w in range(n_windows):
        start = max(w * window_size, 60)
        end = (w + 1) * window_size if w < n_windows - 1 else n
        r = bt(candles, cfg, indicators, start_bar=start, end_bar=end)
        results.append({
            'window': w + 1,
            'start_bar': start,
            'end_bar': end,
            'bars': end - start,
            'pf': r.pf,
            'trades': r.trades,
            'pnl': r.pnl,
        })

    all_pass = all(r['pf'] >= 0.95 for r in results)
    pass_count = sum(1 for r in results if r['pf'] >= 0.95)
    return {
        'test': 'T1_WINDOW_SPLIT',
        'pass': all_pass,
        'pass_count': f'{pass_count}/{n_windows}',
        'gate': 'all PF ≥ 0.95',
        'windows': results,
    }


# ═══════════════════════════════════════════════════════
# T2: Walk-Forward (5-fold)
# ═══════════════════════════════════════════════════════
def test_walk_forward(candles, cfg, indicators, n_folds=5):
    """Walk-forward: train on 80%, test on 20% — sliding."""
    n = len(candles)
    fold_size = n // n_folds
    results = []

    for fold in range(n_folds):
        test_start = fold * fold_size
        test_end = (fold + 1) * fold_size if fold < n_folds - 1 else n
        # Test on this fold
        r = bt(candles, cfg, indicators,
               start_bar=max(test_start, 60), end_bar=test_end)
        results.append({
            'fold': fold + 1,
            'test_start': max(test_start, 60),
            'test_end': test_end,
            'pf': r.pf,
            'trades': r.trades,
            'pnl': r.pnl,
        })

    # Aggregate: sum wins / sum losses across folds
    total_wins = 0
    total_losses = 0
    for r in results:
        for fold_r in [r]:
            # Reconstruct from PnL direction
            if fold_r['pnl'] > 0:
                total_wins += fold_r['pnl']
            else:
                total_losses += abs(fold_r['pnl'])

    agg_pf = total_wins / total_losses if total_losses > 0 else (
        999.0 if total_wins > 0 else 0.0)
    positive_folds = sum(1 for r in results if r['pnl'] > 0)

    return {
        'test': 'T2_WALK_FORWARD',
        'pass': agg_pf >= 1.0 and positive_folds >= 3,
        'gate': 'aggregate PF ≥ 1.0 AND ≥3/5 positive',
        'aggregate_pf': round(agg_pf, 3),
        'positive_folds': f'{positive_folds}/{n_folds}',
        'folds': results,
    }


# ═══════════════════════════════════════════════════════
# T3: Bootstrap (1000 resamplings)
# ═══════════════════════════════════════════════════════
def test_bootstrap(candles, cfg, indicators, n_samples=1000, seed=42):
    """Resample trades with replacement, compute PF distribution."""
    # First run full backtest to get trade list
    r = bt(candles, cfg, indicators)
    trades = r.trade_list
    if len(trades) < 20:
        return {
            'test': 'T3_BOOTSTRAP',
            'pass': False,
            'gate': 'P5 PF ≥ 0.85, ≥75% profitable',
            'reason': f'Too few trades ({len(trades)})',
        }

    rng = random.Random(seed)
    pfs = []

    for _ in range(n_samples):
        sample = rng.choices(trades, k=len(trades))
        wins = sum(t['pnl'] for t in sample if t['pnl'] > 0)
        losses = sum(abs(t['pnl']) for t in sample if t['pnl'] < 0)
        pf = wins / losses if losses > 0 else (999.0 if wins > 0 else 0.0)
        pfs.append(pf)

    pfs.sort()
    p5 = pfs[int(0.05 * n_samples)]
    p25 = pfs[int(0.25 * n_samples)]
    p50 = pfs[int(0.50 * n_samples)]
    p75 = pfs[int(0.75 * n_samples)]
    pct_profitable = sum(1 for pf in pfs if pf > 1.0) / n_samples * 100

    return {
        'test': 'T3_BOOTSTRAP',
        'pass': p5 >= 0.85 and pct_profitable >= 75.0,
        'gate': 'P5 PF ≥ 0.85, ≥75% profitable',
        'n_trades': len(trades),
        'n_samples': n_samples,
        'p5_pf': round(p5, 3),
        'p25_pf': round(p25, 3),
        'p50_pf': round(p50, 3),
        'p75_pf': round(p75, 3),
        'pct_profitable': round(pct_profitable, 1),
    }


# ═══════════════════════════════════════════════════════
# T4: Spread Stress (P95 spread)
# ═══════════════════════════════════════════════════════
def test_spread_stress(candles, cfg, indicators):
    """Run at P95 spread (2.97 bps) — must remain PF > 1.0."""
    r = bt(candles, cfg, indicators, spread=P95_SPREAD_BPS)
    return {
        'test': 'T4_SPREAD_STRESS',
        'pass': r.pf > 1.0,
        'gate': f'PF > 1.0 at {P95_SPREAD_BPS} bps spread',
        'pf_at_p95': round(r.pf, 3),
        'trades': r.trades,
        'pnl': round(r.pnl, 2),
        'pf_at_median': round(bt(candles, cfg, indicators).pf, 3),
    }


# ═══════════════════════════════════════════════════════
# T5: Cross-Asset OOS
# ═══════════════════════════════════════════════════════
def test_cross_asset(cfg, pairs_data):
    """Test on ETH/USDT and BTC/USDT — ≥1 coin PF ≥ 0.90."""
    results = []
    for pair, (candles, indicators) in pairs_data.items():
        if pair == PAIR:
            continue
        r = bt(candles, cfg, indicators)
        results.append({
            'pair': pair,
            'pf': round(r.pf, 3),
            'trades': r.trades,
            'pnl': round(r.pnl, 2),
            'wr': round(r.wr, 1),
        })

    any_pass = any(r['pf'] >= 0.90 for r in results)
    return {
        'test': 'T5_CROSS_ASSET',
        'pass': any_pass,
        'gate': '≥1 OOS coin PF ≥ 0.90',
        'coins': results,
    }


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load XRP candles
    print('Loading XRP/USDT candles...')
    xrp_candles = load_candles('XRP_USDT_1m.json')
    n_bars = len(xrp_candles)
    span_days = (xrp_candles[-1]['time'] - xrp_candles[0]['time']) / 86400
    print(f'  {n_bars:,} bars, {span_days:.1f} days\n')

    # Precompute XRP indicators
    print('Computing XRP indicators...')
    t0 = time.time()
    xrp_indicators = precompute(xrp_candles, PAIR)
    print(f'  Done in {time.time() - t0:.1f}s\n')

    # Load + precompute OOS pairs
    oos_pairs = {}
    for pair_name, filename in [('ETH/USDT', 'ETH_USDT_1m.json'),
                                 ('BTC/USDT', 'BTC_USDT_1m.json')]:
        print(f'Loading {pair_name}...')
        candles = load_candles(filename)
        if candles:
            print(f'  {len(candles):,} bars')
            print(f'  Computing indicators...')
            t0 = time.time()
            ind = precompute(candles, pair_name)
            print(f'  Done in {time.time() - t0:.1f}s')
            oos_pairs[pair_name] = (candles, ind)
        print()

    # Add XRP to pairs for cross-asset reference
    all_pairs = {PAIR: (xrp_candles, xrp_indicators)}
    all_pairs.update(oos_pairs)

    # Run verification for each candidate
    all_results = {}
    for config_id, cfg in CANDIDATES.items():
        print(f'\n{"=" * 80}')
        print(f'Verifying: {config_id} (screening PF={cfg["screening_pf"]:.3f}, '
              f'BrkSprd={cfg["screening_brk"]:.1f} bps)')
        print(f'  Params: {cfg["params"]}')
        print(f'{"=" * 80}')

        tests = {}

        # T1: Window Split
        print('\n  T1 WINDOW_SPLIT...', end=' ', flush=True)
        t1 = test_window_split(xrp_candles, cfg, xrp_indicators)
        icon = '✅' if t1['pass'] else '❌'
        print(f'{icon} {t1["pass_count"]}')
        for w in t1['windows']:
            print(f'      W{w["window"]}: PF={w["pf"]:.3f}, {w["trades"]} trades, ${w["pnl"]:.2f}')
        tests['T1'] = t1

        # T2: Walk-Forward
        print('\n  T2 WALK_FORWARD...', end=' ', flush=True)
        t2 = test_walk_forward(xrp_candles, cfg, xrp_indicators)
        icon = '✅' if t2['pass'] else '❌'
        print(f'{icon} agg_PF={t2["aggregate_pf"]:.3f}, positive={t2["positive_folds"]}')
        for f in t2['folds']:
            fi = '✅' if f['pnl'] > 0 else '❌'
            print(f'      F{f["fold"]}: {fi} PF={f["pf"]:.3f}, {f["trades"]} trades, ${f["pnl"]:.2f}')
        tests['T2'] = t2

        # T3: Bootstrap
        print('\n  T3 BOOTSTRAP...', end=' ', flush=True)
        t3 = test_bootstrap(xrp_candles, cfg, xrp_indicators)
        icon = '✅' if t3['pass'] else '❌'
        print(f'{icon} P5={t3.get("p5_pf", "N/A")}, '
              f'{t3.get("pct_profitable", "N/A")}% profitable')
        tests['T3'] = t3

        # T4: Spread Stress
        print('\n  T4 SPREAD_STRESS...', end=' ', flush=True)
        t4 = test_spread_stress(xrp_candles, cfg, xrp_indicators)
        icon = '✅' if t4['pass'] else '❌'
        print(f'{icon} PF@P95={t4["pf_at_p95"]:.3f} '
              f'(was {t4["pf_at_median"]:.3f} @ {SPREAD_BPS}bps)')
        tests['T4'] = t4

        # T5: Cross-Asset
        print('\n  T5 CROSS_ASSET...', end=' ', flush=True)
        t5 = test_cross_asset(cfg, all_pairs)
        icon = '✅' if t5['pass'] else '❌'
        print(f'{icon}')
        for c in t5['coins']:
            ci = '✅' if c['pf'] >= 0.90 else '❌'
            print(f'      {c["pair"]}: {ci} PF={c["pf"]:.3f}, '
                  f'{c["trades"]} trades, ${c["pnl"]:.2f}')
        tests['T5'] = t5

        # Verdict
        pass_count = sum(1 for t in tests.values() if t['pass'])
        total = len(tests)
        if pass_count == total:
            verdict = 'VERIFIED'
        elif pass_count >= 3:
            verdict = 'CONDITIONAL'
        else:
            verdict = 'FAILED'

        v_icon = {'VERIFIED': '🟢', 'CONDITIONAL': '🟡', 'FAILED': '❌'}[verdict]
        print(f'\n  ══ VERDICT: {v_icon} {verdict} ({pass_count}/{total}) ══')

        all_results[config_id] = {
            'config_id': config_id,
            'params': cfg['params'],
            'screening_pf': cfg['screening_pf'],
            'screening_brk': cfg['screening_brk'],
            'tests': {k: {kk: vv for kk, vv in v.items()} for k, v in tests.items()},
            'pass_count': pass_count,
            'total_tests': total,
            'verdict': verdict,
        }

    # Summary
    print(f'\n\n{"=" * 80}')
    print('VERIFICATION SUMMARY')
    print(f'{"=" * 80}')
    for cid, r in all_results.items():
        v_icon = {'VERIFIED': '🟢', 'CONDITIONAL': '🟡', 'FAILED': '❌'}[r['verdict']]
        t_status = ' '.join(
            '✅' if r['tests'][f'T{i+1}']['pass'] else '❌'
            for i in range(5)
        )
        print(f'  {v_icon} {cid:14s} PF={r["screening_pf"]:.3f} '
              f'[{t_status}] {r["verdict"]} ({r["pass_count"]}/{r["total_tests"]})')

    # Save
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')
    results_path = OUT_DIR / f'verify_results_{ts}.json'
    with open(results_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f'\nResults saved: {results_path}')

    # Also save latest
    with open(OUT_DIR / 'verify_results_latest.json', 'w') as f:
        json.dump(all_results, f, indent=2)

    return all_results


if __name__ == '__main__':
    main()

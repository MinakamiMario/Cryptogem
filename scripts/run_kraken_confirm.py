#!/usr/bin/env python3
"""
Kraken Confirm Runner — A/B comparison of native vs proxy data.

Runs the same configs on both native Kraken and CryptoCompare proxy data,
enabling direct delta measurement. Supports baseline, slope-as-sizing,
and hard regime gate modes.

Usage:
    python scripts/run_kraken_confirm.py \
        --plan strategies/4h/sweep_plan_kraken_confirm.json \
        --native ~/CryptogemData/derived/candle_cache/kraken/4h/candle_cache_4h_kraken_native_confirm.json \
        --proxy ~/CryptogemData/derived/candle_cache/kraken/4h/candle_cache_4h_kraken_v2.json
"""
from __future__ import annotations

import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / 'trading_bot') not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / 'trading_bot'))

import agent_team_v3 as engine
from agent_team_v3 import (
    run_backtest, precompute_all, normalize_cfg,
    INITIAL_CAPITAL, KRAKEN_FEE, START_BAR,
)

import importlib
_gates_mod = importlib.import_module('strategies.4h.gates_4h')
evaluate_gates = _gates_mod.evaluate_gates
gates_to_dict = _gates_mod.gates_to_dict

# Import slope-sizing from extended runner
sys.path.insert(0, str(REPO_ROOT / 'scripts'))
from run_4h_sweep_extended import (
    add_sma_slope_to_indicators, run_backtest_slope_sizing,
)
from run_4h_sweep_regime import (
    _make_regime_entry_filter,
)


def _git_hash() -> str:
    try:
        r = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                           capture_output=True, text=True, timeout=5, cwd=str(REPO_ROOT))
        return r.stdout.strip() if r.returncode == 0 else 'unknown'
    except Exception:
        return 'unknown'


def _trim_proxy_to_native_window(proxy_data: dict, native_data: dict) -> dict:
    """Trim proxy data to match native data's time window (per coin).

    Returns a new dict with only bars that fall within the native time range.
    """
    trimmed = {}
    for pair in native_data:
        if pair.startswith('_'):
            continue
        if pair not in proxy_data:
            continue

        n_candles = native_data[pair]
        if not n_candles:
            continue

        n_times = {c['time'] for c in n_candles}
        n_min = min(n_times)
        n_max = max(n_times)

        # Keep proxy bars within native time range
        p_candles = [c for c in proxy_data[pair]
                     if n_min <= c['time'] <= n_max]
        if p_candles:
            trimmed[pair] = p_candles

    return trimmed


def run_confirm(args):
    plan_path = Path(args.plan)
    with open(plan_path) as f:
        plan = json.load(f)
    configs = plan.get('configs', plan)

    print(f"\n{'='*70}")
    print(f"  Kraken Confirm Runner — Native vs Proxy A/B")
    print(f"{'='*70}")
    print(f"  Plan: {plan_path} ({len(configs)} configs)")

    git_short = _git_hash()
    output_base = Path(args.output_dir)

    # Load native data
    native_path = Path(args.native)
    print(f"\n  Loading native Kraken data from {native_path.name}...")
    with open(native_path) as f:
        native_raw = json.load(f)
    native_coins = sorted([k for k in native_raw if not k.startswith('_')])
    print(f"  Native: {len(native_coins)} coins")

    # Load proxy data
    proxy_path = Path(args.proxy)
    print(f"  Loading proxy CryptoCompare data from {proxy_path.name}...")
    with open(proxy_path) as f:
        proxy_raw = json.load(f)

    # Trim proxy to native window
    print(f"  Trimming proxy data to native 120-day window...")
    proxy_trimmed = _trim_proxy_to_native_window(proxy_raw, native_raw)
    proxy_coins = sorted([k for k in proxy_trimmed if not k.startswith('_')])
    print(f"  Proxy (trimmed): {len(proxy_coins)} coins")
    del proxy_raw  # free memory

    # Precompute indicators for both datasets
    print(f"\n  Precomputing indicators (native)...")
    t0 = time.time()
    ind_native = precompute_all(native_raw, native_coins)
    del native_raw
    print(f"  Precomputing indicators (proxy)...")
    ind_proxy = precompute_all(proxy_trimmed, proxy_coins)
    del proxy_trimmed

    # Add SMA slope to both
    needs_slope = any(c.get('slope_sizing') or c.get('regime_filter') for c in configs)
    if needs_slope:
        print(f"  Adding SMA50 slope to both datasets...")
        add_sma_slope_to_indicators(ind_native, 50)
        add_sma_slope_to_indicators(ind_proxy, 50)

    pre_elapsed = time.time() - t0
    print(f"  Precompute: {pre_elapsed:.1f}s")

    # Run configs
    results = []
    print(f"\n{'='*70}")
    print(f"  Running {len(configs)} configs...")
    print(f"{'='*70}\n")

    for i, entry in enumerate(configs):
        idx = entry.get('idx', i + 1)
        label = entry.get('label', f'config_{idx}')
        cfg_raw = entry.get('params', entry.get('cfg', {}))
        slope_sizing = entry.get('slope_sizing')
        regime_filter = entry.get('regime_filter')
        use_proxy = entry.get('_use_proxy_data', False)

        source_tag = "PROXY" if use_proxy else "NATIVE"
        indicators = ind_proxy if use_proxy else ind_native
        coins = proxy_coins if use_proxy else native_coins

        run_id = f"confirm_{idx:03d}_{label}_{git_short}"
        print(f"  [{idx:02d}] {label} [{source_tag}]", end="")

        cfg = normalize_cfg(dict(cfg_raw))
        t_run = time.time()

        if regime_filter:
            # Hard gate: monkeypatch check_entry_at_bar
            slope_max = regime_filter.get('slope_max_pct', -8.0)
            original_fn = engine.check_entry_at_bar
            engine.check_entry_at_bar = _make_regime_entry_filter(original_fn, slope_max)
            try:
                bt = run_backtest(indicators, coins, cfg)
            finally:
                engine.check_entry_at_bar = original_fn
            print(f" [GATE: slope<{slope_max}%]", end="")
        elif slope_sizing:
            bt = run_backtest_slope_sizing(
                indicators, coins, cfg,
                steep_thresh=slope_sizing.get('steep_thresh', -10.0),
                mild_thresh=slope_sizing.get('mild_thresh', -3.0),
                min_scale=slope_sizing.get('min_scale', 0.3),
            )
            avg_s = bt.get('_slope_sizing', {}).get('avg_scale', '?')
            print(f" [SLOPE: avgS={avg_s}]", end="")
        else:
            bt = run_backtest(indicators, coins, cfg)

        bt_elapsed = time.time() - t_run

        gate_report = evaluate_gates(bt)
        gate_dict = gates_to_dict(gate_report)
        verdict = gate_dict['verdict']
        ev = bt['pnl'] / bt['trades'] if bt['trades'] > 0 else 0

        print(f"\n        {bt['trades']:3d}tr | WR {bt['wr']:5.1f}% | "
              f"P&L ${bt['pnl']:+8,.2f} | PF {bt['pf']:5.2f} | "
              f"DD {bt['dd']:5.1f}% | EV ${ev:+6.1f} | {verdict}")

        # Save results
        run_dir = output_base / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        slope_info = bt.get('_slope_sizing') if slope_sizing else None
        payload = {
            'metadata': {
                'run_id': run_id,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'git_hash': git_short,
                'data_source': source_tag.lower(),
                'n_coins': len(coins),
                'elapsed_s': round(bt_elapsed, 2),
                'label': label,
            },
            'summary': {
                'trades': bt['trades'], 'wr': round(bt['wr'], 2),
                'pnl': round(bt['pnl'], 2), 'final_equity': round(bt['final_equity'], 2),
                'pf': round(bt['pf'], 4), 'dd': round(bt['dd'], 2),
                'broke': bt['broke'], 'early_stopped': bt['early_stopped'],
            },
            'exit_classes': bt['exit_classes'],
            'gates': gate_dict,
            'slope_sizing': slope_sizing,
            'regime_filter': regime_filter,
            'slope_sizing_stats': slope_info,
            'trades': [
                {k: (round(v, 4) if isinstance(v, float) else v) for k, v in t.items()}
                for t in bt['trade_list']
            ],
        }

        with open(run_dir / 'results.json', 'w') as f:
            json.dump(payload, f, indent=2, default=str)
        with open(run_dir / 'params.json', 'w') as f:
            json.dump(cfg, f, indent=2, sort_keys=True)
        with open(run_dir / 'gates.json', 'w') as f:
            json.dump(gate_dict, f, indent=2)

        results.append({
            'idx': idx, 'label': label, 'run_id': run_id,
            'source': source_tag.lower(),
            'trades': bt['trades'], 'pnl': round(bt['pnl'], 2),
            'pf': round(bt['pf'], 4), 'wr': round(bt['wr'], 2),
            'dd': round(bt['dd'], 2), 'ev': round(ev, 2),
            'verdict': verdict,
            'mode': 'regime_gate' if regime_filter else ('slope_sizing' if slope_sizing else 'baseline'),
        })

    # A/B Delta report
    print(f"\n{'='*70}")
    print(f"  PROXY vs NATIVE DELTA")
    print(f"{'='*70}")
    print(f"\n  {'Config':<30s} {'Source':<8s} {'Tr':>4s} {'PF':>6s} {'P&L':>10s} {'DD':>6s} {'Verdict':<8s}")
    print(f"  {'-'*30} {'-'*8} {'-'*4} {'-'*6} {'-'*10} {'-'*6} {'-'*8}")

    # Group by mode for A/B comparison
    by_mode = {}
    for r in results:
        mode = r['mode']
        if mode not in by_mode:
            by_mode[mode] = {}
        by_mode[mode][r['source']] = r

    for mode in ['baseline', 'slope_sizing', 'regime_gate']:
        if mode not in by_mode:
            continue
        for source in ['native', 'proxy']:
            r = by_mode[mode].get(source)
            if r:
                print(f"  {r['label']:<30s} {source:<8s} {r['trades']:>4d} "
                      f"{r['pf']:>6.2f} ${r['pnl']:>+9,.2f} {r['dd']:>5.1f}% {r['verdict']:<8s}")

        # Delta
        native_r = by_mode[mode].get('native')
        proxy_r = by_mode[mode].get('proxy')
        if native_r and proxy_r:
            d_tr = native_r['trades'] - proxy_r['trades']
            d_pnl = native_r['pnl'] - proxy_r['pnl']
            d_pf = native_r['pf'] - proxy_r['pf']
            d_dd = native_r['dd'] - proxy_r['dd']
            print(f"  {'  DELTA':<30s} {'':8s} {d_tr:>+4d} "
                  f"{d_pf:>+6.2f} ${d_pnl:>+9,.2f} {d_dd:>+5.1f}%")
        print()

    # Save summary
    summary_path = output_base / 'kraken_confirm_summary.json'
    with open(summary_path, 'w') as f:
        json.dump({
            'version': 'kraken-confirm',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'results': results,
            'deltas': {mode: {
                'trades': by_mode[mode].get('native', {}).get('trades', 0) - by_mode[mode].get('proxy', {}).get('trades', 0),
                'pnl': round(by_mode[mode].get('native', {}).get('pnl', 0) - by_mode[mode].get('proxy', {}).get('pnl', 0), 2),
                'pf': round(by_mode[mode].get('native', {}).get('pf', 0) - by_mode[mode].get('proxy', {}).get('pf', 0), 4),
            } for mode in by_mode if by_mode[mode].get('native') and by_mode[mode].get('proxy')},
        }, f, indent=2)
    print(f"  Summary: {summary_path}")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description='Kraken Confirm Runner')
    parser.add_argument('--plan', required=True)
    parser.add_argument('--native', required=True)
    parser.add_argument('--proxy', required=True)
    parser.add_argument('--output-dir', default=str(REPO_ROOT / 'reports' / '4h'))
    args = parser.parse_args()
    run_confirm(args)


if __name__ == '__main__':
    main()

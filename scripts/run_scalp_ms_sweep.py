#!/usr/bin/env python3
"""
Phase 2 — MS Scalp Signal Screening Sweep (19 configs × XRP/USDT 1m).

Runs all MS_SCALP_CONFIGS through the backtest harness with MS structural
indicators. Adapted from run_scalp_sweep.py for market structure signals.

Gates (adjusted for lower MS trade frequency):
    G0 TRADES:      ≥ 100          (hard)
    G1 PF:          ≥ 1.10         (hard)
    G2 PF_ADV:      ≥ 1.20         (soft)
    S1 DD:          ≤ 30%          (soft)
    S2 TPD:         ≥ 0.5/day      (soft)
    S3 WR:          ≥ 40%          (info)
    S4 BRK_SPREAD:  ≥ 3.0 bps      (hard — breakeven spread)

Output:
    ~/CryptogemData/scalp/ms/sweep/sweep_results_<ts>.json
    ~/CryptogemData/scalp/ms/sweep/scoreboard_<ts>.md

Usage:
    python scripts/run_scalp_ms_sweep.py                          # full sweep (19 configs)
    python scripts/run_scalp_ms_sweep.py --config mssa_001        # single config
    python scripts/run_scalp_ms_sweep.py --family SHIFT_PB        # single family
    python scripts/run_scalp_ms_sweep.py --expand --family FVG_FILL # grid expansion
"""

import json
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from itertools import product as iterproduct

from strategies.scalp.ms_hypotheses import (
    MS_SCALP_CONFIGS,
    signal_mssa, signal_mssb, signal_mssc, signal_mssd, signal_msse,
)
from strategies.scalp.ms_indicators import precompute_scalp_ms_indicators
from strategies.scalp.ms_gates import (
    evaluate_gates, G0_TRADES, G1_PF, G2_PF_ADV,
    S1_DD, S2_TPD, S3_WR, S4_BRK_SPREAD,
)
from strategies.scalp.harness import run_backtest

# ─── Config ─────────────────────────────────────────────
DATA_DIR = Path.home() / 'CryptogemData' / 'scalp' / '1m' / 'mexc'
OUT_DIR = Path.home() / 'CryptogemData' / 'scalp' / 'ms' / 'sweep'
PAIR = 'XRP/USDT'
SPREAD_BPS = 1.5  # Measured median from Phase 0A

# ─── Grid Expansion Definitions ────────────────────────
EXPAND_GRIDS = {
    'FVG_FILL': {
        'signal_fn': signal_mssb,
        'grid': {
            'max_fvg_age': [15, 20, 25, 30, 40],
            'fill_depth': [0.25, 0.50, 0.75],
            'rsi_max': [0, 30, 35, 40, 45, 50],
            'tp_atr': [1.5, 2.0, 2.5],
            'sl_atr': [0.75, 1.0, 1.5],
            'time_limit': [15, 20, 30],
        },
    },
    'SHIFT_PB': {
        'signal_fn': signal_mssa,
        'grid': {
            'max_bos_age': [10, 15, 20, 30],
            'pullback_pct': [0.30, 0.382, 0.50, 0.618],
            'tp_atr': [1.5, 2.0, 2.5],
            'sl_atr': [0.75, 1.0, 1.5],
            'time_limit': [10, 15, 20, 30],
        },
    },
    'LIQ_SWEEP': {
        'signal_fn': signal_mssc,
        'grid': {
            'swing_lookback': [20, 30, 60],
            'min_wick_atr': [0.2, 0.3, 0.5],
            'require_green': [True, False],
            'vol_mult': [1.0, 1.5, 2.0],
            'tp_atr': [1.5, 2.0, 2.5],
            'sl_atr': [0.75, 1.0, 1.5],
            'time_limit': [10, 15, 20],
        },
    },
    'SFP': {
        'signal_fn': signal_mssd,
        'grid': {
            'swing_lookback': [20, 30, 60],
            'min_close_strength': [0.40, 0.50, 0.60],
            'vol_mult': [1.0, 1.5],
            'tp_atr': [1.5, 2.0, 2.5],
            'sl_atr': [0.75, 1.0, 1.5],
            'time_limit': [10, 15, 20],
        },
    },
    'OB_REJECT': {
        'signal_fn': signal_msse,
        'grid': {
            'max_ob_age': [15, 20, 30, 60],
            'require_close_in_zone': [True, False],
            'vol_mult': [1.0, 1.5],
            'tp_atr': [1.5, 2.0, 2.5],
            'sl_atr': [0.75, 1.0, 1.5],
            'time_limit': [10, 15, 20],
        },
    },
}


def build_grid_configs(family: str) -> dict:
    """Build expanded grid configs for a family."""
    if family not in EXPAND_GRIDS:
        print(f'[ERROR] No grid defined for {family}. '
              f'Available: {list(EXPAND_GRIDS.keys())}')
        sys.exit(1)

    spec = EXPAND_GRIDS[family]
    signal_fn = spec['signal_fn']
    grid = spec['grid']

    keys = sorted(grid.keys())
    values = [grid[k] for k in keys]
    combos = list(iterproduct(*values))

    configs = {}
    for i, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        config_id = f'{family.lower()[:4]}_x{i:04d}'
        configs[config_id] = {
            'signal_fn': signal_fn,
            'family': family,
            'params': params,
        }

    return configs


def run_sweep(config_ids: list[str] | None = None):
    """Run screening sweep on specified configs (or all)."""
    data_path = DATA_DIR / 'XRP_USDT_1m.json'
    if not data_path.exists():
        print(f'[ERROR] Data not found: {data_path}')
        sys.exit(1)

    print(f'Loading candles from {data_path}...')
    with open(data_path) as f:
        candles = json.load(f)
    n_bars = len(candles)
    span_days = (candles[-1]['time'] - candles[0]['time']) / 86400
    print(f'  {n_bars:,} bars, {span_days:.1f} days\n')

    # Precompute indicators (technical + structural)
    print('Computing indicators (technical + MS structural)...')
    t0 = time.time()
    data = {PAIR: candles}
    all_indicators = precompute_scalp_ms_indicators(
        data, [PAIR],
        swing_left=3, swing_right=1,  # Calibrated for 1m
        min_gap_atr=0.3,
        min_impulse_atr=1.5,
        lookback_impulse=3,
        tolerance_atr=0.5,
        min_touches=2,
    )
    indicators = all_indicators[PAIR]
    elapsed_ind = time.time() - t0
    print(f'  Done in {elapsed_ind:.1f}s\n')

    # Select configs
    if config_ids:
        configs_to_run = {k: v for k, v in MS_SCALP_CONFIGS.items() if k in config_ids}
    else:
        configs_to_run = MS_SCALP_CONFIGS

    if not configs_to_run:
        print('[ERROR] No matching configs found.')
        sys.exit(1)

    print(f'Running {len(configs_to_run)} MS configs (spread={SPREAD_BPS} bps)')
    print('=' * 90)

    results = []
    for config_id, cfg in sorted(configs_to_run.items()):
        t0 = time.time()
        result = run_backtest(
            candles=candles,
            signal_fn=cfg['signal_fn'],
            params=cfg['params'],
            indicators=indicators,
            spread_bps=SPREAD_BPS,
            initial_capital=2000.0,
            capital_per_trade=200.0,
            max_positions=1,
            start_bar=60,  # After indicator warmup (VWAP 60, BB 20, ATR 14)
            cooldown_bars=2,
            cooldown_after_stop=5,
            daily_loss_limit=-0.02,
        )
        elapsed = time.time() - t0

        gates = evaluate_gates(result, base_spread_bps=SPREAD_BPS)

        # Exit type breakdown
        exit_counts = {}
        for t in result.trade_list:
            et = t.get('exit_type', 'UNKNOWN')
            exit_counts[et] = exit_counts.get(et, 0) + 1

        entry = {
            'config_id': config_id,
            'family': cfg['family'],
            'params': {k: v for k, v in cfg['params'].items()},
            'trades': result.trades,
            'pf': result.pf,
            'wr': result.wr,
            'dd': result.dd,
            'pnl': result.pnl,
            'avg_hold': result.avg_hold,
            'trades_per_day': result.trades_per_day,
            'exit_types': exit_counts,
            'gates': gates,
            'elapsed_s': round(elapsed, 2),
        }
        results.append(entry)

        # Print line
        v = gates['verdict']
        v_icon = {
            'GO_ADVANCED': '🟢',
            'GO': '✅',
            'GO_SPREAD_RISK': '⚠️',
            'MARGINAL': '🟡',
            'NO_GO': '❌',
        }[v]
        brk = gates['breakeven_spread_bps']
        print(f'  {v_icon} {config_id:10s} [{cfg["family"]:12s}] '
              f'PF={result.pf:5.3f} WR={result.wr:4.1f}% '
              f'Trades={result.trades:5d} DD={result.dd:4.1f}% '
              f'PnL=${result.pnl:7.2f} TPD={result.trades_per_day:4.1f} '
              f'BrkSprd={brk:4.1f}bps [{v}]')

    print('=' * 90)

    return results


def build_scoreboard(results: list[dict]) -> str:
    """Build markdown scoreboard."""
    lines = [
        '# MS Scalp Screening Scoreboard',
        f'**Date**: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}',
        f'**Pair**: XRP/USDT 1m | **Spread**: {SPREAD_BPS} bps | **Configs**: {len(results)}',
        f'**Approach**: Market Structure (BoS, FVG, OB, LiqSweep, SFP)',
        '',
        '## Gates',
        f'- G0 TRADES: ≥ {G0_TRADES} (hard)',
        f'- G1 PF: ≥ {G1_PF} (hard)',
        f'- G2 PF_ADV: ≥ {G2_PF_ADV} (soft — promotes to verification)',
        f'- S1 DD: ≤ {S1_DD}% (soft)',
        f'- S2 TPD: ≥ {S2_TPD} trades/day (soft)',
        f'- S3 WR: ≥ {S3_WR}% (info)',
        f'- S4 BRK_SPREAD: ≥ {S4_BRK_SPREAD} bps (hard — must survive P95 spread)',
        '',
        '## Results',
        '',
        '| # | Config | Family | PF | WR% | Trades | DD% | PnL | TPD | BrkSprd | G0 | G1 | S4 | G2 | S1 | S2 | Verdict |',
        '|---|--------|--------|----|-----|--------|-----|-----|-----|---------|----|----|----|----|----|----|---------|',
    ]

    # Sort by PF descending
    sorted_results = sorted(results, key=lambda x: x['pf'], reverse=True)

    for i, r in enumerate(sorted_results, 1):
        g = r['gates']
        lines.append(
            f'| {i} | {r["config_id"]} | {r["family"]} | '
            f'{r["pf"]:.3f} | {r["wr"]:.1f} | {r["trades"]} | '
            f'{r["dd"]:.1f} | ${r["pnl"]:.2f} | {r["trades_per_day"]:.1f} | '
            f'{g["breakeven_spread_bps"]:.1f} | '
            f'{"✅" if g["g0_trades"] else "❌"} | '
            f'{"✅" if g["g1_pf"] else "❌"} | '
            f'{"✅" if g["s4_brk_spread"] else "❌"} | '
            f'{"✅" if g["g2_pf_adv"] else "❌"} | '
            f'{"✅" if g["s1_dd"] else "❌"} | '
            f'{"✅" if g["s2_tpd"] else "❌"} | '
            f'{g["verdict"]} |'
        )

    # Summary
    go_count = sum(1 for r in results if r['gates']['hard_pass'])
    go_adv = sum(1 for r in results if r['gates']['verdict'] == 'GO_ADVANCED')
    go_base = sum(1 for r in results if r['gates']['verdict'] == 'GO')
    spread_risk = sum(1 for r in results if r['gates']['verdict'] == 'GO_SPREAD_RISK')
    marginal = sum(1 for r in results if r['gates']['verdict'] == 'MARGINAL')
    nogo = sum(1 for r in results if r['gates']['verdict'] == 'NO_GO')

    lines.extend([
        '',
        '## Summary',
        f'- **GO_ADVANCED**: {go_adv}',
        f'- **GO**: {go_base}',
        f'- **GO_SPREAD_RISK**: {spread_risk} (PF OK but breakeven < {S4_BRK_SPREAD} bps)',
        f'- **MARGINAL**: {marginal}',
        f'- **NO_GO**: {nogo}',
        '',
    ])

    # Family summary
    families = {}
    for r in results:
        fam = r['family']
        if fam not in families:
            families[fam] = []
        families[fam].append(r)

    lines.append('## Family Summary')
    lines.append('')
    lines.append('| Family | Configs | Best PF | Avg PF | Best BrkSprd | Best Config |')
    lines.append('|--------|---------|---------|--------|-------------|-------------|')
    for fam, fam_results in sorted(families.items()):
        best = max(fam_results, key=lambda x: x['pf'])
        avg_pf = sum(r['pf'] for r in fam_results) / len(fam_results)
        best_brk = max(r['gates']['breakeven_spread_bps'] for r in fam_results)
        lines.append(
            f'| {fam} | {len(fam_results)} | {best["pf"]:.3f} | '
            f'{avg_pf:.3f} | {best_brk:.1f} bps | {best["config_id"]} |'
        )

    # Exit type breakdown
    lines.extend(['', '## Exit Type Distribution', ''])
    lines.append('| Config | STOP | TARGET | TIME | TRAIL | FORCE |')
    lines.append('|--------|------|--------|------|-------|-------|')
    for r in sorted_results[:10]:  # Top 10
        et = r.get('exit_types', {})
        lines.append(
            f'| {r["config_id"]} | {et.get("STOP", 0)} | {et.get("TARGET", 0)} | '
            f'{et.get("TIME", 0)} | {et.get("TRAIL", 0)} | {et.get("FORCE_CLOSE", 0)} |'
        )

    # Decision
    lines.extend([
        '',
        '## GO/NO-GO Decision',
        '',
    ])
    if go_adv > 0:
        lines.append(f'**GO** — {go_adv} config(s) pass G0 + G1 + S4 + G2. '
                      f'Proceed to Phase 3 verification.')
    elif go_count > 0:
        lines.append(f'**CONDITIONAL GO** — {go_count} config(s) pass G0 + G1 + S4 '
                      f'(PF ≥ {G1_PF}, breakeven ≥ {S4_BRK_SPREAD} bps). '
                      f'Consider grid expansion.')
    elif spread_risk > 0:
        lines.append(f'**SPREAD RISK** — {spread_risk} config(s) pass PF gate but '
                      f'breakeven < {S4_BRK_SPREAD} bps. Same failure mode as indicators.')
    else:
        lines.append(f'**NO-GO** — 0 configs pass G0 + G1. '
                      f'MS signals on 1m XRP/USDT do not generate edge.')

    # Comparison to indicator approach
    lines.extend([
        '',
        '## Comparison to Indicator Approach',
        '',
        '| Metric | Indicator (best) | MS (best) |',
        '|--------|-----------------|-----------|',
    ])
    best_ms = max(results, key=lambda x: x['pf']) if results else None
    if best_ms:
        lines.append(
            f'| Best PF | 1.127 | {best_ms["pf"]:.3f} |'
        )
        lines.append(
            f'| Best BrkSprd | 2.1 bps | '
            f'{best_ms["gates"]["breakeven_spread_bps"]:.1f} bps |'
        )
        lines.append(
            f'| Best Config | sa_002 | {best_ms["config_id"]} |'
        )

    return '\n'.join(lines)


def run_expand(family: str):
    """Run grid expansion sweep for a single family."""
    configs = build_grid_configs(family)
    n_combos = len(configs)
    print(f'Grid expansion: {family} — {n_combos} combos')
    print(f'(Indicators will be computed once, then reused for all combos)\n')

    # Load data
    data_path = DATA_DIR / 'XRP_USDT_1m.json'
    if not data_path.exists():
        print(f'[ERROR] Data not found: {data_path}')
        sys.exit(1)

    print(f'Loading candles from {data_path}...')
    with open(data_path) as f:
        candles = json.load(f)
    n_bars = len(candles)
    span_days = (candles[-1]['time'] - candles[0]['time']) / 86400
    print(f'  {n_bars:,} bars, {span_days:.1f} days\n')

    # Precompute indicators ONCE
    print('Computing indicators (technical + MS structural)...')
    t0 = time.time()
    data = {PAIR: candles}
    all_indicators = precompute_scalp_ms_indicators(
        data, [PAIR],
        swing_left=3, swing_right=1,
        min_gap_atr=0.3, min_impulse_atr=1.5,
        lookback_impulse=3, tolerance_atr=0.5, min_touches=2,
    )
    indicators = all_indicators[PAIR]
    elapsed_ind = time.time() - t0
    print(f'  Done in {elapsed_ind:.1f}s\n')

    print(f'Running {n_combos} grid combos (spread={SPREAD_BPS} bps)')
    print('=' * 90)

    results = []
    t_sweep = time.time()

    for idx, (config_id, cfg) in enumerate(sorted(configs.items())):
        t0 = time.time()
        result = run_backtest(
            candles=candles,
            signal_fn=cfg['signal_fn'],
            params=cfg['params'],
            indicators=indicators,
            spread_bps=SPREAD_BPS,
            initial_capital=2000.0,
            capital_per_trade=200.0,
            max_positions=1,
            start_bar=60,
            cooldown_bars=2,
            cooldown_after_stop=5,
            daily_loss_limit=-0.02,
        )
        elapsed = time.time() - t0

        gates = evaluate_gates(result, base_spread_bps=SPREAD_BPS)

        exit_counts = {}
        for t in result.trade_list:
            et = t.get('exit_type', 'UNKNOWN')
            exit_counts[et] = exit_counts.get(et, 0) + 1

        entry = {
            'config_id': config_id,
            'family': cfg['family'],
            'params': {k: v for k, v in cfg['params'].items()},
            'trades': result.trades,
            'pf': result.pf,
            'wr': result.wr,
            'dd': result.dd,
            'pnl': result.pnl,
            'avg_hold': result.avg_hold,
            'trades_per_day': result.trades_per_day,
            'exit_types': exit_counts,
            'gates': gates,
            'elapsed_s': round(elapsed, 2),
        }
        results.append(entry)

        # Only print GO/MARGINAL or every 100th combo
        if gates['verdict'] in ('GO_ADVANCED', 'GO', 'GO_SPREAD_RISK') or (idx + 1) % 100 == 0:
            v = gates['verdict']
            v_icon = {
                'GO_ADVANCED': '🟢', 'GO': '✅', 'GO_SPREAD_RISK': '⚠️',
                'MARGINAL': '🟡', 'NO_GO': '❌',
            }[v]
            brk = gates['breakeven_spread_bps']
            print(f'  {v_icon} {config_id:12s} '
                  f'PF={result.pf:5.3f} WR={result.wr:4.1f}% '
                  f'Trades={result.trades:5d} DD={result.dd:4.1f}% '
                  f'PnL=${result.pnl:7.2f} BrkSprd={brk:4.1f}bps [{v}]')

    total_elapsed = time.time() - t_sweep
    print(f'\n  Grid complete: {n_combos} combos in {total_elapsed:.0f}s '
          f'({total_elapsed / n_combos:.2f}s/combo)')
    print('=' * 90)

    # Top 20 by PF
    print('\nTop 20 by PF:')
    sorted_by_pf = sorted(results, key=lambda x: x['pf'], reverse=True)
    for i, r in enumerate(sorted_by_pf[:20], 1):
        g = r['gates']
        brk = g['breakeven_spread_bps']
        print(f'  {i:2d}. {r["config_id"]:12s} PF={r["pf"]:.3f} '
              f'Trades={r["trades"]:5d} WR={r["wr"]:.1f}% DD={r["dd"]:.1f}% '
              f'PnL=${r["pnl"]:.2f} BrkSprd={brk:.1f}bps [{g["verdict"]}]')

    return results


def main():
    parser = argparse.ArgumentParser(description='MS Scalp Signal Screening Sweep')
    parser.add_argument('--config', type=str, default=None,
                        help='Run single config (e.g., mssa_001)')
    parser.add_argument('--family', type=str, default=None,
                        help='Run single family (e.g., SHIFT_PB) or filter for expansion')
    parser.add_argument('--expand', action='store_true',
                        help='Grid expansion mode (requires --family)')
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Grid expansion mode
    if args.expand:
        if not args.family:
            print('[ERROR] --expand requires --family (e.g., --expand --family FVG_FILL)')
            sys.exit(1)
        results = run_expand(args.family)
    else:
        # Build config filter
        if args.config:
            config_ids = [args.config]
        elif args.family:
            config_ids = [
                k for k, v in MS_SCALP_CONFIGS.items()
                if v['family'] == args.family
            ]
            if not config_ids:
                print(f'[ERROR] Family "{args.family}" not found. '
                      f'Available: {sorted(set(v["family"] for v in MS_SCALP_CONFIGS.values()))}')
                sys.exit(1)
        else:
            config_ids = None

        results = run_sweep(config_ids)

    # Save results
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')
    results_path = OUT_DIR / f'sweep_results_{ts}.json'

    # Serialize (strip non-JSON-safe fields)
    serializable = []
    for r in results:
        sr = dict(r)
        sr['params'] = {k: v for k, v in r['params'].items()}
        serializable.append(sr)

    with open(results_path, 'w') as f:
        json.dump(serializable, f, indent=2)
    print(f'\nResults saved: {results_path}')

    # Build and save scoreboard
    scoreboard = build_scoreboard(results)
    sb_path = OUT_DIR / f'scoreboard_{ts}.md'
    with open(sb_path, 'w') as f:
        f.write(scoreboard)
    print(f'Scoreboard saved: {sb_path}')

    # Also save latest versions
    latest_results = OUT_DIR / 'sweep_results_latest.json'
    latest_sb = OUT_DIR / 'scoreboard_latest.md'
    with open(latest_results, 'w') as f:
        json.dump(serializable, f, indent=2)
    with open(latest_sb, 'w') as f:
        f.write(scoreboard)

    # Print scoreboard
    print(f'\n{scoreboard}')


if __name__ == '__main__':
    main()

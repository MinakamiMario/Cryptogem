#!/usr/bin/env python3
"""
Phase 2 — Scalp Signal Screening Sweep (21 configs × XRP/USDT 1m).

Runs all CONFIGS from strategies/scalp/hypotheses.py through the backtest harness.
Evaluates against screening gates:
    G0 TRADES:  ≥ 500           (hard)
    G1 PF:      ≥ 1.05          (hard)
    G2 PF_ADV:  ≥ 1.15          (soft — promotes to verification)
    S1 DD:      ≤ 30%           (soft)
    S2 TPD:     ≥ 3 trades/day  (soft)
    S3 DAILY:   ≤ -2% equity/day (hard — enforced in harness)

Output:
    ~/CryptogemData/scalp/sweep/sweep_results.json    — full results
    ~/CryptogemData/scalp/sweep/scoreboard.md         — human-readable

Usage:
    python scripts/run_scalp_sweep.py                  # full sweep
    python scripts/run_scalp_sweep.py --config sa_002  # single config
"""

import json
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategies.scalp.hypotheses import CONFIGS
from strategies.scalp.indicators import precompute_scalp_indicators
from strategies.scalp.harness import run_backtest

# ─── Config ─────────────────────────────────────────────
DATA_DIR = Path.home() / 'CryptogemData' / 'scalp' / '1m' / 'mexc'
OUT_DIR = Path.home() / 'CryptogemData' / 'scalp' / 'sweep'
PAIR = 'XRP/USDT'
SPREAD_BPS = 1.5  # Measured median from Phase 0A

# Gates
G0_TRADES = 500
G1_PF = 1.05
G2_PF_ADV = 1.15
S1_DD = 30.0
S2_TPD = 3.0


def evaluate_gates(result) -> dict:
    """Evaluate a BacktestResult against screening gates."""
    g0 = result.trades >= G0_TRADES
    g1 = result.pf >= G1_PF
    g2 = result.pf >= G2_PF_ADV
    s1 = result.dd <= S1_DD
    s2 = result.trades_per_day >= S2_TPD

    # Verdict logic
    if g0 and g1 and g2:
        verdict = 'GO_ADVANCED'
    elif g0 and g1:
        verdict = 'GO'
    elif g0 and result.pf >= 1.0:
        verdict = 'MARGINAL'
    else:
        verdict = 'NO_GO'

    return {
        'g0_trades': g0,
        'g1_pf': g1,
        'g2_pf_adv': g2,
        's1_dd': s1,
        's2_tpd': s2,
        'verdict': verdict,
        'hard_pass': g0 and g1,
        'soft_flags': sum([s1, s2]),
    }


def run_sweep(config_ids: list[str] | None = None):
    """Run screening sweep on specified configs (or all)."""
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

    # Precompute indicators
    print('Computing indicators...')
    t0 = time.time()
    data = {PAIR: candles}
    all_indicators = precompute_scalp_indicators(data, [PAIR])
    indicators = all_indicators[PAIR]
    print(f'  Done in {time.time() - t0:.1f}s\n')

    # Select configs
    if config_ids:
        configs_to_run = {k: v for k, v in CONFIGS.items() if k in config_ids}
    else:
        configs_to_run = CONFIGS

    print(f'Running {len(configs_to_run)} configs (spread={SPREAD_BPS} bps)')
    print('=' * 80)

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
            start_bar=60,  # After VWAP warmup
            cooldown_bars=2,
            cooldown_after_stop=5,
            daily_loss_limit=-0.02,
        )
        elapsed = time.time() - t0

        gates = evaluate_gates(result)

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
        v_icon = {'GO_ADVANCED': '🟢', 'GO': '✅', 'MARGINAL': '🟡', 'NO_GO': '❌'}[v]
        print(f'  {v_icon} {config_id:8s} [{cfg["family"]:12s}] '
              f'PF={result.pf:5.3f} WR={result.wr:4.1f}% '
              f'Trades={result.trades:5d} DD={result.dd:4.1f}% '
              f'PnL=${result.pnl:7.2f} TPD={result.trades_per_day:4.1f} '
              f'[{v}]')

    print('=' * 80)

    return results


def build_scoreboard(results: list[dict]) -> str:
    """Build markdown scoreboard."""
    lines = [
        '# Scalp Screening Scoreboard',
        f'**Date**: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}',
        f'**Pair**: XRP/USDT 1m | **Spread**: {SPREAD_BPS} bps | **Configs**: {len(results)}',
        '',
        '## Gates',
        f'- G0 TRADES: ≥ {G0_TRADES} (hard)',
        f'- G1 PF: ≥ {G1_PF} (hard)',
        f'- G2 PF_ADV: ≥ {G2_PF_ADV} (soft)',
        f'- S1 DD: ≤ {S1_DD}% (soft)',
        f'- S2 TPD: ≥ {S2_TPD} trades/day (soft)',
        '',
        '## Results',
        '',
        '| # | Config | Family | PF | WR% | Trades | DD% | PnL | TPD | G0 | G1 | G2 | S1 | S2 | Verdict |',
        '|---|--------|--------|----|-----|--------|-----|-----|-----|----|----|----|----|----|---------|',
    ]

    # Sort by PF descending
    sorted_results = sorted(results, key=lambda x: x['pf'], reverse=True)

    for i, r in enumerate(sorted_results, 1):
        g = r['gates']
        lines.append(
            f'| {i} | {r["config_id"]} | {r["family"]} | '
            f'{r["pf"]:.3f} | {r["wr"]:.1f} | {r["trades"]} | '
            f'{r["dd"]:.1f} | ${r["pnl"]:.2f} | {r["trades_per_day"]:.1f} | '
            f'{"✅" if g["g0_trades"] else "❌"} | '
            f'{"✅" if g["g1_pf"] else "❌"} | '
            f'{"✅" if g["g2_pf_adv"] else "❌"} | '
            f'{"✅" if g["s1_dd"] else "❌"} | '
            f'{"✅" if g["s2_tpd"] else "❌"} | '
            f'{g["verdict"]} |'
        )

    # Summary
    go_count = sum(1 for r in results if r['gates']['hard_pass'])
    go_adv = sum(1 for r in results if r['gates']['verdict'] == 'GO_ADVANCED')
    marginal = sum(1 for r in results if r['gates']['verdict'] == 'MARGINAL')
    nogo = sum(1 for r in results if r['gates']['verdict'] == 'NO_GO')

    lines.extend([
        '',
        '## Summary',
        f'- **GO_ADVANCED**: {go_adv}',
        f'- **GO**: {go_count - go_adv}',
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
    lines.append('| Family | Configs | Best PF | Avg PF | Best Config |')
    lines.append('|--------|---------|---------|--------|-------------|')
    for fam, fam_results in sorted(families.items()):
        best = max(fam_results, key=lambda x: x['pf'])
        avg_pf = sum(r['pf'] for r in fam_results) / len(fam_results)
        lines.append(
            f'| {fam} | {len(fam_results)} | {best["pf"]:.3f} | '
            f'{avg_pf:.3f} | {best["config_id"]} |'
        )

    # Exit type breakdown
    lines.extend(['', '## Exit Type Distribution', ''])
    lines.append('| Config | STOP | TARGET | TIME | FORCE |')
    lines.append('|--------|------|--------|------|-------|')
    for r in sorted_results[:10]:  # Top 10
        et = r.get('exit_types', {})
        lines.append(
            f'| {r["config_id"]} | {et.get("STOP", 0)} | {et.get("TARGET", 0)} | '
            f'{et.get("TIME", 0)} | {et.get("FORCE_CLOSE", 0)} |'
        )

    # Decision
    lines.extend([
        '',
        '## GO/NO-GO Decision',
        '',
    ])
    if go_adv > 0:
        lines.append(f'**GO** — {go_adv} config(s) pass G0 + G1 + G2. Proceed to Phase 3 verification.')
    elif go_count > 0:
        lines.append(f'**CONDITIONAL GO** — {go_count} config(s) pass G0 + G1 (PF ≥ {G1_PF}). '
                      f'Consider expanding configs or adjusting parameters.')
    else:
        lines.append(f'**NO-GO** — 0 configs pass G0 + G1. Review signal families or data.')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Scalp Signal Screening Sweep')
    parser.add_argument('--config', type=str, default=None,
                        help='Run single config (e.g., sa_002)')
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    config_ids = [args.config] if args.config else None
    results = run_sweep(config_ids)

    # Save results
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')
    results_path = OUT_DIR / f'sweep_results_{ts}.json'
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f'\nResults saved: {results_path}')

    # Build and save scoreboard
    scoreboard = build_scoreboard(results)
    sb_path = OUT_DIR / f'scoreboard_{ts}.md'
    with open(sb_path, 'w') as f:
        f.write(scoreboard)
    print(f'Scoreboard saved: {sb_path}')

    # Also save latest symlinks
    latest_results = OUT_DIR / 'sweep_results_latest.json'
    latest_sb = OUT_DIR / 'scoreboard_latest.md'
    with open(latest_results, 'w') as f:
        json.dump(results, f, indent=2)
    with open(latest_sb, 'w') as f:
        f.write(scoreboard)

    # Print scoreboard
    print(f'\n{scoreboard}')


if __name__ == '__main__':
    main()

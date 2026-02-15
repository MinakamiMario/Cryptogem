#!/usr/bin/env python3
"""
Sprint 5 -- Layer 1 Hypothesis Screening CLI
=============================================
Runs Sprint 5 hypotheses (H16-H25) through updated screening pipeline
with market context, extended indicators, and updated scoreboard.

Usage:
    python -m strategies.hf.screening.run_screen_s5
    python -m strategies.hf.screening.run_screen_s5 --timeframe 1h
    python -m strategies.hf.screening.run_screen_s5 --hypothesis H16 H21
"""
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

# Ensure project root on path
ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from strategies.hf.screening.harness import precompute_base_indicators
from strategies.hf.screening.hypotheses_s5 import (
    get_all_hypotheses_s5, get_hypothesis_s5,
)
from strategies.hf.screening.indicators_extended import (
    extend_indicators, get_feature_coverage,
)
from strategies.hf.screening.market_context import precompute_market_context
from strategies.hf.screening.screener_s5 import screen_all_s5, get_survivors_s5
from strategies.hf.screening.report import write_screen_json, write_screen_md


# ============================================================
# Data Loading (reuse patterns from run_screen.py)
# ============================================================

def load_candle_cache(timeframe: str = '1h') -> dict:
    """Load candle cache from data directory."""
    cache_path = ROOT / 'data' / f'candle_cache_{timeframe}.json'
    if not cache_path.exists():
        raise FileNotFoundError(f'Cache not found: {cache_path}')
    print(f'[Load] Reading {cache_path.name}...')
    with open(cache_path) as f:
        data = json.load(f)
    # Filter out metadata keys
    coins_data = {k: v for k, v in data.items() if not k.startswith('_')}
    n_coins = len(coins_data)
    print(f'[Load] {n_coins} coins loaded')
    return coins_data


def load_universe_tiering() -> dict:
    """Load universe tiering from reports."""
    tiering_path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not tiering_path.exists():
        raise FileNotFoundError(f'Tiering not found: {tiering_path}')
    with open(tiering_path) as f:
        tiering = json.load(f)
    return tiering


def build_tier_coins(tiering: dict, available_coins: set) -> dict:
    """
    Build tier -> coin list mapping.
    Returns {'tier1': [...], 'tier2': [...]}.
    Only includes coins that exist in the candle data.
    """
    tier_coins = {'tier1': [], 'tier2': []}

    # Format 1: tier_breakdown with numeric keys '1', '2'
    tb = tiering.get('tier_breakdown', {})
    if tb:
        for tier_num, tier_key in [('1', 'tier1'), ('2', 'tier2')]:
            if tier_num in tb:
                coins = tb[tier_num].get('coins', [])
                tier_coins[tier_key] = [c for c in coins if c in available_coins]
        if tier_coins['tier1'] or tier_coins['tier2']:
            return tier_coins

    # Format 2: tiers dict with various key names
    tiers = tiering.get('tiers', {})
    for tier_key in ['tier_1', 'Tier 1 (Liquid)', 'tier1', '1']:
        if tier_key in tiers:
            coins = tiers[tier_key].get('coins', [])
            tier_coins['tier1'] = [c for c in coins if c in available_coins]
            break

    for tier_key in ['tier_2', 'Tier 2 (Mid)', 'tier2', '2']:
        if tier_key in tiers:
            coins = tiers[tier_key].get('coins', [])
            tier_coins['tier2'] = [c for c in coins if c in available_coins]
            break

    return tier_coins


# ============================================================
# Sprint 5 Markdown Report Writer
# ============================================================

def write_screen_s5_md(results: list, meta: dict, path: Path) -> Path:
    """Write Sprint 5 screening results to Markdown with scoreboard columns."""
    from strategies.hf.screening.screener_s5 import get_survivors_s5

    survivors = get_survivors_s5(results)
    killed_list = [r for r in results if r.get('killed', True)]

    lines = []
    lines.append('# Sprint 5 -- Layer 1 Screening Report')
    lines.append('')
    lines.append(f'**Date**: {meta.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M"))}')
    lines.append(f'**Timeframe**: {meta.get("timeframe", "1H")}')
    lines.append(f'**Universe**: T1 ({meta.get("t1_coins", "?")} coins) + '
                 f'T2 ({meta.get("t2_coins", "?")} coins)')
    lines.append(f'**Configs tested**: {len(results)}')
    lines.append(f'**Runtime**: {meta.get("runtime_s", 0):.1f}s')
    lines.append('')

    # --- Verdict ---
    lines.append('## Verdict')
    lines.append('')
    if survivors:
        lines.append(f'**{len(survivors)} survivor(s)** out of {len(results)} configs '
                      f'passed all KILL gates (K1 exp/week, K2 trades/week, K3 BE ratio).')
    else:
        lines.append(f'**NO SURVIVORS** -- all {len(results)} configs failed KILL gates.')
        lines.append('')
        lines.append('No Sprint 5 hypothesis has positive weekly expectancy with '
                      'sufficient trade frequency and acceptable break-even ratio.')
    lines.append('')

    # --- Gate Summary Table ---
    lines.append('## Gate Summary')
    lines.append('')
    lines.append('| Gate | Description | Pass | Fail | Rate |')
    lines.append('|------|-------------|------|------|------|')
    gate_keys = [
        ('K1_exp_week', 'Exp/week > $0'),
        ('K2_trades_week', 'Trades/week >= 7'),
        ('K3_be_ratio', 'BE ratio < 40%'),
        ('S3_pf', 'PF >= 1.1'),
        ('S4_wf', 'WF >= 2/5 positive'),
        ('S5_concentration', 'Top1 < 40%, Top3 < 70%'),
    ]
    for gate_id, desc in gate_keys:
        passed = sum(1 for r in results if r.get('gate_results', {}).get(gate_id, False))
        failed = len(results) - passed
        rate = f'{passed / len(results) * 100:.0f}%' if results else '0%'
        lines.append(f'| {gate_id} | {desc} | {passed} | {failed} | {rate} |')
    lines.append('')

    # --- Survivors ---
    if survivors:
        lines.append('## Survivors (passed K1 + K2 + K3)')
        lines.append('')
        lines.append('| Rank | ID | Name | Trades | Exp/Trade | Exp/Week | '
                      'Tr/Week | PF | WR% | BE% | Fee Drag% | Stress PnL | DD% | Score |')
        lines.append('|------|----|------|--------|-----------|----------|'
                      '---------|----|----|-----|-----------|------------|-----|-------|')
        for i, r in enumerate(survivors, 1):
            lines.append(
                f'| {i} | {r["hypothesis_id"]} v{r["variant_idx"]} | {r.get("name", "")} '
                f'| {r["trades"]} | ${r.get("expectancy", 0):.2f} '
                f'| ${r.get("exp_per_week", 0):.2f} '
                f'| {r.get("trades_per_week", 0):.1f} '
                f'| {r.get("pf", 0):.2f} | {r.get("wr", 0):.1f}% '
                f'| {r.get("be_trade_ratio", 0):.1f}% '
                f'| {r.get("fee_drag_pct", 0):.1f}% '
                f'| ${r.get("stress_2x_pnl", 0):.2f} '
                f'| {r.get("dd", 0):.1f}% | {r.get("score", 0):.1f} |'
            )
        lines.append('')

    # --- Best Variant Per Hypothesis ---
    lines.append('## Best Variant Per Hypothesis')
    lines.append('')
    lines.append('| ID | Name | Category | Trades | Exp/Week | Tr/Week | '
                 'BE% | PF | Killed? |')
    lines.append('|----|------|----------|--------|----------|---------|'
                 '-----|----|---------| ')

    by_hyp = {}
    for r in results:
        hid = r['hypothesis_id']
        if hid not in by_hyp or r.get('exp_per_week', 0) > by_hyp[hid].get('exp_per_week', 0):
            by_hyp[hid] = r

    for hid in sorted(by_hyp.keys()):
        r = by_hyp[hid]
        killed_str = 'KILL' if r.get('killed', True) else 'PASS'
        lines.append(
            f'| {hid} | {r.get("name", "")} | {r.get("category", "")} '
            f'| {r.get("trades", 0)} | ${r.get("exp_per_week", 0):.2f} '
            f'| {r.get("trades_per_week", 0):.1f} '
            f'| {r.get("be_trade_ratio", 0):.1f}% '
            f'| {r.get("pf", 0):.2f} | {killed_str} |'
        )
    lines.append('')

    # --- Walk-Forward Detail for survivors ---
    if survivors:
        lines.append('## Walk-Forward Detail (Survivors)')
        lines.append('')
        for r in survivors[:3]:
            wf = r.get('wf_detail', [])
            if wf:
                lines.append(f'### {r["hypothesis_id"]} v{r["variant_idx"]}')
                lines.append('')
                lines.append('| Fold | Trades | P&L | PF | WR% | Positive |')
                lines.append('|------|--------|-----|----|-----|----------|')
                for i, f in enumerate(wf, 1):
                    pos = 'YES' if f.get('pnl', 0) > 0 else 'NO'
                    lines.append(
                        f'| {i} | {f.get("trades", 0)} | ${f.get("pnl", 0):.2f} '
                        f'| {f.get("pf", 0):.2f} | {f.get("wr", 0):.1f}% | {pos} |'
                    )
                lines.append('')

    # --- Feature Coverage ---
    if 'feature_coverage' in meta:
        lines.append('## Feature Coverage')
        lines.append('')
        for tier_name, cov in meta['feature_coverage'].items():
            lines.append(f'**{tier_name}**: VWAP {cov.get("vwap_pct", 0):.0f}% '
                          f'({cov.get("vwap_available", 0)}/{cov.get("total_coins", 0)}), '
                          f'Count {cov.get("count_pct", 0):.0f}% '
                          f'({cov.get("count_available", 0)}/{cov.get("total_coins", 0)})')
        lines.append('')

    # --- Footer ---
    lines.append('---')
    lines.append(f'*Generated by screening/run_screen_s5.py at '
                 f'{datetime.now().strftime("%Y-%m-%d %H:%M")} -- Sprint 5 Layer 1 screening*')

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines))
    return path


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Sprint 5 Layer 1 Screening')
    parser.add_argument('--timeframe', default='1h',
                        help='Timeframe (default: 1h)')
    parser.add_argument('--hypothesis', nargs='*', default=None,
                        help='Specific hypothesis IDs to test (e.g., H16 H20)')
    parser.add_argument('--quiet', action='store_true',
                        help='Suppress per-variant output')
    args = parser.parse_args()

    print(f'=== Sprint 5 Layer 1 Screening ({args.timeframe}) ===')
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0 = time.time()

    # --- Load data ---
    data = load_candle_cache(args.timeframe)
    available_coins = set(data.keys())

    tiering = load_universe_tiering()
    tier_coins = build_tier_coins(tiering, available_coins)

    print(f'[Universe] T1: {len(tier_coins["tier1"])} coins, '
          f'T2: {len(tier_coins["tier2"])} coins')

    if not tier_coins['tier1'] and not tier_coins['tier2']:
        print('[ERROR] No coins in T1 or T2. Check universe_tiering_001.json format.')
        sys.exit(1)

    # --- Precompute base indicators per tier ---
    print('[Indicators] Precomputing base indicators...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    # --- Extend indicators per tier (Sprint 5 additions) ---
    print('[Indicators] Extending with microstructure fields...')
    feature_coverage = {}
    for tier_name, coins in tier_coins.items():
        if coins and tier_name in tier_indicators:
            extend_indicators(data, coins, tier_indicators[tier_name])
            cov = get_feature_coverage(tier_indicators[tier_name], coins)
            feature_coverage[tier_name] = cov
            print(f'  {tier_name}: VWAP {cov["vwap_pct"]:.0f}% '
                  f'({cov["vwap_available"]}/{cov["total_coins"]}), '
                  f'Count {cov["count_pct"]:.0f}% '
                  f'({cov["count_available"]}/{cov["total_coins"]})')

    # --- Precompute market context ---
    # Include BTC/USD (and variants) even if not in any trading tier,
    # because market context needs BTC for btc_atr_ratio.
    print('[Market Context] Precomputing cross-coin context...')
    all_coins = []
    for coins in tier_coins.values():
        all_coins.extend(coins)
    all_coins = list(set(all_coins))
    # Ensure BTC is present for market context even if not in tiers
    for btc_candidate in ('BTC/USD', 'XBT/USD', 'BTC/USDT'):
        if btc_candidate in available_coins and btc_candidate not in all_coins:
            all_coins.append(btc_candidate)
    t_mc = time.time()
    market_context = precompute_market_context(data, all_coins)
    print(f'  {len(all_coins)} coins, btc_atr_ratio len={len(market_context.get("btc_atr_ratio", []))}, '
          f'breadth_up len={len(market_context.get("breadth_up", []))} in {time.time()-t_mc:.1f}s')

    # --- Select hypotheses ---
    if args.hypothesis:
        hypotheses = [get_hypothesis_s5(h) for h in args.hypothesis]
        print(f'[Hypotheses] Testing {len(hypotheses)} selected: {args.hypothesis}')
    else:
        hypotheses = get_all_hypotheses_s5()
        total_variants = sum(len(h.param_grid) for h in hypotheses)
        print(f'[Hypotheses] Testing all {len(hypotheses)} hypotheses '
              f'({total_variants} configs)')

    # --- Run screening ---
    results = screen_all_s5(
        data=data,
        tier_coins=tier_coins,
        tier_indicators=tier_indicators,
        market_context=market_context,
        hypotheses=hypotheses,
        verbose=not args.quiet,
    )

    elapsed = time.time() - t0

    # --- Build meta ---
    meta = {
        'sprint': 5,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'timeframe': args.timeframe,
        't1_coins': len(tier_coins['tier1']),
        't2_coins': len(tier_coins['tier2']),
        'total_configs': len(results),
        'runtime_s': elapsed,
        'hypotheses_tested': [h.id for h in hypotheses],
        'feature_coverage': feature_coverage,
        'kill_gates': {
            'K1': 'exp_per_week > $0',
            'K2': 'trades_per_week >= 7',
            'K3': 'be_trade_ratio < 40%',
        },
    }

    # --- Write reports ---
    reports_dir = ROOT / 'reports' / 'hf' / 'screening'
    reports_dir.mkdir(parents=True, exist_ok=True)

    json_path = write_screen_json(results, meta, path=reports_dir / 'screen_s5_001.json')
    md_path = write_screen_s5_md(results, meta, path=reports_dir / 'screen_s5_001.md')

    # --- Print summary ---
    print(f'\n=== Sprint 5 Results ===')
    survivors = get_survivors_s5(results)
    print(f'Total configs: {len(results)}')
    print(f'Survivors (passed K1+K2+K3): {len(survivors)}')

    if survivors:
        print(f'\nTop survivors:')
        for i, s in enumerate(survivors[:5], 1):
            print(f'  {i}. {s["hypothesis_id"]} v{s["variant_idx"]}: '
                  f'exp/w=${s["exp_per_week"]:.2f} '
                  f'tr/w={s["trades_per_week"]:.1f} '
                  f'BE={s["be_trade_ratio"]:.1f}% '
                  f'PF={s["pf"]:.2f} '
                  f'stress=${s["stress_2x_pnl"]:.2f} '
                  f'score={s["score"]:.1f}')
    else:
        print('\nNO SURVIVORS -- all configs failed KILL gates.')

    # Gate pass summary
    print(f'\nGate pass rates:')
    gate_keys = ['K1_exp_week', 'K2_trades_week', 'K3_be_ratio',
                 'S3_pf', 'S4_wf', 'S5_concentration']
    for gk in gate_keys:
        n_pass = sum(1 for r in results if r.get('gate_results', {}).get(gk, False))
        print(f'  {gk}: {n_pass}/{len(results)} '
              f'({n_pass/len(results)*100:.0f}%)' if results else f'  {gk}: 0/0')

    print(f'\nReports:')
    print(f'  JSON: {json_path}')
    print(f'  MD:   {md_path}')
    print(f'Runtime: {elapsed:.1f}s')


if __name__ == '__main__':
    main()

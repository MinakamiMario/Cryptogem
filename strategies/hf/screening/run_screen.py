#!/usr/bin/env python3
"""
Sprint 4 — Layer 1 Hypothesis Screening CLI
=============================================
Loads 1H candle cache, runs all 15 hypotheses × ≤6 variants through
Layer 1 screening gates, and writes JSON + Markdown reports.

Usage:
    python -m strategies.hf.screening.run_screen
    python -m strategies.hf.screening.run_screen --timeframe 1h
    python -m strategies.hf.screening.run_screen --hypothesis H01 H05
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
from strategies.hf.screening.hypotheses import get_all_hypotheses, get_hypothesis
from strategies.hf.screening.screener import screen_all, get_survivors
from strategies.hf.screening.report import write_screen_json, write_screen_md


# ============================================================
# Data Loading
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
    # (universe_tiering_001.json uses this format)
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
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Sprint 4 Layer 1 Screening')
    parser.add_argument('--timeframe', default='1h', help='Timeframe (default: 1h)')
    parser.add_argument('--hypothesis', nargs='*', default=None,
                        help='Specific hypothesis IDs to test (e.g., H01 H05)')
    parser.add_argument('--quiet', action='store_true', help='Suppress per-variant output')
    args = parser.parse_args()

    print(f'=== Sprint 4 Layer 1 Screening ({args.timeframe}) ===')
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

    # --- Precompute indicators per tier ---
    print('[Indicators] Precomputing base indicators...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    # --- Select hypotheses ---
    if args.hypothesis:
        hypotheses = [get_hypothesis(h) for h in args.hypothesis]
        print(f'[Hypotheses] Testing {len(hypotheses)} selected: {args.hypothesis}')
    else:
        hypotheses = get_all_hypotheses()
        total_variants = sum(len(h.param_grid) for h in hypotheses)
        print(f'[Hypotheses] Testing all {len(hypotheses)} hypotheses ({total_variants} configs)')

    # --- Run screening ---
    results = screen_all(
        data=data,
        tier_coins=tier_coins,
        tier_indicators=tier_indicators,
        hypotheses=hypotheses,
        verbose=not args.quiet,
    )

    elapsed = time.time() - t0

    # --- Build meta ---
    meta = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'timeframe': args.timeframe,
        't1_coins': len(tier_coins['tier1']),
        't2_coins': len(tier_coins['tier2']),
        'total_configs': len(results),
        'runtime_s': elapsed,
        'hypotheses_tested': [h.id for h in hypotheses],
    }

    # --- Write reports ---
    json_path = write_screen_json(results, meta)
    md_path = write_screen_md(results, meta)

    print(f'\n=== Results ===')
    survivors = get_survivors(results)
    print(f'Total configs: {len(results)}')
    print(f'Survivors (passed S1+S2): {len(survivors)}')
    if survivors:
        print(f'\nTop survivors:')
        for i, s in enumerate(survivors[:5], 1):
            print(f'  {i}. {s["hypothesis_id"]} v{s["variant_idx"]}: '
                  f'exp=${s["expectancy"]:.2f} PF={s["pf"]:.2f} '
                  f'trades={s["trades"]} score={s["score"]:.1f}')
    else:
        print('\nNO SURVIVORS — all configs failed KILL gates.')

    print(f'\nReports:')
    print(f'  JSON: {json_path}')
    print(f'  MD:   {md_path}')
    print(f'Runtime: {elapsed:.1f}s')


if __name__ == '__main__':
    main()

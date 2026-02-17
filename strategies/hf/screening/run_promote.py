#!/usr/bin/env python3
"""
Sprint 4 — Layer 2 Promotion CLI
=================================
Loads Layer 1 screening results, picks top survivors, and runs
Layer 2 promotion gates.

Usage:
    python -m strategies.hf.screening.run_promote
    python -m strategies.hf.screening.run_promote --max-candidates 3
    python -m strategies.hf.screening.run_promote --results reports/hf/screening/screen_001.json
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
from strategies.hf.screening.promoter import promote_all
from strategies.hf.screening.report import write_promote_json, write_promote_md


# ============================================================
# Data Loading (reuse from run_screen)
# ============================================================

def load_candle_cache(timeframe: str = '1h') -> dict:
    """Load candle cache from data directory."""
    cache_path = ROOT / 'data' / f'candle_cache_{timeframe}.json'
    if not cache_path.exists():
        raise FileNotFoundError(f'Cache not found: {cache_path}')
    print(f'[Load] Reading {cache_path.name}...')
    with open(cache_path) as f:
        data = json.load(f)
    coins_data = {k: v for k, v in data.items() if not k.startswith('_')}
    print(f'[Load] {len(coins_data)} coins loaded')
    return coins_data


def load_universe_tiering() -> dict:
    """Load universe tiering from reports."""
    tiering_path = ROOT / 'reports' / 'hf' / 'universe_tiering_001.json'
    if not tiering_path.exists():
        raise FileNotFoundError(f'Tiering not found: {tiering_path}')
    with open(tiering_path) as f:
        return json.load(f)


def build_tier_coins(tiering: dict, available_coins: set) -> dict:
    """Build tier -> coin list mapping."""
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


def load_screen_results(path: Path) -> list:
    """Load Layer 1 screening results from JSON."""
    if not path.exists():
        raise FileNotFoundError(f'Screening results not found: {path}')
    with open(path) as f:
        data = json.load(f)
    return data.get('results', [])


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Sprint 4 Layer 2 Promotion')
    parser.add_argument('--timeframe', default='1h', help='Timeframe (default: 1h)')
    parser.add_argument('--results', default=None,
                        help='Path to Layer 1 JSON results (default: reports/hf/screening/screen_001.json)')
    parser.add_argument('--max-candidates', type=int, default=2,
                        help='Max candidates to promote (default: 2)')
    parser.add_argument('--quiet', action='store_true', help='Suppress verbose output')
    args = parser.parse_args()

    print(f'=== Sprint 4 Layer 2 Promotion ({args.timeframe}) ===')
    print(f'Started: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    t0 = time.time()

    # --- Load Layer 1 results ---
    if args.results:
        results_path = Path(args.results)
    else:
        results_path = ROOT / 'reports' / 'hf' / 'screening' / 'screen_001.json'

    all_results = load_screen_results(results_path)
    print(f'[Results] {len(all_results)} configs loaded from {results_path.name}')

    # --- Filter survivors ---
    survivors = [r for r in all_results if not r.get('killed', True)]
    survivors.sort(key=lambda x: x.get('score', 0), reverse=True)
    print(f'[Survivors] {len(survivors)} configs passed Layer 1 KILL gates')

    if not survivors:
        print('\n[HALT] No survivors to promote. Layer 2 skipped.')
        print('All hypotheses failed at Layer 1. See screen_001.md for details.')
        sys.exit(0)

    # --- Load candle data ---
    data = load_candle_cache(args.timeframe)
    available_coins = set(data.keys())

    tiering = load_universe_tiering()
    tier_coins = build_tier_coins(tiering, available_coins)

    print(f'[Universe] T1: {len(tier_coins["tier1"])} coins, '
          f'T2: {len(tier_coins["tier2"])} coins')

    # --- Precompute indicators ---
    print('[Indicators] Precomputing base indicators...')
    tier_indicators = {}
    for tier_name, coins in tier_coins.items():
        if coins:
            t_ind = time.time()
            tier_indicators[tier_name] = precompute_base_indicators(data, coins)
            print(f'  {tier_name}: {len(coins)} coins in {time.time()-t_ind:.1f}s')

    # --- Run promotion ---
    print(f'\n[Promote] Running Layer 2 on top {args.max_candidates} survivors...')
    results = promote_all(
        survivors=survivors,
        data=data,
        tier_coins=tier_coins,
        tier_indicators=tier_indicators,
        max_candidates=args.max_candidates,
        verbose=not args.quiet,
    )

    elapsed = time.time() - t0

    # --- Build meta ---
    meta = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'timeframe': args.timeframe,
        'layer1_results': results_path.name,
        'candidates': len(results),
        'runtime_s': elapsed,
    }

    # --- Write reports ---
    json_path = write_promote_json(results, meta)
    md_path = write_promote_md(results, meta)

    # --- Summary ---
    promoted = [r for r in results if r.get('promoted', False)]
    print(f'\n=== Layer 2 Results ===')
    print(f'Candidates: {len(results)}')
    print(f'Promoted: {len(promoted)}')

    if promoted:
        for r in promoted:
            print(f'  ✅ {r["hypothesis_id"]} ({r["name"]})')
        print(f'\nThese configs are ready for 15m build / live testing.')
    else:
        print(f'\n  ❌ No candidates promoted.')
        print(f'  All survivors failed Layer 2 hardening gates.')

    print(f'\nReports:')
    print(f'  JSON: {json_path}')
    print(f'  MD:   {md_path}')
    print(f'Runtime: {elapsed:.1f}s')


if __name__ == '__main__':
    main()

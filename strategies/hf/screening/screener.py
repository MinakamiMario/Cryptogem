"""
Layer 1 Screening Pipeline
===========================
Runs all hypotheses × variants through the backtest harness,
applies Layer 1 gates, and ranks survivors.

Gate spec: strategies/hf/GATES_SCREENING.md
"""
import time
import math
from typing import Optional

from strategies.hf.screening.harness import (
    run_backtest, walk_forward, precompute_base_indicators, BacktestResult,
)
from strategies.hf.screening.hypotheses import get_all_hypotheses, Hypothesis


# ============================================================
# Layer 1 Gate Thresholds
# ============================================================
GATE_S1_MIN_TRADES = 60        # KILL gate
GATE_S1B_THROUGHPUT = 120      # Soft bonus
GATE_S2_EXPECTANCY = 0.0       # KILL gate: > $0
GATE_S3_PF = 1.1               # Soft
GATE_S4_WF_POSITIVE = 2        # Soft: >= 2/5 folds positive
GATE_S4_WF_FOLDS = 5
GATE_S5_TOP1_PCT = 40.0        # Soft: < 40%
GATE_S5_TOP3_PCT = 70.0        # Soft: < 70%

# Tier fees
TIER_FEES = {
    'tier1': 0.0031,  # 31 bps
    'tier2': 0.0056,  # 56 bps
}


def screen_hypothesis(
    hypothesis: Hypothesis,
    data: dict,
    tier_coins: dict,        # {'tier1': [coins], 'tier2': [coins]}
    tier_indicators: dict,   # {'tier1': {indicators}, 'tier2': {indicators}}
    verbose: bool = False,
) -> list:
    """
    Screen all variants of a hypothesis through Layer 1 gates.

    Returns list of result dicts, one per variant.
    """
    results = []

    for var_idx, params in enumerate(hypothesis.param_grid):
        result = _screen_one_config(
            hypothesis=hypothesis,
            params=params,
            variant_idx=var_idx,
            data=data,
            tier_coins=tier_coins,
            tier_indicators=tier_indicators,
        )
        results.append(result)

        if verbose:
            status = 'KILL' if result['killed'] else 'PASS'
            print(f'  {hypothesis.id} v{var_idx}: {status} '
                  f'trades={result["trades"]} exp=${result.get("expectancy", 0):.2f} '
                  f'PF={result.get("pf", 0):.2f}')

    return results


def screen_all(
    data: dict,
    tier_coins: dict,
    tier_indicators: dict,
    hypotheses: Optional[list] = None,
    verbose: bool = True,
) -> list:
    """
    Run full Layer 1 screening across all hypotheses.

    Returns list of all result dicts.
    """
    if hypotheses is None:
        hypotheses = get_all_hypotheses()

    all_results = []
    t0 = time.time()

    for hyp in hypotheses:
        if verbose:
            print(f'\n[Screen] {hyp.id} {hyp.name} ({len(hyp.param_grid)} variants)')

        hyp_results = screen_hypothesis(
            hypothesis=hyp,
            data=data,
            tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            verbose=verbose,
        )
        all_results.extend(hyp_results)

    elapsed = time.time() - t0
    if verbose:
        survivors = sum(1 for r in all_results if not r.get('killed', True))
        print(f'\n[Screen] Done: {len(all_results)} configs, '
              f'{survivors} survivors, {elapsed:.1f}s')

    return all_results


# ============================================================
# Internal: Screen One Config
# ============================================================

def _screen_one_config(
    hypothesis: Hypothesis,
    params: dict,
    variant_idx: int,
    data: dict,
    tier_coins: dict,
    tier_indicators: dict,
) -> dict:
    """Screen a single hypothesis + params combination."""

    # --- Run per-tier backtests ---
    tier_results = {}
    all_trades = []
    total_pnl = 0.0

    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = TIER_FEES.get(tier_name, 0.0031)
        indicators = tier_indicators.get(tier_name, {})

        bt = run_backtest(
            data=data,
            coins=coins,
            signal_fn=hypothesis.signal_fn,
            params=params,
            indicators=indicators,
            fee=fee,
        )

        tier_results[tier_name] = {
            'trades': bt.trades,
            'pnl': bt.pnl,
            'pf': bt.pf,
            'wr': bt.wr,
            'dd': bt.dd,
        }
        all_trades.extend(bt.trade_list)
        total_pnl += bt.pnl

    # --- Composite metrics ---
    n_trades = len(all_trades)
    composite_pnl = total_pnl
    expectancy = composite_pnl / n_trades if n_trades > 0 else 0.0
    wins = [t for t in all_trades if t['pnl'] > 0]
    losses = [t for t in all_trades if t['pnl'] <= 0]
    wr = len(wins) / n_trades * 100 if n_trades > 0 else 0.0
    tw = sum(t['pnl'] for t in wins)
    tl = abs(sum(t['pnl'] for t in losses))
    pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)

    # Max drawdown: use worst tier DD as approximation
    dd = max((tr.get('dd', 0) for tr in tier_results.values()), default=0)

    # Concentration: top1 and top3 coin share of total P&L
    top1_pct, top3_pct = _calc_concentration(all_trades)

    # --- Walk-forward (combined universe) ---
    # Use tier1 coins + fee for WF (simplification: run on tier1 only for speed)
    # If tier1 has coins, use those; otherwise tier2
    wf_tier = 'tier1' if tier_coins.get('tier1') else 'tier2'
    wf_coins = tier_coins.get(wf_tier, [])
    wf_indicators = tier_indicators.get(wf_tier, {})
    wf_fee = TIER_FEES.get(wf_tier, 0.0031)

    wf_folds = []
    wf_positive = 0
    if wf_coins and n_trades >= 10:  # only run WF if enough base trades
        wf_results = walk_forward(
            data=data,
            coins=wf_coins,
            signal_fn=hypothesis.signal_fn,
            params=params,
            indicators=wf_indicators,
            n_folds=GATE_S4_WF_FOLDS,
            fee=wf_fee,
        )
        for fold_bt in wf_results:
            fold_info = {
                'trades': fold_bt.trades,
                'pnl': fold_bt.pnl,
                'pf': fold_bt.pf,
                'wr': fold_bt.wr,
            }
            wf_folds.append(fold_info)
            if fold_bt.pnl > 0:
                wf_positive += 1

    # --- Apply Gates ---
    gate_results = {
        'S1': n_trades >= GATE_S1_MIN_TRADES,
        'S1b': n_trades >= GATE_S1B_THROUGHPUT,
        'S2': expectancy > GATE_S2_EXPECTANCY,
        'S3': pf >= GATE_S3_PF,
        'S4': wf_positive >= GATE_S4_WF_POSITIVE,
        'S5': top1_pct < GATE_S5_TOP1_PCT and top3_pct < GATE_S5_TOP3_PCT,
    }

    # KILL if S1 or S2 fails
    killed = not gate_results['S1'] or not gate_results['S2']

    # --- Score (secondary to gates) ---
    score = 0.0
    if not killed and pf > 1.0:
        score = expectancy * math.sqrt(max(n_trades, 1)) * (pf - 1.0)
        if gate_results['S1b']:
            score *= 1.20  # +20% throughput bonus

    return {
        'hypothesis_id': hypothesis.id,
        'name': hypothesis.name,
        'category': hypothesis.category,
        'variant_idx': variant_idx,
        'params': params,
        'trades': n_trades,
        'pnl': composite_pnl,
        'pf': pf,
        'wr': wr,
        'dd': dd,
        'expectancy': expectancy,
        'wf_positive': wf_positive,
        'wf_folds': len(wf_folds),
        'wf_detail': wf_folds,
        'top1_pct': top1_pct,
        'top3_pct': top3_pct,
        'gate_results': gate_results,
        'killed': killed,
        'score': score,
        'tier_results': tier_results,
    }


def _calc_concentration(trades: list) -> tuple:
    """
    Calculate top-1 and top-3 coin concentration of P&L.

    Returns (top1_pct, top3_pct) as percentages.
    Uses positive profit attribution (not abs total pnl).
    """
    if not trades:
        return 0.0, 0.0

    # Group P&L by coin
    coin_pnl = {}
    for t in trades:
        pair = t.get('pair', 'unknown')
        coin_pnl[pair] = coin_pnl.get(pair, 0.0) + t['pnl']

    # Use total positive P&L as denominator (not abs total)
    total_positive = sum(max(0, v) for v in coin_pnl.values())
    if total_positive <= 0:
        return 0.0, 0.0

    # Sort by absolute contribution
    sorted_coins = sorted(coin_pnl.values(), key=abs, reverse=True)

    top1 = abs(sorted_coins[0]) / total_positive * 100 if len(sorted_coins) >= 1 else 0
    top3_sum = sum(abs(v) for v in sorted_coins[:3])
    top3 = top3_sum / total_positive * 100 if len(sorted_coins) >= 3 else top1

    return top1, top3


def get_survivors(results: list) -> list:
    """Get surviving configs sorted by score (descending)."""
    survivors = [r for r in results if not r.get('killed', True)]
    return sorted(survivors, key=lambda x: x.get('score', 0), reverse=True)

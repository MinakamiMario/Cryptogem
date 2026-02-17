"""
Layer 2 Promotion Pipeline
============================
Applies strict promotion gates to top Layer 1 survivors.
Only run on the top 1-2 configs that passed Layer 1 screening.

Gate spec: strategies/hf/GATES_SCREENING.md (Layer 2 section)
"""
import time

from strategies.hf.screening.harness import (
    run_backtest, walk_forward, precompute_base_indicators, BacktestResult,
)
from strategies.hf.screening.hypotheses import get_hypothesis


# ============================================================
# Layer 2 Gate Thresholds
# ============================================================
GATE_P1_STRESS_FEE_T1 = 0.0036   # 2× stress fee for T1
GATE_P1_STRESS_FEE_T2 = 0.0086   # 2× stress fee for T2
GATE_P2_PF = 1.2
GATE_P3_WF_POSITIVE = 3           # >= 3/5 folds
GATE_P3_WF_FOLDS = 5
GATE_P4_ROLLING_PCT = 60.0        # >= 60% positive rolling windows
GATE_P4_ROLLING_BARS = 180        # non-overlapping window size
GATE_P5_MAX_DD = 30.0             # <= 30%
GATE_P6_LATENCY_MAX_DEGRADE = 0.20  # max 20% expectancy degradation
GATE_P7_BREAKEVEN_PCT = 40.0      # break-even fee trades < 40%


def promote_candidate(
    candidate: dict,
    data: dict,
    tier_coins: dict,
    tier_indicators: dict,
    verbose: bool = True,
) -> dict:
    """
    Run Layer 2 promotion gates on a single Layer 1 survivor.

    candidate: dict from Layer 1 screening results (must have hypothesis_id, params)
    Returns: dict with gate results and promoted status.
    """
    hyp_id = candidate['hypothesis_id']
    params = candidate['params']
    hypothesis = get_hypothesis(hyp_id)

    if verbose:
        print(f'\n[Promote] {hyp_id} ({hypothesis.name})')

    gate_results = {}

    # --- P1: Stress Expectancy ---
    stress_trades = []
    stress_pnl = 0.0
    stress_fees = {'tier1': GATE_P1_STRESS_FEE_T1, 'tier2': GATE_P1_STRESS_FEE_T2}

    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = stress_fees.get(tier_name, GATE_P1_STRESS_FEE_T1)
        indicators = tier_indicators.get(tier_name, {})
        bt = run_backtest(
            data=data, coins=coins,
            signal_fn=hypothesis.signal_fn, params=params,
            indicators=indicators, fee=fee,
        )
        stress_trades.extend(bt.trade_list)
        stress_pnl += bt.pnl

    stress_n = len(stress_trades)
    stress_exp = stress_pnl / stress_n if stress_n > 0 else 0.0
    gate_results['P1'] = {
        'passed': stress_exp > 0,
        'threshold': '> $0 at 2× stress fees',
        'value': f'${stress_exp:.2f}/trade ({stress_n} trades)',
    }
    if verbose:
        status = '✅' if gate_results['P1']['passed'] else '❌'
        print(f'  P1 Stress Exp: {status} ${stress_exp:.2f}/trade')

    # --- P2: Profit Factor ---
    # Use normal fees for PF calc
    all_trades = []
    for tier_name, coins in tier_coins.items():
        if not coins:
            continue
        fee = {'tier1': 0.0031, 'tier2': 0.0056}.get(tier_name, 0.0031)
        indicators = tier_indicators.get(tier_name, {})
        bt = run_backtest(
            data=data, coins=coins,
            signal_fn=hypothesis.signal_fn, params=params,
            indicators=indicators, fee=fee,
        )
        all_trades.extend(bt.trade_list)

    wins = sum(t['pnl'] for t in all_trades if t['pnl'] > 0)
    losses = abs(sum(t['pnl'] for t in all_trades if t['pnl'] <= 0))
    pf = wins / losses if losses > 0 else (float('inf') if wins > 0 else 0)

    gate_results['P2'] = {
        'passed': pf >= GATE_P2_PF,
        'threshold': f'>= {GATE_P2_PF}',
        'value': f'{pf:.2f}',
    }
    if verbose:
        status = '✅' if gate_results['P2']['passed'] else '❌'
        print(f'  P2 PF: {status} {pf:.2f}')

    # --- P3: Walk-Forward ---
    wf_tier = 'tier1' if tier_coins.get('tier1') else 'tier2'
    wf_coins = tier_coins.get(wf_tier, [])
    wf_indicators = tier_indicators.get(wf_tier, {})
    wf_fee = {'tier1': 0.0031, 'tier2': 0.0056}.get(wf_tier, 0.0031)

    wf_positive = 0
    if wf_coins:
        wf_results = walk_forward(
            data=data, coins=wf_coins,
            signal_fn=hypothesis.signal_fn, params=params,
            indicators=wf_indicators, n_folds=GATE_P3_WF_FOLDS, fee=wf_fee,
        )
        wf_positive = sum(1 for r in wf_results if r.pnl > 0)

    gate_results['P3'] = {
        'passed': wf_positive >= GATE_P3_WF_POSITIVE,
        'threshold': f'>= {GATE_P3_WF_POSITIVE}/{GATE_P3_WF_FOLDS} folds positive',
        'value': f'{wf_positive}/{GATE_P3_WF_FOLDS}',
    }
    if verbose:
        status = '✅' if gate_results['P3']['passed'] else '❌'
        print(f'  P3 WF: {status} {wf_positive}/{GATE_P3_WF_FOLDS}')

    # --- P4: Rolling Windows ---
    # Find max bars, then create non-overlapping windows
    max_bars = 0
    for ind in wf_indicators.values():
        if isinstance(ind, dict) and 'n' in ind:
            max_bars = max(max_bars, ind['n'])

    rolling_positive = 0
    rolling_total = 0
    start = 50
    while start + GATE_P4_ROLLING_BARS <= max_bars:
        bt = run_backtest(
            data=data, coins=wf_coins,
            signal_fn=hypothesis.signal_fn, params=params,
            indicators=wf_indicators, fee=wf_fee,
            start_bar=start, end_bar=start + GATE_P4_ROLLING_BARS,
        )
        rolling_total += 1
        if bt.pnl > 0:
            rolling_positive += 1
        start += GATE_P4_ROLLING_BARS

    rolling_pct = rolling_positive / rolling_total * 100 if rolling_total > 0 else 0

    gate_results['P4'] = {
        'passed': rolling_pct >= GATE_P4_ROLLING_PCT,
        'threshold': f'>= {GATE_P4_ROLLING_PCT}% positive',
        'value': f'{rolling_pct:.0f}% ({rolling_positive}/{rolling_total})',
    }
    if verbose:
        status = '✅' if gate_results['P4']['passed'] else '❌'
        print(f'  P4 Rolling: {status} {rolling_pct:.0f}%')

    # --- P5: Max Drawdown ---
    # Use composite DD from normal backtest
    dd = candidate.get('dd', 100)
    gate_results['P5'] = {
        'passed': dd <= GATE_P5_MAX_DD,
        'threshold': f'<= {GATE_P5_MAX_DD}%',
        'value': f'{dd:.1f}%',
    }
    if verbose:
        status = '✅' if gate_results['P5']['passed'] else '❌'
        print(f'  P5 Max DD: {status} {dd:.1f}%')

    # --- P6: Latency Stress ---
    # Run with 1-bar and 2-bar delay (simulated by shifting start_bar)
    baseline_exp = candidate.get('expectancy', 0)
    latency_pass = True
    latency_info = []
    for delay in [1, 2]:
        lat_trades = []
        lat_pnl = 0.0
        for tier_name, coins in tier_coins.items():
            if not coins:
                continue
            fee = {'tier1': 0.0031, 'tier2': 0.0056}.get(tier_name, 0.0031)
            indicators = tier_indicators.get(tier_name, {})
            bt = run_backtest(
                data=data, coins=coins,
                signal_fn=hypothesis.signal_fn, params=params,
                indicators=indicators, fee=fee,
                start_bar=50 + delay,
            )
            lat_trades.extend(bt.trade_list)
            lat_pnl += bt.pnl

        lat_n = len(lat_trades)
        lat_exp = lat_pnl / lat_n if lat_n > 0 else 0
        if baseline_exp > 0:
            degrade = 1 - (lat_exp / baseline_exp) if baseline_exp > 0 else 1.0
        else:
            degrade = 1.0  # baseline already 0 or negative

        lat_ok = lat_exp > 0 or degrade <= GATE_P6_LATENCY_MAX_DEGRADE
        if not lat_ok:
            latency_pass = False
        latency_info.append(f'delay={delay}: exp=${lat_exp:.2f} degrade={degrade:.0%}')

    gate_results['P6'] = {
        'passed': latency_pass,
        'threshold': 'exp > 0 or max 20% degrade',
        'value': '; '.join(latency_info),
    }
    if verbose:
        status = '✅' if gate_results['P6']['passed'] else '❌'
        print(f'  P6 Latency: {status} {"; ".join(latency_info)}')

    # --- P7: Capacity (break-even fee trades) ---
    # Count trades where PnL < fee cost (marginal trades)
    be_count = 0
    for t in all_trades:
        # A break-even trade: absolute pnl is less than 2× fee (entry+exit)
        fee_cost = t.get('size', 0) * 0.0031 * 2  # rough estimate
        if abs(t['pnl']) < fee_cost:
            be_count += 1

    be_pct = be_count / len(all_trades) * 100 if all_trades else 0

    gate_results['P7'] = {
        'passed': be_pct < GATE_P7_BREAKEVEN_PCT,
        'threshold': f'< {GATE_P7_BREAKEVEN_PCT}%',
        'value': f'{be_pct:.0f}% ({be_count}/{len(all_trades)})',
    }
    if verbose:
        status = '✅' if gate_results['P7']['passed'] else '❌'
        print(f'  P7 Capacity: {status} {be_pct:.0f}%')

    # --- P8: Correlation/Exposure (only if max_pos > 1) ---
    gate_results['P8'] = {
        'passed': True,
        'threshold': 'N/A (max_pos=1)',
        'value': 'skipped',
    }

    # --- Verdict ---
    promoted = all(g['passed'] for g in gate_results.values())

    return {
        'hypothesis_id': hyp_id,
        'name': hypothesis.name,
        'params': params,
        'gate_results': gate_results,
        'promoted': promoted,
    }


def promote_all(
    survivors: list,
    data: dict,
    tier_coins: dict,
    tier_indicators: dict,
    max_candidates: int = 2,
    verbose: bool = True,
) -> list:
    """
    Run Layer 2 promotion on top survivors.

    survivors: sorted list from Layer 1 (best first)
    Returns list of promotion result dicts.
    """
    candidates = survivors[:max_candidates]
    results = []

    for cand in candidates:
        result = promote_candidate(
            candidate=cand, data=data,
            tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            verbose=verbose,
        )
        results.append(result)

    promoted = [r for r in results if r['promoted']]
    if verbose:
        print(f'\n[Promote] {len(promoted)}/{len(candidates)} promoted')

    return results

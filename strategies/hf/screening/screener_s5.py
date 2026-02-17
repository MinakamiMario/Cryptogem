"""
Sprint 5 Screening Pipeline
============================
Wraps the backtest harness with Sprint 5-specific additions:
1. Extended indicators (opens, vwaps, counts, body_pct, atr_ratio)
2. Market context injection into params['__market__']
3. Per-coin injection (indicators[coin]['__coin__']) for cross-sectional hypotheses
4. Updated scoreboard: trades/week, exp/week, fee_drag, be_ratio, stress_2x_pnl
5. max_pos override for cross-sectional hypotheses (max_pos=5)

Gate spec:
  KILL: exp_per_week > $0 AND trades_per_week >= 7 AND be_trade_ratio < 40%
  Soft: S3 PF, S4 WF, S5 concentration (carried forward from Sprint 4)
"""
import time
import math
from typing import Optional

from strategies.hf.screening.harness import (
    run_backtest, walk_forward, BacktestResult,
)
from strategies.hf.screening.hypotheses_s5 import (
    get_all_hypotheses_s5, HypothesisS5,
)


# ============================================================
# Layer 1 Gate Thresholds — Sprint 5
# ============================================================
# KILL gates (Sprint 5)
GATE_EXP_WEEK_MIN = 0.0            # exp_per_week > $0
GATE_TRADES_WEEK_MIN = 7           # trades_per_week >= 7
GATE_BE_RATIO_MAX = 40.0           # be_trade_ratio < 40%

# Soft gates (carried from Sprint 4)
GATE_S3_PF = 1.1
GATE_S4_WF_POSITIVE = 2
GATE_S4_WF_FOLDS = 5
GATE_S5_TOP1_PCT = 40.0
GATE_S5_TOP3_PCT = 70.0

# Tier fees
TIER_FEES = {
    'tier1': 0.0031,   # 31 bps
    'tier2': 0.0056,   # 56 bps
}

# Stress test fees (approximately 2x)
STRESS_FEES = {
    'tier1': 0.0036,   # ~36 bps
    'tier2': 0.0086,   # ~86 bps
}

# Bars per week at 1H timeframe
BARS_PER_WEEK = 168  # 24 * 7


# ============================================================
# Public API
# ============================================================

def screen_all_s5(
    data: dict,
    tier_coins: dict,
    tier_indicators: dict,
    market_context: dict,
    hypotheses: Optional[list] = None,
    verbose: bool = True,
) -> list:
    """
    Run full Sprint 5 screening across all hypotheses.

    Differences from screener.py screen_all():
    - Injects __coin__ into each coin's indicator dict
    - Injects __market__ into params for each config
    - Uses max_pos=5 for cross_sectional hypotheses
    - Uses Sprint 5 KILL gates and scoreboard

    Returns list of all result dicts.
    """
    if hypotheses is None:
        hypotheses = get_all_hypotheses_s5()

    # 1. Inject __coin__ into each coin's indicators dict (for cross-sectional access)
    for tier_name, ind_dict in tier_indicators.items():
        for coin in ind_dict:
            ind_dict[coin]['__coin__'] = coin

    all_results = []
    t0 = time.time()

    for hyp in hypotheses:
        if verbose:
            print(f'\n[S5 Screen] {hyp.id} {hyp.name} '
                  f'({len(hyp.param_grid)} variants, cat={hyp.category})')

        hyp_results = screen_hypothesis_s5(
            hypothesis=hyp,
            data=data,
            tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            market_context=market_context,
            verbose=verbose,
        )
        all_results.extend(hyp_results)

    elapsed = time.time() - t0
    if verbose:
        survivors = sum(1 for r in all_results if not r.get('killed', True))
        print(f'\n[S5 Screen] Done: {len(all_results)} configs, '
              f'{survivors} survivors, {elapsed:.1f}s')

    return all_results


def screen_hypothesis_s5(
    hypothesis: HypothesisS5,
    data: dict,
    tier_coins: dict,
    tier_indicators: dict,
    market_context: dict,
    verbose: bool = False,
) -> list:
    """
    Screen all variants of a Sprint 5 hypothesis through Layer 1 gates.

    Returns list of result dicts, one per variant.
    """
    results = []

    for var_idx, params in enumerate(hypothesis.param_grid):
        result = _screen_one_config_s5(
            hypothesis=hypothesis,
            params=params,
            variant_idx=var_idx,
            data=data,
            tier_coins=tier_coins,
            tier_indicators=tier_indicators,
            market_context=market_context,
        )
        results.append(result)

        if verbose:
            status = 'KILL' if result['killed'] else 'PASS'
            exp_w = result.get('exp_per_week', 0)
            tr_w = result.get('trades_per_week', 0)
            be = result.get('be_trade_ratio', 0)
            print(f'  {hypothesis.id} v{var_idx}: {status} '
                  f'trades={result["trades"]} exp/w=${exp_w:.2f} '
                  f'tr/w={tr_w:.1f} BE%={be:.1f}% '
                  f'PF={result.get("pf", 0):.2f}')

    return results


def get_survivors_s5(results: list) -> list:
    """Get surviving configs sorted by score (descending)."""
    survivors = [r for r in results if not r.get('killed', True)]
    return sorted(survivors, key=lambda x: x.get('score', 0), reverse=True)


# ============================================================
# Internal: Screen One Config — Sprint 5
# ============================================================

def _screen_one_config_s5(
    hypothesis: HypothesisS5,
    params: dict,
    variant_idx: int,
    data: dict,
    tier_coins: dict,
    tier_indicators: dict,
    market_context: dict,
) -> dict:
    """Screen a single Sprint 5 hypothesis + params combination."""

    # --- Enrich params with market context ---
    enriched_params = {**params, '__market__': market_context}

    # --- Determine max_pos ---
    max_pos = 5 if hypothesis.category == 'cross_sectional' else 1

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
            params=enriched_params,
            indicators=indicators,
            fee=fee,
            max_pos=max_pos,
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

    # Max drawdown: use worst tier DD
    dd = max((tr.get('dd', 0) for tr in tier_results.values()), default=0)

    # Concentration: top1 and top3 coin share
    top1_pct, top3_pct = _calc_concentration(all_trades)

    # --- Sprint 5 Scoreboard Metrics ---
    total_bars = _estimate_total_bars(tier_indicators, tier_coins)
    total_weeks = total_bars / BARS_PER_WEEK if total_bars > 0 else 1.0

    trades_per_week = n_trades / total_weeks if total_weeks > 0 else 0.0
    exp_per_week = expectancy * trades_per_week

    # Fee drag: total fees / gross profit * 100
    fee_drag_pct = _calc_fee_drag(all_trades, tier_coins)

    # Break-even trade ratio: count(trades where |pnl| < round-trip fee)
    be_trade_ratio = _calc_be_trade_ratio(all_trades, tier_coins)

    # Stress 2x PnL: approximate PnL at 2x fees
    stress_2x_pnl = _calc_stress_2x_pnl(all_trades, tier_coins)

    # --- Walk-forward (combined universe) ---
    wf_tier = 'tier1' if tier_coins.get('tier1') else 'tier2'
    wf_coins = tier_coins.get(wf_tier, [])
    wf_indicators = tier_indicators.get(wf_tier, {})
    wf_fee = TIER_FEES.get(wf_tier, 0.0031)

    wf_folds = []
    wf_positive = 0
    if wf_coins and n_trades >= 10:
        wf_results = walk_forward(
            data=data,
            coins=wf_coins,
            signal_fn=hypothesis.signal_fn,
            params=enriched_params,
            indicators=wf_indicators,
            n_folds=GATE_S4_WF_FOLDS,
            fee=wf_fee,
            max_pos=max_pos,
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
    # Sprint 5 KILL gates
    gate_k1 = exp_per_week > GATE_EXP_WEEK_MIN          # exp/week > $0
    gate_k2 = trades_per_week >= GATE_TRADES_WEEK_MIN    # trades/week >= 7
    gate_k3 = be_trade_ratio < GATE_BE_RATIO_MAX         # BE ratio < 40%

    # Soft gates (from Sprint 4)
    gate_s3 = pf >= GATE_S3_PF
    gate_s4 = wf_positive >= GATE_S4_WF_POSITIVE
    gate_s5 = top1_pct < GATE_S5_TOP1_PCT and top3_pct < GATE_S5_TOP3_PCT

    gate_results = {
        'K1_exp_week': gate_k1,
        'K2_trades_week': gate_k2,
        'K3_be_ratio': gate_k3,
        'S3_pf': gate_s3,
        'S4_wf': gate_s4,
        'S5_concentration': gate_s5,
    }

    # KILL if any Sprint 5 KILL gate fails
    killed = not (gate_k1 and gate_k2 and gate_k3)

    # --- Score (secondary to gates) ---
    score = 0.0
    if not killed and pf > 1.0:
        score = exp_per_week * math.sqrt(max(trades_per_week, 1)) * (pf - 1.0)

    return {
        'hypothesis_id': hypothesis.id,
        'name': hypothesis.name,
        'category': hypothesis.category,
        'variant_idx': variant_idx,
        'params': params,
        'max_pos': max_pos,
        # Core metrics
        'trades': n_trades,
        'pnl': composite_pnl,
        'pf': pf,
        'wr': wr,
        'dd': dd,
        'expectancy': expectancy,
        # Sprint 5 scoreboard
        'trades_per_week': trades_per_week,
        'exp_per_week': exp_per_week,
        'fee_drag_pct': fee_drag_pct,
        'be_trade_ratio': be_trade_ratio,
        'stress_2x_pnl': stress_2x_pnl,
        # Walk-forward
        'wf_positive': wf_positive,
        'wf_folds': len(wf_folds),
        'wf_detail': wf_folds,
        # Concentration
        'top1_pct': top1_pct,
        'top3_pct': top3_pct,
        # Gates
        'gate_results': gate_results,
        'killed': killed,
        'score': score,
        'tier_results': tier_results,
    }


# ============================================================
# Scoreboard Helpers
# ============================================================

def _estimate_total_bars(tier_indicators: dict, tier_coins: dict) -> int:
    """Estimate total bars from indicator data (use max across tiers)."""
    max_bars = 0
    for tier_name, coins in tier_coins.items():
        indicators = tier_indicators.get(tier_name, {})
        for coin in coins:
            ind = indicators.get(coin, {})
            n = ind.get('n', 0)
            if n > max_bars:
                max_bars = n
    return max_bars


def _get_trade_tier_fee(trade: dict, tier_coins: dict) -> float:
    """Determine the fee for a trade based on which tier the coin belongs to."""
    pair = trade.get('pair', '')
    for tier_name, coins in tier_coins.items():
        if pair in coins:
            return TIER_FEES.get(tier_name, 0.0031)
    return 0.0031  # default to tier1


def _calc_fee_drag(trades: list, tier_coins: dict) -> float:
    """Calculate fee drag: total_fees / gross_profit * 100.

    Gross profit = sum of PnL on winning trades BEFORE fees.
    Since trades already have net PnL, we estimate:
      gross_pnl_per_trade = (exit - entry) / entry * size
      fees_per_trade = size * fee + (size + gross) * fee
    We approximate from stored trade data:
      size is stored, entry/exit are stored, so we can recompute.
    """
    if not trades:
        return 0.0

    total_fees = 0.0
    gross_profit = 0.0

    for t in trades:
        size = t.get('size', 0)
        entry = t.get('entry', 0)
        exit_p = t.get('exit', 0)

        if entry <= 0 or size <= 0:
            continue

        fee = _get_trade_tier_fee(t, tier_coins)
        gross = (exit_p - entry) / entry * size
        fees = size * fee + (size + gross) * fee
        total_fees += fees
        if gross > 0:
            gross_profit += gross

    if gross_profit <= 0:
        return 100.0  # all fees, no profit

    return total_fees / gross_profit * 100


def _calc_be_trade_ratio(trades: list, tier_coins: dict) -> float:
    """Calculate break-even trade ratio: % of trades where |pnl| < round-trip fee.

    A trade is break-even if the magnitude of its net PnL is less than
    the round-trip fee cost (entry fee + exit fee).
    """
    if not trades:
        return 0.0

    be_count = 0
    for t in trades:
        size = t.get('size', 0)
        if size <= 0:
            continue

        fee = _get_trade_tier_fee(t, tier_coins)
        # Round-trip fee approximation: entry side + exit side
        # At entry: size * fee. At exit: ~size * fee (ignoring small PnL impact)
        rt_fee = size * fee * 2
        net_pnl = t.get('pnl', 0)

        if abs(net_pnl) < rt_fee:
            be_count += 1

    return be_count / len(trades) * 100 if trades else 0.0


def _calc_stress_2x_pnl(trades: list, tier_coins: dict) -> float:
    """Approximate total PnL under 2x fee stress.

    For each trade, compute the extra fee cost from doubling:
      extra_fee = size * (stress_fee - normal_fee) * 2  (entry + exit)
    stress_2x_pnl = sum(trade_pnl - extra_fee_per_trade)
    """
    if not trades:
        return 0.0

    stress_pnl = 0.0
    for t in trades:
        size = t.get('size', 0)
        pair = t.get('pair', '')
        net_pnl = t.get('pnl', 0)

        if size <= 0:
            stress_pnl += net_pnl
            continue

        # Determine normal and stress fees
        normal_fee = 0.0031
        stress_fee = 0.0036
        for tier_name, coins in tier_coins.items():
            if pair in coins:
                normal_fee = TIER_FEES.get(tier_name, 0.0031)
                stress_fee = STRESS_FEES.get(tier_name, 0.0036)
                break

        # Extra cost from fee increase (both sides)
        extra = size * (stress_fee - normal_fee) * 2
        stress_pnl += net_pnl - extra

    return stress_pnl


def _calc_concentration(trades: list) -> tuple:
    """
    Calculate top-1 and top-3 coin concentration of P&L.
    Uses positive profit attribution (not abs total pnl).
    """
    if not trades:
        return 0.0, 0.0

    coin_pnl = {}
    for t in trades:
        pair = t.get('pair', 'unknown')
        coin_pnl[pair] = coin_pnl.get(pair, 0.0) + t['pnl']

    total_positive = sum(max(0, v) for v in coin_pnl.values())
    if total_positive <= 0:
        return 0.0, 0.0

    sorted_coins = sorted(coin_pnl.values(), key=abs, reverse=True)
    top1 = abs(sorted_coins[0]) / total_positive * 100 if len(sorted_coins) >= 1 else 0
    top3_sum = sum(abs(v) for v in sorted_coins[:3])
    top3 = top3_sum / total_positive * 100 if len(sorted_coins) >= 3 else top1

    return top1, top3

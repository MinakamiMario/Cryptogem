"""
Fill model v2 for HF screening.

Improvements over fill_model.py (v1):
- 5 execution modes: market, limit_moderate, limit_conservative,
  hybrid_optimistic, hybrid_conservative
- Continuous adverse_correlation (0.0-1.0) replaces binary adverse_bias
- Correct MEXC taker fee: 10 bps (not 0 bps as in v1)
- Per-trade surviving-trade selection with blended adverse/random miss

Does NOT modify harness.py or fill_model.py (v1 preserved for backward compat).
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Cost defaults (from fill_model_002.json proposed_v2_modes)
# ---------------------------------------------------------------------------
try:
    from strategies.hf.screening.costs_mexc_v2 import get_cost_breakdown
    _HAS_COSTS_V2 = True
except ImportError:
    _HAS_COSTS_V2 = False

# MEXC corrected fees (v1 had 0 bps taker -- WRONG per fee schedule)
MEXC_TAKER_FEE_BPS = 10.0   # 0.10% taker fee
MEXC_MAKER_FEE_BPS = 0.0    # 0% maker fee

# ---------------------------------------------------------------------------
# Mode definitions  (source: fill_model_002.json proposed_v2_modes)
# ---------------------------------------------------------------------------
_MODES: Dict[str, dict] = {
    'market': {
        'description': 'MEXC taker with spread + slippage, 100% fill',
        'fill_rate': 1.00,
        'adverse_bps': 0.0,
        'adverse_correlation': 0.0,
        'cost_per_side_bps': {'tier1': 6.0, 'tier2': 25.0},
    },
    'limit_moderate': {
        'description': 'Limit at close-spread, 72% fill, 50% adverse corr',
        'fill_rate': 0.72,
        'adverse_bps': 4.0,
        'adverse_correlation': 0.50,
        'cost_per_side_bps': {'tier1': 4.0, 'tier2': 7.0},
    },
    'limit_conservative': {
        'description': 'Conservative limit, 55% fill, 50% adverse corr',
        'fill_rate': 0.55,
        'adverse_bps': 6.0,
        'adverse_correlation': 0.50,
        'cost_per_side_bps': {'tier1': 6.0, 'tier2': 10.0},
    },
    'hybrid_optimistic': {
        'description': 'Limit entry + market fallback, 90% fill, 30% adverse corr',
        'fill_rate': 0.90,
        'adverse_bps': 2.0,
        'adverse_correlation': 0.30,
        'cost_per_side_bps': {'tier1': 5.0, 'tier2': 15.5},
    },
    'hybrid_conservative': {
        'description': 'Limit entry + market fallback, 85% fill, 50% adverse corr',
        'fill_rate': 0.85,
        'adverse_bps': 3.0,
        'adverse_correlation': 0.50,
        'cost_per_side_bps': {'tier1': 5.5, 'tier2': 16.0},
    },
}

# Kraken reference (for delta reports)
KRAKEN_FEES = {
    'tier1': {'per_side_bps': 31.0, 'round_trip_bps': 62.0},
    'tier2': {'per_side_bps': 56.0, 'round_trip_bps': 112.0},
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_fill_model(mode: str, tier: str = 'tier1') -> dict:
    """
    Return fill-model parameters for *mode* and *tier*.

    Returns dict with: mode, tier, description, fill_rate, adverse_bps,
    adverse_correlation, cost_per_side_bps, cost_round_trip_bps,
    harness_fee_decimal.
    """
    if mode not in _MODES:
        raise ValueError(
            f"Unknown mode {mode!r}. Choose from {list(_MODES.keys())}"
        )
    if tier not in ('tier1', 'tier2'):
        raise ValueError(f"Unknown tier {tier!r}. Choose from tier1, tier2")

    cfg = _MODES[mode]
    cost_bps = cfg['cost_per_side_bps'][tier]
    return {
        'mode': mode,
        'tier': tier,
        'description': cfg['description'],
        'fill_rate': cfg['fill_rate'],
        'adverse_bps': cfg['adverse_bps'],
        'adverse_correlation': cfg['adverse_correlation'],
        'cost_per_side_bps': cost_bps,
        'cost_round_trip_bps': cost_bps * 2,
        'harness_fee_decimal': cost_bps / 10_000.0,
    }


def adjust_backtest_result(
    mode: str,
    tier: str,
    n_trades: int,
    total_pnl: float,
    trade_list: Optional[list] = None,
) -> dict:
    """
    Post-process a harness backtest result through the fill model.

    If *trade_list* is provided (list of dicts with keys ``pnl``, ``size``,
    ``entry``, ``exit``), per-trade PnL is recomputed with surviving-trade
    selection driven by *adverse_correlation*.  Otherwise a simple PnL
    scaling is applied.

    Returns dict with original + adjusted metrics.
    """
    params = apply_fill_model(mode, tier)
    fill_rate = params['fill_rate']
    adverse_corr = params['adverse_correlation']

    n_effective = int(round(n_trades * fill_rate))
    n_missed = n_trades - n_effective

    if trade_list is not None and len(trade_list) > 0:
        surviving = _select_surviving_trades(
            trade_list, fill_rate, adverse_corr
        )
        adjusted_pnl = _recompute_pnl(surviving, params)
        n_effective = len(surviving)
        n_missed = n_trades - n_effective
    else:
        # No per-trade data: scale PnL by fill_rate (random-miss approx)
        adjusted_pnl = total_pnl * fill_rate

    return {
        'mode': mode,
        'tier': tier,
        'original_trades': n_trades,
        'effective_trades': n_effective,
        'missed_trades': n_missed,
        'fill_rate': fill_rate,
        'adverse_correlation': adverse_corr,
        'original_pnl': total_pnl,
        'adjusted_pnl': adjusted_pnl,
        'cost_per_side_bps': params['cost_per_side_bps'],
        'cost_round_trip_bps': params['cost_round_trip_bps'],
        'harness_fee_decimal': params['harness_fee_decimal'],
    }


def get_all_modes_summary(tier: str = 'tier1') -> dict:
    """Return a summary dict for all 5 modes at the given tier."""
    summary = {}
    for mode in _MODES:
        p = apply_fill_model(mode, tier)
        summary[mode] = {
            'fill_rate': p['fill_rate'],
            'adverse_bps': p['adverse_bps'],
            'adverse_correlation': p['adverse_correlation'],
            'cost_per_side_bps': p['cost_per_side_bps'],
            'cost_round_trip_bps': p['cost_round_trip_bps'],
        }
    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _select_surviving_trades(
    trade_list: list,
    fill_rate: float,
    adverse_correlation: float,
    seed: int = 42,
) -> list:
    """
    Select trades that survive fill-rate filtering with blended adverse
    selection.

    Parameters
    ----------
    trade_list : list
        Trade dicts, each must have at least ``pnl`` key.
    fill_rate : float
        Fraction of trades that fill (0.0 to 1.0).
    adverse_correlation : float
        Blend between random miss (0.0) and worst-case top-winner
        removal (1.0).

        - 0.0 : missed trades are uniformly random (preserves W/L ratio)
        - 1.0 : ALL missed trades are top winners (worst case)
        - 0.5 : 50% of misses target top winners, 50% random

    seed : int
        RNG seed for reproducible random removal.

    Returns
    -------
    list : surviving trade dicts (order may differ from input).

    Algorithm
    ---------
    1. Sort trades by PnL descending.
    2. n_missed  = round(n * (1 - fill_rate))
    3. n_adverse = round(n_missed * adverse_correlation)
    4. n_random  = n_missed - n_adverse
    5. Remove top n_adverse winners from sorted list.
    6. Remove n_random trades uniformly from the remainder.
    """
    if not trade_list:
        return []

    n = len(trade_list)
    n_missed = int(round(n * (1.0 - fill_rate)))
    if n_missed <= 0:
        return list(trade_list)
    if n_missed >= n:
        return []

    n_adverse = int(round(n_missed * adverse_correlation))
    n_random = n_missed - n_adverse

    # Sort descending by PnL (best first)
    sorted_trades = sorted(
        trade_list, key=lambda t: t.get('pnl', 0.0), reverse=True
    )

    # Step 1: remove top n_adverse winners (adversely selected misses)
    remainder = sorted_trades[n_adverse:]

    # Step 2: remove n_random trades uniformly from remainder
    if n_random > 0 and len(remainder) > 0:
        n_random = min(n_random, len(remainder))
        rng = random.Random(seed)
        remove_indices = set(rng.sample(range(len(remainder)), n_random))
        remainder = [
            t for i, t in enumerate(remainder) if i not in remove_indices
        ]

    return remainder


def _recompute_pnl(surviving_trades: list, fill_params: dict) -> float:
    """
    Recompute total PnL for *surviving_trades* under the v2 fee model.

    For each trade:
      gross  = (exit - entry) / entry * size
      fees   = size * fee + (size + gross) * fee  (entry + exit side)
      adv    = size * (adverse_bps / 10000)
      net    = gross - fees - adv

    Falls back to the trade's own ``pnl`` if entry/size data is missing.
    """
    if not surviving_trades:
        return 0.0

    fee_dec = fill_params['harness_fee_decimal']
    adv_bps = fill_params['adverse_bps']
    total = 0.0

    for t in surviving_trades:
        size = t.get('size', 0)
        entry = t.get('entry', 0)
        exit_p = t.get('exit', 0)

        if entry <= 0 or size <= 0:
            # Fallback: use raw PnL from trade record
            total += t.get('pnl', 0.0)
            continue

        gross = (exit_p - entry) / entry * size
        fees = size * fee_dec + (size + gross) * fee_dec
        adverse_cost = size * (adv_bps / 10_000.0)
        total += gross - fees - adverse_cost

    return total

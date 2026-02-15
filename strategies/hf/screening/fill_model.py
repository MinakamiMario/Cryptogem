"""
Fill model for Reality Check sprint.
3 modes: market, limit_optimistic, limit_realistic

Each mode defines:
- entry_fee_bps: exchange fee per side at entry
- exit_fee_bps: exchange fee per side at exit
- fill_rate: probability that a limit order fills (1.0 for market)
- adverse_selection_bps: extra cost when limit fills (winner's curse)
- spread_bps: half-spread cost (0 for limit at mid)
- slippage_bps: market impact cost (0 for limit)

MEXC reference values (2025-2026):
- MEXC spot taker fee: 0 bps (0% for most tiers)
- MEXC spot maker fee: 0 bps (0% for most tiers)
- T1 half-spread: ~4 bps
- T2 half-spread: ~15 bps
- T1 slippage ($500): ~2 bps
- T2 slippage ($500): ~10 bps

Kraken reference (current harness):
- T1 per-side: 31 bps (0.0031)
- T2 per-side: 56 bps (0.0056)

This module does NOT modify harness.py. It provides parameters and
post-processing functions for fill-adjusted screening.
"""

from __future__ import annotations

import math
from typing import Tuple

# ---------------------------------------------------------------------------
# MEXC fee schedule (spot, most VIP tiers as of 2025-2026)
# ---------------------------------------------------------------------------
MEXC_TAKER_FEE_BPS = 0.0   # 0% taker fee
MEXC_MAKER_FEE_BPS = 0.0   # 0% maker fee

# ---------------------------------------------------------------------------
# Spread & slippage estimates by tier (for $500 order size)
# ---------------------------------------------------------------------------
SPREAD_ESTIMATES = {
    'tier1': {'half_spread_bps': 4.0,  'slippage_bps': 2.0},
    'tier2': {'half_spread_bps': 15.0, 'slippage_bps': 10.0},
}

# ---------------------------------------------------------------------------
# Adverse selection estimates
# ---------------------------------------------------------------------------
ADVERSE_SELECTION = {
    'limit_optimistic': 3.0,   # bps
    'limit_realistic':  8.0,   # bps
}

# ---------------------------------------------------------------------------
# Fill rates
# ---------------------------------------------------------------------------
FILL_RATES = {
    'market':            1.00,
    'limit_optimistic':  0.80,
    'limit_realistic':   0.55,
}

# ---------------------------------------------------------------------------
# Mode definitions
# ---------------------------------------------------------------------------
FILL_MODES = {
    'market': {
        'description': 'MEXC taker with spread + slippage',
        'order_type': 'market',
        'exchange_fee_bps': MEXC_TAKER_FEE_BPS,
        'uses_spread': True,
        'uses_slippage': True,
        'fill_rate': FILL_RATES['market'],
        'adverse_selection_bps': 0.0,
        'adverse_bias': False,
    },
    'limit_optimistic': {
        'description': 'MEXC maker limit, 80% fill, mild adverse selection',
        'order_type': 'limit',
        'exchange_fee_bps': MEXC_MAKER_FEE_BPS,
        'uses_spread': False,
        'uses_slippage': False,
        'fill_rate': FILL_RATES['limit_optimistic'],
        'adverse_selection_bps': ADVERSE_SELECTION['limit_optimistic'],
        'adverse_bias': False,
    },
    'limit_realistic': {
        'description': 'MEXC maker limit, 55% fill, significant adverse selection',
        'order_type': 'limit',
        'exchange_fee_bps': MEXC_MAKER_FEE_BPS,
        'uses_spread': False,
        'uses_slippage': False,
        'fill_rate': FILL_RATES['limit_realistic'],
        'adverse_selection_bps': ADVERSE_SELECTION['limit_realistic'],
        'adverse_bias': True,   # missed fills are the strongest signals
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_fill_model(mode: str, tier: str = 'tier1') -> dict:
    """
    Return fill model parameters for given mode and tier.

    Parameters
    ----------
    mode : str
        One of 'market', 'limit_optimistic', 'limit_realistic'.
    tier : str
        One of 'tier1', 'tier2'.

    Returns
    -------
    dict with keys:
        fee_per_side_bps, fill_rate, adverse_selection_bps, spread_bps,
        slippage_bps, total_per_side_bps, total_round_trip_bps,
        harness_fee_decimal (fee value to pass to harness.run_backtest)
    """
    if mode not in FILL_MODES:
        raise ValueError(f"Unknown fill mode: {mode!r}. "
                         f"Choose from {list(FILL_MODES.keys())}")
    if tier not in SPREAD_ESTIMATES:
        raise ValueError(f"Unknown tier: {tier!r}. "
                         f"Choose from {list(SPREAD_ESTIMATES.keys())}")

    cfg = FILL_MODES[mode]
    spread_cfg = SPREAD_ESTIMATES[tier]

    exchange_fee = cfg['exchange_fee_bps']
    spread = spread_cfg['half_spread_bps'] if cfg['uses_spread'] else 0.0
    slippage = spread_cfg['slippage_bps'] if cfg['uses_slippage'] else 0.0
    adverse = cfg['adverse_selection_bps']
    fill_rate = cfg['fill_rate']

    total_per_side = exchange_fee + spread + slippage + adverse
    total_round_trip = total_per_side * 2

    # Convert to decimal for harness compatibility (bps / 10000)
    harness_fee = total_per_side / 10000.0

    return {
        'mode': mode,
        'tier': tier,
        'order_type': cfg['order_type'],
        'fee_per_side_bps': exchange_fee,
        'spread_bps': spread,
        'slippage_bps': slippage,
        'adverse_selection_bps': adverse,
        'fill_rate': fill_rate,
        'adverse_bias': cfg['adverse_bias'],
        'total_per_side_bps': total_per_side,
        'total_round_trip_bps': total_round_trip,
        'harness_fee_decimal': harness_fee,
    }


def effective_cost_per_side(mode: str, tier: str = 'tier1') -> float:
    """
    Total cost in bps per side: exchange_fee + spread + slippage + adverse_selection.

    Parameters
    ----------
    mode : str
        One of 'market', 'limit_optimistic', 'limit_realistic'.
    tier : str
        One of 'tier1', 'tier2'.

    Returns
    -------
    float : total cost in basis points per side.
    """
    params = apply_fill_model(mode, tier)
    return params['total_per_side_bps']


def adjust_for_fill_rate(
    n_trades: int,
    fill_rate: float,
    adverse_bias: bool = False,
) -> Tuple[int, int]:
    """
    Compute effective and missed trades after fill-rate adjustment.

    Parameters
    ----------
    n_trades : int
        Original number of trade signals generated.
    fill_rate : float
        Probability that a limit order fills (0.0 to 1.0).
    adverse_bias : bool
        If True (realistic mode), missed trades are the strongest signals.
        The best momentum trades don't fill because price runs away.
        This flag is informational for the caller to decide how to
        handle PnL adjustments on the remaining trades.

    Returns
    -------
    tuple of (effective_trades, missed_trades)
        effective_trades: int - number of trades that actually execute
        missed_trades: int - number of signals that don't fill
    """
    if fill_rate < 0.0 or fill_rate > 1.0:
        raise ValueError(f"fill_rate must be in [0, 1], got {fill_rate}")

    effective = int(round(n_trades * fill_rate))
    missed = n_trades - effective
    return effective, missed


def adjust_backtest_result(
    mode: str,
    tier: str,
    n_trades: int,
    total_pnl: float,
    trade_list: list = None,
) -> dict:
    """
    Apply fill-model adjustments to a backtest result.

    This is the main post-processor. Given raw backtest results from the
    harness (which used Kraken fees), compute what the results would look
    like under a different fill model.

    Parameters
    ----------
    mode : str
        Fill mode name.
    tier : str
        Tier name.
    n_trades : int
        Number of trades from harness backtest.
    total_pnl : float
        Total PnL from harness backtest.
    trade_list : list, optional
        List of trade dicts from BacktestResult.trade_list.
        If provided, enables per-trade PnL recomputation.

    Returns
    -------
    dict with adjusted metrics:
        effective_trades, missed_trades, fill_rate,
        adjusted_pnl, cost_per_side_bps, cost_round_trip_bps,
        adverse_bias, mode, tier
    """
    params = apply_fill_model(mode, tier)
    fill_rate = params['fill_rate']
    adverse_bias = params['adverse_bias']
    harness_fee = params['harness_fee_decimal']

    effective_trades, missed_trades = adjust_for_fill_rate(
        n_trades, fill_rate, adverse_bias
    )

    # If we have per-trade data, recompute PnL with new fee structure
    adjusted_pnl = total_pnl
    if trade_list is not None and len(trade_list) > 0:
        adjusted_pnl = _recompute_pnl(trade_list, params)

    return {
        'mode': mode,
        'tier': tier,
        'original_trades': n_trades,
        'effective_trades': effective_trades,
        'missed_trades': missed_trades,
        'fill_rate': fill_rate,
        'adverse_bias': adverse_bias,
        'original_pnl': total_pnl,
        'adjusted_pnl': adjusted_pnl,
        'cost_per_side_bps': params['total_per_side_bps'],
        'cost_round_trip_bps': params['total_round_trip_bps'],
        'harness_fee_decimal': harness_fee,
    }


def get_all_modes_summary(tier: str = 'tier1') -> dict:
    """
    Return a summary dict for all 3 modes at the given tier.
    Useful for reports and comparisons.
    """
    summary = {}
    for mode in FILL_MODES:
        p = apply_fill_model(mode, tier)
        summary[mode] = {
            'fee_bps': p['fee_per_side_bps'],
            'spread_bps': p['spread_bps'],
            'slippage_bps': p['slippage_bps'],
            'adverse_bps': p['adverse_selection_bps'],
            'fill_rate': p['fill_rate'],
            'total_per_side_bps': p['total_per_side_bps'],
            'total_round_trip_bps': p['total_round_trip_bps'],
        }
    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _recompute_pnl(trade_list: list, fill_params: dict) -> float:
    """
    Recompute total PnL for a trade list using fill model parameters.

    Strategy:
    1. Sort trades by absolute PnL descending (strongest first).
    2. If adverse_bias is True, the missed trades (strongest momentum)
       are removed from the front (best trades missed).
    3. If adverse_bias is False, missed trades are removed uniformly
       (every Nth trade).
    4. For surviving trades, recompute fees using fill model rates.
    """
    if not trade_list:
        return 0.0

    n = len(trade_list)
    fill_rate = fill_params['fill_rate']
    adverse_bias = fill_params['adverse_bias']
    new_fee = fill_params['harness_fee_decimal']

    effective_n, missed_n = adjust_for_fill_rate(n, fill_rate, adverse_bias)

    if effective_n == 0:
        return 0.0

    # Sort trades for selection
    sorted_trades = sorted(trade_list, key=lambda t: t.get('pnl', 0), reverse=True)

    if adverse_bias:
        # Realistic mode: best trades (highest PnL) are missed
        # because price ran away before limit filled.
        # Remove the top 'missed_n' winning trades.
        surviving_trades = sorted_trades[missed_n:]
    else:
        # Optimistic / market mode: uniform fill miss.
        # Remove every Nth trade evenly across the distribution.
        if missed_n == 0:
            surviving_trades = sorted_trades
        else:
            step = max(1, n // missed_n) if missed_n > 0 else n + 1
            skip_indices = set()
            idx = 0
            while len(skip_indices) < missed_n and idx < n:
                skip_indices.add(idx)
                idx += step
            # If step didn't cover enough, fill from the end
            idx = n - 1
            while len(skip_indices) < missed_n and idx >= 0:
                skip_indices.add(idx)
                idx -= 1
            surviving_trades = [
                t for i, t in enumerate(sorted_trades) if i not in skip_indices
            ]

    # Recompute PnL with new fee structure
    total_pnl = 0.0
    for t in surviving_trades:
        size = t.get('size', 0)
        entry = t.get('entry', 0)
        exit_p = t.get('exit', 0)

        if entry <= 0 or size <= 0:
            total_pnl += t.get('pnl', 0)
            continue

        # Gross PnL (same as harness)
        gross = (exit_p - entry) / entry * size

        # New fee structure: entry side + exit side
        fees = size * new_fee + (size + gross) * new_fee

        # Add adverse selection cost (applied as extra slippage on fill)
        adverse_cost = size * (fill_params['adverse_selection_bps'] / 10000.0)
        fees += adverse_cost

        net = gross - fees
        total_pnl += net

    return total_pnl


# ---------------------------------------------------------------------------
# Kraken comparison constants (for report generation)
# ---------------------------------------------------------------------------
KRAKEN_FEES = {
    'tier1': {'per_side_bps': 31.0, 'round_trip_bps': 62.0},
    'tier2': {'per_side_bps': 56.0, 'round_trip_bps': 112.0},
}

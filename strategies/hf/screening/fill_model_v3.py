"""
Bar-structure fill model v3.

Post-processing wrapper for harness trade lists. Determines fill probability
based on OHLCV bar structure. Does NOT modify harness.py (READ-ONLY).

CONTRACT: This module does ONLY fill/no-fill decisions.
NO extra cost deduction — all costs sit in total_per_side_bps via harness fee.
PnL recompute ONLY when applying different fee than harness used.
"""

from __future__ import annotations
import random
from typing import Dict, List, Optional, Tuple


def bar_structure_fill_probability(
    low: float, high: float, close: float, limit_price: float,
    queue_factor: float = 0.7,
) -> float:
    """
    Fill probability for a limit buy at `limit_price` on a bar with given OHLCV.

    Logic:
    - If low > limit_price: price never reached limit -> 0.0
    - If low <= limit_price:
        bar_range = high - low
        if bar_range <= 0: return queue_factor (flat bar, touched limit)
        penetration = (limit_price - low) / bar_range
        fill_prob = queue_factor * min(1.0, penetration * 2.0)

    The 2.0 multiplier means: if price went 50%+ of bar range below limit,
    you almost certainly filled. queue_factor (0.5-0.8) accounts for queue position.

    Parameters
    ----------
    low : bar low price
    high : bar high price
    close : bar close price (unused in calc, but needed for context)
    limit_price : limit order price
    queue_factor : max fill probability (accounts for queue position)

    Returns
    -------
    float : fill probability [0.0, queue_factor]
    """
    if low > limit_price:
        return 0.0

    # low <= limit_price: price reached or passed the limit
    bar_range = high - low
    if bar_range <= 0:
        # Flat bar that touched limit -> queue_factor
        return queue_factor

    penetration = (limit_price - low) / bar_range
    fill_prob = queue_factor * min(1.0, penetration * 2.0)
    return fill_prob


def compute_limit_entry_price(close: float, half_spread_bps: float) -> float:
    """
    Limit buy price = close - half_spread.

    For a maker limit order, you place your bid at close - half_spread,
    hoping to get filled when price dips.

    Parameters
    ----------
    close : current close price
    half_spread_bps : half-spread in basis points

    Returns
    -------
    float : limit order price
    """
    return close * (1.0 - half_spread_bps / 10_000.0)


def adjust_trades_bar_structure(
    trade_list: List[dict],
    candle_data: dict,
    half_spread_bps: float,
    queue_factor: float = 0.7,
    seed: int = 42,
) -> Tuple[List[dict], dict]:
    """
    Filter trades based on bar-structure fill probability.

    Per trade:
    1. Look up entry bar OHLCV from candle_data[coin]
    2. Compute limit_price = close - half_spread (tier-specific from caller)
    3. Compute fill probability from bar structure
    4. Seeded random draw -> fill or miss
    5. Return surviving trades + summary

    Parameters
    ----------
    trade_list : list of trade dicts from harness BacktestResult.trade_list
        Each has: 'coin', 'entry_bar', 'entry', 'exit', 'pnl', 'size', etc.
    candle_data : dict[coin] -> list of [ts, open, high, low, close, volume]
        Raw candle data from cache
    half_spread_bps : half-spread in bps for limit price computation
    queue_factor : max fill probability (0.5-0.8)
    seed : random seed for determinism

    Returns
    -------
    (surviving_trades, summary) where summary has:
        total, filled, missed, fill_rate, avg_fill_prob, missed_coins
    """
    rng = random.Random(seed)
    surviving = []
    n_total = len(trade_list)
    n_filled = 0
    n_missed = 0
    fill_probs = []
    missed_coins: Dict[str, int] = {}

    for trade in trade_list:
        coin = trade.get('coin', '')
        entry_bar = trade.get('entry_bar', 0)

        # Get candle data for this coin
        candles = candle_data.get(coin, [])
        if entry_bar < 0 or entry_bar >= len(candles):
            # Can't verify, assume fill
            surviving.append(trade)
            n_filled += 1
            fill_probs.append(1.0)
            continue

        candle = candles[entry_bar]
        # candle format: [ts, open, high, low, close, volume]
        bar_high = candle[2]
        bar_low = candle[3]
        bar_close = candle[4]

        # Compute limit price
        limit_price = compute_limit_entry_price(bar_close, half_spread_bps)

        # Compute fill probability
        fill_prob = bar_structure_fill_probability(
            low=bar_low, high=bar_high, close=bar_close,
            limit_price=limit_price, queue_factor=queue_factor,
        )
        fill_probs.append(fill_prob)

        # Random draw
        if rng.random() < fill_prob:
            surviving.append(trade)
            n_filled += 1
        else:
            n_missed += 1
            missed_coins[coin] = missed_coins.get(coin, 0) + 1

    summary = {
        'total': n_total,
        'filled': n_filled,
        'missed': n_missed,
        'fill_rate': n_filled / n_total if n_total > 0 else 0.0,
        'avg_fill_prob': sum(fill_probs) / len(fill_probs) if fill_probs else 0.0,
        'missed_coins': missed_coins,
    }

    return surviving, summary


def recompute_pnl_with_costs(
    trade: dict, cost_per_side_bps: float,
) -> dict:
    """
    Recompute PnL for a trade with a different fee level.

    Uses the EXACT same formula as harness.py:
        gross = (exit_price - entry_price) / entry_price * size
        fees = size * (cost/10000) + (size + gross) * (cost/10000)
        net = gross - fees

    CONTRACT: This is ONLY used when the P0-3 runner needs to apply a different
    fee than what the harness originally used (e.g., size-dependent slippage).

    Parameters
    ----------
    trade : trade dict with 'entry', 'exit', 'size', 'pnl' keys
    cost_per_side_bps : all-in cost per side in basis points

    Returns
    -------
    dict : copy of trade with updated 'pnl', 'fees', 'gross' fields
    """
    t = dict(trade)  # shallow copy
    entry = t.get('entry', 0)
    exit_p = t.get('exit', 0)
    size = t.get('size', 0)

    if entry <= 0 or size <= 0:
        return t

    fee_decimal = cost_per_side_bps / 10_000.0
    gross = (exit_p - entry) / entry * size
    fees = size * fee_decimal + (size + gross) * fee_decimal
    net = gross - fees

    t['gross'] = round(gross, 6)
    t['fees'] = round(fees, 6)
    t['pnl'] = round(net, 6)
    t['_recomputed_fee_bps'] = cost_per_side_bps

    return t


def full_fill_model_v3(
    trade_list: List[dict],
    candle_data: dict,
    half_spread_bps: float = 5.0,
    new_fee_bps: Optional[float] = None,
    queue_factor: float = 0.7,
    seed: int = 42,
) -> dict:
    """
    Complete pipeline: bar-structure fill check + optional PnL recompute.

    Steps:
    1. Run bar-structure fill model -> surviving trades
    2. If new_fee_bps provided, recompute PnL with new fee level
    3. Compute summary metrics

    Parameters
    ----------
    trade_list : harness trade list
    candle_data : raw candle data
    half_spread_bps : half-spread for limit price (per tier, caller provides)
    new_fee_bps : if not None, recompute PnL with this all-in fee
    queue_factor : fill probability cap
    seed : random seed

    Returns
    -------
    dict with: trades, fill_summary, metrics (pnl, pf, wr)
    """
    # Step 1: bar-structure fill
    surviving, fill_summary = adjust_trades_bar_structure(
        trade_list, candle_data, half_spread_bps, queue_factor, seed,
    )

    # Step 2: optional PnL recompute
    if new_fee_bps is not None:
        surviving = [recompute_pnl_with_costs(t, new_fee_bps) for t in surviving]

    # Step 3: summary metrics
    n = len(surviving)
    if n > 0:
        total_pnl = sum(t['pnl'] for t in surviving)
        wins = [t for t in surviving if t['pnl'] > 0]
        losses = [t for t in surviving if t['pnl'] <= 0]
        tw = sum(t['pnl'] for t in wins)
        tl = abs(sum(t['pnl'] for t in losses))
        pf = tw / tl if tl > 0 else (float('inf') if tw > 0 else 0.0)
        wr = len(wins) / n * 100
    else:
        total_pnl = 0.0
        pf = 0.0
        wr = 0.0

    return {
        'trades': surviving,
        'fill_summary': fill_summary,
        'metrics': {
            'n_trades': n,
            'total_pnl': round(total_pnl, 2),
            'profit_factor': round(pf, 3),
            'win_rate': round(wr, 1),
        },
    }

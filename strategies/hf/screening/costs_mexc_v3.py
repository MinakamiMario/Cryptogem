"""
MEXC execution cost model v3 -- per-trade cost estimation from candle data.
Supersedes flat-rate costs from v2 with candle-derived cost proxies.

v2 used Kaiko-calibrated formulas with fixed percentile-based cost numbers.
v3 measures costs PER TRADE from actual candle data at the time of execution:
  - spread_bps: half-spread proxy from bar range (high-low) / (2*close)
  - slippage_bps: sqrt(trade_size / bar_volume_usd) * close_to_close_vol
  - exchange_fee_bps: 10.0 (MEXC taker, unchanged)
  - fill_rate: bar_volume_usd / (5 * trade_size)

Re-exports the full v2 API for backward compatibility.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Dict, List, Optional

# -----------------------------------------------------------------------
# Re-export full v2 API for backward compatibility
# -----------------------------------------------------------------------
from strategies.hf.screening.costs_mexc_v2 import (  # noqa: F401
    COST_REGIMES,
    get_regime_names,
    get_cost_breakdown,
    get_harness_fee,
    stress_multiplier,
)


# -----------------------------------------------------------------------
# Per-trade cost estimation from candle data
# -----------------------------------------------------------------------

def estimate_trade_cost(
    candles: list,
    bar: int,
    trade_size: float = 200.0,
    tier: str = 'tier2',
    exchange_fee_bps: float = 10.0,
    lookback: int = 20,
) -> dict:
    """Estimate all-in execution cost for a single trade from candle data.

    Args:
        candles: list of candle dicts for one coin (OHLCV format)
        bar: bar index at which the trade enters
        trade_size: trade size in USD
        tier: 'tier1' or 'tier2' (informational, does not affect calculation)
        exchange_fee_bps: exchange taker fee in bps (default 10.0 for MEXC)
        lookback: number of bars for volatility estimation

    Returns:
        dict with spread_bps, slippage_bps, exchange_fee_bps, total_per_side_bps,
        fill_rate, bar_volume_usd, close_to_close_vol, and component details.
    """
    if bar < 1 or bar >= len(candles):
        return _empty_cost(exchange_fee_bps, tier)

    c = candles[bar]
    high = c['high']
    low = c['low']
    close = c['close']

    if close <= 0 or high <= 0:
        return _empty_cost(exchange_fee_bps, tier)

    # --- Spread proxy: half the bar range as fraction of close ---
    bar_range = high - low
    spread_bps = (bar_range / (2.0 * close)) * 10_000

    # --- Bar volume in USD ---
    raw_vol = c.get('volume', 0)
    bar_volume_usd = raw_vol * close  # volume is in base currency (coins)

    # --- Close-to-close volatility (per bar) ---
    start = max(1, bar - lookback)
    returns = []
    for i in range(start, bar + 1):
        prev_close = candles[i - 1]['close']
        cur_close = candles[i]['close']
        if prev_close > 0 and cur_close > 0:
            returns.append(math.log(cur_close / prev_close))

    if len(returns) >= 2:
        mean_r = sum(returns) / len(returns)
        var_r = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        close_to_close_vol = math.sqrt(var_r)
    else:
        close_to_close_vol = 0.02  # fallback: 2% per bar

    # --- Slippage proxy ---
    safe_vol = max(bar_volume_usd, 1.0)
    slippage_bps = math.sqrt(trade_size / safe_vol) * close_to_close_vol * 10_000

    # --- Total per side ---
    total_per_side_bps = spread_bps + slippage_bps + exchange_fee_bps

    # --- Fill rate proxy ---
    fill_rate = min(1.0, bar_volume_usd / (5.0 * max(trade_size, 1.0)))

    return {
        'spread_bps': round(spread_bps, 2),
        'slippage_bps': round(slippage_bps, 2),
        'exchange_fee_bps': round(exchange_fee_bps, 2),
        'total_per_side_bps': round(total_per_side_bps, 2),
        'total_round_trip_bps': round(total_per_side_bps * 2, 2),
        'fill_rate': round(fill_rate, 4),
        'bar_volume_usd': round(bar_volume_usd, 0),
        'close_to_close_vol': round(close_to_close_vol, 6),
        'tier': tier,
        'trade_size': trade_size,
        'bar': bar,
    }


def _empty_cost(exchange_fee_bps: float, tier: str) -> dict:
    """Return a cost dict with zeroed estimates (missing data fallback)."""
    return {
        'spread_bps': 0.0,
        'slippage_bps': 0.0,
        'exchange_fee_bps': round(exchange_fee_bps, 2),
        'total_per_side_bps': round(exchange_fee_bps, 2),
        'total_round_trip_bps': round(exchange_fee_bps * 2, 2),
        'fill_rate': 0.0,
        'bar_volume_usd': 0.0,
        'close_to_close_vol': 0.0,
        'tier': tier,
        'trade_size': 0.0,
        'bar': -1,
    }


# -----------------------------------------------------------------------
# Batch cost measurement
# -----------------------------------------------------------------------

def build_cost_table(
    data: dict,
    trade_list: list,
    trade_size: float = 200.0,
    exchange_fee_bps: float = 10.0,
    lookback: int = 20,
) -> List[dict]:
    """Compute per-trade costs for a list of trades from backtest output."""
    cost_table = []
    for trade in trade_list:
        pair = trade['pair']
        entry_bar = trade.get('entry_bar', 0)
        tier = trade.get('_tier', 'tier2')
        candles = data.get(pair, [])

        cost = estimate_trade_cost(
            candles=candles, bar=entry_bar, trade_size=trade_size,
            tier=tier, exchange_fee_bps=exchange_fee_bps, lookback=lookback,
        )

        cost['pair'] = pair
        cost['entry_bar'] = entry_bar
        cost['exit_bar'] = trade.get('exit_bar', 0)
        cost['pnl'] = trade.get('pnl', 0.0)
        cost['reason'] = trade.get('reason', '')
        cost['_tier'] = tier
        cost['entry_price'] = trade.get('entry', 0.0)
        cost['exit_price'] = trade.get('exit', 0.0)

        ind_atr = None
        if entry_bar < len(candles) and entry_bar > 0:
            c_entry = candles[entry_bar]
            ind_atr = c_entry['high'] - c_entry['low']
        cost['bar_atr'] = ind_atr

        cost_table.append(cost)

    return cost_table


def summarize_cost_table(
    cost_table: List[dict],
    by_tier: bool = True,
) -> dict:
    """Compute percentile summaries of cost components."""
    percentiles = [10, 25, 50, 75, 90, 95, 99]
    components = ['spread_bps', 'slippage_bps', 'exchange_fee_bps',
                  'total_per_side_bps', 'fill_rate', 'bar_volume_usd']

    def _compute_pctiles(rows):
        if not rows:
            return {}
        result = {'n_trades': len(rows)}
        for comp in components:
            vals = sorted(v[comp] for v in rows)
            n = len(vals)
            pcts = {}
            for p in percentiles:
                idx = int(n * p / 100)
                idx = min(idx, n - 1)
                pcts[f'P{p}'] = round(vals[idx], 2)
            pcts['mean'] = round(sum(vals) / n, 2)
            result[comp] = pcts
        return result

    summary = {'all': _compute_pctiles(cost_table)}
    if by_tier:
        t1 = [c for c in cost_table if c.get('_tier') == 'tier1']
        t2 = [c for c in cost_table if c.get('_tier') == 'tier2']
        summary['tier1'] = _compute_pctiles(t1)
        summary['tier2'] = _compute_pctiles(t2)
    return summary


def get_calibrated_regime(cost_table: List[dict]) -> dict:
    """Build a new COST_REGIMES-compatible entry from measured costs."""
    t1 = [c for c in cost_table if c.get('_tier') == 'tier1']
    t2 = [c for c in cost_table if c.get('_tier') == 'tier2']

    def _median(rows, key):
        if not rows:
            return 0.0
        vals = sorted(v[key] for v in rows)
        return vals[len(vals) // 2]

    def _percentile(rows, key, pct):
        if not rows:
            return 0.0
        vals = sorted(v[key] for v in rows)
        idx = min(int(len(vals) * pct / 100), len(vals) - 1)
        return vals[idx]

    regime_p50 = {
        'description': 'MEXC taker, candle-measured P50 costs',
        'tier1': {
            'exchange_fee_bps': 10.0,
            'spread_bps': round(_median(t1, 'spread_bps'), 1),
            'slippage_bps': round(_median(t1, 'slippage_bps'), 1),
        },
        'tier2': {
            'exchange_fee_bps': 10.0,
            'spread_bps': round(_median(t2, 'spread_bps'), 1),
            'slippage_bps': round(_median(t2, 'slippage_bps'), 1),
        },
        'percentile': 'p50',
    }
    for tk in ('tier1', 'tier2'):
        t = regime_p50[tk]
        t['total_per_side_bps'] = round(t['exchange_fee_bps'] + t['spread_bps'] + t['slippage_bps'], 1)

    regime_p90 = {
        'description': 'MEXC taker, candle-measured P90 costs',
        'tier1': {
            'exchange_fee_bps': 10.0,
            'spread_bps': round(_percentile(t1, 'spread_bps', 90), 1),
            'slippage_bps': round(_percentile(t1, 'slippage_bps', 90), 1),
        },
        'tier2': {
            'exchange_fee_bps': 10.0,
            'spread_bps': round(_percentile(t2, 'spread_bps', 90), 1),
            'slippage_bps': round(_percentile(t2, 'slippage_bps', 90), 1),
        },
        'percentile': 'p90',
    }
    for tk in ('tier1', 'tier2'):
        t = regime_p90[tk]
        t['total_per_side_bps'] = round(t['exchange_fee_bps'] + t['spread_bps'] + t['slippage_bps'], 1)

    return {'measured_p50': regime_p50, 'measured_p90': regime_p90}

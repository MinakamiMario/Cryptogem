#!/usr/bin/env python3
"""
Sprint 5 Hypothesis Definitions (H16-H25)
==========================================
Separate registry from Sprint 4 (REGISTRY_S5, not REGISTRY).
H16-H20: Microstructure (candle anatomy, volume expansion, gaps, VWAP)
H21-H23: Market State / Regime (BTC regime, breadth momentum, decorrelation)
H24-H25: Cross-Sectional (momentum rank, mean reversion rank)

Signal protocol: signal_fn(candles, bar, indicators, params) -> Optional[dict]
  Returns {'stop_price': float, 'target_price': float, 'time_limit': int, 'strength': float}
  or None when conditions are not met.
"""

from dataclasses import dataclass
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Hypothesis dataclass and registry (separate from Sprint 4)
# ---------------------------------------------------------------------------

@dataclass
class HypothesisS5:
    id: str            # H16, H17, ...
    name: str          # DISPLACEMENT_BAR, WICK_REJECTION, ...
    category: str      # microstructure, market_state, cross_sectional
    signal_fn: Callable
    param_grid: list   # list of param dicts (max 6 variants)
    description: str


REGISTRY_S5: dict[str, HypothesisS5] = {}


def register_s5(hyp: HypothesisS5):
    """Add a hypothesis to the Sprint 5 registry."""
    REGISTRY_S5[hyp.id] = hyp


# ===================================================================
# CATEGORY: MICROSTRUCTURE (H16-H20)
# ===================================================================

# -------------------------------------------------------------------
# H16 DISPLACEMENT_BAR
# -------------------------------------------------------------------
def signal_h16_displacement_bar(candles, bar, indicators, params):
    """H16 DISPLACEMENT_BAR: Big bullish candle with follow-through.

    body/ATR > disp_thresh AND close > open (bullish) AND close > prev_high.
    """
    if bar < 1:
        return None
    n = indicators.get('n', 0)
    if bar >= n:
        return None

    atr_list = indicators.get('atr')
    if atr_list is None:
        return None
    atr = atr_list[bar] if bar < len(atr_list) else None
    if atr is None or atr <= 0:
        return None

    close = candles[bar]['close']
    open_p = candles[bar]['open']
    prev_high = candles[bar - 1]['high']

    if close <= open_p:
        return None  # must be bullish

    body = abs(close - open_p)
    disp_ratio = body / atr

    if disp_ratio < params['disp_thresh']:
        return None
    if close <= prev_high:
        return None  # must break prev high

    tp = close * (1 + params['tp_pct'] / 100)
    sl = close * (1 - params['sl_pct'] / 100)
    if sl <= 0 or sl >= close:
        return None

    strength = min(disp_ratio / params['disp_thresh'], 3.0)

    return {
        'stop_price': sl,
        'target_price': tp,
        'time_limit': params.get('time_limit', 12),
        'strength': strength,
    }


# -------------------------------------------------------------------
# H17 WICK_REJECTION
# -------------------------------------------------------------------
def signal_h17_wick_rejection(candles, bar, indicators, params):
    """H17 WICK_REJECTION: Long lower wick with volume confirmation (hammer).

    lower_wick > wick_pct * candle_range AND volume > vol_mult * vol_avg
    AND close in upper 30% of range.
    """
    if bar < 1:
        return None
    n = indicators.get('n', 0)
    if bar >= n:
        return None

    vol_avg_list = indicators.get('vol_avg')
    if vol_avg_list is None:
        return None
    vol_avg = vol_avg_list[bar] if bar < len(vol_avg_list) else None
    if vol_avg is None or vol_avg <= 0:
        return None

    c = candles[bar]
    close = c['close']
    open_p = c['open']
    high = c['high']
    low = c['low']
    volume = c.get('volume', 0)

    candle_range = high - low
    if candle_range <= 0:
        return None

    lower_wick = min(close, open_p) - low

    if lower_wick < params['wick_pct'] * candle_range:
        return None
    if volume < params['vol_mult'] * vol_avg:
        return None

    # Close must be in upper 30% of range
    close_position = (close - low) / candle_range
    if close_position < 0.7:
        return None

    tp = close * (1 + params['tp_pct'] / 100)
    sl = low  # stop at the wick low
    if sl <= 0 or sl >= close:
        return None

    strength = lower_wick / candle_range * (volume / vol_avg)
    return {
        'stop_price': sl,
        'target_price': tp,
        'time_limit': params.get('time_limit', 10),
        'strength': min(strength, 5.0),
    }


# -------------------------------------------------------------------
# H18 VOL_EXPANSION
# -------------------------------------------------------------------
def signal_h18_vol_expansion(candles, bar, indicators, params):
    """H18 VOL_EXPANSION: Volatility compression then expansion breakout.

    ATR ratio < 1.0 for last compress_bars (compression),
    then current ATR ratio crosses above expansion_thresh.
    Must be bullish (close > open).
    """
    n = indicators.get('n', 0)
    compress_bars = params['compress_bars']
    if bar < compress_bars + 1 or bar >= n:
        return None

    atr_list = indicators.get('atr')
    if atr_list is None:
        return None
    if atr_list[bar] is None:
        return None

    close = candles[bar]['close']
    if close <= 0:
        return None

    # Compute ATR ratios inline (don't depend on extended indicators)
    # Get ATR mean over last 50 bars
    atr_vals = []
    for j in range(max(0, bar - 49), bar + 1):
        if j < len(atr_list) and atr_list[j] is not None:
            atr_vals.append(atr_list[j])
    if len(atr_vals) < 10:
        return None
    mean_atr = sum(atr_vals) / len(atr_vals)
    if mean_atr <= 0:
        return None

    cur_ratio = atr_list[bar] / mean_atr

    # Check compression: previous compress_bars all had ratio < 1.0 (below average)
    for offset in range(1, compress_bars + 1):
        prev_bar = bar - offset
        if prev_bar < 0 or atr_list[prev_bar] is None:
            return None
        prev_ratio = atr_list[prev_bar] / mean_atr
        if prev_ratio >= 1.0:
            return None  # not compressed

    # Current bar must show expansion
    if cur_ratio < params['expansion_thresh']:
        return None

    # Must be bullish (close > open)
    if close <= candles[bar]['open']:
        return None

    tp = close * (1 + params['tp_pct'] / 100)
    sl = close * (1 - params['sl_pct'] / 100)
    if sl <= 0 or sl >= close:
        return None

    strength = cur_ratio / params['expansion_thresh']

    return {
        'stop_price': sl,
        'target_price': tp,
        'time_limit': params.get('time_limit', 15),
        'strength': min(strength, 3.0),
    }


# -------------------------------------------------------------------
# H19 GAP_PROXY
# -------------------------------------------------------------------
def signal_h19_gap_proxy(candles, bar, indicators, params):
    """H19 GAP_PROXY: Fade large gap-down (open much lower than prev_close).

    |open - prev_close| / prev_close > gap_thresh, gap is DOWN,
    current close > open (recovering). Long-only: only fades gap-downs.
    """
    if bar < 1:
        return None
    n = indicators.get('n', 0)
    if bar >= n:
        return None

    atr_list = indicators.get('atr')
    if atr_list is None:
        return None
    atr = atr_list[bar] if bar < len(atr_list) else None
    if atr is None:
        return None

    cur = candles[bar]
    prev = candles[bar - 1]
    open_p = cur['open']
    close = cur['close']
    prev_close = prev['close']

    if prev_close <= 0:
        return None

    gap = (open_p - prev_close) / prev_close

    if abs(gap) < params['gap_thresh']:
        return None

    # Long-only: fade gap-downs (open much LOWER than prev close)
    if gap >= 0:
        return None  # gap up -- no long signal for fading

    # Gap down detected, expect bounce
    # Confirmation: current close must be recovering (close > open)
    if close <= open_p:
        return None

    tp = close * (1 + params['tp_pct'] / 100)
    sl = close * (1 - params['sl_pct'] / 100)
    if sl <= 0 or sl >= close:
        return None

    strength = abs(gap) / params['gap_thresh']

    return {
        'stop_price': sl,
        'target_price': tp,
        'time_limit': params.get('time_limit', 8),
        'strength': min(strength, 3.0),
    }


# -------------------------------------------------------------------
# H20 VWAP_DEVIATION
# -------------------------------------------------------------------
def signal_h20_vwap_deviation(candles, bar, indicators, params):
    """H20 VWAP_DEVIATION: Price significantly below VWAP, bouncing back.

    (vwap - close) / ATR > dev_thresh AND close > prev_close (bounce).
    Returns None for coins without VWAP data.
    """
    if bar < 1:
        return None
    n = indicators.get('n', 0)
    if bar >= n:
        return None

    # Check VWAP availability
    if not indicators.get('has_vwap', False):
        return None
    vwaps = indicators.get('vwaps', [])
    if bar >= len(vwaps) or vwaps[bar] is None:
        return None

    atr_list = indicators.get('atr')
    if atr_list is None:
        return None
    atr = atr_list[bar] if bar < len(atr_list) else None
    if atr is None or atr <= 0:
        return None

    close = candles[bar]['close']
    prev_close = candles[bar - 1]['close']
    vwap = vwaps[bar]

    # VWAP above close -> price is below VWAP
    deviation = (vwap - close) / atr
    if deviation < params['dev_thresh']:
        return None

    # Bounce confirmation
    if close <= prev_close:
        return None

    tp = close * (1 + params['tp_pct'] / 100)
    sl = close * (1 - params['sl_pct'] / 100)
    if sl <= 0 or sl >= close:
        return None

    strength = deviation / params['dev_thresh']

    return {
        'stop_price': sl,
        'target_price': tp,
        'time_limit': params.get('time_limit', 10),
        'strength': min(strength, 3.0),
    }


# ===================================================================
# PARAMETER GRIDS (6 variants each)
# ===================================================================

GRID_H16 = [
    {'disp_thresh': 2.0, 'tp_pct': 6, 'sl_pct': 4, 'time_limit': 12},
    {'disp_thresh': 2.0, 'tp_pct': 10, 'sl_pct': 6, 'time_limit': 12},
    {'disp_thresh': 2.5, 'tp_pct': 6, 'sl_pct': 4, 'time_limit': 12},
    {'disp_thresh': 2.5, 'tp_pct': 10, 'sl_pct': 6, 'time_limit': 12},
    {'disp_thresh': 3.0, 'tp_pct': 6, 'sl_pct': 4, 'time_limit': 12},
    {'disp_thresh': 3.0, 'tp_pct': 10, 'sl_pct': 6, 'time_limit': 12},
]

GRID_H17 = [
    {'wick_pct': 0.6, 'vol_mult': 1.5, 'tp_pct': 6, 'sl_pct': 4, 'time_limit': 10},
    {'wick_pct': 0.6, 'vol_mult': 2.0, 'tp_pct': 10, 'sl_pct': 6, 'time_limit': 10},
    {'wick_pct': 0.7, 'vol_mult': 1.5, 'tp_pct': 6, 'sl_pct': 4, 'time_limit': 10},
    {'wick_pct': 0.7, 'vol_mult': 2.0, 'tp_pct': 10, 'sl_pct': 6, 'time_limit': 10},
    {'wick_pct': 0.8, 'vol_mult': 1.5, 'tp_pct': 6, 'sl_pct': 4, 'time_limit': 10},
    {'wick_pct': 0.8, 'vol_mult': 2.0, 'tp_pct': 10, 'sl_pct': 6, 'time_limit': 10},
]

GRID_H18 = [
    {'compress_bars': 3, 'expansion_thresh': 1.3, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 15},
    {'compress_bars': 3, 'expansion_thresh': 1.5, 'tp_pct': 12, 'sl_pct': 7, 'time_limit': 15},
    {'compress_bars': 3, 'expansion_thresh': 1.8, 'tp_pct': 12, 'sl_pct': 7, 'time_limit': 15},
    {'compress_bars': 5, 'expansion_thresh': 1.3, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 15},
    {'compress_bars': 5, 'expansion_thresh': 1.5, 'tp_pct': 12, 'sl_pct': 7, 'time_limit': 15},
    {'compress_bars': 5, 'expansion_thresh': 1.8, 'tp_pct': 12, 'sl_pct': 7, 'time_limit': 15},
]

GRID_H19 = [
    {'gap_thresh': 0.01, 'tp_pct': 4, 'sl_pct': 3, 'time_limit': 8},
    {'gap_thresh': 0.01, 'tp_pct': 6, 'sl_pct': 5, 'time_limit': 8},
    {'gap_thresh': 0.015, 'tp_pct': 4, 'sl_pct': 3, 'time_limit': 8},
    {'gap_thresh': 0.015, 'tp_pct': 6, 'sl_pct': 5, 'time_limit': 8},
    {'gap_thresh': 0.02, 'tp_pct': 4, 'sl_pct': 3, 'time_limit': 8},
    {'gap_thresh': 0.02, 'tp_pct': 6, 'sl_pct': 5, 'time_limit': 8},
]

GRID_H20 = [
    {'dev_thresh': 1.0, 'tp_pct': 5, 'sl_pct': 3, 'time_limit': 10},
    {'dev_thresh': 1.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10},
    {'dev_thresh': 1.5, 'tp_pct': 5, 'sl_pct': 3, 'time_limit': 10},
    {'dev_thresh': 1.5, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10},
    {'dev_thresh': 2.0, 'tp_pct': 5, 'sl_pct': 3, 'time_limit': 10},
    {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10},
]


# ===================================================================
# REGISTRATION
# ===================================================================

register_s5(HypothesisS5(
    id='H16', name='DISPLACEMENT_BAR', category='microstructure',
    signal_fn=signal_h16_displacement_bar, param_grid=GRID_H16,
    description='Big bullish displacement candle: body/ATR > threshold with close breaking prev high.',
))

register_s5(HypothesisS5(
    id='H17', name='WICK_REJECTION', category='microstructure',
    signal_fn=signal_h17_wick_rejection, param_grid=GRID_H17,
    description='Hammer/wick rejection: long lower wick with volume spike, close in upper 30% of range.',
))

register_s5(HypothesisS5(
    id='H18', name='VOL_EXPANSION', category='microstructure',
    signal_fn=signal_h18_vol_expansion, param_grid=GRID_H18,
    description='Volatility compression-expansion: ATR below average for N bars then sudden expansion breakout.',
))

register_s5(HypothesisS5(
    id='H19', name='GAP_PROXY', category='microstructure',
    signal_fn=signal_h19_gap_proxy, param_grid=GRID_H19,
    description='Gap-down fade: large open-to-prev_close gap down with bullish recovery candle.',
))

register_s5(HypothesisS5(
    id='H20', name='VWAP_DEVIATION', category='microstructure',
    signal_fn=signal_h20_vwap_deviation, param_grid=GRID_H20,
    description='VWAP mean reversion: price significantly below VWAP with bounce confirmation.',
))


# ===================================================================
# PUBLIC API
# ===================================================================

def get_all_hypotheses_s5() -> list[HypothesisS5]:
    """Return all registered Sprint 5 hypotheses as a list."""
    return list(REGISTRY_S5.values())


def get_hypothesis_s5(hyp_id: str) -> HypothesisS5:
    """Return a single hypothesis by ID. Raises KeyError if not found."""
    return REGISTRY_S5[hyp_id]


def get_all_configs_s5() -> list[tuple[str, dict]]:
    """Return list of (hypothesis_id, params) for every variant across all S5 hypotheses."""
    result = []
    for hyp in REGISTRY_S5.values():
        for params in hyp.param_grid:
            result.append((hyp.id, params))
    return result


# ===================================================================
# CATEGORY: MARKET STATE (H21-H23)
# ===================================================================

# -------------------------------------------------------------------
# H21 BTC_REGIME_MR
# -------------------------------------------------------------------
def signal_h21_btc_regime_mr(candles, bar, indicators, params):
    """H21 BTC_REGIME_MR: Mean reversion only when BTC is calm.

    BTC ATR_ratio < calm_thresh (calm market)
    AND coin RSI < rsi_thresh (oversold)
    AND close > prev_close (bounce).
    """
    if bar < 1:
        return None
    n = indicators.get('n', 0)
    if bar >= n:
        return None

    # Require __market__ context
    market = params.get('__market__')
    if market is None:
        return None

    btc_atr_ratio = market.get('btc_atr_ratio')
    if btc_atr_ratio is None or bar >= len(btc_atr_ratio):
        return None
    if btc_atr_ratio[bar] is None:
        return None

    # BTC must be calm
    if btc_atr_ratio[bar] >= params['calm_thresh']:
        return None

    # Coin RSI must be oversold
    rsi_list = indicators.get('rsi')
    if rsi_list is None:
        return None
    rsi = rsi_list[bar] if bar < len(rsi_list) else None
    if rsi is None:
        return None
    if rsi >= params['rsi_thresh']:
        return None

    close = candles[bar]['close']
    prev_close = candles[bar - 1]['close']

    # Bounce confirmation
    if close <= prev_close:
        return None

    sl_pct = 5
    tp = close * (1 + params['tp_pct'] / 100)
    sl = close * (1 - sl_pct / 100)
    if sl <= 0 or sl >= close:
        return None

    strength = (params['rsi_thresh'] - rsi) / params['rsi_thresh']

    return {
        'stop_price': sl,
        'target_price': tp,
        'time_limit': params.get('time_limit', 12),
        'strength': min(max(strength, 0.1), 3.0),
    }


# -------------------------------------------------------------------
# H22 BREADTH_MOMENTUM
# -------------------------------------------------------------------
def signal_h22_breadth_momentum(candles, bar, indicators, params):
    """H22 BREADTH_MOMENTUM: Buy when market breadth recovers.

    breadth_up crosses above breadth_thresh from below (recovery)
    AND coin is green (close > open) AND vol > vol_avg.
    """
    if bar < 1:
        return None
    n = indicators.get('n', 0)
    if bar >= n:
        return None

    # Require __market__ context
    market = params.get('__market__')
    if market is None:
        return None

    breadth_up = market.get('breadth_up')
    if breadth_up is None or bar >= len(breadth_up):
        return None
    if breadth_up[bar] is None:
        return None

    lookback = params['lookback']
    thresh = params['breadth_thresh']

    # Current breadth must be above threshold
    if breadth_up[bar] <= thresh:
        return None

    # At least one of last lookback breadths must have been below threshold
    crossed = False
    for offset in range(1, lookback + 1):
        prev_bar = bar - offset
        if prev_bar < 0:
            break
        if prev_bar < len(breadth_up) and breadth_up[prev_bar] is not None:
            if breadth_up[prev_bar] < thresh:
                crossed = True
                break
    if not crossed:
        return None

    close = candles[bar]['close']
    open_p = candles[bar]['open']

    # Coin must be green
    if close <= open_p:
        return None

    # Volume confirmation
    vol_avg_list = indicators.get('vol_avg')
    if vol_avg_list is None:
        return None
    vol_avg = vol_avg_list[bar] if bar < len(vol_avg_list) else None
    if vol_avg is None or vol_avg <= 0:
        return None
    volume = candles[bar].get('volume', 0)
    if volume <= vol_avg:
        return None

    sl_pct = 5
    tp = close * (1 + params['tp_pct'] / 100)
    sl = close * (1 - sl_pct / 100)
    if sl <= 0 or sl >= close:
        return None

    strength = breadth_up[bar] * (volume / vol_avg)

    return {
        'stop_price': sl,
        'target_price': tp,
        'time_limit': params.get('time_limit', 12),
        'strength': min(strength, 5.0),
    }


# -------------------------------------------------------------------
# H23 DECORRELATION
# -------------------------------------------------------------------
def signal_h23_decorrelation(candles, bar, indicators, params):
    """H23 DECORRELATION: Coin diverges positively from market.

    Coin return over lookback bars > decorr_thresh * ATR_ratio
    AND market breadth < 0.5 (market down but coin up).
    Uses existing __market__ data (btc_atr_ratio, breadth_up).
    """
    lookback = params['lookback']
    if bar < lookback:
        return None
    n = indicators.get('n', 0)
    if bar >= n:
        return None

    # Require __market__ context
    market = params.get('__market__')
    if market is None:
        return None

    btc_atr_ratio = market.get('btc_atr_ratio')
    breadth_up = market.get('breadth_up')
    if btc_atr_ratio is None or breadth_up is None:
        return None
    if bar >= len(btc_atr_ratio) or bar >= len(breadth_up):
        return None
    if btc_atr_ratio[bar] is None or breadth_up[bar] is None:
        return None

    # Market must be weak (breadth < 0.5)
    if breadth_up[bar] >= 0.5:
        return None

    # Compute coin return over lookback bars
    close = candles[bar]['close']
    prev_close = candles[bar - lookback]['close']
    if prev_close <= 0:
        return None
    coin_return = (close - prev_close) / prev_close

    # Coin must be positive (up while market is down)
    if coin_return <= 0:
        return None

    # Divergence threshold: coin_return > decorr_thresh * atr_ratio (normalized)
    atr_ratio = btc_atr_ratio[bar]
    if atr_ratio <= 0:
        return None
    threshold = params['decorr_thresh'] * atr_ratio * 0.01  # scale to percentage
    if coin_return <= threshold:
        return None

    sl_pct = 6
    tp = close * (1 + params['tp_pct'] / 100)
    sl = close * (1 - sl_pct / 100)
    if sl <= 0 or sl >= close:
        return None

    strength = coin_return / max(threshold, 1e-9)

    return {
        'stop_price': sl,
        'target_price': tp,
        'time_limit': params.get('time_limit', 15),
        'strength': min(strength, 5.0),
    }


# ===================================================================
# CATEGORY: CROSS-SECTIONAL (H24-H25)
# ===================================================================

# -------------------------------------------------------------------
# H24 MOMENTUM_RANK
# -------------------------------------------------------------------
def signal_h24_momentum_rank(candles, bar, indicators, params):
    """H24 MOMENTUM_RANK: Trade only top-ranked momentum coins.

    Coin must be in top top_n by momentum_rank AND vol > vol_avg.
    Requires params['__coin__'] and params['__market__']['momentum_rank'].
    """
    if bar < 1:
        return None
    n = indicators.get('n', 0)
    if bar >= n:
        return None

    # Require __market__ and __coin__ context
    market = params.get('__market__')
    if market is None:
        return None
    coin_symbol = indicators.get('__coin__')
    if coin_symbol is None:
        return None

    momentum_rank = market.get('momentum_rank')
    if momentum_rank is None:
        return None
    coin_ranks = momentum_rank.get(coin_symbol)
    if coin_ranks is None or bar >= len(coin_ranks):
        return None
    rank = coin_ranks[bar]
    if rank is None:
        return None

    # Must be in top N
    if rank > params['top_n']:
        return None

    # Volume confirmation
    vol_avg_list = indicators.get('vol_avg')
    if vol_avg_list is None:
        return None
    vol_avg = vol_avg_list[bar] if bar < len(vol_avg_list) else None
    if vol_avg is None or vol_avg <= 0:
        return None
    volume = candles[bar].get('volume', 0)
    if volume <= vol_avg:
        return None

    close = candles[bar]['close']
    sl_pct = 6
    tp = close * (1 + params['tp_pct'] / 100)
    sl = close * (1 - sl_pct / 100)
    if sl <= 0 or sl >= close:
        return None

    # Strength: higher rank = higher strength. N = total coins estimated.
    total_coins = len(momentum_rank)
    if total_coins <= 0:
        total_coins = 1
    strength = (total_coins - rank + 1) / total_coins

    return {
        'stop_price': sl,
        'target_price': tp,
        'time_limit': params.get('time_limit', 15),
        'strength': min(max(strength, 0.1), 3.0),
    }


# -------------------------------------------------------------------
# H25 MEAN_REVERT_RANK
# -------------------------------------------------------------------
def signal_h25_mean_revert_rank(candles, bar, indicators, params):
    """H25 MEAN_REVERT_RANK: Trade only most oversold coins by rank.

    Coin must be in top top_n by mean_revert_rank
    AND bounce (close > prev_close).
    Requires params['__coin__'] and params['__market__']['mean_revert_rank'].
    """
    if bar < 1:
        return None
    n = indicators.get('n', 0)
    if bar >= n:
        return None

    # Require __market__ and __coin__ context
    market = params.get('__market__')
    if market is None:
        return None
    coin_symbol = indicators.get('__coin__')
    if coin_symbol is None:
        return None

    mean_revert_rank = market.get('mean_revert_rank')
    if mean_revert_rank is None:
        return None
    coin_ranks = mean_revert_rank.get(coin_symbol)
    if coin_ranks is None or bar >= len(coin_ranks):
        return None
    rank = coin_ranks[bar]
    if rank is None:
        return None

    # Must be in top N (most oversold)
    if rank > params['top_n']:
        return None

    close = candles[bar]['close']
    prev_close = candles[bar - 1]['close']

    # Bounce confirmation
    if close <= prev_close:
        return None

    sl_pct = 5
    tp = close * (1 + params['tp_pct'] / 100)
    sl = close * (1 - sl_pct / 100)
    if sl <= 0 or sl >= close:
        return None

    # Strength: higher rank = higher strength
    total_coins = len(mean_revert_rank)
    if total_coins <= 0:
        total_coins = 1
    strength = (total_coins - rank + 1) / total_coins

    return {
        'stop_price': sl,
        'target_price': tp,
        'time_limit': params.get('time_limit', 12),
        'strength': min(max(strength, 0.1), 3.0),
    }


# ===================================================================
# PARAMETER GRIDS H21-H25 (6 variants each)
# ===================================================================

GRID_H21 = [
    {'calm_thresh': 0.7, 'rsi_thresh': 25, 'tp_pct': 6, 'time_limit': 12},
    {'calm_thresh': 0.7, 'rsi_thresh': 30, 'tp_pct': 8, 'time_limit': 12},
    {'calm_thresh': 0.8, 'rsi_thresh': 25, 'tp_pct': 8, 'time_limit': 12},
    {'calm_thresh': 0.8, 'rsi_thresh': 35, 'tp_pct': 6, 'time_limit': 12},
    {'calm_thresh': 0.9, 'rsi_thresh': 30, 'tp_pct': 6, 'time_limit': 12},
    {'calm_thresh': 0.9, 'rsi_thresh': 35, 'tp_pct': 8, 'time_limit': 12},
]

GRID_H22 = [
    {'breadth_thresh': 0.45, 'lookback': 3, 'tp_pct': 6, 'time_limit': 12},
    {'breadth_thresh': 0.45, 'lookback': 5, 'tp_pct': 10, 'time_limit': 12},
    {'breadth_thresh': 0.50, 'lookback': 3, 'tp_pct': 10, 'time_limit': 12},
    {'breadth_thresh': 0.50, 'lookback': 5, 'tp_pct': 6, 'time_limit': 12},
    {'breadth_thresh': 0.55, 'lookback': 3, 'tp_pct': 6, 'time_limit': 12},
    {'breadth_thresh': 0.55, 'lookback': 5, 'tp_pct': 10, 'time_limit': 12},
]

GRID_H23 = [
    {'decorr_thresh': 1.5, 'lookback': 10, 'tp_pct': 8, 'time_limit': 15},
    {'decorr_thresh': 1.5, 'lookback': 20, 'tp_pct': 12, 'time_limit': 15},
    {'decorr_thresh': 2.0, 'lookback': 10, 'tp_pct': 12, 'time_limit': 15},
    {'decorr_thresh': 2.0, 'lookback': 20, 'tp_pct': 8, 'time_limit': 15},
    {'decorr_thresh': 2.5, 'lookback': 10, 'tp_pct': 8, 'time_limit': 15},
    {'decorr_thresh': 2.5, 'lookback': 20, 'tp_pct': 12, 'time_limit': 15},
]

GRID_H24 = [
    {'lookback': 5, 'top_n': 3, 'tp_pct': 8, 'time_limit': 15},
    {'lookback': 5, 'top_n': 5, 'tp_pct': 12, 'time_limit': 15},
    {'lookback': 10, 'top_n': 3, 'tp_pct': 12, 'time_limit': 15},
    {'lookback': 10, 'top_n': 5, 'tp_pct': 8, 'time_limit': 15},
    {'lookback': 20, 'top_n': 3, 'tp_pct': 8, 'time_limit': 15},
    {'lookback': 20, 'top_n': 5, 'tp_pct': 12, 'time_limit': 15},
]

GRID_H25 = [
    {'top_n': 3, 'rsi_weight': 0.5, 'tp_pct': 6, 'time_limit': 12},
    {'top_n': 3, 'rsi_weight': 0.7, 'tp_pct': 10, 'time_limit': 12},
    {'top_n': 5, 'rsi_weight': 0.5, 'tp_pct': 10, 'time_limit': 12},
    {'top_n': 5, 'rsi_weight': 0.7, 'tp_pct': 6, 'time_limit': 12},
    {'top_n': 3, 'rsi_weight': 0.5, 'tp_pct': 10, 'time_limit': 12},
    {'top_n': 5, 'rsi_weight': 0.7, 'tp_pct': 10, 'time_limit': 12},
]


# ===================================================================
# REGISTRATION H21-H25
# ===================================================================

register_s5(HypothesisS5(
    id='H21', name='BTC_REGIME_MR', category='market_state',
    signal_fn=signal_h21_btc_regime_mr, param_grid=GRID_H21,
    description='Mean reversion when BTC is calm: low BTC ATR ratio + oversold RSI + bounce.',
))

register_s5(HypothesisS5(
    id='H22', name='BREADTH_MOMENTUM', category='market_state',
    signal_fn=signal_h22_breadth_momentum, param_grid=GRID_H22,
    description='Breadth recovery: market breadth crosses above threshold + green candle + volume.',
))

register_s5(HypothesisS5(
    id='H23', name='DECORRELATION', category='market_state',
    signal_fn=signal_h23_decorrelation, param_grid=GRID_H23,
    description='Coin diverges positively from weak market: positive return while breadth < 0.5.',
))

register_s5(HypothesisS5(
    id='H24', name='MOMENTUM_RANK', category='cross_sectional',
    signal_fn=signal_h24_momentum_rank, param_grid=GRID_H24,
    description='Top momentum coins: rank in top_n by momentum + volume confirmation.',
))

register_s5(HypothesisS5(
    id='H25', name='MEAN_REVERT_RANK', category='cross_sectional',
    signal_fn=signal_h25_mean_revert_rank, param_grid=GRID_H25,
    description='Most oversold coins: rank in top_n by mean reversion + bounce confirmation.',
))

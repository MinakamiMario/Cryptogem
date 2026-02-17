"""15 Hypothesis Definitions for Sprint 4 Screening.

Each hypothesis defines a signal function, parameter grid (max 6 variants),
and metadata.  Signal functions are causal (no look-ahead) and return None
when conditions are not met or data is insufficient.
"""

from dataclasses import dataclass
from typing import Callable, Optional

from strategies.hf.screening.indicators import (
    calc_ema,
    calc_sma,
    calc_stochastic,
    calc_macd,
    calc_rsi,
    calc_atr,
    calc_bollinger,
    calc_donchian,
    calc_rsi_divergence,
    calc_roc,
    calc_higher_low,
    calc_bb_width,
)


# ---------------------------------------------------------------------------
# Hypothesis dataclass and registry
# ---------------------------------------------------------------------------

@dataclass
class Hypothesis:
    id: str            # H01, H02, ...
    name: str          # RSI_EXTREME, BB_REVERT, ...
    category: str      # mean_reversion, momentum, volume, price_action, multi_indicator
    signal_fn: Callable
    param_grid: list   # list of param dicts (max 6 variants)
    description: str


REGISTRY: dict[str, Hypothesis] = {}


def register(hyp: Hypothesis):
    """Add a hypothesis to the global registry."""
    REGISTRY[hyp.id] = hyp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_close(candles, bar):
    """Return close price at bar, or None if out of range."""
    if bar < 0 or bar >= len(candles):
        return None
    return candles[bar].get('close')


def _safe_prev_close(candles, bar):
    """Return previous close price, or None if bar < 1."""
    if bar < 1:
        return None
    return candles[bar - 1].get('close')


def _base_checks(candles, bar, indicators):
    """Common null-safety checks.  Returns True if data is valid."""
    if bar < 1 or bar >= len(candles):
        return False
    if indicators.get('rsi') is None or indicators['rsi'][bar] is None:
        return False
    if indicators.get('atr') is None or indicators['atr'][bar] is None:
        return False
    close = candles[bar].get('close')
    if close is None or close <= 0:
        return False
    return True


# ===================================================================
# CATEGORY A: MEAN REVERSION (H01-H04)
# ===================================================================

def signal_h01_rsi_extreme(candles, bar, indicators, params):
    """H01 RSI_EXTREME: RSI(14) < threshold AND close > prev_close (bounce)."""
    if not _base_checks(candles, bar, indicators):
        return None

    rsi = indicators['rsi'][bar]
    close = candles[bar]['close']
    prev_close = candles[bar - 1]['close']
    atr = indicators['atr'][bar]

    rsi_thresh = params['rsi_thresh']
    tp_pct = params['tp_pct']
    sl_pct = params['sl_pct']
    time_limit = params.get('time_limit', 12)

    if rsi >= rsi_thresh:
        return None
    if close <= prev_close:
        return None

    target_price = close * (1 + tp_pct / 100)
    stop_price = close * (1 - sl_pct / 100)

    # Strength: how oversold (lower RSI = stronger signal)
    strength = max(0.0, (rsi_thresh - rsi) / rsi_thresh)

    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
    }


def signal_h02_bb_revert(candles, bar, indicators, params):
    """H02 BB_REVERT: close < bb_lower AND close > prev_close."""
    if not _base_checks(candles, bar, indicators):
        return None

    close = candles[bar]['close']
    prev_close = candles[bar - 1]['close']
    atr = indicators['atr'][bar]

    bb_period = params['bb_period']
    bb_dev = params['bb_dev']
    time_limit = params.get('time_limit', 15)

    closes = indicators['closes'][:bar + 1]
    if len(closes) < bb_period:
        return None

    # Compute BB for the requested period/dev (on demand)
    bb_mid, bb_upper, bb_lower = calc_bollinger(closes, period=bb_period, dev=bb_dev)
    if bb_mid is None or bb_lower is None:
        return None

    if close >= bb_lower:
        return None
    if close <= prev_close:
        return None

    target_price = bb_mid
    stop_price = bb_lower - atr

    if stop_price <= 0 or target_price <= close:
        return None

    strength = 1.0
    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
    }


def signal_h03_stoch_cross(candles, bar, indicators, params):
    """H03 STOCH_CROSS: Stochastic K < 20 AND K crosses above D."""
    if not _base_checks(candles, bar, indicators):
        return None

    close = candles[bar]['close']

    k_period = params['k_period']
    tp_pct = params['tp_pct']
    sl_pct = params['sl_pct']
    time_limit = params.get('time_limit', 10)

    highs = indicators['highs'][:bar + 1]
    lows = indicators['lows'][:bar + 1]
    closes = indicators['closes'][:bar + 1]

    min_bars = k_period + 3 + 1  # need d_period=3 + 1 extra for crossover
    if len(closes) < min_bars:
        return None

    # Current K, D
    k_cur, d_cur = calc_stochastic(highs, lows, closes, k_period=k_period, d_period=3)

    # Previous K, D (one bar earlier)
    k_prev, d_prev = calc_stochastic(
        highs[:-1], lows[:-1], closes[:-1], k_period=k_period, d_period=3
    )

    # K < 20 (oversold) and cross above D
    if k_cur >= 20:
        return None
    if not (k_prev <= d_prev and k_cur > d_cur):
        return None

    target_price = close * (1 + tp_pct / 100)
    stop_price = close * (1 - sl_pct / 100)

    strength = max(0.0, (20 - k_cur) / 20)
    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
    }


def signal_h04_rsi_divergence(candles, bar, indicators, params):
    """H04 RSI_DIVERGENCE: Bullish divergence (price lower low, RSI higher low)."""
    if not _base_checks(candles, bar, indicators):
        return None

    close = candles[bar]['close']

    lookback = params['lookback']
    tp_pct = params['tp_pct']
    sl_pct = params.get('sl_pct', 5)
    time_limit = params.get('time_limit', 15)

    if bar < lookback:
        return None

    closes = indicators['closes'][:bar + 1]

    # Build RSI values for the lookback window
    rsi_values = []
    for i in range(bar - lookback + 1, bar + 1):
        r = indicators['rsi'][i]
        if r is None:
            return None
        rsi_values.append(r)

    price_window = closes[-lookback:]

    div = calc_rsi_divergence(price_window, rsi_values, lookback=lookback)
    if div != 1:  # only bullish divergence
        return None

    target_price = close * (1 + tp_pct / 100)
    stop_price = close * (1 - sl_pct / 100)

    strength = 1.0
    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
    }


# ===================================================================
# CATEGORY B: MOMENTUM / BREAKOUT (H05-H08)
# ===================================================================

def signal_h05_dc_breakout_up(candles, bar, indicators, params):
    """H05 DC_BREAKOUT_UP: high > Donchian upper (breakout)."""
    if not _base_checks(candles, bar, indicators):
        return None

    close = candles[bar]['close']
    high = candles[bar]['high']
    atr = indicators['atr'][bar]

    dc_period = params['dc_period']
    atr_mult = params['atr_mult']
    tp_pct = params.get('tp_pct', 15)
    time_limit = params.get('time_limit', 20)

    if bar < dc_period:
        return None

    highs = indicators['highs'][:bar + 1]
    lows = indicators['lows'][:bar + 1]

    # DC upper = max of highs BEFORE current bar (lookback period ending bar-1)
    dc_upper = max(highs[bar - dc_period:bar])

    if high <= dc_upper:
        return None

    stop_price = close - atr_mult * atr
    target_price = close * (1 + tp_pct / 100)

    if stop_price <= 0:
        return None

    # Strength: how far above the channel
    strength = (high - dc_upper) / dc_upper if dc_upper > 0 else 1.0

    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': min(strength, 2.0),
    }


def signal_h06_ema_cross(candles, bar, indicators, params):
    """H06 EMA_CROSS: EMA fast crosses above EMA slow."""
    if not _base_checks(candles, bar, indicators):
        return None

    close = candles[bar]['close']

    ema_fast_period = params['ema_fast']
    ema_slow_period = params['ema_slow']
    tp_pct = params.get('tp_pct', 10)
    sl_pct = params.get('sl_pct', 5)
    time_limit = params.get('time_limit', 20)

    # Need enough data for slow EMA + 1 bar for crossover detection
    min_bars = ema_slow_period + 1
    if bar < min_bars:
        return None

    closes = indicators['closes'][:bar + 1]
    closes_prev = closes[:-1]

    # Current EMA values
    ema_fast_cur = calc_ema(closes, ema_fast_period)
    ema_slow_cur = calc_ema(closes, ema_slow_period)

    # Previous EMA values (one bar earlier)
    ema_fast_prev = calc_ema(closes_prev, ema_fast_period)
    ema_slow_prev = calc_ema(closes_prev, ema_slow_period)

    # Crossover: fast was below slow, now fast is above slow
    if not (ema_fast_prev <= ema_slow_prev and ema_fast_cur > ema_slow_cur):
        return None

    target_price = close * (1 + tp_pct / 100)
    stop_price = close * (1 - sl_pct / 100)

    strength = 1.0
    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
    }


def signal_h07_macd_cross(candles, bar, indicators, params):
    """H07 MACD_CROSS: MACD histogram goes from negative to positive."""
    if not _base_checks(candles, bar, indicators):
        return None

    close = candles[bar]['close']

    macd_fast = params['macd_fast']
    macd_slow = params['macd_slow']
    macd_signal = params['macd_signal']
    tp_pct = params.get('tp_pct', 8)
    sl_pct = params.get('sl_pct', 6)
    time_limit = params.get('time_limit', 15)

    min_bars = macd_slow + macd_signal + 1
    if bar < min_bars:
        return None

    closes = indicators['closes'][:bar + 1]
    closes_prev = closes[:-1]

    _, _, hist_cur = calc_macd(closes, fast=macd_fast, slow=macd_slow, signal=macd_signal)
    _, _, hist_prev = calc_macd(closes_prev, fast=macd_fast, slow=macd_slow, signal=macd_signal)

    # Histogram crosses from negative to positive
    if not (hist_prev <= 0 and hist_cur > 0):
        return None

    target_price = close * (1 + tp_pct / 100)
    stop_price = close * (1 - sl_pct / 100)

    strength = 1.0
    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
    }


def signal_h08_acceleration(candles, bar, indicators, params):
    """H08 ACCELERATION: ROC acceleration > threshold AND close > prev_close."""
    if not _base_checks(candles, bar, indicators):
        return None

    close = candles[bar]['close']
    prev_close = candles[bar - 1]['close']

    lookback = params['lookback']
    accel_thresh = params['accel_thresh']
    tp_pct = params.get('tp_pct', 10)
    sl_pct = params.get('sl_pct', 5)
    time_limit = params.get('time_limit', 12)

    # Need lookback + 1 extra bar for the previous ROC
    if bar < lookback + 1:
        return None

    closes = indicators['closes'][:bar + 1]
    closes_prev = closes[:-1]

    roc_cur = calc_roc(closes, period=lookback)
    roc_prev = calc_roc(closes_prev, period=lookback)

    # Acceleration = difference in ROC (note: calc_roc returns percentage)
    acceleration = (roc_cur - roc_prev) / 100.0  # convert to fraction

    if acceleration <= accel_thresh:
        return None
    if close <= prev_close:
        return None

    target_price = close * (1 + tp_pct / 100)
    stop_price = close * (1 - sl_pct / 100)

    strength = min(acceleration / accel_thresh, 3.0)
    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
    }


# ===================================================================
# CATEGORY C: VOLUME ANOMALY (H09-H11)
# ===================================================================

def signal_h09_vol_spike_green(candles, bar, indicators, params):
    """H09 VOL_SPIKE_GREEN: volume > vol_avg * spike_mult AND green candle."""
    if not _base_checks(candles, bar, indicators):
        return None

    close = candles[bar]['close']
    open_price = candles[bar]['open']
    volume = candles[bar].get('volume', 0)

    spike_mult = params['spike_mult']
    vol_period = params['vol_period']
    tp_pct = params.get('tp_pct', 8)
    sl_pct = params.get('sl_pct', 6)
    time_limit = params.get('time_limit', 10)

    # Compute volume average on demand for the requested period
    volumes = indicators['volumes'][:bar + 1]
    if len(volumes) < vol_period:
        return None

    vol_avg = sum(volumes[bar - vol_period:bar]) / vol_period
    if vol_avg <= 0:
        return None

    # Green candle: close > open
    if close <= open_price:
        return None

    # Volume spike
    if volume <= vol_avg * spike_mult:
        return None

    target_price = close * (1 + tp_pct / 100)
    stop_price = close * (1 - sl_pct / 100)

    # Strength: volume relative to average
    strength = volume / vol_avg

    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
    }


def signal_h10_vol_divergence(candles, bar, indicators, params):
    """H10 VOL_DIVERGENCE: Price new low + declining volume (bearish exhaustion)."""
    if not _base_checks(candles, bar, indicators):
        return None

    close = candles[bar]['close']
    volume = candles[bar].get('volume', 0)

    lookback = params['lookback']
    vol_ratio = params['vol_ratio']
    tp_pct = params.get('tp_pct', 10)
    sl_pct = params.get('sl_pct', 5)
    time_limit = params.get('time_limit', 15)

    if bar < lookback:
        return None

    closes = indicators['closes'][:bar + 1]
    volumes = indicators['volumes'][:bar + 1]

    # Price makes new low over lookback (current close < min of prior bars)
    prior_min = min(closes[bar - lookback:bar])
    if close >= prior_min:
        return None

    # Volume declining: current volume < vol_avg * vol_ratio
    if len(volumes) < lookback:
        return None
    vol_avg = sum(volumes[bar - lookback:bar]) / lookback
    if vol_avg <= 0:
        return None
    if volume >= vol_avg * vol_ratio:
        return None

    target_price = close * (1 + tp_pct / 100)
    stop_price = close * (1 - sl_pct / 100)

    # Strength: inverse of volume ratio (lower volume = stronger signal)
    vol_cur_ratio = volume / vol_avg if vol_avg > 0 else 1.0
    strength = max(0.1, 1.0 - vol_cur_ratio)

    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
    }


def signal_h11_squeeze_break(candles, bar, indicators, params):
    """H11 SQUEEZE_BREAK: BB inside DC for squeeze_bars + volume spike + up breakout."""
    if not _base_checks(candles, bar, indicators):
        return None

    close = candles[bar]['close']
    prev_close = candles[bar - 1]['close']
    volume = candles[bar].get('volume', 0)

    squeeze_bars = params['squeeze_bars']
    vol_mult = params['vol_mult']
    tp_pct = params.get('tp_pct', 12)
    sl_pct = params.get('sl_pct', 8)
    time_limit = params.get('time_limit', 20)

    # Need enough bars for BB(20) + squeeze_bars + DC(20)
    min_bars = 20 + squeeze_bars
    if bar < min_bars:
        return None

    closes = indicators['closes'][:bar + 1]
    highs = indicators['highs'][:bar + 1]
    lows = indicators['lows'][:bar + 1]
    volumes = indicators['volumes'][:bar + 1]

    # Check squeeze: BB width < DC width for last squeeze_bars bars
    for offset in range(squeeze_bars):
        b = bar - offset
        if b < 20:
            return None

        c_slice = closes[:b + 1]
        h_slice = highs[:b + 1]
        l_slice = lows[:b + 1]

        bb_mid, bb_upper, bb_lower = calc_bollinger(c_slice, period=20, dev=2.0)
        dc_upper, dc_lower, _ = calc_donchian(h_slice, l_slice, period=20)

        if bb_mid is None or dc_upper is None:
            return None

        bb_w = bb_upper - bb_lower
        dc_w = dc_upper - dc_lower

        if dc_w <= 0:
            return None
        if bb_w >= dc_w:
            return None  # BB is NOT inside DC

    # Volume spike on current bar
    vol_avg_val = indicators.get('vol_avg')
    if vol_avg_val is None or vol_avg_val[bar] is None or vol_avg_val[bar] <= 0:
        # Fallback: compute from last 20 bars
        if len(volumes) >= 20:
            vol_avg_fallback = sum(volumes[bar - 20:bar]) / 20
        else:
            return None
    else:
        vol_avg_fallback = vol_avg_val[bar]

    if volume <= vol_avg_fallback * vol_mult:
        return None

    # Breakout direction: up
    if close <= prev_close:
        return None

    target_price = close * (1 + tp_pct / 100)
    stop_price = close * (1 - sl_pct / 100)

    strength = volume / vol_avg_fallback if vol_avg_fallback > 0 else 1.0

    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
    }


# ===================================================================
# CATEGORY D: PRICE ACTION (H12-H13)
# ===================================================================

def signal_h12_engulfing(candles, bar, indicators, params):
    """H12 ENGULFING: Bullish engulfing candle + RSI < rsi_max."""
    if not _base_checks(candles, bar, indicators):
        return None
    if bar < 1:
        return None

    cur = candles[bar]
    prev = candles[bar - 1]

    rsi = indicators['rsi'][bar]
    body_ratio = params['body_ratio']
    rsi_max = params['rsi_max']
    tp_pct = params.get('tp_pct', 8)
    time_limit = params.get('time_limit', 10)

    close = cur['close']
    open_price = cur['open']
    prev_close = prev['close']
    prev_open = prev['open']

    # RSI filter
    if rsi >= rsi_max:
        return None

    # Current candle is bullish, previous is bearish
    if close <= open_price:
        return None
    if prev_close >= prev_open:
        return None

    cur_body = abs(close - open_price)
    prev_body = abs(prev_close - prev_open)

    if prev_body <= 0:
        return None

    # Current body engulfs previous body
    if not (open_price <= prev_close and close >= prev_open):
        return None

    # Body ratio check
    if cur_body < body_ratio * prev_body:
        return None

    target_price = close * (1 + tp_pct / 100)
    # SL at previous candle's low
    stop_price = prev['low']

    if stop_price <= 0 or stop_price >= close:
        return None

    strength = cur_body / prev_body

    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': min(strength, 5.0),
    }


def signal_h13_inside_break(candles, bar, indicators, params):
    """H13 INSIDE_BREAK: Inside bar (bar-1 inside bar-2) + breakout above bar-1 high."""
    if not _base_checks(candles, bar, indicators):
        return None
    if bar < 2:
        return None

    cur = candles[bar]
    prev = candles[bar - 1]     # potential inside bar
    prev2 = candles[bar - 2]    # mother bar

    min_contraction = params['min_contraction']
    sl_buffer_pct = params['sl_buffer_pct']
    tp_pct = params.get('tp_pct', 10)
    time_limit = params.get('time_limit', 15)

    close = cur['close']
    cur_high = cur['high']

    prev_high = prev['high']
    prev_low = prev['low']
    prev2_high = prev2['high']
    prev2_low = prev2['low']

    # bar-1 must be inside bar relative to bar-2
    if prev_high >= prev2_high or prev_low <= prev2_low:
        return None

    # Contraction check: (bar-1 range) / (bar-2 range) < min_contraction
    prev_range = prev_high - prev_low
    prev2_range = prev2_high - prev2_low
    if prev2_range <= 0:
        return None

    contraction = prev_range / prev2_range
    if contraction >= min_contraction:
        return None

    # Current bar breaks above bar-1's high
    if cur_high <= prev_high:
        return None

    target_price = close * (1 + tp_pct / 100)
    # SL = inside bar's low minus buffer
    stop_price = prev_low * (1 - sl_buffer_pct / 100)

    if stop_price <= 0 or stop_price >= close:
        return None

    strength = 1.0
    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
    }


# ===================================================================
# CATEGORY E: MULTI-INDICATOR (H14-H15)
# ===================================================================

def signal_h14_rsi_macd_agree(candles, bar, indicators, params):
    """H14 RSI_MACD_AGREE: RSI < rsi_max AND MACD histogram > 0."""
    if not _base_checks(candles, bar, indicators):
        return None

    close = candles[bar]['close']
    rsi = indicators['rsi'][bar]
    atr = indicators['atr'][bar]

    rsi_max = params['rsi_max']
    macd_fast = params['macd_fast']
    macd_slow = params.get('macd_slow', 26)
    macd_signal = params.get('macd_signal', 9)
    tp_pct = params.get('tp_pct', 8)
    sl_pct = params.get('sl_pct', 8)
    time_limit = params.get('time_limit', 12)

    # RSI must be oversold
    if rsi >= rsi_max:
        return None

    min_bars = macd_slow + macd_signal
    if bar < min_bars:
        return None

    closes = indicators['closes'][:bar + 1]
    _, _, histogram = calc_macd(closes, fast=macd_fast, slow=macd_slow, signal=macd_signal)

    # MACD histogram must be positive (momentum turning up)
    if histogram <= 0:
        return None

    target_price = close * (1 + tp_pct / 100)
    stop_price = close * (1 - sl_pct / 100)

    # Strength: how oversold RSI is combined with histogram magnitude
    strength = max(0.1, (rsi_max - rsi) / rsi_max)

    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
    }


def signal_h15_higher_low_vol(candles, bar, indicators, params):
    """H15 HIGHER_LOW_VOL: Higher low + volume > avg + RSI in mid-range (35-55)."""
    if not _base_checks(candles, bar, indicators):
        return None

    close = candles[bar]['close']
    volume = candles[bar].get('volume', 0)
    rsi = indicators['rsi'][bar]

    hl_lookback = params['hl_lookback']
    vol_mult = params['vol_mult']
    sl_pct = params['sl_pct']
    tp_pct = params.get('tp_pct', 8)
    time_limit = params.get('time_limit', 15)

    if bar < 2 * hl_lookback:
        return None

    # RSI must be in mid-range (35-55)
    if rsi < 35 or rsi > 55:
        return None

    lows = indicators['lows'][:bar + 1]

    # Higher low pattern
    if not calc_higher_low(lows, lookback=hl_lookback):
        return None

    # Volume > avg * vol_mult
    vol_avg_val = indicators.get('vol_avg')
    if vol_avg_val is not None and vol_avg_val[bar] is not None and vol_avg_val[bar] > 0:
        va = vol_avg_val[bar]
    else:
        # Fallback
        volumes = indicators['volumes'][:bar + 1]
        if len(volumes) < 20:
            return None
        va = sum(volumes[bar - 20:bar]) / 20
        if va <= 0:
            return None

    if volume <= va * vol_mult:
        return None

    target_price = close * (1 + tp_pct / 100)
    stop_price = close * (1 - sl_pct / 100)

    strength = volume / va if va > 0 else 1.0

    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
    }


# ===================================================================
# PARAMETER GRIDS
# ===================================================================

GRID_H01 = [
    {'rsi_thresh': 15, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 12},
    {'rsi_thresh': 15, 'tp_pct': 10, 'sl_pct': 8, 'time_limit': 12},
    {'rsi_thresh': 20, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 12},
    {'rsi_thresh': 20, 'tp_pct': 10, 'sl_pct': 8, 'time_limit': 12},
    {'rsi_thresh': 25, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 12},
    {'rsi_thresh': 25, 'tp_pct': 10, 'sl_pct': 8, 'time_limit': 12},
]

GRID_H02 = [
    {'bb_period': 15, 'bb_dev': 1.5, 'time_limit': 15},
    {'bb_period': 15, 'bb_dev': 2.0, 'time_limit': 15},
    {'bb_period': 20, 'bb_dev': 2.0, 'time_limit': 15},
    {'bb_period': 20, 'bb_dev': 2.5, 'time_limit': 15},
    {'bb_period': 30, 'bb_dev': 1.5, 'time_limit': 15},
    {'bb_period': 30, 'bb_dev': 2.5, 'time_limit': 15},
]

GRID_H03 = [
    {'k_period': 9, 'tp_pct': 6, 'sl_pct': 4, 'time_limit': 10},
    {'k_period': 9, 'tp_pct': 10, 'sl_pct': 4, 'time_limit': 10},
    {'k_period': 9, 'tp_pct': 10, 'sl_pct': 8, 'time_limit': 10},
    {'k_period': 14, 'tp_pct': 6, 'sl_pct': 4, 'time_limit': 10},
    {'k_period': 14, 'tp_pct': 6, 'sl_pct': 8, 'time_limit': 10},
    {'k_period': 14, 'tp_pct': 10, 'sl_pct': 8, 'time_limit': 10},
]

GRID_H04 = [
    {'lookback': 8, 'tp_pct': 6, 'sl_pct': 5, 'time_limit': 15},
    {'lookback': 8, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 15},
    {'lookback': 10, 'tp_pct': 6, 'sl_pct': 5, 'time_limit': 15},
    {'lookback': 10, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 15},
    {'lookback': 14, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 15},
    {'lookback': 14, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 15},
]

GRID_H05 = [
    {'dc_period': 10, 'atr_mult': 1.5, 'tp_pct': 15, 'time_limit': 20},
    {'dc_period': 10, 'atr_mult': 2.0, 'tp_pct': 15, 'time_limit': 20},
    {'dc_period': 20, 'atr_mult': 1.5, 'tp_pct': 15, 'time_limit': 20},
    {'dc_period': 20, 'atr_mult': 3.0, 'tp_pct': 15, 'time_limit': 20},
    {'dc_period': 30, 'atr_mult': 2.0, 'tp_pct': 15, 'time_limit': 20},
    {'dc_period': 30, 'atr_mult': 3.0, 'tp_pct': 15, 'time_limit': 20},
]

GRID_H06 = [
    {'ema_fast': 5, 'ema_slow': 21, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 20},
    {'ema_fast': 5, 'ema_slow': 34, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 20},
    {'ema_fast': 8, 'ema_slow': 21, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 20},
    {'ema_fast': 8, 'ema_slow': 26, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 20},
    {'ema_fast': 12, 'ema_slow': 26, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 20},
    {'ema_fast': 12, 'ema_slow': 34, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 20},
]

GRID_H07 = [
    {'macd_fast': 8, 'macd_slow': 21, 'macd_signal': 7, 'tp_pct': 8, 'sl_pct': 6, 'time_limit': 15},
    {'macd_fast': 8, 'macd_slow': 21, 'macd_signal': 9, 'tp_pct': 8, 'sl_pct': 6, 'time_limit': 15},
    {'macd_fast': 8, 'macd_slow': 26, 'macd_signal': 9, 'tp_pct': 8, 'sl_pct': 6, 'time_limit': 15},
    {'macd_fast': 12, 'macd_slow': 21, 'macd_signal': 7, 'tp_pct': 8, 'sl_pct': 6, 'time_limit': 15},
    {'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 7, 'tp_pct': 8, 'sl_pct': 6, 'time_limit': 15},
    {'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9, 'tp_pct': 8, 'sl_pct': 6, 'time_limit': 15},
]

GRID_H08 = [
    {'lookback': 3, 'accel_thresh': 0.03, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 12},
    {'lookback': 3, 'accel_thresh': 0.05, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 12},
    {'lookback': 5, 'accel_thresh': 0.03, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 12},
    {'lookback': 5, 'accel_thresh': 0.08, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 12},
    {'lookback': 8, 'accel_thresh': 0.05, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 12},
    {'lookback': 8, 'accel_thresh': 0.08, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 12},
]

GRID_H09 = [
    {'spike_mult': 3, 'vol_period': 10, 'tp_pct': 8, 'sl_pct': 6, 'time_limit': 10},
    {'spike_mult': 3, 'vol_period': 20, 'tp_pct': 8, 'sl_pct': 6, 'time_limit': 10},
    {'spike_mult': 4, 'vol_period': 10, 'tp_pct': 8, 'sl_pct': 6, 'time_limit': 10},
    {'spike_mult': 4, 'vol_period': 20, 'tp_pct': 8, 'sl_pct': 6, 'time_limit': 10},
    {'spike_mult': 5, 'vol_period': 10, 'tp_pct': 8, 'sl_pct': 6, 'time_limit': 10},
    {'spike_mult': 5, 'vol_period': 20, 'tp_pct': 8, 'sl_pct': 6, 'time_limit': 10},
]

GRID_H10 = [
    {'lookback': 5, 'vol_ratio': 0.5, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 15},
    {'lookback': 5, 'vol_ratio': 0.7, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 15},
    {'lookback': 10, 'vol_ratio': 0.5, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 15},
    {'lookback': 10, 'vol_ratio': 0.7, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 15},
    {'lookback': 15, 'vol_ratio': 0.5, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 15},
    {'lookback': 15, 'vol_ratio': 0.7, 'tp_pct': 10, 'sl_pct': 5, 'time_limit': 15},
]

GRID_H11 = [
    {'squeeze_bars': 3, 'vol_mult': 2, 'tp_pct': 12, 'sl_pct': 8, 'time_limit': 20},
    {'squeeze_bars': 3, 'vol_mult': 3, 'tp_pct': 12, 'sl_pct': 8, 'time_limit': 20},
    {'squeeze_bars': 5, 'vol_mult': 2, 'tp_pct': 12, 'sl_pct': 8, 'time_limit': 20},
    {'squeeze_bars': 5, 'vol_mult': 3, 'tp_pct': 12, 'sl_pct': 8, 'time_limit': 20},
    {'squeeze_bars': 3, 'vol_mult': 2, 'tp_pct': 15, 'sl_pct': 8, 'time_limit': 20},
    {'squeeze_bars': 5, 'vol_mult': 3, 'tp_pct': 15, 'sl_pct': 8, 'time_limit': 20},
]

GRID_H12 = [
    {'body_ratio': 1.5, 'rsi_max': 40, 'tp_pct': 8, 'time_limit': 10},
    {'body_ratio': 1.5, 'rsi_max': 50, 'tp_pct': 8, 'time_limit': 10},
    {'body_ratio': 2.0, 'rsi_max': 40, 'tp_pct': 8, 'time_limit': 10},
    {'body_ratio': 2.0, 'rsi_max': 50, 'tp_pct': 8, 'time_limit': 10},
    {'body_ratio': 2.5, 'rsi_max': 40, 'tp_pct': 8, 'time_limit': 10},
    {'body_ratio': 2.5, 'rsi_max': 50, 'tp_pct': 8, 'time_limit': 10},
]

GRID_H13 = [
    {'min_contraction': 0.3, 'sl_buffer_pct': 0.5, 'tp_pct': 10, 'time_limit': 15},
    {'min_contraction': 0.3, 'sl_buffer_pct': 1.0, 'tp_pct': 10, 'time_limit': 15},
    {'min_contraction': 0.5, 'sl_buffer_pct': 0.5, 'tp_pct': 10, 'time_limit': 15},
    {'min_contraction': 0.5, 'sl_buffer_pct': 1.0, 'tp_pct': 10, 'time_limit': 15},
    {'min_contraction': 0.7, 'sl_buffer_pct': 0.5, 'tp_pct': 10, 'time_limit': 15},
    {'min_contraction': 0.7, 'sl_buffer_pct': 1.0, 'tp_pct': 10, 'time_limit': 15},
]

GRID_H14 = [
    {'rsi_max': 30, 'macd_fast': 8, 'macd_slow': 26, 'macd_signal': 9, 'tp_pct': 8, 'sl_pct': 8, 'time_limit': 12},
    {'rsi_max': 30, 'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9, 'tp_pct': 8, 'sl_pct': 8, 'time_limit': 12},
    {'rsi_max': 35, 'macd_fast': 8, 'macd_slow': 26, 'macd_signal': 9, 'tp_pct': 8, 'sl_pct': 8, 'time_limit': 12},
    {'rsi_max': 35, 'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9, 'tp_pct': 8, 'sl_pct': 8, 'time_limit': 12},
    {'rsi_max': 40, 'macd_fast': 8, 'macd_slow': 26, 'macd_signal': 9, 'tp_pct': 8, 'sl_pct': 8, 'time_limit': 12},
    {'rsi_max': 40, 'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9, 'tp_pct': 8, 'sl_pct': 8, 'time_limit': 12},
]

GRID_H15 = [
    {'hl_lookback': 3, 'vol_mult': 1.5, 'sl_pct': 4, 'tp_pct': 8, 'time_limit': 15},
    {'hl_lookback': 3, 'vol_mult': 1.5, 'sl_pct': 6, 'tp_pct': 8, 'time_limit': 15},
    {'hl_lookback': 3, 'vol_mult': 2.0, 'sl_pct': 4, 'tp_pct': 8, 'time_limit': 15},
    {'hl_lookback': 5, 'vol_mult': 1.5, 'sl_pct': 4, 'tp_pct': 8, 'time_limit': 15},
    {'hl_lookback': 5, 'vol_mult': 2.0, 'sl_pct': 4, 'tp_pct': 8, 'time_limit': 15},
    {'hl_lookback': 5, 'vol_mult': 2.0, 'sl_pct': 6, 'tp_pct': 8, 'time_limit': 15},
]


# ===================================================================
# REGISTRATION
# ===================================================================

register(Hypothesis(
    id='H01', name='RSI_EXTREME', category='mean_reversion',
    signal_fn=signal_h01_rsi_extreme, param_grid=GRID_H01,
    description='RSI(14) oversold bounce: RSI < threshold with close > prev_close confirmation.',
))

register(Hypothesis(
    id='H02', name='BB_REVERT', category='mean_reversion',
    signal_fn=signal_h02_bb_revert, param_grid=GRID_H02,
    description='Bollinger Band mean reversion: close below lower BB with bounce confirmation, target = BB mid.',
))

register(Hypothesis(
    id='H03', name='STOCH_CROSS', category='mean_reversion',
    signal_fn=signal_h03_stoch_cross, param_grid=GRID_H03,
    description='Stochastic oversold crossover: K < 20 crossing above D line.',
))

register(Hypothesis(
    id='H04', name='RSI_DIVERGENCE', category='mean_reversion',
    signal_fn=signal_h04_rsi_divergence, param_grid=GRID_H04,
    description='Bullish RSI divergence: price makes lower low while RSI makes higher low.',
))

register(Hypothesis(
    id='H05', name='DC_BREAKOUT_UP', category='momentum',
    signal_fn=signal_h05_dc_breakout_up, param_grid=GRID_H05,
    description='Donchian channel breakout: high exceeds upper channel with ATR-based stop.',
))

register(Hypothesis(
    id='H06', name='EMA_CROSS', category='momentum',
    signal_fn=signal_h06_ema_cross, param_grid=GRID_H06,
    description='EMA crossover: fast EMA crosses above slow EMA (golden cross).',
))

register(Hypothesis(
    id='H07', name='MACD_CROSS', category='momentum',
    signal_fn=signal_h07_macd_cross, param_grid=GRID_H07,
    description='MACD histogram crossover: histogram turns from negative to positive.',
))

register(Hypothesis(
    id='H08', name='ACCELERATION', category='momentum',
    signal_fn=signal_h08_acceleration, param_grid=GRID_H08,
    description='Price acceleration: rate-of-change increasing above threshold with upward close.',
))

register(Hypothesis(
    id='H09', name='VOL_SPIKE_GREEN', category='volume',
    signal_fn=signal_h09_vol_spike_green, param_grid=GRID_H09,
    description='Volume spike on green candle: volume exceeds average by multiplier with bullish close.',
))

register(Hypothesis(
    id='H10', name='VOL_DIVERGENCE', category='volume',
    signal_fn=signal_h10_vol_divergence, param_grid=GRID_H10,
    description='Volume-price divergence: price makes new low on declining volume (exhaustion).',
))

register(Hypothesis(
    id='H11', name='SQUEEZE_BREAK', category='volume',
    signal_fn=signal_h11_squeeze_break, param_grid=GRID_H11,
    description='Volatility squeeze breakout: BB contracts inside DC for N bars, then volume spike + up move.',
))

register(Hypothesis(
    id='H12', name='ENGULFING', category='price_action',
    signal_fn=signal_h12_engulfing, param_grid=GRID_H12,
    description='Bullish engulfing candle pattern with RSI confirmation (RSI < max threshold).',
))

register(Hypothesis(
    id='H13', name='INSIDE_BREAK', category='price_action',
    signal_fn=signal_h13_inside_break, param_grid=GRID_H13,
    description='Inside bar breakout: contracted bar followed by break above its high.',
))

register(Hypothesis(
    id='H14', name='RSI_MACD_AGREE', category='multi_indicator',
    signal_fn=signal_h14_rsi_macd_agree, param_grid=GRID_H14,
    description='Multi-indicator confluence: RSI oversold while MACD histogram turns positive.',
))

register(Hypothesis(
    id='H15', name='HIGHER_LOW_VOL', category='multi_indicator',
    signal_fn=signal_h15_higher_low_vol, param_grid=GRID_H15,
    description='Higher low structure with volume confirmation and RSI in neutral zone (35-55).',
))


# ===================================================================
# PUBLIC API
# ===================================================================

def get_all_hypotheses() -> list[Hypothesis]:
    """Return all registered hypotheses as a list."""
    return list(REGISTRY.values())


def get_hypothesis(hyp_id: str) -> Hypothesis:
    """Return a single hypothesis by ID. Raises KeyError if not found."""
    return REGISTRY[hyp_id]


def get_all_configs() -> list[tuple[str, dict]]:
    """Return list of (hypothesis_id, params) for every variant across all hypotheses."""
    result = []
    for hyp in REGISTRY.values():
        for params in hyp.param_grid:
            result.append((hyp.id, params))
    return result

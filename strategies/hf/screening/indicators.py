"""
Extended indicator library for hypothesis screening framework.

All functions are pure (no side effects, no global state), use only
historical data up to the current bar (no look-ahead), and handle
insufficient data gracefully by returning neutral/sensible defaults.

Callers must pass causal slices, e.g. closes[:bar+1].
"""

# Re-export base indicators from the backtest engine
from trading_bot.strategy import calc_rsi, calc_atr, calc_donchian, calc_bollinger


# ---------------------------------------------------------------------------
# Trend / moving-average indicators
# ---------------------------------------------------------------------------

def calc_ema(closes: list, period: int) -> float:
    """Exponential moving average of the last *period* values.

    Args:
        closes: list of close prices (causal slice).
        period: EMA lookback window.

    Returns:
        EMA value.  Falls back to closes[-1] when len < period.
    """
    if not closes:
        return 0.0
    if len(closes) < period:
        return closes[-1]

    mult = 2 / (period + 1)
    ema = closes[-period]  # seed with first value in window
    for c in closes[-period + 1:]:
        ema = c * mult + ema * (1 - mult)
    return ema


def calc_sma(closes: list, period: int) -> float:
    """Simple moving average of the last *period* values.

    Args:
        closes: list of close prices (causal slice).
        period: SMA lookback window.

    Returns:
        SMA value.  Falls back to closes[-1] when len < period.
    """
    if not closes:
        return 0.0
    if len(closes) < period:
        return closes[-1]
    return sum(closes[-period:]) / period


# ---------------------------------------------------------------------------
# Oscillators
# ---------------------------------------------------------------------------

def calc_stochastic(
    highs: list,
    lows: list,
    closes: list,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple:
    """Stochastic oscillator (%K, %D).

    %K = (close - lowest_low) / (highest_high - lowest_low) * 100
    %D = SMA of the last *d_period* %K values.

    Args:
        highs:    list of high prices.
        lows:     list of low prices.
        closes:   list of close prices.
        k_period: lookback for %K calculation.
        d_period: smoothing period for %D.

    Returns:
        (K, D) tuple.  Returns (50.0, 50.0) if insufficient data.
    """
    min_bars = k_period + d_period - 1
    if len(highs) < min_bars or len(lows) < min_bars or len(closes) < min_bars:
        return (50.0, 50.0)

    # Compute K values for the last d_period bars
    k_values = []
    for i in range(d_period):
        # index offset from end: -(d_period - i)  ... -1, 0(last)
        end = len(closes) - (d_period - 1 - i)
        start = end - k_period
        window_highs = highs[start:end]
        window_lows = lows[start:end]
        hh = max(window_highs)
        ll = min(window_lows)
        close = closes[end - 1]
        if hh == ll:
            k_values.append(50.0)
        else:
            k_values.append((close - ll) / (hh - ll) * 100)

    k = k_values[-1]
    d = sum(k_values) / len(k_values)
    return (k, d)


def calc_macd(
    closes: list,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple:
    """MACD indicator: (macd_line, signal_line, histogram).

    MACD line   = EMA(fast) - EMA(slow)
    Signal line = EMA of last *signal* MACD values
    Histogram   = MACD - Signal

    Args:
        closes: list of close prices.
        fast:   fast EMA period.
        slow:   slow EMA period.
        signal: signal-line EMA period.

    Returns:
        (macd_line, signal_line, histogram).  (0, 0, 0) if insufficient data.
    """
    min_bars = slow + signal
    if len(closes) < min_bars:
        return (0.0, 0.0, 0.0)

    # Helper: compute a running EMA series starting from closes[start_idx:]
    def _ema_series(data: list, period: int) -> list:
        mult = 2 / (period + 1)
        ema = data[0]
        result = [ema]
        for val in data[1:]:
            ema = val * mult + ema * (1 - mult)
            result.append(ema)
        return result

    # We need at least `slow` bars for a valid slow EMA.
    # Use the full closes list so the EMA has maximum warm-up.
    fast_ema_series = _ema_series(closes, fast)
    slow_ema_series = _ema_series(closes, slow)

    # MACD line series (aligned to slow_ema start)
    macd_series = [
        f - s for f, s in zip(fast_ema_series, slow_ema_series)
    ]

    # Signal line: EMA of the last portion of the MACD series
    # Use at least `signal` values from the end of the MACD series
    if len(macd_series) < signal:
        return (0.0, 0.0, 0.0)

    signal_ema_series = _ema_series(macd_series, signal)

    macd_line = macd_series[-1]
    signal_line = signal_ema_series[-1]
    histogram = macd_line - signal_line
    return (macd_line, signal_line, histogram)


# ---------------------------------------------------------------------------
# Divergence detection
# ---------------------------------------------------------------------------

def calc_rsi_divergence(
    closes: list,
    rsi_values: list,
    lookback: int = 10,
) -> int:
    """Detect bullish/bearish RSI divergence over the last *lookback* bars.

    Bullish  (+1): price makes a lower low  but RSI makes a higher low.
    Bearish  (-1): price makes a higher high but RSI makes a lower high.
    No signal (0): no divergence detected.

    Local extrema are identified as simple swing points:
    a bar whose value is lower (for minima) or higher (for maxima) than
    both its immediate neighbours.

    Args:
        closes:     list of close prices.
        rsi_values: list of RSI values (same length as closes).
        lookback:   number of recent bars to scan.

    Returns:
        +1, -1, or 0.
    """
    if len(closes) < lookback or len(rsi_values) < lookback or lookback < 3:
        return 0

    price_window = closes[-lookback:]
    rsi_window = rsi_values[-lookback:]

    def _local_minima(series):
        """Return list of (index, value) for local minima."""
        mins = []
        for i in range(1, len(series) - 1):
            if series[i] < series[i - 1] and series[i] < series[i + 1]:
                mins.append((i, series[i]))
        return mins

    def _local_maxima(series):
        """Return list of (index, value) for local maxima."""
        maxs = []
        for i in range(1, len(series) - 1):
            if series[i] > series[i - 1] and series[i] > series[i + 1]:
                maxs.append((i, series[i]))
        return maxs

    # --- Bullish divergence: lower low in price, higher low in RSI ---
    price_mins = _local_minima(price_window)
    rsi_mins = _local_minima(rsi_window)
    if len(price_mins) >= 2 and len(rsi_mins) >= 2:
        # Compare the two most recent minima
        if (price_mins[-1][1] < price_mins[-2][1]
                and rsi_mins[-1][1] > rsi_mins[-2][1]):
            return 1

    # --- Bearish divergence: higher high in price, lower high in RSI ---
    price_maxs = _local_maxima(price_window)
    rsi_maxs = _local_maxima(rsi_window)
    if len(price_maxs) >= 2 and len(rsi_maxs) >= 2:
        if (price_maxs[-1][1] > price_maxs[-2][1]
                and rsi_maxs[-1][1] < rsi_maxs[-2][1]):
            return -1

    return 0


# ---------------------------------------------------------------------------
# Volume & volatility
# ---------------------------------------------------------------------------

def calc_volume_profile(volumes: list, period: int = 20) -> dict:
    """Rolling volume statistics and z-score.

    Args:
        volumes: list of volume values.
        period:  lookback for mean/std calculation.

    Returns:
        {'mean': float, 'std': float, 'z_score': float}.
        Returns zeros when insufficient data.
    """
    if len(volumes) < period:
        return {'mean': 0.0, 'std': 0.0, 'z_score': 0.0}

    window = volumes[-period:]
    mean = sum(window) / period
    variance = sum((v - mean) ** 2 for v in window) / period
    std = variance ** 0.5

    current = volumes[-1]
    z_score = (current - mean) / std if std > 0 else 0.0

    return {'mean': mean, 'std': std, 'z_score': z_score}


def calc_atr_ratio(atr_values: list, lookback: int = 10) -> float:
    """Ratio of current ATR to its rolling mean over *lookback* bars.

    Values > 1 indicate expanding volatility; < 1 contracting.

    Args:
        atr_values: list of ATR values.
        lookback:   rolling mean window.

    Returns:
        ATR ratio (float).  Returns 1.0 if insufficient data.
    """
    if len(atr_values) < lookback or lookback == 0:
        return 1.0

    window = atr_values[-lookback:]
    mean_atr = sum(window) / lookback
    if mean_atr == 0:
        return 1.0
    return atr_values[-1] / mean_atr


def calc_bb_width(bb_upper: float, bb_lower: float, close: float) -> float:
    """Normalised Bollinger Band width: (upper - lower) / close.

    Args:
        bb_upper: upper Bollinger Band value.
        bb_lower: lower Bollinger Band value.
        close:    current close price.

    Returns:
        Normalised width (float).  Returns 0.0 if close is zero.
    """
    if close == 0:
        return 0.0
    return (bb_upper - bb_lower) / close


# ---------------------------------------------------------------------------
# Momentum / rate-of-change
# ---------------------------------------------------------------------------

def calc_roc(closes: list, period: int = 1) -> float:
    """Rate of change: percentage move over *period* bars.

    ROC = (close[-1] - close[-1-period]) / close[-1-period] * 100

    Args:
        closes: list of close prices.
        period: lookback bars for rate-of-change.

    Returns:
        ROC percentage (float).  Returns 0.0 if insufficient data.
    """
    if len(closes) < period + 1:
        return 0.0
    prev = closes[-1 - period]
    if prev == 0:
        return 0.0
    return (closes[-1] - prev) / prev * 100


# ---------------------------------------------------------------------------
# Price-action / candle patterns
# ---------------------------------------------------------------------------

def calc_candle_pattern(
    opens: list,
    highs: list,
    lows: list,
    closes: list,
) -> str:
    """Detect basic candle patterns on the last two bars.

    Patterns (checked in priority order):
        'engulfing'   -- bullish engulfing: current body fully engulfs prior
                         body, current close > open, prior close < open.
        'pin_bar'     -- long lower wick (> 2x body), small upper wick.
        'inside_bar'  -- current range entirely inside previous range.
        'none'        -- no pattern detected.

    Args:
        opens:  list of open prices.
        highs:  list of high prices.
        lows:   list of low prices.
        closes: list of close prices.

    Returns:
        Pattern name string.
    """
    if (len(opens) < 2 or len(highs) < 2
            or len(lows) < 2 or len(closes) < 2):
        return 'none'

    o0, h0, l0, c0 = opens[-2], highs[-2], lows[-2], closes[-2]
    o1, h1, l1, c1 = opens[-1], highs[-1], lows[-1], closes[-1]

    body0 = abs(c0 - o0)
    body1 = abs(c1 - o1)

    # Bullish engulfing
    if (c0 < o0 and c1 > o1           # prior bearish, current bullish
            and o1 <= c0 and c1 >= o0):  # current body engulfs prior body
        return 'engulfing'

    # Pin bar (hammer-like)
    lower_wick = min(o1, c1) - l1
    upper_wick = h1 - max(o1, c1)
    if body1 > 0 and lower_wick > 2 * body1 and upper_wick < body1:
        return 'pin_bar'

    # Inside bar
    if h1 < h0 and l1 > l0:
        return 'inside_bar'

    return 'none'


# ---------------------------------------------------------------------------
# Structure / swing detection
# ---------------------------------------------------------------------------

def calc_higher_low(lows: list, lookback: int = 5) -> bool:
    """Check whether the recent low is higher than the preceding low.

    Compares the minimum of the last *lookback* bars to the minimum
    of the *lookback* bars immediately before them.

    Args:
        lows:     list of low prices.
        lookback: window size for each comparison group.

    Returns:
        True if a higher-low pattern is present; False otherwise.
    """
    if len(lows) < 2 * lookback:
        return False

    recent_low = min(lows[-lookback:])
    prior_low = min(lows[-2 * lookback:-lookback])
    return recent_low > prior_low


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Re-exported base indicators
    'calc_rsi',
    'calc_atr',
    'calc_donchian',
    'calc_bollinger',
    # Trend / moving averages
    'calc_ema',
    'calc_sma',
    # Oscillators
    'calc_stochastic',
    'calc_macd',
    # Divergence
    'calc_rsi_divergence',
    # Volume & volatility
    'calc_volume_profile',
    'calc_atr_ratio',
    'calc_bb_width',
    # Momentum
    'calc_roc',
    # Candle patterns
    'calc_candle_pattern',
    # Structure
    'calc_higher_low',
]

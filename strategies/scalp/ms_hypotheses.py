"""
Market Structure Scalp Hypotheses — 5 families, 19 configs for 1m XRP/USDT.
============================================================================

Ports MS structural concepts to 1-minute scalping with ATR-based exits.
No DC geometry checks (4H-specific). No DC exits (single-coin, no Donchian context).

Families:
  MS-SA: Structure Shift + Pullback (port of ms_018 core logic)
  MS-SB: FVG Fill (price returns to fill bullish imbalance)
  MS-SC: Liquidity Sweep (stop hunt below swing low cluster + reclaim)
  MS-SD: Swing Failure Pattern (failed breakdown = trapped sellers)
  MS-SE: Order Block Rejection (bounce from institutional demand zone)

signal_fn protocol:
    signal_fn(candles, bar, indicators, params) → dict | None
    Return: {stop_price, target_price, time_limit, strength,
             breakeven_atr (opt), trail_atr (opt)}
"""

from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.ms.indicators import (
    get_recent_swing_low,
    get_recent_swing_high,
    get_active_bullish_fvgs,
)


# ═══════════════════════════════════════════════════════════════════
# MS-SA: Structure Shift + Pullback (port of ms_018 core logic)
# ═══════════════════════════════════════════════════════════════════

def signal_mssa(candles, bar, indicators, params) -> dict | None:
    """Bullish BoS → pullback into range → entry.

    Core concept: After price confirms a bullish Break of Structure
    (closes above recent swing high), wait for a pullback towards the
    swing low that anchored the BoS range. Buy when pullback depth
    reaches the configured percentage.

    Adapted from ms_018 shift_pb — WITHOUT dc_geometry check.
    """
    max_bos_age = params.get('max_bos_age', 20)
    pullback_pct = params.get('pullback_pct', 0.50)
    max_pullback_bars = params.get('max_pullback_bars', max_bos_age)
    tp_atr = params.get('tp_atr', 2.0)
    sl_atr = params.get('sl_atr', 1.0)
    time_limit = params.get('time_limit', 20)
    be_atr = params.get('breakeven_atr')
    tr_atr = params.get('trail_atr')

    bos_events = indicators['bos_events']
    closes = indicators['closes']
    swing_lows = indicators['swing_lows']
    lows_arr = indicators['lows']
    atr = indicators['atr']

    close = closes[bar]
    cur_atr = atr[bar]
    if cur_atr is None or cur_atr <= 0:
        return None

    # Search backward for recent bullish BoS
    recent_bos = None
    for b in range(bar - 1, max(bar - max_bos_age - 1, -1), -1):
        if b < 0:
            break
        event = bos_events[b]
        if event is not None and event.direction == 'bullish':
            recent_bos = event
            break

    if recent_bos is None:
        return None

    bos_age = bar - recent_bos.bar
    if bos_age > max_pullback_bars:
        return None

    # Find swing low that anchored the BoS
    swing_price, _ = get_recent_swing_low(
        swing_lows, recent_bos.bar, max_lookback=60,
    )
    if swing_price is None:
        return None

    # Structure intact: no new low below swing low since BoS
    for b in range(recent_bos.bar, bar + 1):
        if lows_arr[b] < swing_price:
            return None

    # Pullback depth
    range_size = recent_bos.broken_level - swing_price
    if range_size <= 0:
        return None

    pullback = (recent_bos.broken_level - close) / range_size
    pullback = min(1.0, max(0.0, pullback))

    if pullback < pullback_pct:
        return None

    strength = min(pullback * recent_bos.break_strength, 3.0)

    stop_price = close - sl_atr * cur_atr
    target_price = close + tp_atr * cur_atr

    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': strength,
        'breakeven_atr': be_atr,
        'trail_atr': tr_atr,
    }


# ═══════════════════════════════════════════════════════════════════
# MS-SB: FVG Fill
# ═══════════════════════════════════════════════════════════════════

def signal_mssb(candles, bar, indicators, params) -> dict | None:
    """Price returns to fill a bullish Fair Value Gap.

    Bullish FVG = 3-candle imbalance (highs[i] < lows[i+2]).
    When price retraces into the gap zone, it often bounces.
    Entry: close enters the FVG zone at configured depth.
    """
    max_fvg_age = params.get('max_fvg_age', 15)
    fill_depth = params.get('fill_depth', 0.50)
    rsi_max = params.get('rsi_max', 0)  # 0 = disabled
    tp_atr = params.get('tp_atr', 2.0)
    sl_atr = params.get('sl_atr', 1.0)
    time_limit = params.get('time_limit', 20)
    be_atr = params.get('breakeven_atr')
    tr_atr = params.get('trail_atr')

    closes = indicators['closes']
    atr = indicators['atr']
    fvg_snapshots = indicators['fvg_snapshots']

    close = closes[bar]
    cur_atr = atr[bar]
    if cur_atr is None or cur_atr <= 0:
        return None

    # Get active bullish FVGs at this bar
    active_fvgs = get_active_bullish_fvgs(fvg_snapshots, bar, max_age=max_fvg_age)
    if not active_fvgs:
        return None

    # RSI filter (optional)
    if rsi_max > 0:
        rsi = indicators.get('rsi14', indicators.get('rsi', [None] * (bar + 1)))
        cur_rsi = rsi[bar] if bar < len(rsi) else None
        if cur_rsi is None or cur_rsi > rsi_max:
            return None

    # Check if price is in an FVG zone at the configured depth
    best_fvg = None
    best_depth = 0.0

    for fvg in active_fvgs:
        gap_size = fvg.gap_high - fvg.gap_low
        if gap_size <= 0:
            continue

        # Price must be at or below gap_high (entering from above)
        if close > fvg.gap_high:
            continue

        # Compute depth into gap: 0 = at gap_high, 1 = at gap_low
        depth = (fvg.gap_high - close) / gap_size
        depth = min(1.0, max(0.0, depth))

        if depth >= fill_depth and depth > best_depth:
            best_depth = depth
            best_fvg = fvg

    if best_fvg is None:
        return None

    strength = best_depth * (1.0 + (bar - best_fvg.bar_created) / max_fvg_age)

    stop_price = close - sl_atr * cur_atr
    target_price = close + tp_atr * cur_atr

    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': min(strength, 3.0),
        'breakeven_atr': be_atr,
        'trail_atr': tr_atr,
    }


# ═══════════════════════════════════════════════════════════════════
# MS-SC: Liquidity Sweep + Reclaim
# ═══════════════════════════════════════════════════════════════════

def signal_mssc(candles, bar, indicators, params) -> dict | None:
    """Price sweeps below swing low(s) then reclaims above.

    Stop hunt reversal: price wicks below a swing low cluster
    (liquidity zone) but closes back above. Trapped shorts provide fuel.
    """
    swing_lookback = params.get('swing_lookback', 30)
    min_wick_atr = params.get('min_wick_atr', 0.3)
    require_green = params.get('require_green', True)
    vol_mult = params.get('vol_mult', 1.0)  # 1.0 = disabled
    tp_atr = params.get('tp_atr', 2.0)
    sl_atr = params.get('sl_atr', 1.0)
    time_limit = params.get('time_limit', 15)
    be_atr = params.get('breakeven_atr')
    tr_atr = params.get('trail_atr')

    closes = indicators['closes']
    highs = indicators['highs']
    lows_arr = indicators['lows']
    opens = indicators['opens']
    atr = indicators['atr']
    swing_lows = indicators['swing_lows']
    volumes = indicators['volumes']

    close = closes[bar]
    low = lows_arr[bar]
    high = highs[bar]
    opn = opens[bar]
    cur_atr = atr[bar]
    if cur_atr is None or cur_atr <= 0:
        return None

    # Find recent swing low to sweep
    swing_price, swing_bar = get_recent_swing_low(
        swing_lows, bar, max_lookback=swing_lookback,
    )
    if swing_price is None:
        return None

    # Low must wick BELOW swing low
    if low >= swing_price:
        return None

    # Close must be ABOVE swing low (reclaim)
    if close <= swing_price:
        return None

    # Wick depth must be meaningful (in ATR units)
    wick_depth = swing_price - low
    if wick_depth < min_wick_atr * cur_atr:
        return None

    # Green candle filter
    if require_green and close <= opn:
        return None

    # Volume filter (optional)
    if vol_mult > 1.0:
        vol_avg = indicators.get('vol_avg', [None] * (bar + 1))
        cur_vol_avg = vol_avg[bar] if bar < len(vol_avg) else None
        if cur_vol_avg is None or cur_vol_avg <= 0:
            return None
        if volumes[bar] < vol_mult * cur_vol_avg:
            return None

    strength = wick_depth / cur_atr

    stop_price = low - sl_atr * cur_atr  # Stop below the sweep wick
    target_price = close + tp_atr * cur_atr

    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': min(strength, 3.0),
        'breakeven_atr': be_atr,
        'trail_atr': tr_atr,
    }


# ═══════════════════════════════════════════════════════════════════
# MS-SD: Swing Failure Pattern (SFP)
# ═══════════════════════════════════════════════════════════════════

def signal_mssd(candles, bar, indicators, params) -> dict | None:
    """Failed breakdown — price breaks below swing low but closes above.

    Similar to liquidity sweep but focuses on the candle close strength:
    the higher the close relative to the range, the stronger the rejection.
    """
    swing_lookback = params.get('swing_lookback', 30)
    min_close_strength = params.get('min_close_strength', 0.50)
    vol_mult = params.get('vol_mult', 1.0)
    tp_atr = params.get('tp_atr', 2.0)
    sl_atr = params.get('sl_atr', 1.0)
    time_limit = params.get('time_limit', 15)
    be_atr = params.get('breakeven_atr')
    tr_atr = params.get('trail_atr')

    closes = indicators['closes']
    highs = indicators['highs']
    lows_arr = indicators['lows']
    atr = indicators['atr']
    swing_lows = indicators['swing_lows']
    volumes = indicators['volumes']

    close = closes[bar]
    low = lows_arr[bar]
    high = highs[bar]
    cur_atr = atr[bar]
    if cur_atr is None or cur_atr <= 0:
        return None

    swing_price, _ = get_recent_swing_low(
        swing_lows, bar, max_lookback=swing_lookback,
    )
    if swing_price is None:
        return None

    # Low must break below swing low
    if low >= swing_price:
        return None

    # Close must be above swing low (failed breakdown)
    if close <= swing_price:
        return None

    # Close strength: where in the bar's range did we close?
    bar_range = high - low
    if bar_range <= 0:
        return None
    close_strength = (close - low) / bar_range

    if close_strength < min_close_strength:
        return None

    # Volume filter
    if vol_mult > 1.0:
        vol_avg = indicators.get('vol_avg', [None] * (bar + 1))
        cur_vol_avg = vol_avg[bar] if bar < len(vol_avg) else None
        if cur_vol_avg is None or cur_vol_avg <= 0:
            return None
        if volumes[bar] < vol_mult * cur_vol_avg:
            return None

    strength = close_strength * (1.0 + (swing_price - low) / cur_atr)

    stop_price = low - sl_atr * cur_atr
    target_price = close + tp_atr * cur_atr

    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': min(strength, 3.0),
        'breakeven_atr': be_atr,
        'trail_atr': tr_atr,
    }


# ═══════════════════════════════════════════════════════════════════
# MS-SE: Order Block Rejection
# ═══════════════════════════════════════════════════════════════════

def signal_msse(candles, bar, indicators, params) -> dict | None:
    """Bounce from bullish Order Block zone.

    OB = last bearish candle before a bullish impulse. When price
    returns to this zone, institutional demand often provides support.
    """
    max_ob_age = params.get('max_ob_age', 30)
    require_close_in_zone = params.get('require_close_in_zone', True)
    vol_mult = params.get('vol_mult', 1.0)
    tp_atr = params.get('tp_atr', 2.0)
    sl_atr = params.get('sl_atr', 1.0)
    time_limit = params.get('time_limit', 15)
    be_atr = params.get('breakeven_atr')
    tr_atr = params.get('trail_atr')

    closes = indicators['closes']
    lows_arr = indicators['lows']
    atr = indicators['atr']
    ob_snapshots = indicators['ob_snapshots']
    volumes = indicators['volumes']

    close = closes[bar]
    low = lows_arr[bar]
    cur_atr = atr[bar]
    if cur_atr is None or cur_atr <= 0:
        return None

    # Get active bullish OBs at this bar
    if bar >= len(ob_snapshots):
        return None
    active_obs = [
        ob for ob in ob_snapshots[bar]
        if ob.direction == 'bullish' and (bar - ob.bar_created) <= max_ob_age
    ]
    if not active_obs:
        return None

    # Check if price is in an OB zone
    best_ob = None
    best_score = 0.0

    for ob in active_obs:
        # Price must touch or enter the OB zone
        if low > ob.zone_high:
            continue  # Price above zone, no interaction

        in_zone = (low <= ob.zone_high)
        if require_close_in_zone and close > ob.zone_high:
            continue  # Close not in zone

        # Score: impulse strength * zone interaction quality
        zone_range = ob.zone_high - ob.zone_low
        if zone_range <= 0:
            continue

        # How deep into the zone did we go?
        depth = (ob.zone_high - max(low, ob.zone_low)) / zone_range
        depth = min(1.0, max(0.0, depth))

        score = depth * ob.impulse_size_atr
        if score > best_score:
            best_score = score
            best_ob = ob

    if best_ob is None:
        return None

    # Volume filter
    if vol_mult > 1.0:
        vol_avg = indicators.get('vol_avg', [None] * (bar + 1))
        cur_vol_avg = vol_avg[bar] if bar < len(vol_avg) else None
        if cur_vol_avg is None or cur_vol_avg <= 0:
            return None
        if volumes[bar] < vol_mult * cur_vol_avg:
            return None

    stop_price = best_ob.zone_low - sl_atr * cur_atr
    target_price = close + tp_atr * cur_atr

    return {
        'stop_price': stop_price,
        'target_price': target_price,
        'time_limit': time_limit,
        'strength': min(best_score, 3.0),
        'breakeven_atr': be_atr,
        'trail_atr': tr_atr,
    }


# ═══════════════════════════════════════════════════════════════════
# CONFIG REGISTRY — 19 initial configs
# ═══════════════════════════════════════════════════════════════════

MS_SCALP_CONFIGS = {
    # ─── MS-SA: Shift+Pullback (4 variants) ─────────────────
    'mssa_001': {
        'signal_fn': signal_mssa, 'family': 'SHIFT_PB',
        'params': {'max_bos_age': 20, 'pullback_pct': 0.50,
                   'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 20},
    },
    'mssa_002': {
        'signal_fn': signal_mssa, 'family': 'SHIFT_PB',
        'params': {'max_bos_age': 15, 'pullback_pct': 0.382,
                   'tp_atr': 1.5, 'sl_atr': 1.0, 'time_limit': 15},
    },
    'mssa_003': {
        'signal_fn': signal_mssa, 'family': 'SHIFT_PB',
        'params': {'max_bos_age': 30, 'pullback_pct': 0.618,
                   'tp_atr': 2.5, 'sl_atr': 1.5, 'time_limit': 30},
    },
    'mssa_004': {
        'signal_fn': signal_mssa, 'family': 'SHIFT_PB',
        'params': {'max_bos_age': 10, 'pullback_pct': 0.382,
                   'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 10},
    },

    # ─── MS-SB: FVG Fill (4 variants) ───────────────────────
    'mssb_001': {
        'signal_fn': signal_mssb, 'family': 'FVG_FILL',
        'params': {'max_fvg_age': 15, 'fill_depth': 0.50, 'rsi_max': 50,
                   'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 20},
    },
    'mssb_002': {
        'signal_fn': signal_mssb, 'family': 'FVG_FILL',
        'params': {'max_fvg_age': 20, 'fill_depth': 0.25, 'rsi_max': 0,
                   'tp_atr': 1.5, 'sl_atr': 1.0, 'time_limit': 15},
    },
    'mssb_003': {
        'signal_fn': signal_mssb, 'family': 'FVG_FILL',
        'params': {'max_fvg_age': 10, 'fill_depth': 0.75, 'rsi_max': 45,
                   'tp_atr': 2.5, 'sl_atr': 1.5, 'time_limit': 30},
    },
    'mssb_004': {
        'signal_fn': signal_mssb, 'family': 'FVG_FILL',
        'params': {'max_fvg_age': 30, 'fill_depth': 0.50, 'rsi_max': 40,
                   'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 20},
    },

    # ─── MS-SC: Liquidity Sweep (4 variants) ────────────────
    'mssc_001': {
        'signal_fn': signal_mssc, 'family': 'LIQ_SWEEP',
        'params': {'swing_lookback': 30, 'min_wick_atr': 0.3,
                   'require_green': True, 'vol_mult': 1.0,
                   'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 15},
    },
    'mssc_002': {
        'signal_fn': signal_mssc, 'family': 'LIQ_SWEEP',
        'params': {'swing_lookback': 20, 'min_wick_atr': 0.5,
                   'require_green': True, 'vol_mult': 1.5,
                   'tp_atr': 2.5, 'sl_atr': 1.5, 'time_limit': 15},
    },
    'mssc_003': {
        'signal_fn': signal_mssc, 'family': 'LIQ_SWEEP',
        'params': {'swing_lookback': 60, 'min_wick_atr': 0.2,
                   'require_green': False, 'vol_mult': 1.0,
                   'tp_atr': 1.5, 'sl_atr': 1.0, 'time_limit': 20},
    },
    'mssc_004': {
        'signal_fn': signal_mssc, 'family': 'LIQ_SWEEP',
        'params': {'swing_lookback': 30, 'min_wick_atr': 0.3,
                   'require_green': True, 'vol_mult': 2.0,
                   'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 10},
    },

    # ─── MS-SD: Swing Failure Pattern (3 variants) ──────────
    'mssd_001': {
        'signal_fn': signal_mssd, 'family': 'SFP',
        'params': {'swing_lookback': 30, 'min_close_strength': 0.50,
                   'vol_mult': 1.0,
                   'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 15},
    },
    'mssd_002': {
        'signal_fn': signal_mssd, 'family': 'SFP',
        'params': {'swing_lookback': 30, 'min_close_strength': 0.60,
                   'vol_mult': 1.5,
                   'tp_atr': 2.5, 'sl_atr': 1.5, 'time_limit': 15},
    },
    'mssd_003': {
        'signal_fn': signal_mssd, 'family': 'SFP',
        'params': {'swing_lookback': 60, 'min_close_strength': 0.40,
                   'vol_mult': 1.0,
                   'tp_atr': 1.5, 'sl_atr': 1.0, 'time_limit': 20},
    },

    # ─── MS-SE: Order Block Rejection (4 variants) ──────────
    'msse_001': {
        'signal_fn': signal_msse, 'family': 'OB_REJECT',
        'params': {'max_ob_age': 30, 'require_close_in_zone': True,
                   'vol_mult': 1.0,
                   'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 15},
    },
    'msse_002': {
        'signal_fn': signal_msse, 'family': 'OB_REJECT',
        'params': {'max_ob_age': 15, 'require_close_in_zone': True,
                   'vol_mult': 1.5,
                   'tp_atr': 2.5, 'sl_atr': 1.5, 'time_limit': 15},
    },
    'msse_003': {
        'signal_fn': signal_msse, 'family': 'OB_REJECT',
        'params': {'max_ob_age': 60, 'require_close_in_zone': False,
                   'vol_mult': 1.0,
                   'tp_atr': 1.5, 'sl_atr': 1.0, 'time_limit': 20},
    },
    'msse_004': {
        'signal_fn': signal_msse, 'family': 'OB_REJECT',
        'params': {'max_ob_age': 20, 'require_close_in_zone': True,
                   'vol_mult': 1.0,
                   'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 10},
    },
}

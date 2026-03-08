"""
Scalp Hypotheses — 5 families, 21 signal configs for 1m XRP/USDT.
=================================================================

All signals follow the signal_fn protocol:
    signal_fn(candles, bar, indicators, params) → dict | None

Families:
    S-A: RSI Mean Reversion (5 configs)
    S-B: VWAP Mean Reversion (4 configs)
    S-C: BB Squeeze Breakout (4 configs)
    S-D: Volume Spike Momentum (4 configs)
    S-E: EMA Cross Micro-Trend (4 configs)

TP/SL expressed in ATR units (calibrated from Phase 0C: median ATR = 13.1 bps).
"""

from __future__ import annotations


# ═══════════════════════════════════════════════════════════
# FAMILY S-A: RSI Mean Reversion
# ═══════════════════════════════════════════════════════════
# Logic: RSI oversold → expect bounce. Buy when RSI dips below threshold.

def signal_sa_001(candles, bar, indicators, params):
    """RSI(14) < 25, TP=2x ATR, SL=1.5x ATR, TL=15 bars."""
    if bar < 50:
        return None
    rsi = indicators.get('rsi14', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    close = candles[bar]['close']
    if rsi is None or atr is None or atr <= 0:
        return None
    if rsi < params.get('rsi_threshold', 25):
        return {
            'stop_price': close - params.get('sl_atr', 1.5) * atr,
            'target_price': close + params.get('tp_atr', 2.0) * atr,
            'time_limit': params.get('time_limit', 15),
            'strength': (25 - rsi) / 25,
        }
    return None


def signal_sa_002(candles, bar, indicators, params):
    """RSI(14) < 30, TP=1.5x ATR, SL=1x ATR, TL=10 bars."""
    if bar < 50:
        return None
    rsi = indicators.get('rsi14', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    close = candles[bar]['close']
    if rsi is None or atr is None or atr <= 0:
        return None
    if rsi < params.get('rsi_threshold', 30):
        return {
            'stop_price': close - params.get('sl_atr', 1.0) * atr,
            'target_price': close + params.get('tp_atr', 1.5) * atr,
            'time_limit': params.get('time_limit', 10),
            'strength': (30 - rsi) / 30,
        }
    return None


def signal_sa_003(candles, bar, indicators, params):
    """RSI(5) < 20, fast oversold. TP=2.5x ATR, SL=1.5x ATR, TL=8 bars."""
    if bar < 50:
        return None
    rsi = indicators.get('rsi5', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    close = candles[bar]['close']
    if rsi is None or atr is None or atr <= 0:
        return None
    if rsi < params.get('rsi_threshold', 20):
        return {
            'stop_price': close - params.get('sl_atr', 1.5) * atr,
            'target_price': close + params.get('tp_atr', 2.5) * atr,
            'time_limit': params.get('time_limit', 8),
            'strength': (20 - rsi) / 20,
        }
    return None


def signal_sa_004(candles, bar, indicators, params):
    """RSI(5) < 15, extreme oversold. TP=3x ATR, SL=2x ATR, TL=10 bars."""
    if bar < 50:
        return None
    rsi = indicators.get('rsi5', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    close = candles[bar]['close']
    if rsi is None or atr is None or atr <= 0:
        return None
    if rsi < params.get('rsi_threshold', 15):
        return {
            'stop_price': close - params.get('sl_atr', 2.0) * atr,
            'target_price': close + params.get('tp_atr', 3.0) * atr,
            'time_limit': params.get('time_limit', 10),
            'strength': (15 - rsi) / 15,
        }
    return None


def signal_sa_005(candles, bar, indicators, params):
    """RSI(14) < 30 + close < BB lower. TP=2x ATR, SL=1x ATR, TL=12 bars."""
    if bar < 50:
        return None
    rsi = indicators.get('rsi14', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    bb_lower = indicators.get('bb_lower', [None])[bar]
    close = candles[bar]['close']
    if rsi is None or atr is None or bb_lower is None or atr <= 0:
        return None
    if rsi < params.get('rsi_threshold', 30) and close < bb_lower:
        return {
            'stop_price': close - params.get('sl_atr', 1.0) * atr,
            'target_price': close + params.get('tp_atr', 2.0) * atr,
            'time_limit': params.get('time_limit', 12),
            'strength': min(1.0, (30 - rsi) / 20 + (bb_lower - close) / atr * 0.5),
        }
    return None


# ═══════════════════════════════════════════════════════════
# FAMILY S-B: VWAP Mean Reversion
# ═══════════════════════════════════════════════════════════
# Logic: Price deviates below rolling VWAP → expect revert to mean.

def signal_sb_001(candles, bar, indicators, params):
    """Close < VWAP - 1x ATR. TP=1.5x ATR, SL=1.5x ATR, TL=20 bars."""
    if bar < 60:
        return None
    close = candles[bar]['close']
    vwap = indicators.get('vwap60', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    if vwap is None or atr is None or atr <= 0:
        return None
    deviation = (vwap - close) / atr
    if deviation >= params.get('dev_thresh', 1.0):
        return {
            'stop_price': close - params.get('sl_atr', 1.5) * atr,
            'target_price': close + params.get('tp_atr', 1.5) * atr,
            'time_limit': params.get('time_limit', 20),
            'strength': min(1.0, deviation / 3.0),
        }
    return None


def signal_sb_002(candles, bar, indicators, params):
    """Close < VWAP - 1.5x ATR. TP=2x ATR, SL=1x ATR, TL=15 bars."""
    if bar < 60:
        return None
    close = candles[bar]['close']
    vwap = indicators.get('vwap60', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    if vwap is None or atr is None or atr <= 0:
        return None
    deviation = (vwap - close) / atr
    if deviation >= params.get('dev_thresh', 1.5):
        return {
            'stop_price': close - params.get('sl_atr', 1.0) * atr,
            'target_price': close + params.get('tp_atr', 2.0) * atr,
            'time_limit': params.get('time_limit', 15),
            'strength': min(1.0, deviation / 3.0),
        }
    return None


def signal_sb_003(candles, bar, indicators, params):
    """Close < VWAP - 10 bps (percentage-based). TP=15 bps, SL=10 bps, TL=20."""
    if bar < 60:
        return None
    close = candles[bar]['close']
    vwap = indicators.get('vwap60', [None])[bar]
    if vwap is None or vwap <= 0:
        return None
    dev_bps = (vwap - close) / vwap * 10000
    if dev_bps >= params.get('dev_bps', 10):
        tp_bps = params.get('tp_bps', 15)
        sl_bps = params.get('sl_bps', 10)
        return {
            'stop_price': close * (1 - sl_bps / 10000),
            'target_price': close * (1 + tp_bps / 10000),
            'time_limit': params.get('time_limit', 20),
            'strength': min(1.0, dev_bps / 30),
        }
    return None


def signal_sb_004(candles, bar, indicators, params):
    """Close < VWAP - 2x ATR + RSI < 40. TP=2.5x ATR, SL=1.5x ATR, TL=15."""
    if bar < 60:
        return None
    close = candles[bar]['close']
    vwap = indicators.get('vwap60', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    rsi = indicators.get('rsi14', [None])[bar]
    if vwap is None or atr is None or rsi is None or atr <= 0:
        return None
    deviation = (vwap - close) / atr
    if deviation >= params.get('dev_thresh', 2.0) and rsi < params.get('rsi_cap', 40):
        return {
            'stop_price': close - params.get('sl_atr', 1.5) * atr,
            'target_price': close + params.get('tp_atr', 2.5) * atr,
            'time_limit': params.get('time_limit', 15),
            'strength': min(1.0, deviation / 4.0 + (40 - rsi) / 80),
        }
    return None


# ═══════════════════════════════════════════════════════════
# FAMILY S-C: BB Squeeze Breakout
# ═══════════════════════════════════════════════════════════
# Logic: BB contracts (squeeze) then expands → momentum breakout.

def signal_sc_001(candles, bar, indicators, params):
    """BB width < P25 + close breaks above BB mid. TP=2x ATR, SL=1x ATR, TL=10."""
    if bar < 50:
        return None
    close = candles[bar]['close']
    bb_mid = indicators.get('bb_mid', [None])[bar]
    bb_width = indicators.get('bb_width', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    if bb_mid is None or bb_width is None or atr is None or atr <= 0:
        return None
    prev_close = candles[bar - 1]['close']
    if bb_width < params.get('squeeze_thresh', 0.004) and prev_close < bb_mid and close > bb_mid:
        return {
            'stop_price': close - params.get('sl_atr', 1.0) * atr,
            'target_price': close + params.get('tp_atr', 2.0) * atr,
            'time_limit': params.get('time_limit', 10),
            'strength': (0.004 - bb_width) / 0.004,
        }
    return None


def signal_sc_002(candles, bar, indicators, params):
    """BB squeeze + vol ratio > 2x. TP=2.5x ATR, SL=1x ATR, TL=8."""
    if bar < 50:
        return None
    close = candles[bar]['close']
    bb_mid = indicators.get('bb_mid', [None])[bar]
    bb_width = indicators.get('bb_width', [None])[bar]
    vol_ratio = indicators.get('vol_ratio', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    if bb_mid is None or bb_width is None or vol_ratio is None or atr is None or atr <= 0:
        return None
    prev_close = candles[bar - 1]['close']
    if (bb_width < params.get('squeeze_thresh', 0.004)
            and vol_ratio > params.get('vol_mult', 2.0)
            and prev_close < bb_mid and close > bb_mid):
        return {
            'stop_price': close - params.get('sl_atr', 1.0) * atr,
            'target_price': close + params.get('tp_atr', 2.5) * atr,
            'time_limit': params.get('time_limit', 8),
            'strength': min(1.0, vol_ratio / 5.0),
        }
    return None


def signal_sc_003(candles, bar, indicators, params):
    """BB squeeze + EMA(9) > EMA(21). TP=2x ATR, SL=1.5x ATR, TL=12."""
    if bar < 50:
        return None
    close = candles[bar]['close']
    bb_mid = indicators.get('bb_mid', [None])[bar]
    bb_width = indicators.get('bb_width', [None])[bar]
    ema9 = indicators.get('ema9', [None])[bar]
    ema21 = indicators.get('ema21', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    if any(v is None for v in [bb_mid, bb_width, ema9, ema21, atr]) or atr <= 0:
        return None
    if (bb_width < params.get('squeeze_thresh', 0.004)
            and ema9 > ema21 and close > bb_mid):
        return {
            'stop_price': close - params.get('sl_atr', 1.5) * atr,
            'target_price': close + params.get('tp_atr', 2.0) * atr,
            'time_limit': params.get('time_limit', 12),
            'strength': (ema9 - ema21) / atr * 0.5,
        }
    return None


def signal_sc_004(candles, bar, indicators, params):
    """BB squeeze expanding: width[bar] > width[bar-1] + close > upper. TP=3x ATR."""
    if bar < 51:
        return None
    close = candles[bar]['close']
    bb_upper = indicators.get('bb_upper', [None])[bar]
    bb_width = indicators.get('bb_width', [None])[bar]
    bb_width_prev = indicators.get('bb_width', [None])[bar - 1]
    atr = indicators.get('atr14', [None])[bar]
    if any(v is None for v in [bb_upper, bb_width, bb_width_prev, atr]) or atr <= 0:
        return None
    if bb_width > bb_width_prev and close > bb_upper and bb_width_prev < params.get('squeeze_thresh', 0.005):
        return {
            'stop_price': close - params.get('sl_atr', 1.5) * atr,
            'target_price': close + params.get('tp_atr', 3.0) * atr,
            'time_limit': params.get('time_limit', 10),
            'strength': min(1.0, (close - bb_upper) / atr),
        }
    return None


# ═══════════════════════════════════════════════════════════
# FAMILY S-D: Volume Spike Momentum
# ═══════════════════════════════════════════════════════════
# Logic: Volume spike + green bar → momentum continuation.

def signal_sd_001(candles, bar, indicators, params):
    """Vol > 3x avg + green bar. TP=2x ATR, SL=1x ATR, TL=8."""
    if bar < 50:
        return None
    close = candles[bar]['close']
    open_ = candles[bar]['open']
    vol_ratio = indicators.get('vol_ratio', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    if vol_ratio is None or atr is None or atr <= 0:
        return None
    if vol_ratio > params.get('vol_mult', 3.0) and close > open_:
        return {
            'stop_price': close - params.get('sl_atr', 1.0) * atr,
            'target_price': close + params.get('tp_atr', 2.0) * atr,
            'time_limit': params.get('time_limit', 8),
            'strength': min(1.0, vol_ratio / 10.0),
        }
    return None


def signal_sd_002(candles, bar, indicators, params):
    """Vol > 5x avg + green bar. TP=3x ATR, SL=1.5x ATR, TL=10."""
    if bar < 50:
        return None
    close = candles[bar]['close']
    open_ = candles[bar]['open']
    vol_ratio = indicators.get('vol_ratio', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    if vol_ratio is None or atr is None or atr <= 0:
        return None
    if vol_ratio > params.get('vol_mult', 5.0) and close > open_:
        return {
            'stop_price': close - params.get('sl_atr', 1.5) * atr,
            'target_price': close + params.get('tp_atr', 3.0) * atr,
            'time_limit': params.get('time_limit', 10),
            'strength': min(1.0, vol_ratio / 15.0),
        }
    return None


def signal_sd_003(candles, bar, indicators, params):
    """Vol > 3x + green + EMA(9) > EMA(21). TP=2.5x ATR, SL=1x ATR, TL=10."""
    if bar < 50:
        return None
    close = candles[bar]['close']
    open_ = candles[bar]['open']
    vol_ratio = indicators.get('vol_ratio', [None])[bar]
    ema9 = indicators.get('ema9', [None])[bar]
    ema21 = indicators.get('ema21', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    if any(v is None for v in [vol_ratio, ema9, ema21, atr]) or atr <= 0:
        return None
    if vol_ratio > params.get('vol_mult', 3.0) and close > open_ and ema9 > ema21:
        return {
            'stop_price': close - params.get('sl_atr', 1.0) * atr,
            'target_price': close + params.get('tp_atr', 2.5) * atr,
            'time_limit': params.get('time_limit', 10),
            'strength': min(1.0, vol_ratio / 10.0 + (ema9 - ema21) / atr * 0.3),
        }
    return None


def signal_sd_004(candles, bar, indicators, params):
    """Vol > 3x + green + RSI < 60 (not overbought). TP=2x ATR, SL=1x ATR, TL=10."""
    if bar < 50:
        return None
    close = candles[bar]['close']
    open_ = candles[bar]['open']
    vol_ratio = indicators.get('vol_ratio', [None])[bar]
    rsi = indicators.get('rsi14', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    if vol_ratio is None or rsi is None or atr is None or atr <= 0:
        return None
    if vol_ratio > params.get('vol_mult', 3.0) and close > open_ and rsi < params.get('rsi_cap', 60):
        return {
            'stop_price': close - params.get('sl_atr', 1.0) * atr,
            'target_price': close + params.get('tp_atr', 2.0) * atr,
            'time_limit': params.get('time_limit', 10),
            'strength': min(1.0, vol_ratio / 10.0),
        }
    return None


# ═══════════════════════════════════════════════════════════
# FAMILY S-E: EMA Cross Micro-Trend
# ═══════════════════════════════════════════════════════════
# Logic: EMA(9) crosses above EMA(21) → micro uptrend start.

def signal_se_001(candles, bar, indicators, params):
    """EMA(9) crosses above EMA(21). TP=2x ATR, SL=1.5x ATR, TL=15."""
    if bar < 50:
        return None
    ema9 = indicators.get('ema9', [None])[bar]
    ema21 = indicators.get('ema21', [None])[bar]
    ema9_prev = indicators.get('ema9', [None])[bar - 1]
    ema21_prev = indicators.get('ema21', [None])[bar - 1]
    atr = indicators.get('atr14', [None])[bar]
    close = candles[bar]['close']
    if any(v is None for v in [ema9, ema21, ema9_prev, ema21_prev, atr]) or atr <= 0:
        return None
    if ema9_prev <= ema21_prev and ema9 > ema21:
        return {
            'stop_price': close - params.get('sl_atr', 1.5) * atr,
            'target_price': close + params.get('tp_atr', 2.0) * atr,
            'time_limit': params.get('time_limit', 15),
            'strength': (ema9 - ema21) / atr,
        }
    return None


def signal_se_002(candles, bar, indicators, params):
    """EMA cross + vol > 1.5x avg. TP=2.5x ATR, SL=1x ATR, TL=12."""
    if bar < 50:
        return None
    ema9 = indicators.get('ema9', [None])[bar]
    ema21 = indicators.get('ema21', [None])[bar]
    ema9_prev = indicators.get('ema9', [None])[bar - 1]
    ema21_prev = indicators.get('ema21', [None])[bar - 1]
    vol_ratio = indicators.get('vol_ratio', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    close = candles[bar]['close']
    if any(v is None for v in [ema9, ema21, ema9_prev, ema21_prev, vol_ratio, atr]) or atr <= 0:
        return None
    if ema9_prev <= ema21_prev and ema9 > ema21 and vol_ratio > params.get('vol_min', 1.5):
        return {
            'stop_price': close - params.get('sl_atr', 1.0) * atr,
            'target_price': close + params.get('tp_atr', 2.5) * atr,
            'time_limit': params.get('time_limit', 12),
            'strength': min(1.0, (ema9 - ema21) / atr + vol_ratio / 5.0),
        }
    return None


def signal_se_003(candles, bar, indicators, params):
    """EMA cross + close > VWAP. TP=2x ATR, SL=1x ATR, TL=15."""
    if bar < 60:
        return None
    ema9 = indicators.get('ema9', [None])[bar]
    ema21 = indicators.get('ema21', [None])[bar]
    ema9_prev = indicators.get('ema9', [None])[bar - 1]
    ema21_prev = indicators.get('ema21', [None])[bar - 1]
    vwap = indicators.get('vwap60', [None])[bar]
    atr = indicators.get('atr14', [None])[bar]
    close = candles[bar]['close']
    if any(v is None for v in [ema9, ema21, ema9_prev, ema21_prev, vwap, atr]) or atr <= 0:
        return None
    if ema9_prev <= ema21_prev and ema9 > ema21 and close > vwap:
        return {
            'stop_price': close - params.get('sl_atr', 1.0) * atr,
            'target_price': close + params.get('tp_atr', 2.0) * atr,
            'time_limit': params.get('time_limit', 15),
            'strength': (ema9 - ema21) / atr,
        }
    return None


def signal_se_004(candles, bar, indicators, params):
    """EMA(9) > EMA(21) sustained (3 bars) + RSI 40-60. TP=2x ATR, SL=1.5x ATR, TL=20."""
    if bar < 53:
        return None
    atr = indicators.get('atr14', [None])[bar]
    rsi = indicators.get('rsi14', [None])[bar]
    close = candles[bar]['close']
    if atr is None or rsi is None or atr <= 0:
        return None
    # Check EMA9 > EMA21 for last 3 bars
    ema9_list = indicators.get('ema9', [])
    ema21_list = indicators.get('ema21', [])
    sustained = True
    for i in range(3):
        e9 = ema9_list[bar - i] if bar - i < len(ema9_list) else None
        e21 = ema21_list[bar - i] if bar - i < len(ema21_list) else None
        if e9 is None or e21 is None or e9 <= e21:
            sustained = False
            break
    # Also check that 3 bars ago it was NOT sustained (entry trigger, not continuation)
    if bar >= 53:
        e9_3 = ema9_list[bar - 3] if bar - 3 < len(ema9_list) else None
        e21_3 = ema21_list[bar - 3] if bar - 3 < len(ema21_list) else None
        if e9_3 is not None and e21_3 is not None and e9_3 > e21_3:
            sustained = False  # Already in trend, not a new cross

    if sustained and params.get('rsi_low', 40) < rsi < params.get('rsi_high', 60):
        return {
            'stop_price': close - params.get('sl_atr', 1.5) * atr,
            'target_price': close + params.get('tp_atr', 2.0) * atr,
            'time_limit': params.get('time_limit', 20),
            'strength': min(1.0, (ema9_list[bar] - ema21_list[bar]) / atr),
        }
    return None


# ═══════════════════════════════════════════════════════════
# CONFIG REGISTRY — all 21 configs
# ═══════════════════════════════════════════════════════════

CONFIGS = {
    # Family S-A: RSI Mean Reversion
    'sa_001': {'signal_fn': signal_sa_001, 'family': 'RSI_MR', 'params': {'rsi_threshold': 25, 'tp_atr': 2.0, 'sl_atr': 1.5, 'time_limit': 15}},
    'sa_002': {'signal_fn': signal_sa_002, 'family': 'RSI_MR', 'params': {'rsi_threshold': 30, 'tp_atr': 1.5, 'sl_atr': 1.0, 'time_limit': 10}},
    'sa_003': {'signal_fn': signal_sa_003, 'family': 'RSI_MR', 'params': {'rsi_threshold': 20, 'tp_atr': 2.5, 'sl_atr': 1.5, 'time_limit': 8}},
    'sa_004': {'signal_fn': signal_sa_004, 'family': 'RSI_MR', 'params': {'rsi_threshold': 15, 'tp_atr': 3.0, 'sl_atr': 2.0, 'time_limit': 10}},
    'sa_005': {'signal_fn': signal_sa_005, 'family': 'RSI_MR', 'params': {'rsi_threshold': 30, 'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 12}},

    # Family S-B: VWAP Mean Reversion
    'sb_001': {'signal_fn': signal_sb_001, 'family': 'VWAP_MR', 'params': {'dev_thresh': 1.0, 'tp_atr': 1.5, 'sl_atr': 1.5, 'time_limit': 20}},
    'sb_002': {'signal_fn': signal_sb_002, 'family': 'VWAP_MR', 'params': {'dev_thresh': 1.5, 'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 15}},
    'sb_003': {'signal_fn': signal_sb_003, 'family': 'VWAP_MR', 'params': {'dev_bps': 10, 'tp_bps': 15, 'sl_bps': 10, 'time_limit': 20}},
    'sb_004': {'signal_fn': signal_sb_004, 'family': 'VWAP_MR', 'params': {'dev_thresh': 2.0, 'rsi_cap': 40, 'tp_atr': 2.5, 'sl_atr': 1.5, 'time_limit': 15}},

    # Family S-C: BB Squeeze Breakout
    'sc_001': {'signal_fn': signal_sc_001, 'family': 'BB_SQUEEZE', 'params': {'squeeze_thresh': 0.004, 'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 10}},
    'sc_002': {'signal_fn': signal_sc_002, 'family': 'BB_SQUEEZE', 'params': {'squeeze_thresh': 0.004, 'vol_mult': 2.0, 'tp_atr': 2.5, 'sl_atr': 1.0, 'time_limit': 8}},
    'sc_003': {'signal_fn': signal_sc_003, 'family': 'BB_SQUEEZE', 'params': {'squeeze_thresh': 0.004, 'tp_atr': 2.0, 'sl_atr': 1.5, 'time_limit': 12}},
    'sc_004': {'signal_fn': signal_sc_004, 'family': 'BB_SQUEEZE', 'params': {'squeeze_thresh': 0.005, 'tp_atr': 3.0, 'sl_atr': 1.5, 'time_limit': 10}},

    # Family S-D: Volume Spike Momentum
    'sd_001': {'signal_fn': signal_sd_001, 'family': 'VOL_SPIKE', 'params': {'vol_mult': 3.0, 'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 8}},
    'sd_002': {'signal_fn': signal_sd_002, 'family': 'VOL_SPIKE', 'params': {'vol_mult': 5.0, 'tp_atr': 3.0, 'sl_atr': 1.5, 'time_limit': 10}},
    'sd_003': {'signal_fn': signal_sd_003, 'family': 'VOL_SPIKE', 'params': {'vol_mult': 3.0, 'tp_atr': 2.5, 'sl_atr': 1.0, 'time_limit': 10}},
    'sd_004': {'signal_fn': signal_sd_004, 'family': 'VOL_SPIKE', 'params': {'vol_mult': 3.0, 'rsi_cap': 60, 'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 10}},

    # Family S-E: EMA Cross Micro-Trend
    'se_001': {'signal_fn': signal_se_001, 'family': 'EMA_CROSS', 'params': {'tp_atr': 2.0, 'sl_atr': 1.5, 'time_limit': 15}},
    'se_002': {'signal_fn': signal_se_002, 'family': 'EMA_CROSS', 'params': {'vol_min': 1.5, 'tp_atr': 2.5, 'sl_atr': 1.0, 'time_limit': 12}},
    'se_003': {'signal_fn': signal_se_003, 'family': 'EMA_CROSS', 'params': {'tp_atr': 2.0, 'sl_atr': 1.0, 'time_limit': 15}},
    'se_004': {'signal_fn': signal_se_004, 'family': 'EMA_CROSS', 'params': {'rsi_low': 40, 'rsi_high': 60, 'tp_atr': 2.0, 'sl_atr': 1.5, 'time_limit': 20}},
}

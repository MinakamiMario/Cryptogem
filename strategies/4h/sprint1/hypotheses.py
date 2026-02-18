"""
Sprint 1 Signal Families — 5 hypothesis families for 4H all-weather screening.

Each signal_fn follows the protocol:
    signal_fn(candles, bar, indicators, params) -> dict | None
    Return: {stop_price, target_price, time_limit, strength} or None

Families:
    H4H-01: RSI Mean Reversion
    H4H-02: BB Squeeze Breakout
    H4H-03: EMA Cross + RSI Filter
    H4H-04: Volume Breakout
    H4H-05: Momentum Trend (HH/HL + ADX)

Two exit templates:
    MR (mean-reversion): tighter TP (5-8%), faster TM (10-15 bars)
    TREND (trend-following): wider TP (8-15%), longer TM (20-30 bars)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


# ---------------------------------------------------------------------------
# Exit template helpers
# ---------------------------------------------------------------------------

def _mr_exits(entry_price: float, params: dict) -> dict:
    """Mean-reversion exit template: tighter stops, faster time limit."""
    sl_pct = params.get("sl_pct", 5.0)
    tp_pct = params.get("tp_pct", 8.0)
    tm = params.get("time_limit", 15)
    return {
        "stop_price": entry_price * (1 - sl_pct / 100),
        "target_price": entry_price * (1 + tp_pct / 100),
        "time_limit": tm,
    }


def _trend_exits(entry_price: float, params: dict) -> dict:
    """Trend-following exit template: wider stops, longer hold."""
    sl_pct = params.get("sl_pct", 8.0)
    tp_pct = params.get("tp_pct", 12.0)
    tm = params.get("time_limit", 25)
    return {
        "stop_price": entry_price * (1 - sl_pct / 100),
        "target_price": entry_price * (1 + tp_pct / 100),
        "time_limit": tm,
    }


# ---------------------------------------------------------------------------
# H4H-01: RSI Mean Reversion
# ---------------------------------------------------------------------------

def signal_h4h01_rsi_mr(candles, bar, indicators, params) -> dict | None:
    """Buy when RSI drops below threshold and bar closes green.

    Entry: RSI < rsi_entry AND close > prev_close (bounce confirmation)
    Exit template: MR (mean-reversion)
    Strength: inverse RSI (lower RSI = stronger signal)
    """
    rsi = indicators["rsi"][bar]
    if rsi is None:
        return None

    rsi_entry = params.get("rsi_entry", 30)
    if rsi >= rsi_entry:
        return None

    closes = indicators["closes"]
    if bar < 1 or closes[bar] <= closes[bar - 1]:
        return None  # need green bar (bounce confirmation)

    # Volume floor
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    if cur_vol < vol_avg * 0.5:
        return None

    entry_price = closes[bar]
    exits = _mr_exits(entry_price, params)
    exits["strength"] = (rsi_entry - rsi) / rsi_entry  # 0-1, higher = more oversold

    return exits


# ---------------------------------------------------------------------------
# H4H-02: BB Squeeze Breakout
# ---------------------------------------------------------------------------

def signal_h4h02_bb_squeeze(candles, bar, indicators, params) -> dict | None:
    """Buy when BB width contracts (squeeze) then expands with volume.

    Entry: bb_width < squeeze_threshold AND current_vol > vol_avg * vol_mult
           AND close > bb_mid (expanding upward)
    Exit template: TREND (breakout)
    Strength: volume ratio
    """
    bb_width = indicators.get("bb_width")
    if bb_width is None or bb_width[bar] is None:
        return None

    # Need historical BB width for comparison
    squeeze_lookback = params.get("squeeze_lookback", 20)
    if bar < squeeze_lookback:
        return None

    # Current BB width
    cur_width = bb_width[bar]

    # Percentile-based squeeze detection
    recent_widths = [bb_width[i] for i in range(bar - squeeze_lookback, bar) if bb_width[i] is not None]
    if len(recent_widths) < squeeze_lookback // 2:
        return None

    sorted_widths = sorted(recent_widths)
    squeeze_pct = params.get("squeeze_pct", 50)
    threshold_idx = max(0, int(len(sorted_widths) * squeeze_pct / 100) - 1)
    squeeze_threshold = sorted_widths[threshold_idx]

    if cur_width > squeeze_threshold:
        return None  # not in squeeze

    # Volume confirmation
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_mult = params.get("vol_mult", 1.5)
    if cur_vol < vol_avg * vol_mult:
        return None

    # Price above BB mid (expanding upward)
    bb_mid = indicators["bb_mid"][bar]
    if bb_mid is None:
        return None
    closes = indicators["closes"]
    if closes[bar] <= bb_mid:
        return None

    entry_price = closes[bar]
    exits = _trend_exits(entry_price, params)
    exits["strength"] = cur_vol / vol_avg if vol_avg > 0 else 0.0

    return exits


# ---------------------------------------------------------------------------
# H4H-03: EMA Cross + RSI Filter
# ---------------------------------------------------------------------------

def signal_h4h03_ema_cross(candles, bar, indicators, params) -> dict | None:
    """Buy on EMA(20) crossing above EMA(50) with RSI confirmation.

    Entry: ema20[bar] > ema50[bar] AND ema20[bar-1] <= ema50[bar-1]
           AND rsi > rsi_min (confirm upward momentum)
    Exit template: TREND
    Strength: (ema20 - ema50) / ema50 ratio
    """
    ema20 = indicators.get("ema20")
    ema50 = indicators.get("ema50")
    if ema20 is None or ema50 is None:
        return None
    if bar < 1 or ema20[bar] is None or ema50[bar] is None:
        return None
    if ema20[bar - 1] is None or ema50[bar - 1] is None:
        return None

    # Crossover: ema20 crosses above ema50
    if not (ema20[bar] > ema50[bar] and ema20[bar - 1] <= ema50[bar - 1]):
        return None

    # RSI filter
    rsi = indicators["rsi"][bar]
    if rsi is None:
        return None
    rsi_min = params.get("rsi_min", 40)
    if rsi < rsi_min:
        return None

    # Volume floor
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_mult = params.get("vol_mult", 1.0)
    if cur_vol < vol_avg * vol_mult:
        return None

    entry_price = indicators["closes"][bar]
    exits = _trend_exits(entry_price, params)
    exits["strength"] = (ema20[bar] - ema50[bar]) / ema50[bar] if ema50[bar] > 0 else 0.0

    return exits


# ---------------------------------------------------------------------------
# H4H-04: Volume Breakout
# ---------------------------------------------------------------------------

def signal_h4h04_volume_breakout(candles, bar, indicators, params) -> dict | None:
    """Buy on high-volume green bar that breaks above N-bar high.

    Entry: close > max(highs[bar-lookback:bar]) AND close > open (green bar)
           AND cur_vol > vol_avg * vol_mult
    Exit template: TREND
    Strength: volume ratio
    """
    lookback = params.get("lookback", 20)
    if bar < lookback + 1:
        return None

    closes = indicators["closes"]
    highs = indicators["highs"]

    # Green bar check
    if bar >= len(candles):
        return None
    c = candles[bar]
    if c.get("close", 0) <= c.get("open", 0):
        return None  # red bar

    # Breakout above N-bar high
    prev_high = max(highs[bar - lookback : bar])
    if closes[bar] <= prev_high:
        return None

    # Volume confirmation
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_mult = params.get("vol_mult", 2.0)
    if cur_vol < vol_avg * vol_mult:
        return None

    entry_price = closes[bar]
    exits = _trend_exits(entry_price, params)
    exits["strength"] = cur_vol / vol_avg if vol_avg > 0 else 0.0

    return exits


# ---------------------------------------------------------------------------
# H4H-05: Momentum Trend (Higher Highs/Higher Lows + ADX)
# ---------------------------------------------------------------------------

def signal_h4h05_momentum_trend(candles, bar, indicators, params) -> dict | None:
    """Buy when price makes higher high + higher low AND ADX confirms trend.

    Entry: high[bar] > high[bar-1] AND low[bar] > low[bar-1] (HH/HL)
           AND adx > adx_min (trend strength confirmation)
           AND close > sma50 (above long-term average)
    Exit template: TREND
    Strength: ADX value (higher = stronger trend)
    """
    adx = indicators.get("adx")
    if adx is None or adx[bar] is None:
        return None

    adx_min = params.get("adx_min", 20)
    if adx[bar] < adx_min:
        return None

    # Higher High / Higher Low pattern
    highs = indicators["highs"]
    lows = indicators["lows"]
    lookback = params.get("lookback", 10)
    if bar < lookback + 1:
        return None

    # Check HH/HL over lookback window
    cur_high = highs[bar]
    cur_low = lows[bar]
    prev_high = max(highs[bar - lookback : bar])
    prev_low = min(lows[bar - lookback : bar])

    # Current bar should break above recent range
    if cur_high <= prev_high:
        return None

    # Current low should be above previous period's low (HL)
    recent_lows = lows[bar - lookback : bar]
    if cur_low <= min(recent_lows):
        return None

    # SMA50 filter (above long-term trend)
    sma50 = indicators.get("sma50")
    if sma50 is not None and sma50[bar] is not None:
        if indicators["closes"][bar] <= sma50[bar]:
            return None

    # Volume floor
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    if cur_vol < vol_avg * 0.5:
        return None

    entry_price = indicators["closes"][bar]
    exits = _trend_exits(entry_price, params)
    exits["strength"] = adx[bar] / 100.0  # normalize to 0-1

    return exits


# ---------------------------------------------------------------------------
# Hypothesis registry
# ---------------------------------------------------------------------------

@dataclass
class Hypothesis:
    id: str
    name: str
    category: str
    signal_fn: Callable
    exit_template: str  # "mr" or "trend"
    param_variants: list[dict]
    description: str


REGISTRY: list[Hypothesis] = [
    Hypothesis(
        id="H4H-01",
        name="RSI Mean Reversion",
        category="mean_reversion",
        signal_fn=signal_h4h01_rsi_mr,
        exit_template="mr",
        param_variants=[
            {"rsi_entry": 25, "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
            {"rsi_entry": 30, "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
            {"rsi_entry": 35, "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
            {"rsi_entry": 30, "sl_pct": 8, "tp_pct": 5, "time_limit": 10, "max_pos": 3},
            {"rsi_entry": 30, "sl_pct": 5, "tp_pct": 5, "time_limit": 20, "max_pos": 5},
        ],
        description="Buy on RSI oversold + green bar bounce. MR exit template.",
    ),
    Hypothesis(
        id="H4H-02",
        name="BB Squeeze Breakout",
        category="volatility",
        signal_fn=signal_h4h02_bb_squeeze,
        exit_template="trend",
        param_variants=[
            {"squeeze_pct": 25, "vol_mult": 1.5, "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
            {"squeeze_pct": 50, "vol_mult": 1.5, "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
            {"squeeze_pct": 25, "vol_mult": 2.0, "sl_pct": 5, "tp_pct": 8, "time_limit": 20, "max_pos": 3},
            {"squeeze_pct": 50, "vol_mult": 2.0, "sl_pct": 5, "tp_pct": 12, "time_limit": 25, "max_pos": 5},
        ],
        description="Buy on BB squeeze release with volume. Trend exit template.",
    ),
    Hypothesis(
        id="H4H-03",
        name="EMA Cross + RSI",
        category="trend_following",
        signal_fn=signal_h4h03_ema_cross,
        exit_template="trend",
        param_variants=[
            {"rsi_min": 40, "vol_mult": 1.0, "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
            {"rsi_min": 50, "vol_mult": 1.0, "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
            {"rsi_min": 40, "vol_mult": 1.5, "sl_pct": 5, "tp_pct": 8, "time_limit": 20, "max_pos": 3},
            {"rsi_min": 50, "vol_mult": 1.5, "sl_pct": 8, "tp_pct": 15, "time_limit": 30, "max_pos": 5},
        ],
        description="Buy on EMA(20)>EMA(50) cross with RSI momentum. Trend exit template.",
    ),
    Hypothesis(
        id="H4H-04",
        name="Volume Breakout",
        category="volume",
        signal_fn=signal_h4h04_volume_breakout,
        exit_template="trend",
        param_variants=[
            {"lookback": 10, "vol_mult": 2.0, "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
            {"lookback": 20, "vol_mult": 2.0, "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
            {"lookback": 10, "vol_mult": 3.0, "sl_pct": 5, "tp_pct": 8, "time_limit": 20, "max_pos": 3},
            {"lookback": 20, "vol_mult": 3.0, "sl_pct": 5, "tp_pct": 15, "time_limit": 30, "max_pos": 5},
        ],
        description="Buy on high-volume breakout above N-bar high. Trend exit template.",
    ),
    Hypothesis(
        id="H4H-05",
        name="Momentum Trend (HH/HL + ADX)",
        category="momentum",
        signal_fn=signal_h4h05_momentum_trend,
        exit_template="trend",
        param_variants=[
            {"adx_min": 20, "lookback": 10, "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
            {"adx_min": 25, "lookback": 10, "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
            {"adx_min": 20, "lookback": 20, "sl_pct": 5, "tp_pct": 8, "time_limit": 20, "max_pos": 3},
            {"adx_min": 25, "lookback": 20, "sl_pct": 8, "tp_pct": 15, "time_limit": 30, "max_pos": 5},
        ],
        description="Buy on HH/HL pattern + ADX trend confirmation. Trend exit template.",
    ),
]


def get_hypothesis(hypothesis_id: str) -> Hypothesis:
    for h in REGISTRY:
        if h.id == hypothesis_id:
            return h
    raise KeyError(f"Unknown hypothesis: {hypothesis_id}. Available: {[h.id for h in REGISTRY]}")


def build_sweep_configs() -> list[dict]:
    """Generate all configs for Stage 0 sweep.

    Returns list of dicts with keys: id, label, hypothesis_id, signal_fn, params.
    """
    configs = []
    idx = 0
    for hyp in REGISTRY:
        for v_idx, variant in enumerate(hyp.param_variants):
            idx += 1
            # Build compact label
            param_str = "_".join(f"{k}{v}" for k, v in sorted(variant.items())
                                 if k not in ("max_pos",))
            label = f"{hyp.id.lower().replace('-', '')}_{param_str}"

            configs.append({
                "idx": idx,
                "id": f"sprint1_{idx:03d}_{label}",
                "label": label,
                "hypothesis_id": hyp.id,
                "hypothesis_name": hyp.name,
                "category": hyp.category,
                "exit_template": hyp.exit_template,
                "signal_fn": hyp.signal_fn,
                "params": dict(variant),
            })
    return configs

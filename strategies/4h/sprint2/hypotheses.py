"""
Sprint 2 Signal Families — 4 hypothesis families for entry-edge discovery.

Each signal_fn follows the protocol:
    signal_fn(candles, bar, indicators, params) -> dict | None
    Return: {stop_price, target_price, time_limit, strength} or None

Families:
    H4S-01: Breakout Anti-Fakeout (Donchian high + volume + range + green bar)
    H4S-02: Volatility Exhaustion Fade (BB width expansion → decline + no new low)
    H4S-03: Cross-Sectional Relative Strength (momentum ranking + market context)
    H4S-04: RSI + Trend/Regime Filter (3 sub-types: SMA slope, ADX+DI, momentum)

Design principles:
    - Multi-condition entries (≥3 independent filters per signal)
    - Volume confirmation in every family
    - Simple fixed TP/SL/TM exits (smart exits come after PF>1.05)
    - Cross-sectional signals via __market__ injection (Family 3)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


# ---------------------------------------------------------------------------
# Exit template helpers (same as Sprint 1, consistent TP/SL/TM)
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
# H4S-01: Breakout Anti-Fakeout
# ---------------------------------------------------------------------------

def signal_h4s01_breakout_antifake(candles, bar, indicators, params) -> dict | None:
    """Breakout above Donchian high with anti-fakeout filters.

    Entry conditions (ALL must be true):
    1. close > dc_prev_high * (1 + close_margin_pct/100)
       (close above previous N-bar high with margin)
    2. cur_vol >= vol_avg * vol_mult
       (volume spike confirms genuine breakout)
    3. (high - low) >= atr * min_range_atr
       (large bar body = conviction, not a wick)
    4. close > open (green bar)
    5. Optional: bb_width below percentile (breakout from compression)

    Exit: trend template (wider TP, longer hold)
    Strength: volume ratio * excess breakout
    """
    # Get dc_prev_high
    dc_prev_high = indicators.get("dc_prev_high")
    if dc_prev_high is None or dc_prev_high[bar] is None:
        return None

    closes = indicators["closes"]
    highs = indicators["highs"]
    lows = indicators["lows"]

    # 1. Close above Donchian high with margin
    close_margin_pct = params.get("close_margin_pct", 0.5)
    breakout_level = dc_prev_high[bar] * (1 + close_margin_pct / 100)
    if closes[bar] <= breakout_level:
        return None

    # 2. Volume confirmation
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_mult = params.get("vol_mult", 2.5)
    if cur_vol < vol_avg * vol_mult:
        return None

    # 3. Minimum bar range (conviction check)
    atr = indicators["atr"][bar]
    if atr is None or atr <= 0:
        return None
    bar_range = highs[bar] - lows[bar]
    min_range_atr = params.get("min_range_atr", 0.8)
    if bar_range < atr * min_range_atr:
        return None

    # 4. Green bar (buying pressure)
    if bar >= len(candles):
        return None
    c = candles[bar]
    if c.get("close", 0) <= c.get("open", 0):
        return None

    entry_price = closes[bar]
    exits = _trend_exits(entry_price, params)

    # Strength: volume ratio * breakout excess
    vol_ratio = cur_vol / vol_avg if vol_avg > 0 else 0.0
    breakout_excess = (closes[bar] - dc_prev_high[bar]) / dc_prev_high[bar] if dc_prev_high[bar] > 0 else 0.0
    exits["strength"] = vol_ratio * (1 + breakout_excess * 10)

    return exits


# ---------------------------------------------------------------------------
# H4S-02: Volatility Exhaustion Fade
# ---------------------------------------------------------------------------

def signal_h4s02_vol_exhaustion_fade(candles, bar, indicators, params) -> dict | None:
    """Fade volatility exhaustion (expansion → decline + oversold).

    Entry conditions (ALL must be true):
    1. BB width WAS elevated: max recent bb_width > percentile threshold
    2. BB width is NOW declining: bb_width[bar] < bb_width[bar-1]
       (optional: 2-bar decline)
    3. Price NOT making new low: low[bar] > min(lows[bar-N:bar])
    4. RSI oversold: rsi < rsi_max
    5. Volume declining (panic subsiding): cur_vol < vol_avg * vol_decline_max

    Exit: MR template (tighter TP, faster TM)
    Strength: BB width percentile rank (higher expansion = stronger)
    """
    bb_width = indicators.get("bb_width")
    if bb_width is None or bb_width[bar] is None:
        return None

    expansion_lookback = params.get("expansion_lookback", 20)
    if bar < expansion_lookback + 2:
        return None

    # 1. BB width WAS elevated (check recent max vs percentile)
    recent_widths = [bb_width[i] for i in range(bar - expansion_lookback, bar)
                     if bb_width[i] is not None]
    if len(recent_widths) < expansion_lookback // 2:
        return None

    sorted_widths = sorted(recent_widths)
    bb_width_pct_high = params.get("bb_width_pct_high", 75)
    threshold_idx = max(0, int(len(sorted_widths) * bb_width_pct_high / 100) - 1)
    width_threshold = sorted_widths[threshold_idx]

    # Max recent width must have exceeded threshold
    if max(recent_widths) < width_threshold:
        return None

    # 2. BB width is NOW declining
    if bb_width[bar - 1] is None:
        return None
    if bb_width[bar] >= bb_width[bar - 1]:
        return None  # not declining

    decline_bars = params.get("decline_bars", 2)
    if decline_bars >= 2:
        if bb_width[bar - 2] is None:
            return None
        if bb_width[bar - 1] >= bb_width[bar - 2]:
            return None  # need 2 consecutive declines

    # 3. Price NOT making new low
    lows = indicators["lows"]
    no_new_low_bars = params.get("no_new_low_bars", 5)
    lookback_start = max(0, bar - no_new_low_bars)
    recent_lows = lows[lookback_start: bar]
    if not recent_lows:
        return None
    if lows[bar] <= min(recent_lows):
        return None  # still making new lows

    # 4. RSI oversold
    rsi = indicators["rsi"][bar]
    if rsi is None:
        return None
    rsi_max = params.get("rsi_max", 40)
    if rsi >= rsi_max:
        return None

    # 5. Volume declining (panic subsiding)
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_decline_max = params.get("vol_decline_max", 1.0)
    if cur_vol > vol_avg * vol_decline_max:
        return None  # volume still elevated

    entry_price = indicators["closes"][bar]
    exits = _mr_exits(entry_price, params)

    # Strength: how extreme the prior expansion was (percentile rank of max width)
    max_recent = max(recent_widths)
    pct_rank = sum(1 for w in sorted_widths if w <= max_recent) / len(sorted_widths)
    exits["strength"] = pct_rank

    return exits


# ---------------------------------------------------------------------------
# H4S-03: Cross-Sectional Relative Strength
# ---------------------------------------------------------------------------

def signal_h4s03_relative_strength(candles, bar, indicators, params) -> dict | None:
    """Trade top momentum cohort with volume + trend confirmation.

    Entry conditions (ALL must be true):
    1. Coin in top-N% of momentum ranking
    2. Raw momentum is positive (not just "least bad")
    3. Volume confirmation: cur_vol >= vol_avg * vol_mult
    4. Optional: Price above SMA50 (trend filter)
    5. Optional: Market breadth > breadth_min

    Requires __market__ in params and __coin__ in indicators.

    Exit: trend template (wider TP, longer hold)
    Strength: 1 - (rank / n_ranked) (higher for better rank)
    """
    # Extract market context
    market = params.get("__market__")
    if market is None:
        return None

    coin = indicators.get("__coin__", "")
    if not coin:
        return None

    # Momentum rank for this coin at this bar
    momentum_rank = market.get("momentum_rank", {}).get(coin)
    if momentum_rank is None or bar >= len(momentum_rank):
        return None
    rank = momentum_rank[bar]

    n_ranked_list = market.get("n_ranked", [])
    if bar >= len(n_ranked_list):
        return None
    n_ranked = n_ranked_list[bar]
    if n_ranked == 0:
        return None

    # 1. Top N% check
    top_pct = params.get("top_pct", 10)
    cutoff = max(1, int(n_ranked * top_pct / 100))
    if rank > cutoff:
        return None

    # 2. Positive momentum required
    require_positive = params.get("require_positive_return", True)
    if require_positive:
        momentum_return = market.get("momentum_return", {}).get(coin)
        if momentum_return is None or bar >= len(momentum_return):
            return None
        if momentum_return[bar] <= 0:
            return None

    # 3. Volume confirmation
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_mult = params.get("vol_mult", 1.5)
    if cur_vol < vol_avg * vol_mult:
        return None

    # 4. SMA50 trend filter (optional)
    sma_filter = params.get("sma_filter", True)
    if sma_filter:
        sma50 = indicators.get("sma50")
        if sma50 is not None and sma50[bar] is not None:
            if indicators["closes"][bar] <= sma50[bar]:
                return None

    # 5. Breadth filter (optional)
    breadth_min = params.get("breadth_min", 0.4)
    breadth = market.get("breadth_up", [])
    if bar < len(breadth):
        if breadth[bar] < breadth_min:
            return None

    entry_price = indicators["closes"][bar]
    exits = _trend_exits(entry_price, params)

    # Strength: inverse rank (best rank = highest strength)
    exits["strength"] = 1.0 - (rank / n_ranked) if n_ranked > 0 else 0.0

    return exits


# ---------------------------------------------------------------------------
# H4S-04: RSI + Trend/Regime Filter
# ---------------------------------------------------------------------------

def signal_h4s04_rsi_regime(candles, bar, indicators, params) -> dict | None:
    """RSI oversold with trend/regime confirmation.

    Entry conditions (ALL must be true):
    1. RSI < rsi_max (oversold)
    2. Green bar: close > close[bar-1] (bounce)
    3. Volume floor: cur_vol >= vol_avg * vol_floor_mult
    4. Regime filter (selected by regime_type):
       A: SMA50 slope > 0 (uptrending coin)
       B: ADX > adx_min AND +DI > -DI (strong uptrend)
       C: N-bar return > 0 (medium-term momentum positive)

    Exit: MR template (tighter TP, faster TM)
    Strength: oversold depth * regime strength
    """
    # 1. RSI oversold
    rsi = indicators["rsi"][bar]
    if rsi is None:
        return None
    rsi_max = params.get("rsi_max", 35)
    if rsi >= rsi_max:
        return None

    # 2. Green bar (bounce confirmation)
    closes = indicators["closes"]
    if bar < 1 or closes[bar] <= closes[bar - 1]:
        return None

    # 3. Volume floor
    vol_avg = indicators["vol_avg"][bar]
    if vol_avg is None or vol_avg <= 0:
        return None
    cur_vol = indicators["volumes"][bar]
    vol_floor_mult = params.get("vol_floor_mult", 1.0)
    if cur_vol < vol_avg * vol_floor_mult:
        return None

    # 4. Regime filter
    regime_type = params.get("regime_type", "A")
    regime_strength = 0.0

    if regime_type == "A":
        # SMA50 slope positive
        sma50 = indicators.get("sma50")
        slope_lookback = params.get("slope_lookback", 10)
        if sma50 is None:
            return None
        if sma50[bar] is None or bar < slope_lookback or sma50[bar - slope_lookback] is None:
            return None
        if sma50[bar] <= sma50[bar - slope_lookback]:
            return None  # SMA50 not rising
        regime_strength = (sma50[bar] - sma50[bar - slope_lookback]) / sma50[bar - slope_lookback]

    elif regime_type == "B":
        # ADX + DI
        adx = indicators.get("adx")
        plus_di = indicators.get("plus_di")
        minus_di = indicators.get("minus_di")
        if adx is None or plus_di is None or minus_di is None:
            return None
        if adx[bar] is None or plus_di[bar] is None or minus_di[bar] is None:
            return None
        adx_min = params.get("adx_min", 20)
        if adx[bar] < adx_min:
            return None
        if plus_di[bar] <= minus_di[bar]:
            return None  # bearish direction
        regime_strength = adx[bar] / 100.0

    elif regime_type == "C":
        # N-bar momentum positive
        momentum_lookback = params.get("momentum_lookback", 10)
        if bar < momentum_lookback:
            return None
        if closes[bar - momentum_lookback] <= 0:
            return None
        mom_return = (closes[bar - 1] - closes[bar - 1 - momentum_lookback]) / closes[bar - 1 - momentum_lookback]
        if mom_return <= 0:
            return None
        regime_strength = mom_return

    else:
        return None  # unknown regime type

    entry_price = closes[bar]
    exits = _mr_exits(entry_price, params)

    # Strength: oversold depth * regime strength
    oversold_depth = (rsi_max - rsi) / rsi_max
    exits["strength"] = oversold_depth * (1 + regime_strength * 10)

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
    # -----------------------------------------------------------------------
    # H4S-01: Breakout Anti-Fakeout (6 variants)
    # -----------------------------------------------------------------------
    Hypothesis(
        id="H4S-01",
        name="Breakout Anti-Fakeout",
        category="breakout",
        signal_fn=signal_h4s01_breakout_antifake,
        exit_template="trend",
        param_variants=[
            # A: Tight filter (selective)
            {"dc_period": 20, "close_margin_pct": 1.0, "vol_mult": 3.0,
             "min_range_atr": 1.0, "sl_pct": 5, "tp_pct": 10, "time_limit": 20, "max_pos": 3},
            # B: Moderate filter
            {"dc_period": 20, "close_margin_pct": 0.5, "vol_mult": 2.5,
             "min_range_atr": 0.8, "sl_pct": 5, "tp_pct": 10, "time_limit": 20, "max_pos": 3},
            # C: Loose filter (more trades)
            {"dc_period": 20, "close_margin_pct": 0, "vol_mult": 2.0,
             "min_range_atr": 0.5, "sl_pct": 5, "tp_pct": 10, "time_limit": 20, "max_pos": 3},
            # D: Longer lookback
            {"dc_period": 25, "close_margin_pct": 0.5, "vol_mult": 2.5,
             "min_range_atr": 0.8, "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
            # E: Short lookback (more signals)
            {"dc_period": 15, "close_margin_pct": 0.5, "vol_mult": 2.5,
             "min_range_atr": 0.8, "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
            # F: Maximum selectivity (DualConfirm-like strictness)
            {"dc_period": 20, "close_margin_pct": 1.0, "vol_mult": 3.0,
             "min_range_atr": 1.2, "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
        ],
        description="Donchian high breakout with close/volume/range anti-fakeout filters.",
    ),

    # -----------------------------------------------------------------------
    # H4S-02: Volatility Exhaustion Fade (5 variants)
    # -----------------------------------------------------------------------
    Hypothesis(
        id="H4S-02",
        name="Volatility Exhaustion Fade",
        category="mean_reversion",
        signal_fn=signal_h4s02_vol_exhaustion_fade,
        exit_template="mr",
        param_variants=[
            # A: Classic exhaustion (tight oversold)
            {"expansion_lookback": 20, "bb_width_pct_high": 75, "decline_bars": 2,
             "no_new_low_bars": 5, "rsi_max": 35, "vol_decline_max": 1.0,
             "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
            # B: Wider RSI, shorter lookback
            {"expansion_lookback": 15, "bb_width_pct_high": 70, "decline_bars": 1,
             "no_new_low_bars": 3, "rsi_max": 40, "vol_decline_max": 1.0,
             "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
            # C: Strong expansion required
            {"expansion_lookback": 20, "bb_width_pct_high": 80, "decline_bars": 2,
             "no_new_low_bars": 5, "rsi_max": 40, "vol_decline_max": 0.8,
             "sl_pct": 5, "tp_pct": 5, "time_limit": 10, "max_pos": 3},
            # D: Loose (more trades)
            {"expansion_lookback": 30, "bb_width_pct_high": 70, "decline_bars": 1,
             "no_new_low_bars": 3, "rsi_max": 45, "vol_decline_max": 1.0,
             "sl_pct": 8, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
            # E: Maximum strictness
            {"expansion_lookback": 20, "bb_width_pct_high": 80, "decline_bars": 2,
             "no_new_low_bars": 5, "rsi_max": 35, "vol_decline_max": 0.8,
             "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
        ],
        description="Fade volatility exhaustion: BB width expansion → decline, no new low, RSI oversold.",
    ),

    # -----------------------------------------------------------------------
    # H4S-03: Cross-Sectional Relative Strength (6 variants)
    # -----------------------------------------------------------------------
    Hypothesis(
        id="H4S-03",
        name="Cross-Sectional Relative Strength",
        category="momentum",
        signal_fn=signal_h4s03_relative_strength,
        exit_template="trend",
        param_variants=[
            # A: Top 10% with SMA filter
            {"momentum_period": 10, "top_pct": 10, "vol_mult": 1.5,
             "require_positive_return": True, "sma_filter": True, "breadth_min": 0.4,
             "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
            # B: Top 5% (very selective)
            {"momentum_period": 10, "top_pct": 5, "vol_mult": 2.0,
             "require_positive_return": True, "sma_filter": True, "breadth_min": 0.4,
             "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
            # C: Top 20% (more trades)
            {"momentum_period": 10, "top_pct": 20, "vol_mult": 1.0,
             "require_positive_return": True, "sma_filter": True, "breadth_min": 0.3,
             "sl_pct": 5, "tp_pct": 8, "time_limit": 20, "max_pos": 3},
            # D: Short momentum (5-bar)
            {"momentum_period": 5, "top_pct": 10, "vol_mult": 1.5,
             "require_positive_return": True, "sma_filter": True, "breadth_min": 0.4,
             "sl_pct": 5, "tp_pct": 10, "time_limit": 20, "max_pos": 3},
            # E: Long momentum (20-bar)
            {"momentum_period": 20, "top_pct": 10, "vol_mult": 1.5,
             "require_positive_return": True, "sma_filter": True, "breadth_min": 0.4,
             "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
            # F: No SMA filter, lower breadth (bear-friendly)
            {"momentum_period": 10, "top_pct": 10, "vol_mult": 1.5,
             "require_positive_return": True, "sma_filter": False, "breadth_min": 0.3,
             "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
        ],
        description="Trade top momentum cohort with cross-sectional ranking, volume + trend filters.",
    ),

    # -----------------------------------------------------------------------
    # H4S-04: RSI + Trend/Regime Filter (7 variants, 3 sub-types)
    # -----------------------------------------------------------------------
    Hypothesis(
        id="H4S-04",
        name="RSI + Regime Filter",
        category="mean_reversion",
        signal_fn=signal_h4s04_rsi_regime,
        exit_template="mr",
        param_variants=[
            # Sub-A: SMA Slope filter
            {"rsi_max": 35, "vol_floor_mult": 1.0, "regime_type": "A",
             "slope_lookback": 10, "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
            {"rsi_max": 40, "vol_floor_mult": 0.8, "regime_type": "A",
             "slope_lookback": 5, "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
            # Sub-B: ADX + DI filter
            {"rsi_max": 35, "vol_floor_mult": 1.0, "regime_type": "B",
             "adx_min": 20, "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
            {"rsi_max": 40, "vol_floor_mult": 0.8, "regime_type": "B",
             "adx_min": 25, "sl_pct": 5, "tp_pct": 5, "time_limit": 10, "max_pos": 3},
            # Sub-C: Momentum confirmation
            {"rsi_max": 35, "vol_floor_mult": 1.0, "regime_type": "C",
             "momentum_lookback": 10, "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
            {"rsi_max": 40, "vol_floor_mult": 0.8, "regime_type": "C",
             "momentum_lookback": 20, "sl_pct": 8, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
            # Sub-C: Short momentum (5-bar)
            {"rsi_max": 30, "vol_floor_mult": 1.0, "regime_type": "C",
             "momentum_lookback": 5, "sl_pct": 5, "tp_pct": 5, "time_limit": 10, "max_pos": 3},
        ],
        description="RSI oversold + green bar with regime filter (SMA slope / ADX+DI / momentum).",
    ),
]


def get_hypothesis(hypothesis_id: str) -> Hypothesis:
    for h in REGISTRY:
        if h.id == hypothesis_id:
            return h
    raise KeyError(f"Unknown hypothesis: {hypothesis_id}. Available: {[h.id for h in REGISTRY]}")


def build_sweep_configs() -> list[dict]:
    """Generate all configs for Sprint 2 Stage 0 sweep.

    Returns list of dicts with keys: idx, id, label, hypothesis_id, signal_fn, params.
    Total: 24 configs (6+5+6+7).
    """
    configs = []
    idx = 0
    for hyp in REGISTRY:
        for v_idx, variant in enumerate(hyp.param_variants):
            idx += 1
            # Build compact label
            key_params = {k: v for k, v in sorted(variant.items())
                          if k not in ("max_pos",)}
            param_str = "_".join(f"{k}{v}" for k, v in key_params.items())
            label = f"{hyp.id.lower().replace('-', '')}_{param_str}"

            configs.append({
                "idx": idx,
                "id": f"sprint2_{idx:03d}_{label}",
                "label": label,
                "hypothesis_id": hyp.id,
                "hypothesis_name": hyp.name,
                "category": hyp.category,
                "exit_template": hyp.exit_template,
                "signal_fn": hyp.signal_fn,
                "params": dict(variant),
            })
    return configs


# ---------------------------------------------------------------------------
# Quick validation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    configs = build_sweep_configs()
    print(f"  Total configs: {len(configs)}")

    # Count per family
    from collections import Counter
    family_counts = Counter(c["hypothesis_id"] for c in configs)
    for fam_id, count in sorted(family_counts.items()):
        hyp = get_hypothesis(fam_id)
        print(f"    {fam_id}: {hyp.name} — {count} variants")

    # Verify 24 total
    assert len(configs) == 24, f"Expected 24 configs, got {len(configs)}"

    # Verify unique IDs
    ids = [c["id"] for c in configs]
    assert len(ids) == len(set(ids)), f"Duplicate IDs found: {[x for x in ids if ids.count(x) > 1]}"

    print(f"\n  All {len(configs)} configs valid, unique IDs confirmed")

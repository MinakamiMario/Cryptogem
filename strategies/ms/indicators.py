"""
Market Structure (MS) Indicators — Structural price action detectors.

Provides:
  - calc_swing_lows/highs: Causal fractal pivot detection (extends superhf pattern)
  - calc_fair_value_gaps: 3-candle imbalance zone tracking
  - calc_break_of_structure: Swing level break detection
  - calc_order_blocks: Impulse-origin zone identification
  - calc_liquidity_zones: Equal-low/high stop cluster detection
  - precompute_ms_indicators: Extends Sprint 2 base indicators with structural arrays

All functions are CAUSAL (no lookahead), PURE (lists in → lists out), VECTORIZED (O(n)).
"""
from __future__ import annotations

import importlib
import sys
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Sprint 2 base indicators (extends Sprint 1 with dc_prev_high, +DI, -DI)
_sprint2_ind = importlib.import_module("strategies.4h.sprint2.indicators")


# ═══════════════════════════════════════════════════════════════════════════
# 1. Swing High / Low Detection
# ═══════════════════════════════════════════════════════════════════════════

def calc_swing_lows(
    lows: list[float],
    lookback_left: int = 5,
    lookback_right: int = 2,
) -> list[float | None]:
    """Find swing lows: bar where low is the minimum of [bar-left, bar+right].

    CAUSAL: pivot at bar B is confirmed at bar B+lookback_right.
    Value is returned at the confirmation bar, NOT at bar B itself.

    Returns list same length as lows. Swing low price at confirmation bar,
    else None.
    """
    n = len(lows)
    result: list[float | None] = [None] * n

    for confirm_bar in range(lookback_left + lookback_right, n):
        pivot_bar = confirm_bar - lookback_right
        pivot_low = lows[pivot_bar]

        # Left: all bars in [pivot_bar - lookback_left, pivot_bar) must have higher lows
        is_pivot = True
        for j in range(pivot_bar - lookback_left, pivot_bar):
            if j < 0:
                is_pivot = False
                break
            if lows[j] <= pivot_low:
                is_pivot = False
                break
        if not is_pivot:
            continue

        # Right: all bars in (pivot_bar, pivot_bar + lookback_right] must have higher lows
        for j in range(pivot_bar + 1, pivot_bar + lookback_right + 1):
            if j >= n:
                is_pivot = False
                break
            if lows[j] < pivot_low:
                is_pivot = False
                break

        if is_pivot:
            result[confirm_bar] = pivot_low

    return result


def calc_swing_highs(
    highs: list[float],
    lookback_left: int = 5,
    lookback_right: int = 2,
) -> list[float | None]:
    """Find swing highs: bar where high is the maximum of [bar-left, bar+right].

    CAUSAL: pivot at bar B is confirmed at bar B+lookback_right.
    Value is returned at the confirmation bar.

    Returns list same length as highs. Swing high price at confirmation bar,
    else None.
    """
    n = len(highs)
    result: list[float | None] = [None] * n

    for confirm_bar in range(lookback_left + lookback_right, n):
        pivot_bar = confirm_bar - lookback_right
        pivot_high = highs[pivot_bar]

        # Left: all bars in [pivot_bar - lookback_left, pivot_bar) must have lower highs
        is_pivot = True
        for j in range(pivot_bar - lookback_left, pivot_bar):
            if j < 0:
                is_pivot = False
                break
            if highs[j] >= pivot_high:
                is_pivot = False
                break
        if not is_pivot:
            continue

        # Right: all bars in (pivot_bar, pivot_bar + lookback_right] must have lower highs
        for j in range(pivot_bar + 1, pivot_bar + lookback_right + 1):
            if j >= n:
                is_pivot = False
                break
            if highs[j] > pivot_high:
                is_pivot = False
                break

        if is_pivot:
            result[confirm_bar] = pivot_high

    return result


def get_recent_swing_low(
    swing_lows: list[float | None],
    bar: int,
    max_lookback: int = 60,
) -> tuple[float | None, int | None]:
    """Return (price, confirm_bar) of most recent swing low before bar."""
    for b in range(bar - 1, max(bar - max_lookback - 1, -1), -1):
        if b < 0:
            break
        if swing_lows[b] is not None:
            return swing_lows[b], b
    return None, None


def get_recent_swing_high(
    swing_highs: list[float | None],
    bar: int,
    max_lookback: int = 60,
) -> tuple[float | None, int | None]:
    """Return (price, confirm_bar) of most recent swing high before bar."""
    for b in range(bar - 1, max(bar - max_lookback - 1, -1), -1):
        if b < 0:
            break
        if swing_highs[b] is not None:
            return swing_highs[b], b
    return None, None


def get_n_recent_swing_lows(
    swing_lows: list[float | None],
    bar: int,
    n: int = 3,
    max_lookback: int = 120,
) -> list[tuple[float, int]]:
    """Return the N most recent swing lows as (price, confirm_bar) pairs.

    Ordered most-recent first.
    """
    results: list[tuple[float, int]] = []
    for b in range(bar - 1, max(bar - max_lookback - 1, -1), -1):
        if b < 0:
            break
        if swing_lows[b] is not None:
            results.append((swing_lows[b], b))
            if len(results) >= n:
                break
    return results


# ═══════════════════════════════════════════════════════════════════════════
# 2. Fair Value Gap (FVG) Detection
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class FVG:
    """A Fair Value Gap (price imbalance zone)."""
    bar_created: int
    direction: str       # "bullish" or "bearish"
    gap_high: float      # top of gap zone
    gap_low: float       # bottom of gap zone
    filled: bool = False
    fill_bar: int | None = None


def calc_fair_value_gaps(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    atr: list[float | None],
    min_gap_atr: float = 0.3,
) -> list[list[FVG]]:
    """Detect Fair Value Gaps causally.

    Bullish FVG at bars [i, i+1, i+2]: highs[i] < lows[i+2]
      - Identified at bar i+2 (all 3 candles known)
      - gap_high = lows[i+2], gap_low = highs[i]

    Bearish FVG at bars [i, i+1, i+2]: lows[i] > highs[i+2]
      - gap_high = lows[i], gap_low = highs[i+2]

    min_gap_atr: minimum gap size in ATR multiples.

    Returns list[list[FVG]] — active (unfilled) FVGs at each bar.
    """
    n = len(highs)
    snapshots: list[list[FVG]] = [[] for _ in range(n)]
    active: list[FVG] = []

    for bar in range(n):
        # Check for new FVG at bars [bar-2, bar-1, bar]
        if bar >= 2:
            cur_atr = atr[bar] if atr[bar] is not None else None

            # Bullish FVG: highs[bar-2] < lows[bar]
            if highs[bar - 2] < lows[bar]:
                gap_size = lows[bar] - highs[bar - 2]
                if cur_atr is not None and cur_atr > 0 and gap_size >= min_gap_atr * cur_atr:
                    active.append(FVG(
                        bar_created=bar,
                        direction="bullish",
                        gap_high=lows[bar],
                        gap_low=highs[bar - 2],
                    ))

            # Bearish FVG: lows[bar-2] > highs[bar]
            if lows[bar - 2] > highs[bar]:
                gap_size = lows[bar - 2] - highs[bar]
                if cur_atr is not None and cur_atr > 0 and gap_size >= min_gap_atr * cur_atr:
                    active.append(FVG(
                        bar_created=bar,
                        direction="bearish",
                        gap_high=lows[bar - 2],
                        gap_low=highs[bar],
                    ))

        # Snapshot FIRST: copy unfilled FVGs BEFORE fill checks
        # (signal functions trigger on the same bar that fills the FVG)
        snapshots[bar] = [copy(fvg) for fvg in active if not fvg.filled]

        # Then check fill on existing FVGs (affects next bar's snapshot)
        for fvg in active:
            if fvg.filled:
                continue
            if fvg.direction == "bullish":
                # Filled when close enters from above: close <= gap_high
                if closes[bar] <= fvg.gap_high and bar > fvg.bar_created:
                    fvg.filled = True
                    fvg.fill_bar = bar
            else:  # bearish
                # Filled when close enters from below: close >= gap_low
                if closes[bar] >= fvg.gap_low and bar > fvg.bar_created:
                    fvg.filled = True
                    fvg.fill_bar = bar

    return snapshots


def get_active_bullish_fvgs(
    fvg_snapshots: list[list[FVG]],
    bar: int,
    max_age: int = 40,
) -> list[FVG]:
    """Return unfilled bullish FVGs at bar, filtered by max age."""
    if bar < 0 or bar >= len(fvg_snapshots):
        return []
    return [
        fvg for fvg in fvg_snapshots[bar]
        if fvg.direction == "bullish" and (bar - fvg.bar_created) <= max_age
    ]


# ═══════════════════════════════════════════════════════════════════════════
# 3. Break of Structure (BoS) Detection
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BoS:
    """A Break of Structure event."""
    bar: int
    direction: str        # "bullish" or "bearish"
    broken_level: float
    break_strength: float  # (close - level) / ATR, normalized


def calc_break_of_structure(
    closes: list[float],
    swing_highs: list[float | None],
    swing_lows: list[float | None],
    atr: list[float | None],
) -> list[BoS | None]:
    """Detect Break of Structure events causally.

    Bullish BoS: close > most recent confirmed swing high
    Bearish BoS: close < most recent confirmed swing low

    Only the FIRST break of each swing level is reported (dedup).

    Returns list same length as input. BoS event or None at each bar.
    """
    n = len(closes)
    result: list[BoS | None] = [None] * n

    # Track the most recent unbroken swing levels
    current_swing_high: float | None = None
    current_swing_low: float | None = None
    broken_levels: set[float] = set()

    for bar in range(n):
        # Update tracked swing levels from confirmed swings
        if swing_highs[bar] is not None:
            current_swing_high = swing_highs[bar]
        if swing_lows[bar] is not None:
            current_swing_low = swing_lows[bar]

        close = closes[bar]
        cur_atr = atr[bar] if bar < len(atr) and atr[bar] is not None else None

        # Check bullish BoS: close breaks above current swing high
        if (current_swing_high is not None
                and close > current_swing_high
                and current_swing_high not in broken_levels):
            strength = 0.0
            if cur_atr is not None and cur_atr > 0:
                strength = (close - current_swing_high) / cur_atr
            result[bar] = BoS(
                bar=bar,
                direction="bullish",
                broken_level=current_swing_high,
                break_strength=min(strength, 5.0),
            )
            broken_levels.add(current_swing_high)

        # Check bearish BoS: close breaks below current swing low
        elif (current_swing_low is not None
                and close < current_swing_low
                and current_swing_low not in broken_levels):
            strength = 0.0
            if cur_atr is not None and cur_atr > 0:
                strength = (current_swing_low - close) / cur_atr
            result[bar] = BoS(
                bar=bar,
                direction="bearish",
                broken_level=current_swing_low,
                break_strength=min(strength, 5.0),
            )
            broken_levels.add(current_swing_low)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# 4. Order Block Detection
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class OrderBlock:
    """An Order Block zone (institutional supply/demand)."""
    bar_created: int
    direction: str        # "bullish" (demand) or "bearish" (supply)
    zone_high: float
    zone_low: float
    impulse_size_atr: float
    mitigated: bool = False
    mitigated_bar: int | None = None


def calc_order_blocks(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    atr: list[float | None],
    min_impulse_atr: float = 1.5,
    lookback_impulse: int = 3,
) -> list[list[OrderBlock]]:
    """Detect Order Blocks causally.

    Bullish OB: last bearish candle (close < open) before a bullish impulse.
    Impulse: max(highs[ob_bar+1 .. ob_bar+lookback_impulse]) - closes[ob_bar]
             >= min_impulse_atr * ATR

    CAUSAL: OB confirmed at ob_bar + lookback_impulse.

    Returns list[list[OrderBlock]] — active (unmitigated) OBs at each bar.
    """
    n = len(opens)
    snapshots: list[list[OrderBlock]] = [[] for _ in range(n)]
    active: list[OrderBlock] = []

    for bar in range(n):
        # Check for new OB confirmation at bar
        # The impulse ends at bar, so the OB candle is at bar - lookback_impulse (or earlier)
        if bar >= lookback_impulse + 1:
            confirm_bar = bar
            cur_atr = atr[confirm_bar] if atr[confirm_bar] is not None else None

            if cur_atr is not None and cur_atr > 0:
                # Search for the last bearish candle before the impulse window
                # Impulse window: [confirm_bar - lookback_impulse + 1, confirm_bar]
                impulse_start = confirm_bar - lookback_impulse + 1

                # Find impulse high in the window
                impulse_high = max(highs[i] for i in range(impulse_start, confirm_bar + 1))

                # Search backward from impulse_start for a bearish candle
                for ob_bar in range(impulse_start - 1, max(impulse_start - 10, -1), -1):
                    if ob_bar < 0:
                        break
                    if closes[ob_bar] < opens[ob_bar]:  # bearish candle
                        # Impulse size: from OB candle close to impulse high
                        impulse_size = impulse_high - closes[ob_bar]
                        impulse_atr = impulse_size / cur_atr

                        if impulse_atr >= min_impulse_atr:
                            # Check this OB wasn't already added at a different confirm bar
                            already_exists = any(
                                ob.bar_created == ob_bar and ob.direction == "bullish"
                                for ob in active
                            )
                            if not already_exists:
                                active.append(OrderBlock(
                                    bar_created=ob_bar,
                                    direction="bullish",
                                    zone_high=highs[ob_bar],
                                    zone_low=lows[ob_bar],
                                    impulse_size_atr=impulse_atr,
                                ))
                        break  # only the LAST bearish candle before impulse

                # Bearish OB: last bullish candle before bearish impulse
                impulse_low = min(lows[i] for i in range(impulse_start, confirm_bar + 1))

                for ob_bar in range(impulse_start - 1, max(impulse_start - 10, -1), -1):
                    if ob_bar < 0:
                        break
                    if closes[ob_bar] > opens[ob_bar]:  # bullish candle
                        impulse_size = closes[ob_bar] - impulse_low
                        impulse_atr = impulse_size / cur_atr

                        if impulse_atr >= min_impulse_atr:
                            already_exists = any(
                                ob.bar_created == ob_bar and ob.direction == "bearish"
                                for ob in active
                            )
                            if not already_exists:
                                active.append(OrderBlock(
                                    bar_created=ob_bar,
                                    direction="bearish",
                                    zone_high=highs[ob_bar],
                                    zone_low=lows[ob_bar],
                                    impulse_size_atr=impulse_atr,
                                ))
                        break

        # Snapshot FIRST: copy unmitigated OBs BEFORE mitigation checks
        # (signal functions trigger on the same bar that mitigates the OB)
        snapshots[bar] = [copy(ob) for ob in active if not ob.mitigated]

        # Then check mitigation (affects next bar's snapshot)
        for ob in active:
            if ob.mitigated:
                continue
            if ob.direction == "bullish":
                # Mitigated: price returns into the OB zone (low touches zone_high)
                if lows[bar] <= ob.zone_high and bar > ob.bar_created + lookback_impulse:
                    ob.mitigated = True
                    ob.mitigated_bar = bar
            else:  # bearish
                if highs[bar] >= ob.zone_low and bar > ob.bar_created + lookback_impulse:
                    ob.mitigated = True
                    ob.mitigated_bar = bar

    return snapshots


# ═══════════════════════════════════════════════════════════════════════════
# 5. Liquidity Zone Detection
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class LiquidityZone:
    """A cluster of equal lows/highs (stop-loss pool)."""
    price: float          # average price of the cluster
    n_touches: int
    direction: str        # "below" (equal lows) or "above" (equal highs)
    first_bar: int
    last_bar: int


def calc_liquidity_zones(
    swing_lows: list[float | None],
    swing_highs: list[float | None],
    atr: list[float | None],
    tolerance_atr: float = 0.5,
    min_touches: int = 2,
) -> list[list[LiquidityZone]]:
    """Identify liquidity zones (clusters of equal swing lows/highs).

    Equal lows: 2+ swing lows within tolerance_atr * ATR of each other.
    These represent clustered stop-losses = liquidity pools.

    CAUSAL: zone only visible after min_touches swings confirmed.

    Returns list[list[LiquidityZone]] — active zones at each bar.
    """
    n = len(swing_lows)
    snapshots: list[list[LiquidityZone]] = [[] for _ in range(n)]

    # Collect confirmed swings as we go
    low_swings: list[tuple[float, int]] = []   # (price, confirm_bar)
    high_swings: list[tuple[float, int]] = []

    for bar in range(n):
        if swing_lows[bar] is not None:
            low_swings.append((swing_lows[bar], bar))
        if swing_highs[bar] is not None:
            high_swings.append((swing_highs[bar], bar))

        cur_atr = atr[bar] if atr[bar] is not None else None
        if cur_atr is None or cur_atr <= 0:
            if bar > 0:
                snapshots[bar] = list(snapshots[bar - 1])
            continue

        tolerance = tolerance_atr * cur_atr
        zones: list[LiquidityZone] = []

        # Cluster equal lows
        if len(low_swings) >= min_touches:
            zones.extend(_cluster_swings(low_swings, tolerance, min_touches, "below"))

        # Cluster equal highs
        if len(high_swings) >= min_touches:
            zones.extend(_cluster_swings(high_swings, tolerance, min_touches, "above"))

        snapshots[bar] = zones

    return snapshots


def _cluster_swings(
    swings: list[tuple[float, int]],
    tolerance: float,
    min_touches: int,
    direction: str,
) -> list[LiquidityZone]:
    """Cluster swing points within tolerance into LiquidityZones."""
    if not swings:
        return []

    # Simple greedy clustering: sort by price, group within tolerance
    sorted_swings = sorted(swings, key=lambda x: x[0])
    zones: list[LiquidityZone] = []

    i = 0
    while i < len(sorted_swings):
        cluster = [sorted_swings[i]]
        j = i + 1
        while j < len(sorted_swings):
            if sorted_swings[j][0] - sorted_swings[i][0] <= tolerance:
                cluster.append(sorted_swings[j])
                j += 1
            else:
                break

        if len(cluster) >= min_touches:
            avg_price = sum(s[0] for s in cluster) / len(cluster)
            zones.append(LiquidityZone(
                price=avg_price,
                n_touches=len(cluster),
                direction=direction,
                first_bar=min(s[1] for s in cluster),
                last_bar=max(s[1] for s in cluster),
            ))

        i = j if j > i + 1 else i + 1

    return zones


# ═══════════════════════════════════════════════════════════════════════════
# 6. Precompute All MS Indicators
# ═══════════════════════════════════════════════════════════════════════════

def precompute_ms_indicators(
    data: dict,
    coins: list[str],
    swing_left: int = 5,
    swing_right: int = 2,
) -> dict:
    """Precompute ALL indicators for MS strategy research.

    Extends Sprint 2 precompute_all with structural indicators.

    Returns {pair: {
        # All Sprint 2 indicators (closes, highs, lows, volumes, n,
        #   rsi, atr, dc_prev_low, dc_mid, bb_mid, bb_lower, bb_upper,
        #   vol_avg, ema20, ema50, sma50, adx, obv,
        #   dc_prev_high, plus_di, minus_di, __coin__)
        # Plus:
        'opens': list[float],
        'swing_lows': list[float|None],
        'swing_highs': list[float|None],
        'fvg_snapshots': list[list[FVG]],
        'bos_events': list[BoS|None],
        'ob_snapshots': list[list[OrderBlock]],
        'liq_zones': list[list[LiquidityZone]],
    }}
    """
    # Start with Sprint 2 indicators (RSI, ATR, DC, BB, EMA, vol_avg, etc.)
    indicators = _sprint2_ind.precompute_all(data, coins)

    for pair in coins:
        ind = indicators.get(pair)
        if ind is None:
            continue

        n = ind["n"]
        highs = ind["highs"]
        lows = ind["lows"]
        closes = ind["closes"]
        atr = ind.get("atr", [None] * n)

        # Opens (not in Sprint 2 indicators)
        opens = [c["open"] for c in data[pair]]
        ind["opens"] = opens

        # Structural indicators
        ind["swing_lows"] = calc_swing_lows(lows, swing_left, swing_right)
        ind["swing_highs"] = calc_swing_highs(highs, swing_left, swing_right)

        ind["fvg_snapshots"] = calc_fair_value_gaps(
            highs, lows, closes, atr, min_gap_atr=0.3,
        )

        ind["bos_events"] = calc_break_of_structure(
            closes, ind["swing_highs"], ind["swing_lows"], atr,
        )

        ind["ob_snapshots"] = calc_order_blocks(
            opens, highs, lows, closes, atr,
            min_impulse_atr=1.5, lookback_impulse=3,
        )

        ind["liq_zones"] = calc_liquidity_zones(
            ind["swing_lows"], ind["swing_highs"], atr,
            tolerance_atr=0.5, min_touches=2,
        )

    return indicators


# ═══════════════════════════════════════════════════════════════════════════
# Self-test
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import random
    random.seed(42)
    passed = 0
    total = 0

    # --- Swing Lows ---
    total += 1
    lows = [10, 9, 8, 7, 6, 7, 8, 9, 10, 11, 12, 11, 10, 9, 8, 9, 10, 11, 12, 13]
    sl = calc_swing_lows(lows, lookback_left=3, lookback_right=2)
    # Pivot at bar 4 (low=6), confirmed at bar 6
    assert sl[6] == 6, f"Expected swing low 6 at bar 6, got {sl[6]}"
    assert sl[4] is None, "Swing should not appear at pivot bar itself"
    print(f"  Test {total}: swing_low confirmed at right bar, NOT at pivot bar — PASS")
    passed += 1

    # --- Swing Highs ---
    total += 1
    highs = [10, 11, 12, 13, 14, 13, 12, 11, 10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 7]
    sh = calc_swing_highs(highs, lookback_left=3, lookback_right=2)
    # Pivot at bar 4 (high=14), confirmed at bar 6
    assert sh[6] == 14, f"Expected swing high 14 at bar 6, got {sh[6]}"
    assert sh[4] is None, "Swing high should not appear at pivot bar itself"
    print(f"  Test {total}: swing_high mirror of swing_low — PASS")
    passed += 1

    # --- get_recent_swing_low returns price AND bar ---
    total += 1
    price, bar_idx = get_recent_swing_low(sl, 10, max_lookback=20)
    assert price == 6, f"Expected price=6, got {price}"
    assert bar_idx == 6, f"Expected bar_idx=6, got {bar_idx}"
    print(f"  Test {total}: get_recent_swing_low returns (price, bar) tuple — PASS")
    passed += 1

    # --- get_recent_swing_high ---
    total += 1
    price_h, bar_h = get_recent_swing_high(sh, 10, max_lookback=20)
    assert price_h == 14, f"Expected price=14, got {price_h}"
    assert bar_h == 6, f"Expected bar=6, got {bar_h}"
    print(f"  Test {total}: get_recent_swing_high returns (price, bar) tuple — PASS")
    passed += 1

    # --- get_n_recent_swing_lows ---
    total += 1
    # Create data with two swing lows
    lows2 = [10, 9, 8, 7, 5, 7, 8, 9, 10, 9, 8, 7, 4, 7, 8, 9, 10, 11, 12, 13]
    sl2 = calc_swing_lows(lows2, lookback_left=3, lookback_right=2)
    results = get_n_recent_swing_lows(sl2, 18, n=3, max_lookback=30)
    assert len(results) >= 1, "Should find at least 1 swing low"
    # Most recent should be the last confirmed swing
    print(f"  Test {total}: get_n_recent_swing_lows returns {len(results)} swings — PASS")
    passed += 1

    # --- Flat data: no swings ---
    total += 1
    flat = [10.0] * 20
    sl_flat = calc_swing_lows(flat, lookback_left=3, lookback_right=2)
    assert all(v is None for v in sl_flat), "Flat data should produce no swings"
    print(f"  Test {total}: flat data produces no swings — PASS")
    passed += 1

    # --- FVG: bullish detection ---
    total += 1
    # Bullish FVG: highs[0] < lows[2] → gap between candle 0 high and candle 2 low
    fvg_highs = [10, 15, 20, 19, 18]
    fvg_lows = [8, 12, 15, 17, 16]
    fvg_closes = [9, 14, 18, 18, 17]
    fvg_atr = [2.0] * 5
    fvgs = calc_fair_value_gaps(fvg_highs, fvg_lows, fvg_closes, fvg_atr, min_gap_atr=0.3)
    # At bar 2: highs[0]=10 < lows[2]=15 → bullish FVG, gap_size=5, 5/2.0=2.5 ATR ✓
    bullish_at_2 = [f for f in fvgs[2] if f.direction == "bullish"]
    assert len(bullish_at_2) == 1, f"Expected 1 bullish FVG at bar 2, got {len(bullish_at_2)}"
    assert bullish_at_2[0].gap_low == 10, f"gap_low should be highs[0]=10"
    assert bullish_at_2[0].gap_high == 15, f"gap_high should be lows[2]=15"
    print(f"  Test {total}: bullish FVG detected correctly — PASS")
    passed += 1

    # --- FVG: causality (not at bar 1) ---
    total += 1
    assert len(fvgs[1]) == 0, "FVG should NOT exist at bar 1 (needs bar 2 to confirm)"
    print(f"  Test {total}: FVG causality (not before bar i+2) — PASS")
    passed += 1

    # --- FVG: fill tracking ---
    total += 1
    # At bar 3: close=18, gap_high=15 → close > gap_high → NOT filled yet (close above zone)
    # Actually for bullish FVG fill: close <= gap_high means price came back down into the gap
    # At bar 3: close=18 > gap_high=15 → NOT filled
    # At bar 4: close=17 > gap_high=15 → NOT filled
    # Need to check a scenario where fill happens
    # Bar 0: H=10 L=8 C=9; Bar 1: H=20 L=10 C=15 (big candle, no gap)
    # Bar 2: H=22 L=15 C=18 (highs[0]=10 < lows[2]=15 → bullish FVG gap=[10,15])
    # Bar 3: H=21 L=14 C=17 (no new FVG)
    # Bar 4: H=16 L=9 C=10  (close=10 <= gap_high=15 → fill bar, still in snapshot)
    # Bar 5: FVG removed from snapshot (filled at bar 4)
    fvg_highs2 = [10, 20, 22, 21, 16, 17]
    fvg_lows2 = [8, 10, 15, 14, 9, 10]
    fvg_closes2 = [9, 15, 18, 17, 10, 11]
    fvg_atr2 = [2.0] * 6
    fvgs2 = calc_fair_value_gaps(fvg_highs2, fvg_lows2, fvg_closes2, fvg_atr2, min_gap_atr=0.3)
    # Bar 4: FVG still in snapshot (snapshot taken BEFORE fill check)
    assert len([f for f in fvgs2[4] if f.direction == "bullish"]) >= 1, "FVG should still be in snapshot on fill bar"
    # Bar 5: FVG removed (filled at bar 4)
    assert len([f for f in fvgs2[5] if f.direction == "bullish"]) == 0, "FVG should be gone after fill bar"
    print(f"  Test {total}: FVG fill: present on fill bar, gone next bar — PASS")
    passed += 1

    # --- FVG: min gap filter ---
    total += 1
    tiny_highs = [10, 11, 10.5, 12, 13]
    tiny_lows = [9, 10, 10.2, 11, 12]  # highs[0]=10 < lows[2]=10.2, gap=0.2
    tiny_closes = [9.5, 10.5, 10.3, 11.5, 12.5]
    tiny_atr = [2.0] * 5  # min_gap = 0.3 * 2.0 = 0.6, gap=0.2 < 0.6 → filtered
    fvgs_tiny = calc_fair_value_gaps(tiny_highs, tiny_lows, tiny_closes, tiny_atr, min_gap_atr=0.3)
    assert len(fvgs_tiny[2]) == 0, "Small FVG should be filtered by min_gap_atr"
    print(f"  Test {total}: FVG min_gap_atr filter works — PASS")
    passed += 1

    # --- BoS: bullish ---
    total += 1
    # Set up: swing high at some bar, then close breaks above it
    bos_closes = [10, 11, 12, 13, 14, 13, 12, 11, 10, 9, 8, 9, 10, 11, 12, 15, 16, 17, 18, 19]
    bos_highs = [11, 12, 13, 14, 15, 14, 13, 12, 11, 10, 9, 10, 11, 12, 13, 16, 17, 18, 19, 20]
    bos_lows = [9, 10, 11, 12, 13, 12, 11, 10, 9, 8, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18]
    bos_sh = calc_swing_highs(bos_highs, lookback_left=3, lookback_right=2)
    bos_sl = calc_swing_lows(bos_lows, lookback_left=3, lookback_right=2)
    bos_atr = [1.0] * 20
    bos_events = calc_break_of_structure(bos_closes, bos_sh, bos_sl, bos_atr)
    # Find any bullish BoS
    bullish_bos = [e for e in bos_events if e is not None and e.direction == "bullish"]
    # There should be at least one bullish BoS (price trends up to 19)
    assert len(bullish_bos) >= 1, f"Expected at least 1 bullish BoS, got {len(bullish_bos)}"
    print(f"  Test {total}: bullish BoS detected ({len(bullish_bos)} events) — PASS")
    passed += 1

    # --- BoS: dedup ---
    total += 1
    # Same level should not be broken twice
    levels_broken = set()
    for e in bos_events:
        if e is not None:
            assert e.broken_level not in levels_broken, \
                f"Level {e.broken_level} broken twice (dedup failure)"
            levels_broken.add(e.broken_level)
    print(f"  Test {total}: BoS dedup — no level broken twice — PASS")
    passed += 1

    # --- Order Block: bullish detection ---
    total += 1
    # Create impulse scenario: bearish candle then strong bullish move
    ob_opens = [10, 11, 12, 11, 10, 15, 16, 17, 18, 19]
    ob_highs = [11, 12, 13, 12, 11, 16, 17, 18, 19, 20]
    ob_lows = [9, 10, 11, 10, 9, 14, 15, 16, 17, 18]
    ob_closes = [10.5, 11.5, 12.5, 10.5, 9.5, 15.5, 16.5, 17.5, 18.5, 19.5]
    # Bar 3: close=10.5 < open=11 → bearish candle
    # Bar 4: close=9.5 < open=10 → bearish candle
    # Bars 5-7: strong bullish impulse (highs go 16, 17, 18)
    ob_atr = [1.0] * 10
    obs = calc_order_blocks(ob_opens, ob_highs, ob_lows, ob_closes, ob_atr,
                            min_impulse_atr=1.5, lookback_impulse=3)
    # Should find at least one bullish OB
    all_bullish_obs = set()
    for bar_obs in obs:
        for ob in bar_obs:
            if ob.direction == "bullish":
                all_bullish_obs.add(ob.bar_created)
    assert len(all_bullish_obs) >= 1, f"Expected >= 1 bullish OB, got {len(all_bullish_obs)}"
    print(f"  Test {total}: bullish order block detected — PASS")
    passed += 1

    # --- Liquidity Zone: equal lows ---
    total += 1
    # Two swing lows at similar price within tolerance
    liq_lows_arr: list[float | None] = [None] * 20
    liq_lows_arr[5] = 10.0
    liq_lows_arr[12] = 10.2  # within 0.5 ATR tolerance
    liq_highs_arr: list[float | None] = [None] * 20
    liq_atr = [1.0] * 20
    liq_zones = calc_liquidity_zones(liq_lows_arr, liq_highs_arr, liq_atr,
                                      tolerance_atr=0.5, min_touches=2)
    # After bar 12, should have a zone
    zones_at_15 = [z for z in liq_zones[15] if z.direction == "below"]
    assert len(zones_at_15) >= 1, f"Expected equal lows zone, got {len(zones_at_15)}"
    assert zones_at_15[0].n_touches == 2
    print(f"  Test {total}: equal lows detected as liquidity zone — PASS")
    passed += 1

    # --- Liquidity Zone: single swing = no zone ---
    total += 1
    liq_single: list[float | None] = [None] * 20
    liq_single[5] = 10.0  # only one swing low
    liq_zones_single = calc_liquidity_zones(liq_single, [None]*20, liq_atr,
                                             tolerance_atr=0.5, min_touches=2)
    assert all(len(z) == 0 for z_list in liq_zones_single for z in [z_list]
               if all(zz.direction == "below" for zz in z_list)), \
        "Single swing should not form a zone"
    # Simpler check: no "below" zones at any bar
    below_zones = sum(1 for snap in liq_zones_single
                      for z in snap if z.direction == "below")
    assert below_zones == 0, f"Expected 0 below zones with single swing, got {below_zones}"
    print(f"  Test {total}: single swing produces no zone — PASS")
    passed += 1

    # --- Integration: precompute_ms_indicators ---
    total += 1
    test_data = {}
    price = 100.0
    candles = []
    for i in range(200):
        o = price
        h = price + random.uniform(0, 5)
        l = price - random.uniform(0, 5)
        c = price + random.uniform(-3, 3)
        v = random.uniform(1000, 10000)
        candles.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
        price = c
    test_data["TEST/USD"] = candles
    test_coins = ["TEST/USD"]

    result = precompute_ms_indicators(test_data, test_coins)
    ind = result["TEST/USD"]

    required_keys = [
        "closes", "highs", "lows", "volumes", "n", "rsi", "atr",
        "dc_mid", "dc_prev_low", "bb_mid", "bb_lower",
        "opens", "swing_lows", "swing_highs",
        "fvg_snapshots", "bos_events", "ob_snapshots", "liq_zones",
    ]
    for key in required_keys:
        assert key in ind, f"Missing key: {key}"
    print(f"  Test {total}: precompute_ms_indicators has all required keys — PASS")
    passed += 1

    # --- Integration: array lengths ---
    total += 1
    n = ind["n"]
    for key in ["closes", "highs", "lows", "opens", "swing_lows", "swing_highs",
                "fvg_snapshots", "bos_events", "ob_snapshots", "liq_zones"]:
        assert len(ind[key]) == n, f"{key} length {len(ind[key])} != {n}"
    print(f"  Test {total}: all arrays have correct length ({n}) — PASS")
    passed += 1

    print(f"\n  {passed}/{total} self-tests PASSED")
    if passed < total:
        raise SystemExit(1)

# Sprint 2 Signal Families Specification

## Context & Motivation

Sprint 1 tested 5 simple signal families (21 configs), all NO-GO. Best PF=0.89 (RSI MR).
Root cause: fixed TP/SL exits have no edge on 4H crypto. DualConfirm proves that
**entry quality** (dual confirm + volume spike) combined with **smart exits** (DC TARGET
100% WR, RSI RECOVERY 92-100% WR) is where the profit comes from.

Sprint 2 shifts focus to **entry-edge discovery**: can we find entries that generate
PF>1.05 even with simple fixed exits? If yes, smart exits will amplify the edge.

### What DualConfirm Teaches Us

```python
# From agent_team_v3.py check_entry_at_bar():
dc_sig = (low <= dc_prev_low AND rsi < 40 AND close > prev_close)
bb_sig = (close <= bb_lower  AND rsi < 40 AND close > prev_close)
# Both must fire (dual confirm), PLUS:
#   vol_spike: cur_vol >= vol_avg * 3.0x
#   vol_confirm: cur_vol > prev_vol
```

Key insight: DualConfirm requires **4 simultaneous conditions** (Donchian touch +
BB touch + RSI oversold + green bar) PLUS volume spike. This extreme selectivity
(39 trades / 526 coins / 721 bars) is what creates the edge. Sprint 2 families
must aim for similar selectivity with different market mechanics.

### Design Principles

1. **Multi-condition entries** -- at least 3 independent filters per signal
2. **Volume confirmation** -- every family includes volume as hard filter
3. **Simple exits first** -- fixed TP/SL/TM only; smart exits come after PF>1.05
4. **Engine compatibility** -- same signal_fn protocol, same indicators.py extension
5. **Cross-sectional signals** -- Family 3 requires engine modification (market context injection)

---

## Family 1: Breakout Anti-Fakeout (H4S-01)

### Thesis

Most breakouts on 4H crypto fail ("fakeout"). A breakout that **closes convincingly
above** the level, with **volume confirmation** and a **minimum range requirement**,
filters out the majority of false signals. By requiring the breakout to be
"confirmed" rather than just touched, we capture the real momentum moves.

### Why Donchian Breakout Over BB Breakout

- Donchian high = absolute N-bar high. Breaking this is an unambiguous new high.
- BB upper = statistical band. In trending markets BB upper keeps rising with price,
  so "breaking above BB upper" can happen at mediocre price levels.
- Sprint 1 BB Squeeze (H4H-02) had PF=0.53-0.59 -- worst family.
- DualConfirm uses Donchian low touch as one of its two signals.
- **Decision**: Primary breakout = Donchian high. BB width as secondary volatility filter.

### Anti-Fakeout Filters

| Filter | Rationale | Parameter |
|--------|-----------|-----------|
| **Close above level** | Intrabar wick above != real breakout. Require `close > dc_high` | `close_margin_pct` (0-2%) |
| **Volume spike** | Real breakouts have volume conviction | `vol_mult` (2.0-4.0x) |
| **Minimum bar range** | Large-body candle = conviction. Doji breakout = fake | `min_range_atr` (0.5-1.5x ATR) |
| **Consecutive close** | Require bar+1 also closes above? (2-bar confirm) | `confirm_bars` (1 or 2) |
| **BB width floor** | Breakout from tight range = more meaningful | `bb_width_min` (percentile) |

### Signal Function Design

```python
def signal_h4s01_breakout_antifake(candles, bar, indicators, params):
    """
    Entry conditions (ALL must be true):
    1. close[bar] > dc_high[bar-1] * (1 + close_margin_pct/100)
       (close above previous N-bar high with margin)
    2. cur_vol >= vol_avg * vol_mult
       (volume spike confirms genuine breakout)
    3. (high[bar] - low[bar]) >= atr[bar] * min_range_atr
       (large bar body = conviction, not a wick)
    4. close[bar] > open[bar]
       (green bar -- buying pressure)
    5. Optional: bb_width[bar] < bb_width_percentile
       (breakout from compressed volatility = stronger)

    Exit: fixed TP/SL/TM (trend template)
    Strength: volume ratio * (close - dc_high) / dc_high
    """
```

### Indicator Requirements

All available in existing `indicators.py`:
- `dc_prev_high` -- **NEW**: Donchian previous high (need to add; dc_prev_low exists)
- `atr` -- already computed
- `bb_width` -- already computed
- `vol_avg` -- already computed
- `closes`, `highs`, `lows`, `volumes` -- already computed

**Indicator addition needed**: `dc_prev_high[bar]` = max(highs[bar-DC_PERIOD:bar])
(same causal pattern as existing `dc_prev_low`).

### Parameter Sweep

| Parameter | Range | Default | Sweep Values |
|-----------|-------|---------|--------------|
| `dc_period` | 10-30 | 20 | [15, 20, 25] |
| `close_margin_pct` | 0-3% | 0.5 | [0, 0.5, 1.0] |
| `vol_mult` | 1.5-4.0 | 2.5 | [2.0, 2.5, 3.0] |
| `min_range_atr` | 0.3-2.0 | 0.8 | [0.5, 0.8, 1.2] |
| `confirm_bars` | 1-2 | 1 | [1] (keep simple for Stage 0) |
| `sl_pct` | 3-10 | 5 | [5, 8] |
| `tp_pct` | 8-15 | 10 | [8, 12] |
| `time_limit` | 10-30 | 20 | [15, 20] |
| `max_pos` | 1-5 | 3 | [3] |

**Recommended Stage 0 sweep**: 3x3x3 x 2x2x2 = 216 combos total.
But to keep runtime manageable: select 8-10 representative variants
(vary entry filters first, fix exits at 2 templates).

### Concrete Param Variants (Stage 0)

```python
param_variants = [
    # Variant A: Tight filter (selective)
    {"dc_period": 20, "close_margin_pct": 1.0, "vol_mult": 3.0,
     "min_range_atr": 1.0, "sl_pct": 5, "tp_pct": 10, "time_limit": 20, "max_pos": 3},
    # Variant B: Moderate filter
    {"dc_period": 20, "close_margin_pct": 0.5, "vol_mult": 2.5,
     "min_range_atr": 0.8, "sl_pct": 5, "tp_pct": 10, "time_limit": 20, "max_pos": 3},
    # Variant C: Loose filter (more trades)
    {"dc_period": 20, "close_margin_pct": 0, "vol_mult": 2.0,
     "min_range_atr": 0.5, "sl_pct": 5, "tp_pct": 10, "time_limit": 20, "max_pos": 3},
    # Variant D: Longer lookback
    {"dc_period": 25, "close_margin_pct": 0.5, "vol_mult": 2.5,
     "min_range_atr": 0.8, "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
    # Variant E: Short lookback (more signals)
    {"dc_period": 15, "close_margin_pct": 0.5, "vol_mult": 2.5,
     "min_range_atr": 0.8, "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
    # Variant F: Maximum selectivity (DualConfirm-like strictness)
    {"dc_period": 20, "close_margin_pct": 1.0, "vol_mult": 3.0,
     "min_range_atr": 1.2, "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
]
```

### Expected Trade Frequency

DualConfirm = 39 trades on 526 coins / 721 bars with 4 hard filters.
Breakout anti-fakeout has 4 filters (DC break + vol + range + green bar).
Expect 30-100 trades for tight variants, 100-300 for loose.

---

## Family 2: Volatility Exhaustion Fade (H4S-02)

### Thesis

After a volatility expansion phase (large price swings, wide BB), volatility
**mean-reverts**: it contracts back toward its average. The exhaustion fade enters
when volatility has expanded AND is now **contracting**, betting that the move is
overextended and will reverse or consolidate.

This is NOT the same as Sprint 1's BB Squeeze Breakout (H4H-02), which bought the
expansion. This family does the opposite: it fades the expansion once exhaustion signs
appear.

### Volatility Exhaustion Detection

A 3-phase pattern:

1. **Expansion phase**: BB width rises to high percentile (>75th of recent N bars)
2. **Peak detection**: BB width was high BUT is now declining (width[bar] < width[bar-1])
3. **Exhaustion confirmation**: Price fails to make new extreme
   (high[bar] < high[bar-1] for bearish exhaustion we'd fade into long,
    or close rejects from BB upper for a short-then-long setup)

For long entries (we only go long):
- After a sharp DOWN move (BB expands downward), volatility exhausts
- Price stops making new lows, BB width starts contracting
- RSI is oversold (confirms the move was meaningful)
- Entry = "the worst is over, fade the panic"

### Signal Function Design

```python
def signal_h4s02_vol_exhaustion_fade(candles, bar, indicators, params):
    """
    Entry conditions (ALL must be true):
    1. BB width WAS elevated:
       max(bb_width[bar-expansion_lookback:bar]) > bb_width_pct_high percentile
       (there was a recent volatility expansion)
    2. BB width is NOW declining:
       bb_width[bar] < bb_width[bar-1]
       AND bb_width[bar-1] < bb_width[bar-2] (optional: 2-bar decline)
       (volatility is mean-reverting = exhaustion)
    3. Price NOT making new low:
       low[bar] > min(lows[bar-n_bars_no_new_low:bar])
       (downside exhaustion confirmed)
    4. RSI oversold filter:
       rsi[bar] < rsi_max (confirms meaningful prior move)
    5. Volume declining:
       cur_vol < vol_avg * vol_decline_max
       (panic volume is subsiding)

    Exit: fixed TP/SL/TM (mean-reversion template)
    Strength: bb_width percentile rank (higher expansion = stronger signal)
    """
```

### Key Distinction from Sprint 1 BB Squeeze

| | Sprint 1 H4H-02 (BB Squeeze) | Sprint 2 H4S-02 (Vol Exhaustion) |
|---|---|---|
| **Phase** | Buys at squeeze (low vol) | Buys after expansion exhausts |
| **BB width** | Must be LOW (squeeze) | Must have been HIGH, now declining |
| **Price direction** | Up (above BB mid) | Down exhausted (not making new lows) |
| **Volume** | High (breakout volume) | Declining (panic subsiding) |
| **Template** | Trend (continuation) | MR (mean reversion) |

### Indicator Requirements

All available in existing `indicators.py`:
- `bb_width` -- already computed (BB width ratio)
- `rsi` -- already computed
- `vol_avg` -- already computed
- `closes`, `highs`, `lows`, `volumes` -- already computed

**New computation needed in signal_fn**: BB width percentile over lookback window.
This is a local computation (not a new indicator column), same pattern as Sprint 1
H4H-02 squeeze percentile.

### Parameter Sweep

| Parameter | Range | Default | Sweep Values |
|-----------|-------|---------|--------------|
| `expansion_lookback` | 10-30 | 20 | [15, 20, 30] |
| `bb_width_pct_high` | 60-90 | 75 | [70, 80] |
| `decline_bars` | 1-3 | 2 | [1, 2] |
| `no_new_low_bars` | 3-10 | 5 | [3, 5] |
| `rsi_max` | 30-50 | 40 | [35, 40, 45] |
| `vol_decline_max` | 0.5-1.5 | 1.0 | [0.8, 1.0] |
| `sl_pct` | 3-8 | 5 | [5, 8] |
| `tp_pct` | 5-10 | 8 | [5, 8] |
| `time_limit` | 10-20 | 15 | [10, 15] |
| `max_pos` | 1-5 | 3 | [3] |

### Concrete Param Variants (Stage 0)

```python
param_variants = [
    # Variant A: Classic exhaustion (tight oversold)
    {"expansion_lookback": 20, "bb_width_pct_high": 75, "decline_bars": 2,
     "no_new_low_bars": 5, "rsi_max": 35, "vol_decline_max": 1.0,
     "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
    # Variant B: Wider RSI, shorter lookback
    {"expansion_lookback": 15, "bb_width_pct_high": 70, "decline_bars": 1,
     "no_new_low_bars": 3, "rsi_max": 40, "vol_decline_max": 1.0,
     "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
    # Variant C: Strong expansion required
    {"expansion_lookback": 20, "bb_width_pct_high": 80, "decline_bars": 2,
     "no_new_low_bars": 5, "rsi_max": 40, "vol_decline_max": 0.8,
     "sl_pct": 5, "tp_pct": 5, "time_limit": 10, "max_pos": 3},
    # Variant D: Loose (more trades)
    {"expansion_lookback": 30, "bb_width_pct_high": 70, "decline_bars": 1,
     "no_new_low_bars": 3, "rsi_max": 45, "vol_decline_max": 1.0,
     "sl_pct": 8, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
    # Variant E: Maximum strictness
    {"expansion_lookback": 20, "bb_width_pct_high": 80, "decline_bars": 2,
     "no_new_low_bars": 5, "rsi_max": 35, "vol_decline_max": 0.8,
     "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
]
```

### Expected Trade Frequency

This is a contrarian signal (fade exhaustion). The multi-condition filter
(expansion + decline + no new low + RSI) should produce 40-150 trades.
More selective than Sprint 1 single-filter signals.

---

## Family 3: Cross-Sectional Relative Strength (H4S-03)

### Thesis

Not all coins move equally. In any given period, some coins have stronger momentum
than others. By **ranking all coins** and only trading the top-N% momentum cohort,
we concentrate capital in the strongest movers. This is a well-known factor in
traditional finance ("momentum factor") adapted to crypto.

### Engine Modification Required

The Sprint 1 engine runs per-coin but has no cross-coin awareness. For cross-sectional
signals we need market context -- the same pattern already implemented for HF screening
in `strategies/hf/screening/market_context.py`.

**Approach** (proven pattern from HF Sprint 5, ADR-HF-017):

1. Precompute `market_context` at startup:
   ```python
   from strategies.hf.screening.market_context import precompute_market_context
   market_ctx = precompute_market_context(data, coins)
   ```
   Or: implement a simplified version in `strategies/4h/sprint2/market_context.py`
   that computes only what we need (momentum rank + breadth).

2. Inject into params before backtest:
   ```python
   enriched_params = {**params, '__market__': market_ctx}
   ```

3. Signal function reads `params['__market__']['momentum_rank'][coin][bar]`
   to check if this coin is in the top cohort.

4. Per-coin identity: the engine already passes `pair` to `signal_fn` indirectly
   (via `indicators` which is per-pair). We need to pass the pair name explicitly.
   **Option A**: Add `indicators['__coin__'] = pair` in `precompute_all()`.
   **Option B**: Modify engine to pass `pair` as extra arg.
   Recommendation: Option A (minimal engine change, same pattern as HF).

### Momentum Metrics

| Metric | Formula | Rationale |
|--------|---------|-----------|
| **N-bar return** | `(close[bar-1] - close[bar-1-N]) / close[bar-1-N]` | Raw momentum. Simple, proven. |
| **Vol-adjusted return** | `return / stdev(bar_returns)` | Sharpe-like. Penalizes erratic movers. |
| **Volume-weighted momentum** | `return * (avg_vol / median_vol)` | Rewards liquid movers. |

**Recommended**: Vol-adjusted return (same as HF market_context.py `momentum_rank`).
This is already proven causal in HF screening with 14 tests.

### Signal Function Design

```python
def signal_h4s03_relative_strength(candles, bar, indicators, params):
    """
    Entry conditions (ALL must be true):
    1. Coin is in top-N% of momentum ranking:
       momentum_rank[coin][bar] <= n_coins * top_pct / 100
    2. Momentum is positive (not just "least bad"):
       N-bar return > 0
    3. Volume confirmation:
       cur_vol >= vol_avg * vol_mult
    4. Price above SMA50 (trend filter):
       close[bar] > sma50[bar]
    5. Market breadth filter (optional):
       breadth_up[bar] > breadth_min (only trade when >X% of coins are up)

    Exit: fixed TP/SL/TM (trend template)
    Strength: 1 - (rank / n_coins)  (higher for better rank)
    """
```

### Indicator Requirements

Existing in `indicators.py`:
- `sma50` -- already computed
- `vol_avg` -- already computed
- `closes`, `volumes` -- already computed

New (from market context):
- `momentum_rank[coin][bar]` -- per-coin per-bar rank (1=best)
- `breadth_up[bar]` -- fraction of coins up
- `__coin__` -- pair identifier in indicators dict

**Options for market context**:
1. Reuse HF `market_context.py` directly (import and call)
2. Build simplified Sprint 2 version (less code, 4H-specific lookbacks)

Recommendation: Option 2 (build simplified version). Reasons:
- HF uses 10-bar lookback tuned for 1H. For 4H we might want different periods.
- Sprint 2 does not need BTC ATR ratio or mean-revert rank.
- Simpler code = easier to debug and extend.

### Cross-Sectional Market Context (Sprint 2)

```python
# strategies/4h/sprint2/market_context.py

def precompute_sprint2_context(data, coins, momentum_period=10):
    """
    Returns:
        momentum_rank: {coin: [rank_at_bar_0, rank_at_bar_1, ...]}
        momentum_return: {coin: [return_at_bar_0, ...]}
        breadth_up: [fraction_up_at_bar_0, ...]
        n_ranked: [n_coins_with_data_at_bar_0, ...]

    CAUSALITY: All values at bar N use data up to bar N-1 only.
    """
```

### Parameter Sweep

| Parameter | Range | Default | Sweep Values |
|-----------|-------|---------|--------------|
| `momentum_period` | 5-20 | 10 | [5, 10, 20] |
| `top_pct` | 5-30% | 10 | [5, 10, 20] |
| `vol_mult` | 1.0-3.0 | 1.5 | [1.0, 1.5, 2.0] |
| `require_positive_return` | bool | True | [True] |
| `sma_filter` | bool | True | [True, False] |
| `breadth_min` | 0-0.6 | 0.4 | [0.3, 0.4, 0.5] |
| `sl_pct` | 5-10 | 8 | [5, 8] |
| `tp_pct` | 8-15 | 12 | [8, 12] |
| `time_limit` | 15-30 | 25 | [20, 25] |
| `max_pos` | 1-5 | 3 | [3] |

### Concrete Param Variants (Stage 0)

```python
param_variants = [
    # Variant A: Top 10% with SMA filter
    {"momentum_period": 10, "top_pct": 10, "vol_mult": 1.5,
     "require_positive_return": True, "sma_filter": True, "breadth_min": 0.4,
     "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
    # Variant B: Top 5% (very selective)
    {"momentum_period": 10, "top_pct": 5, "vol_mult": 2.0,
     "require_positive_return": True, "sma_filter": True, "breadth_min": 0.4,
     "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
    # Variant C: Top 20% (more trades)
    {"momentum_period": 10, "top_pct": 20, "vol_mult": 1.0,
     "require_positive_return": True, "sma_filter": True, "breadth_min": 0.3,
     "sl_pct": 5, "tp_pct": 8, "time_limit": 20, "max_pos": 3},
    # Variant D: Short momentum (5-bar)
    {"momentum_period": 5, "top_pct": 10, "vol_mult": 1.5,
     "require_positive_return": True, "sma_filter": True, "breadth_min": 0.4,
     "sl_pct": 5, "tp_pct": 10, "time_limit": 20, "max_pos": 3},
    # Variant E: Long momentum (20-bar)
    {"momentum_period": 20, "top_pct": 10, "vol_mult": 1.5,
     "require_positive_return": True, "sma_filter": True, "breadth_min": 0.4,
     "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
    # Variant F: No SMA filter, lower breadth (bear-market friendly)
    {"momentum_period": 10, "top_pct": 10, "vol_mult": 1.5,
     "require_positive_return": True, "sma_filter": False, "breadth_min": 0.3,
     "sl_pct": 8, "tp_pct": 12, "time_limit": 25, "max_pos": 3},
]
```

### Expected Trade Frequency

Top 10% of 487 coins = ~49 coins eligible per bar. With volume filter + SMA filter +
breadth filter, expect 80-300 trades. More trades than DualConfirm but more selective
than Sprint 1 simple signals.

### Engine Integration Plan

1. Add `__coin__` key to each coin's indicator dict in `precompute_all()`:
   ```python
   indicators[pair]["__coin__"] = pair
   ```

2. Precompute market context before backtest loop:
   ```python
   market_ctx = precompute_sprint2_context(data, coins)
   enriched_params = {**params, "__market__": market_ctx}
   ```

3. Pass `enriched_params` to `run_backtest()` instead of `params`.

4. Signal function extracts:
   ```python
   coin = indicators.get("__coin__", "")
   market = params.get("__market__", {})
   rank = market.get("momentum_rank", {}).get(coin, [0]*999)[bar]
   n_ranked = market.get("n_ranked", [0]*999)[bar]
   ```

This is the exact same injection pattern as HF Sprint 5 (ADR-HF-017),
proven causal with 14 tests. No engine.py modification needed -- just
parameter enrichment at the sweep runner level.

---

## Family 4: RSI + Trend/Regime Filter (H4S-04)

### Thesis

Sprint 1's RSI Mean Reversion (H4H-01) was the best performer (PF=0.89) but failed
because it bought oversold conditions **regardless of regime**. In a bear market,
oversold keeps getting more oversold.

This family adds **regime context**: only buy RSI oversold when the broader environment
suggests the dip will recover. Three regime filters tested as sub-variants:

| Sub-variant | Filter | Logic |
|-------------|--------|-------|
| **A: SMA Slope** | SMA50 slope > 0 | Only buy dips in uptrending coins |
| **B: ADX + DI** | ADX > threshold AND +DI > -DI | Only buy dips in strong uptrend |
| **C: Momentum Confirm** | N-bar return > 0 | Only buy dips if medium-term direction is up |

### Why RSI as Component (Not Standalone)

Sprint 1 proved standalone RSI has no edge (PF=0.83-0.89). But RSI IS useful as a
**timing component** within a multi-filter entry:
- DualConfirm uses RSI<40 as one of 4 filters
- RSI Recovery (target=45) is the dominant exit (100% WR, +$4,581)
- RSI identifies relative oversold within a regime -- the regime filter determines
  whether that oversold is a dip-to-buy or a trap

### Signal Function Design

```python
def signal_h4s04_rsi_regime(candles, bar, indicators, params):
    """
    Entry conditions (ALL must be true):
    1. RSI oversold:
       rsi[bar] < rsi_max
    2. Green bar (bounce):
       close[bar] > close[bar-1]
    3. Volume floor:
       cur_vol >= vol_avg * vol_floor_mult
    4. Regime filter (one of three, selected by regime_type param):
       A: sma50_slope > 0 (SMA50[bar] > SMA50[bar-slope_lookback])
       B: adx[bar] > adx_min AND plus_di > minus_di
       C: close[bar-1] > close[bar-1-momentum_lookback] (N-bar return > 0)

    Exit: fixed TP/SL/TM (MR template)
    Strength: (rsi_max - rsi) / rsi_max * regime_strength_factor
    """
```

### Indicator Requirements

Existing in `indicators.py`:
- `rsi` -- already computed
- `sma50` -- already computed
- `adx` -- already computed
- `vol_avg` -- already computed
- `closes`, `highs`, `lows`, `volumes` -- already computed

New indicator needed:
- `plus_di` and `minus_di` -- directional indicators (for sub-variant B).
  Currently `calc_adx()` computes these internally but only outputs ADX.
  Need to expose +DI/-DI as separate arrays.
  **Alternative**: Skip sub-variant B and use ADX > threshold + price > SMA as proxy.
  Recommendation: Implement +DI/-DI in indicators.py for completeness.

### Parameter Sweep

| Parameter | Range | Default | Sweep Values |
|-----------|-------|---------|--------------|
| `rsi_max` | 25-45 | 35 | [30, 35, 40] |
| `vol_floor_mult` | 0.5-2.0 | 1.0 | [0.8, 1.0, 1.5] |
| `regime_type` | A/B/C | A | [A, B, C] |
| `slope_lookback` (A) | 5-20 | 10 | [5, 10] |
| `adx_min` (B) | 15-30 | 20 | [20, 25] |
| `momentum_lookback` (C) | 5-20 | 10 | [5, 10, 20] |
| `sl_pct` | 3-8 | 5 | [5, 8] |
| `tp_pct` | 5-10 | 8 | [5, 8] |
| `time_limit` | 10-20 | 15 | [10, 15] |
| `max_pos` | 1-5 | 3 | [3] |

### Concrete Param Variants (Stage 0)

```python
param_variants = [
    # Sub-A: SMA Slope filter
    {"rsi_max": 35, "vol_floor_mult": 1.0, "regime_type": "A",
     "slope_lookback": 10, "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
    {"rsi_max": 40, "vol_floor_mult": 0.8, "regime_type": "A",
     "slope_lookback": 5, "sl_pct": 5, "tp_pct": 8, "time_limit": 15, "max_pos": 3},
    # Sub-B: ADX filter
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
]
```

### Expected Trade Frequency

Sprint 1 RSI MR had 280-531 trades. The regime filter will eliminate maybe 50-70%
of those (bear market = most coins have negative SMA slope / momentum). Expect 80-200
trades. This is the right range -- selective enough for edge, frequent enough for
statistical significance.

---

## Implementation Plan

### Phase 1: Infrastructure (before any signal code)

1. **Create `strategies/4h/sprint2/` package**
   - `__init__.py` -- package docstring
   - `indicators.py` -- extends Sprint 1 indicators with new computations
   - `market_context.py` -- cross-sectional context for Family 3
   - `hypotheses.py` -- 4 families with signal functions and param variants
   - `gates.py` -- reuse Sprint 1 gates (import, no copy)

2. **Indicator additions**
   - `dc_prev_high[bar]` = max(highs[bar-DC_PERIOD:bar]) -- for Family 1
   - `plus_di[bar]`, `minus_di[bar]` -- for Family 4B (expose from ADX calc)

3. **Market context module**
   - `precompute_sprint2_context(data, coins)` -- momentum rank + breadth
   - Causality tests (same pattern as HF `test_market_context.py`)

### Phase 2: Signal Functions

4. **H4S-01**: `signal_h4s01_breakout_antifake()` -- 6 variants
5. **H4S-02**: `signal_h4s02_vol_exhaustion_fade()` -- 5 variants
6. **H4S-03**: `signal_h4s03_relative_strength()` -- 6 variants
7. **H4S-04**: `signal_h4s04_rsi_regime()` -- 7 variants (3 sub-types)

Total: 24 configs for Stage 0 sweep.

### Phase 3: Sweep Runner

8. **`scripts/run_sprint2_sweep.py`**
   - Same structure as Sprint 1 runner
   - Extra step: precompute market context for Family 3
   - Inject `__market__` into params for all configs (no-op for families that don't use it)
   - Inject `__coin__` into indicators for all coins

### Phase 4: Evaluation

9. Run sweep on 487-coin universe (same as Sprint 1)
10. Apply Sprint 1 gates (G1-G4 + S1-S2)
11. Any config with PF > 1.05: advance to truth-pass via agent_team_v3
12. Write ADR-4H-008 with results

### Relaxed Stage 0 Gate

For Stage 0 screening, the hard kill gate is:
- **G0: PF > 1.05** (advancement threshold, not production gate)
- Configs with PF > 1.05 get advanced to Stage 1 (truth-pass with smart exits)
- Full Sprint 1 gates (PF >= 1.30, DD <= 15%) apply only after smart exit integration

Rationale: Sprint 1 showed that simple exits kill edge. PF > 1.05 with fixed exits
indicates **entry edge** that smart exits can amplify. DualConfirm has PF~0.9 with
fixed exits but PF 3.2-3.8 with smart exits.

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| All families PF < 1.0 (Sprint 1 repeat) | 40% | High | Multi-condition filters should be more selective |
| Cross-sectional momentum doesn't work in bear market | 50% | Medium | Bear-market-friendly variant without SMA filter |
| Too few trades for statistical significance | 30% | Medium | Loose variants ensure minimum trade count |
| Market context causality violation | Low | Critical | Truncation tests from HF pattern |
| Engine sizing bug (Sprint 1 had one) | Low | High | Verify equity never goes negative in tests |

### Null Hypothesis

If ALL 24 configs produce PF < 1.0, the conclusion is:
**4H crypto with Kraken fees has no exploitable entry edge with simple exits.**
This would confirm that DualConfirm's edge comes entirely from its exit system,
and future research should focus on **exit innovation** rather than entry discovery.

---

## File Inventory (to be created)

```
strategies/4h/sprint2/
    __init__.py
    indicators.py          -- dc_prev_high, plus_di, minus_di
    market_context.py      -- momentum rank, breadth (causal)
    hypotheses.py          -- 4 families, 24 configs
    gates.py               -- imports Sprint 1 gates
    SIGNAL_FAMILIES_SPEC.md -- this file

scripts/
    run_sprint2_sweep.py   -- sweep runner with market context injection
```

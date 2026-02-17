# HF Hypotheses — Higher-Frequency Research Planning

**Date**: 2026-02-15
**Branch**: hf-dev
**Status**: Research planning (no code changes yet)

---

## 1. Current State Assessment

### What We Learned from H1/H2/H3 and the H2 Grid Sweep

**H1 — LTF Mean Reversion** (RSI<30, tp8/sl6, tm8):
Weak results. WR 51.5%, PF 1.18. Tight RSI threshold (30) killed the win rate by filtering out too many viable entries. The DualConfirm signal set already requires oversold conditions via Donchian+Bollinger; layering an aggressive RSI filter on top starves the strategy of trades.

**H2 — Momentum Burst** (vs>=4x, relaxed RSI, tp15/sl8, tm12):
Promising smoke run (WR 66.7%, PF 2.43, $2,288). Selected for Phase 2 grid sweep.

**H3 — Vol Breakout** (vs>=5x, tp20/sl10, tm20):
Too few trades (15). Extreme volume filter (5x) reduces the tradeable universe to a handful of events. PF 1.05 — no edge.

**H2 Grid Sweep (Phase 2)**:
- 1280 configs tested across 5 axes: rsi_max [45-60], sl_pct [6-12], tm [8-15], tp [10-18], vs [3.0-5.0]
- 796 passed HF gates (trades>=20, PF>=1.6, DD<=30%)
- 780 survived both friction tests (2x+20bps, 1-candle-later)
- Champion H2: vs3.0/rsi45/tp12/sl8/tm15 -- 31 trades, $4,114, PF 2.73, DD 24.7%

### Key Insight: Champion H2 Converged to Near-GRID_BEST

The champion differs from GRID_BEST on only two parameters:

| Param | GRID_BEST | Champion H2 | Delta |
|-------|-----------|-------------|-------|
| vol_spike_mult | 2.5 | 3.0 | +0.5 |
| sl_pct | 10 | 8 | -2 |
| rsi_max | 45 | 45 | same |
| tp_pct | 12 | 12 | same |
| time_max_bars | 15 | 15 | same |

This convergence tells us the 4H DualConfirm parameter space is largely explored. The sweep started from a different hypothesis (high volume burst with relaxed RSI) and landed back near GRID_BEST. Further 4H parameter sweeps are unlikely to find material improvement.

### RSI Insensitivity Finding

At vol_spike_mult >= 3.0, RSI threshold is irrelevant between 45 and 60. The top 4 configs in the sweep (ranks 1-4) have identical results across rsi_max = 45, 50, 55, 60. This means:

- At higher volume filters, the volume spike itself is the dominant signal
- RSI adds no incremental filtering power when volume is already screened at 3x
- The volume spike effectively subsumes the RSI condition
- This is consistent with the DualConfirm logic: Donchian+Bollinger already ensure price is at a local low; if volume is strongly elevated, RSI is redundant

**Implication**: If we want RSI to matter, we need either (a) a different RSI variant (e.g., RSI divergence, not just level) or (b) lower timeframes where RSI oscillates faster and provides more discriminating information.

---

## 2. Three HF Strategy Families (Future Research)

**Terminology note**: "HF" in this project means "Higher Frequency" relative to the 4H baseline. This is NOT algorithmic high-frequency trading. All strategies operate on candle data from the Kraken REST API.

### Family A: LTF Mean Reversion (15m-1H)

**Hypothesis**: DualConfirm signals on 1H candles exhibit faster mean-reversion with tighter TP/SL windows, producing more trades with lower per-trade P&L but potentially better risk-adjusted returns.

**Rationale**:
- 1H candles provide 4x the signal frequency of 4H
- Mean-reversion patterns (oversold bounce) should complete faster on shorter timeframes
- More trades enables better statistical significance and smoother equity curves

**Expected behavior**:
- Trade count: 80-150 (vs 31 at 4H)
- Per-trade P&L: $20-60 (vs ~$130 at 4H)
- TP/SL: 4-8% range (vs 10-12% at 4H)
- Time-in-trade: 4-10 bars (4-10 hours vs 2.5 days at 4H)

**Microstructure considerations**:
- 1H candles on Kraken still have reasonable volume data for 500+ coins
- Spread/slippage impact increases at shorter timeframes (need realistic friction model)
- 1H volume spikes may reflect intraday noise rather than institutional flow

**Data requirement**:
- 1H candle cache for 425+ coins, minimum 30 days (~720 bars/coin)
- Estimated storage: ~18,000 candles/coin x 425 coins = 7.6M data points
- Source: Kraken OHLCVT REST API (`Interval=60`)

**Risk**: Entry/exit slippage becomes more significant. At 4% TP, a 0.52% round-trip fee (Kraken maker+taker) eats 13% of gross profit vs 4.3% at 12% TP.

---

### Family B: Multi-Timeframe Confirmation (4H signal, 1H execution)

**Hypothesis**: Use 4H DualConfirm for signal generation (proven edge) but drop to 1H for timing entry and exit, achieving better fill prices and tighter stops.

**Rationale**:
- 4H signal quality is validated (GRID_BEST passed all 6 robustness tests)
- 1H execution allows waiting for a more precise entry within the 4H signal bar
- Tighter stops reduce per-trade risk without degrading signal quality

**Expected behavior**:
- Same trade count as 4H (~30-35) since signal generation unchanged
- Better entry prices (enter on 1H confirmation within 4H signal bar)
- Tighter SL: 4-6% instead of 8-10% (smaller adverse excursion on 1H)
- Potentially higher win rate from improved entry timing

**Data requirement**:
- Both 4H and 1H candle caches with aligned timestamps
- Timestamp alignment logic: each 4H bar maps to exactly 4 x 1H bars
- Need to handle edge cases: partial bars at boundaries, missing 1H data

**Risk**: Complexity. More parameters (1H entry logic, 1H exit triggers) increase overfitting risk. The added complexity may not justify the improvement if entry timing variance is small relative to the 4H bar range.

---

### Family C: Volume Microstructure (15m-1H)

**Hypothesis**: Volume spike detection on 15m-1H captures institutional flow and accumulation patterns earlier and more precisely than 4H aggregated volume.

**Rationale**:
- A 4H volume spike is the sum of 16 x 15m bars; the spike could be concentrated in one 15m bar or spread across many
- Concentrated spikes (single 15m bar with 10x volume) are more likely institutional
- Distributed spikes may be organic retail activity
- Detecting the shape of volume distribution within a 4H bar could improve signal quality

**Expected behavior**:
- Same or fewer trades (more selective entry)
- Higher win rate from better volume signal quality
- Volume profile features: spike concentration, bid-ask imbalance proxy (close position within bar)

**Data requirement**:
- 15m or 1H volume data with sufficient history (30+ days)
- For 15m: 425 coins x 30 days x 96 bars/day = 1.2M candles (substantial)
- Volume profile metrics need to be computed per-bar

**Risk**: Noise at 15m is significantly higher. Wash trading and market maker activity create false volume signals. 15m OHLCV from Kraken may not have enough depth for illiquid coins.

---

## 3. Why "HF-echt" (True HF) Requires a Data Pipeline

### Current data infrastructure

The project currently operates on static JSON caches:

| Cache | Coins | Bars | Timeframe | Size |
|-------|-------|------|-----------|------|
| candle_cache_tradeable.json | 425 | 721 | 4H | ~120 days |
| candle_cache_532.json | 526 | ~660 | 4H | ~110 days |

These caches were fetched once and stored locally. The backtest engine (`agent_team_v3.py`) reads them at startup via `precompute_all()`. There is no incremental update mechanism.

### What LTF research requires

**1. Kraken API integration for 1H/15m candle fetching**
- Endpoint: `GET https://api.kraken.com/0/public/OHLC?pair={pair}&interval={minutes}&since={timestamp}`
- Rate limit: 1 call/second for public endpoints (no auth needed for OHLC)
- Returns max 720 bars per call
- For 425 coins at 1H: 425 API calls minimum (one per coin)
- Estimated time: ~8-10 minutes with rate limiting

**2. Cache management**
- Incremental updates: fetch only new bars since last timestamp
- Deduplication: Kraken sometimes returns overlapping bars at boundaries
- Format: same OHLCVT structure as existing 4H cache for engine compatibility
- File: `candle_cache_1h.json` (separate from 4H cache)

**3. Data validation pipeline**
- OHLCV integrity: open/high/low/close relationships (high >= max(open,close), low <= min(open,close))
- Gap detection: flag coins with missing bars (>2 consecutive gaps)
- Volume sanity: flag coins with zero volume bars (illiquid, exclude from universe)
- Timestamp monotonicity: bars must be strictly increasing in time

**4. Multi-timeframe alignment (for Family B)**
- Each 4H bar at timestamp T maps to 1H bars at T, T+1h, T+2h, T+3h
- Need mapping function: `get_1h_bars_for_4h_bar(coin, bar_index) -> List[1h_bars]`
- Handle timezone and DST edge cases (Kraken uses UTC, no DST issues)

**5. Storage and refresh strategy**

| Cache | Coins | Bars/coin | Total bars | Est. JSON size |
|-------|-------|-----------|------------|----------------|
| 1H x 30 days | 425 | 720 | 306,000 | ~80 MB |
| 15m x 30 days | 425 | 2,880 | 1,224,000 | ~320 MB |
| 15m x 7 days | 425 | 672 | 285,600 | ~75 MB |

Recommendation: Start with 1H x 30 days. The 80 MB cache is manageable and provides enough bars for DualConfirm indicator warmup (20-bar lookback for volume average, 20-bar Bollinger, 20-bar Donchian).

---

## 4. Recommended Next Steps (Prioritized)

**Phase 3A: 1H Data Pipeline** (prerequisite for all families)

1. Build `fetch_1h_candles.py` using Kraken public REST API
   - Input: list of tradeable pairs from existing cache
   - Output: `candle_cache_1h.json` in same format as 4H cache
   - Include rate limiting, retry logic, progress bar
2. Add data validation: OHLCV integrity checks, gap detection, volume sanity
3. Verify indicator computation works on 1H data (same `precompute_all()` function)

**Phase 3B: 1H DualConfirm Baseline**

4. Run DualConfirm on 1H with GRID_BEST params as-is (tp12/sl10/vs2.5/rsi45/tm15)
   - This establishes whether the strategy transfers to 1H without modification
   - Expected: more trades, possibly lower PF (signals may be noisier)
5. If baseline shows edge (PF > 1.3, trades > 50): proceed to 1H param sweep
6. If no edge: pivot to Family B (multi-TF confirmation)

**Phase 3C: 1H Param Sweep (conditional)**

7. Sweep TP/SL on tighter ranges: tp [4,6,8,10], sl [3,5,7,9]
8. Sweep time_max_bars on shorter ranges: tm [4,6,8,10,12]
9. Apply HF gates + friction tests (same as H2 sweep)
10. Select 1H champion, run Phase 3 validation (WF, MC, window sweep)

**Phase 3D: Family B Exploration (conditional)**

11. Build 4H-to-1H alignment logic
12. Implement 1H entry timing within 4H signal bars
13. Test against pure 4H execution as control

---

## 5. What NOT to Do

- **Don't call current 4H research "HF" in any external deliverables or documentation outside this research folder.** The H1/H2/H3 hypotheses and the grid sweep are 4H parameter variants, not higher-frequency strategies.

- **Don't over-optimize on 4H.** The H2 sweep confirmed that the 4H DualConfirm parameter space is saturated. Champion H2 converged to within 2 parameters of GRID_BEST. Further 4H sweeps will produce marginal variants, not new edge.

- **Don't build a 15m pipeline before validating 1H.** 15m data is 4x larger, noisier, and more expensive to fetch. If DualConfirm doesn't work on 1H, it won't work on 15m either. 1H is the minimum viable step down.

- **Don't modify `trading_bot/` for HF research.** The backtest engine is shared and GRID_BEST-locked. All HF code lives under `strategies/hf/`. If engine changes are needed (e.g., multi-timeframe support), they must be proposed, reviewed, and tested against the existing 66-test suite before merging.

- **Don't assume 4H indicator parameters transfer to 1H.** A 20-bar Bollinger on 4H covers 80 hours; on 1H it covers 20 hours. The lookback windows may need recalibration for shorter timeframes. This is a research question, not an assumption.

- **Don't skip friction modeling on LTF.** As timeframe decreases, trading costs consume a larger fraction of gross profit. Every 1H candidate must pass friction tests with at least the same rigor as 4H candidates.

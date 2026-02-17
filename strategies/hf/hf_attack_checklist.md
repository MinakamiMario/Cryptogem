# Red Team Attack Checklist -- HF 4H Variant Research

**Date**: 2026-02-15
**Scope**: DualConfirm strategy on 4H candles, tp_sl exit type, 526 coins (Kraken), 721 bars
**Champion H2**: vs3.0/rsi45/tp12/sl8/tm15 (31 trades, PF 2.73, P&L $4,114)
**GRID_BEST**: vs2.5/rsi45/tp12/sl10/tm15 (32 trades, PF 2.61, P&L $4,718)

---

## 1. Leakage / Purge Attacks

### 1.1 Is indicator precompute causal?

**Attack vector**: `precompute_all(data, coins, end_bar)` uses `end_bar` as exclusive upper bound. If `end_bar` is not set, all bars are used -- indicators at bar N could use data from bar N+1..end, leaking future information into entry/exit decisions.

**Evidence**: The function slices `candles[:n]` where `n = min(len(candles), end_bar)`. For each bar, it computes indicators on `closes[:bar+1]`, using only data up to and including bar. The Donchian prev_low explicitly uses `wh[:-1], wl[:-1]` (excludes current bar high/low). This is causal.

**Severity**: LOW

**Status**: MITIGATED -- The per-bar loop `for bar in range(min_bars, n)` computes indicators using `closes[:bar+1]`, which is causal. The Donchian channel uses `wh[:-1]` to compute the previous channel, which is correct. The `end_bar` parameter further restricts the universe for walk-forward splits.

---

### 1.2 Does WF embargo prevent information leakage?

**Attack vector**: Walk-forward validation must have an embargo zone between train and test to prevent indicators with lookback windows from leaking test-period data into the training evaluation.

**Evidence**: Two WF implementations exist:
- `robustness_harness.py:purged_walk_forward()` -- uses `embargo=2` bars, purges `[test_start-embargo, test_end+embargo]` from train zones. This is correct.
- `agent_team_v3.py` validator -- sets `train_end = test_start` with NO embargo gap. Test immediately follows training. However, indicators are recomputed with `end_bar=fold_end`, so only the indicator precompute is causal (not the bar separation).

**Critical finding**: The agent_team_v3 validator WF has zero embargo between train and test folds. A position entered in the last bars of training could use indicators influenced by data up to `fold_end`, which includes test bars. The `precompute_all(data, coins, end_bar=fold_end)` call means all fold indicators can see up to the fold boundary -- this is intentional (simulates "knowing data up to now") but the lack of embargo means indicator lookback windows at the train/test boundary create a blurred zone.

**Severity**: MED

**Status**: PARTIAL -- The dedicated `purged_walk_forward` in `robustness_harness.py` properly handles this with embargo=2. The agent_team_v3 validator does not. However, the HF sweep (`h2_sweep.py`) runs NO walk-forward at all -- it uses a single full-sample backtest with friction gates only.

---

### 1.3 Are train/test bars truly separated?

**Attack vector**: If the same bars appear in both train and test, the walk-forward result is overfitted and meaningless.

**Evidence**: In `robustness_harness.py`, the train zone explicitly excludes `[purge_start, purge_end)` which covers `[test_start-embargo, test_end+embargo)`. In the agent_team_v3 validator, `train_end = test_start` so they are adjacent but non-overlapping. Both implementations maintain true separation.

**Severity**: LOW

**Status**: MITIGATED -- Both WF implementations separate train from test at the bar level. No overlap detected.

---

### 1.4 Could BB/DC/RSI lookback period create implicit leakage?

**Attack vector**: Indicators with 14-20 bar lookback windows create a "warm-up zone" at the start of any test period. Trades entered in the first 20 bars of a test fold effectively depend on data from the training period's final bars, blurring the boundary.

**Evidence**: DC_PERIOD=20, BB_PERIOD=20, RSI_PERIOD=14, ATR_PERIOD=14. START_BAR=50 ensures warm-up for the first fold, but intra-fold transitions have no such buffer. The robustness harness embargo=2 bars (8 hours at 4H) is only 2 bars, far less than the 20-bar lookback. This means the first ~18 bars of any test fold are computed using indicator windows that span into the training period.

**Severity**: MED

**Status**: PARTIAL -- embargo=2 is insufficient to fully decorrelate the 20-bar lookback windows. However, the impact is modest because: (a) indicators are computed causally per bar, (b) the boundary effect is limited to ~20 bars out of ~134 per fold, and (c) the leakage check (VALIDATION_SUMMARY) showed 0.00% delta between purged and unpurged runs, suggesting no material leakage in practice.

---

## 2. Symbol Mapping Issues

### 2.1 Could different data sources use different pair naming?

**Attack vector**: If the candle cache uses "BTCUSD" but the Kraken API returns "XXBTZUSD", trades placed from backtest signals would fail to match live symbols.

**Evidence**: The data files use keys like coin names directly (coins loaded via `sorted([k for k in data if not k.startswith("_")])`). Kraken uses XBT for Bitcoin, not BTC. The mapping between cache pair names and Kraken API pair names is not explicitly validated in the backtest code.

**Severity**: MED

**Status**: OPEN -- The backtest engine does not validate that cached pair names match Kraken's live API pair naming convention. This is a deployment risk, not a backtest validity risk, but it could cause the live bot to miss signals or place orders on wrong pairs.

---

### 2.2 Are all coins actually tradeable on Kraken?

**Attack vector**: The candle_cache_tradeable.json may contain coins that were tradeable at cache-build time but have since been delisted, or coins with insufficient liquidity for actual order execution.

**Evidence**: The `candle_cache_tradeable.json` has 425 coins. Kraken regularly lists/delists pairs. No runtime check validates that each pair is currently active and has sufficient order book depth.

**Severity**: LOW

**Status**: PARTIAL -- A `tradeable` universe filter exists (vs the full 532-coin cache), suggesting some curation. However, there is no evidence of a minimum liquidity threshold or periodic refresh against the live Kraken asset list.

---

### 2.3 Is there survivorship bias in the coin universe?

**Attack vector**: If the 425/526 coin universe was selected based on coins that exist TODAY, it excludes coins that were listed during the backtest period but later delisted (often after large drawdowns). This inflates backtested returns.

**Evidence**: The candle cache appears to be a snapshot of currently-listed Kraken pairs. Coins that were delisted during the ~120-day (721 bars x 4H) backtest window are absent. These delisted coins likely experienced severe price declines that the strategy would have been exposed to.

**Severity**: MED

**Status**: OPEN -- No delisted-coin inclusion mechanism exists. The backtest only evaluates coins that survived to the present. This is a standard survivorship bias that inflates both trade count and P&L.

---

## 3. Lookahead Bias

### 3.1 Entry signal uses bar N data -- can we actually trade at bar N close?

**Attack vector**: `check_entry_at_bar(ind, bar, cfg)` reads `closes[bar]`, `lows[bar]`, `volumes[bar]`, `rsi[bar]`, and `bb_lower[bar]`. The entry is executed at `closes[bar]`. In live trading, you cannot know the close price until the candle finalizes. Any order placed must wait until bar N is closed, then execute at bar N+1 open (or close).

**Evidence**: Entry price is set as `ep = ind['closes'][bar]` (line 470). In live 4H trading, you would observe the close, compute indicators, then submit an order that fills at or after bar N+1 open. The entry price assumption of bar-N-close is optimistic.

**Severity**: MED

**Status**: PARTIAL -- The friction test with "1-candle-later" fill (2x fees + 50bps) partially models this. Champion H2 still shows $1,827 P&L under 1-candle friction. However, the 50bps slippage may underestimate the real gap between bar-N close and bar-N+1 execution, especially for low-liquidity altcoins.

---

### 3.2 FIXED STOP uses low (intra-bar) while entry uses close

**Attack vector**: The tp_sl exit checks `if low <= sl_p` to trigger FIXED STOP at the exact stop price. This assumes a limit stop-loss order was placed that filled at exactly `sl_p`. In reality, stop-loss orders on Kraken are market orders triggered at the stop price, and the actual fill can be worse (slippage below the stop level).

**Evidence**: Line 368-369: `if low <= sl_p: exit_price, reason = sl_p, 'FIXED STOP'`. The exit price is set to `sl_p`, not to `low`. This is optimistic -- if the low was significantly below the stop level (gap down), the actual fill would be at `low` or worse, not at `sl_p`.

**Severity**: HIGH

**Status**: OPEN -- No slippage is applied to stop-loss fills. In volatile crypto markets with 4H candles, the low can be significantly below the stop level. The backtest credits the trade with a fill at `sl_p` when the actual execution could be at `low` or worse. With 7 FIXED STOP exits out of 31 trades for the champion, this materially affects P&L accuracy.

---

### 3.3 PROFIT TARGET uses high -- is this realistic for limit orders?

**Attack vector**: Line 370-371: `if high >= tp_p: exit_price, reason = tp_p, 'PROFIT TARGET'`. This assumes a limit sell order at `tp_p` was resting in the order book and got filled. For limit orders, this IS realistic -- the fill would be at `tp_p` or better.

**Evidence**: Limit orders at `tp_p` placed at entry time would correctly fill when the high crosses the target. This is one of the few exit assumptions that is optimistic but defensible for limit orders on a centralized exchange.

**Severity**: LOW

**Status**: MITIGATED -- Limit order assumption is reasonable for profit targets. Minor risk: if the price touches `tp_p` briefly with low volume, partial fills could occur on Kraken. The backtest assumes full fill.

---

### 3.4 TIME MAX exits at close -- is this implementable?

**Attack vector**: `if bars_in >= tm_bars: exit_price, reason = close, 'TIME MAX'`. This exits at the bar's close price. In live trading, you know bars_in at the start of the bar, so you can place a market order near the close. This is implementable but the actual fill price will differ from the exact close.

**Evidence**: TIME MAX accounts for 9/31 trades in the champion. The execution is a market order at candle close, which is feasible with a bot that monitors candle completion.

**Severity**: LOW

**Status**: MITIGATED -- Implementable with a bot that tracks candle countdown. The friction model with additional slippage partially covers execution uncertainty.

---

## 4. Entry/Exit Sequencing

### 4.1 Exits processed before entries in same bar -- correct?

**Attack vector**: The backtest loop processes sells first (lines 346-442), then buys (lines 444-479). This means at bar N: (a) existing positions are checked for exit, (b) freed capital is available for new entries. This is correct -- you cannot use capital that is still locked in an open position.

**Evidence**: Sells array is populated and executed first, updating equity. Then buys are evaluated with the updated equity. This is the standard sequencing.

**Severity**: LOW

**Status**: MITIGATED -- Correct sequencing. Exits free capital before entries consume it.

---

### 4.2 Can we enter AND exit same coin same bar?

**Attack vector**: If a position is exited at bar N, the cooldown check `if (bar - last_exit_bar.get(pair, -999)) < cd` would require `0 < cd` which is true (COOLDOWN_BARS=4). So the same coin cannot be re-entered on the same bar it was exited. This is correct behavior.

**Evidence**: `last_exit_bar[pair] = bar` is set during exit processing. The entry check `(bar - last_exit_bar) < cd` with cd >= 4 prevents same-bar re-entry.

**Severity**: LOW

**Status**: MITIGATED -- Cooldown prevents same-bar re-entry.

---

### 4.3 Cooldown enforcement after stop loss

**Attack vector**: `COOLDOWN_AFTER_STOP = 8` bars (32 hours at 4H). After a stop loss, the coin has an extended cooldown. The check is `last_exit_was_stop[pair] = 'STOP' in reason` which matches 'FIXED STOP', 'HARD STOP', 'TRAIL STOP'. This is reasonable but aggressive -- the coin might recover and present a valid signal during the cooldown.

**Evidence**: Lines 434, 451-452. The cooldown is correctly enforced. The 8-bar post-stop cooldown is conservative and reduces the risk of repeatedly entering a falling coin.

**Severity**: LOW

**Status**: MITIGATED -- Properly implemented. The 8-bar cooldown is a reasonable safety mechanism.

---

## 5. Fee Model

### 5.1 Is 0.26% realistic for Kraken taker?

**Attack vector**: `KRAKEN_FEE = 0.0026` (26 bps per side, 52 bps round-trip). Kraken's current taker fee schedule ranges from 0.26% for lowest tier to 0.10% for high-volume traders. For a $2,000 account, the 0.26% taker fee is accurate.

**Evidence**: The fee is applied at both entry and exit: `fees = pos.size_usd * fee + (pos.size_usd + gross) * fee` (line 430). This correctly models taker fees on both legs. The fee is applied to the full position size, not just the profit.

**Severity**: LOW

**Status**: MITIGATED -- Fee model matches Kraken's lowest-tier taker rate. For the $2,000 account size, this is the correct tier.

---

### 5.2 Slippage model: is flat bps adequate for low-liquidity coins?

**Attack vector**: The friction tests use flat additional bps (e.g., +20bps, +50bps) applied uniformly across all 425 coins. In reality, slippage varies enormously by coin: BTC/ETH might see 1-2 bps slippage, while a micro-cap altcoin could see 100-500 bps slippage for a $2,000 market order.

**Evidence**: The friction stress uses `FEE_2X_20BPS = KRAKEN_FEE * 2 + 0.0020` and `FEE_1CANDLE = KRAKEN_FEE * 2 + 0.0050`. These are applied as a uniform fee override, not coin-specific slippage.

**Severity**: HIGH

**Status**: OPEN -- Flat slippage is unrealistic for a 425-coin universe that includes micro-cap tokens. A volume-weighted or order-book-depth-adjusted slippage model per coin would be significantly more accurate. Trades on illiquid coins could experience 10-50x the modeled slippage, potentially turning winners into losers.

---

### 5.3 Volume-weighted slippage would be more realistic

**Attack vector**: The backtest sizes each position as `size_per_pos = available / slots`. For a $2,000 account with max_pos=1, this means ~$2,000 per trade. For coins with $10K daily volume, a $2,000 market order would move the market and experience significant slippage beyond any flat-bps model.

**Evidence**: No volume-relative sizing exists. The `vol_spike_mult` filter ensures entry occurs on high-volume bars (>3x average), which partially mitigates this -- high-volume bars have better liquidity. However, the average volume for many altcoins at 4H resolution could still be very low.

**Severity**: MED

**Status**: PARTIAL -- The vol_spike entry filter provides some protection (only entering on high-volume bars), but no explicit check ensures the position size is small relative to the bar's dollar volume.

---

## 6. Statistical Concerns

### 6.1 Trade count: 31-32 trades on 721 bars -- sufficient?

**Attack vector**: With only 31 trades (champion H2) or 32 trades (GRID_BEST), the sample size is small for robust statistical inference. A binomial test for 67.7% win rate (21 wins out of 31 trades) gives a 95% CI of roughly [49%, 83%]. The true win rate could be near 50%.

**Evidence**: 31 trades over ~120 days (721 bars x 4H). This translates to roughly 1 trade every 4 days. The confidence interval on key metrics (win rate, profit factor, max drawdown) is wide with this sample size.

**Severity**: HIGH

**Status**: OPEN -- The sample size is fundamentally limited by the 4H timeframe and strict entry filters. Monte Carlo and walk-forward help, but cannot overcome the underlying N=31 limitation. A minimum of 100+ trades would be needed for statistical confidence in win rate and profit factor estimates.

---

### 6.2 Multiple hypothesis testing: 1280 configs, p-value inflation?

**Attack vector**: The H2 grid sweep tested 1280 parameter combinations. Without correction for multiple comparisons (Bonferroni, FDR, etc.), the probability of finding a "significant" result by chance is extremely high. If each config has a 5% probability of producing a positive result under the null hypothesis, we'd expect ~64 false positives.

**Evidence**: 796/1280 configs passed HF gates (62%). 780 passed friction tests. The fact that such a large fraction passed suggests the underlying signal is real (or the gates are too loose). However, the champion was selected as the BEST out of 1280, which maximizes selection bias.

**Severity**: HIGH

**Status**: PARTIAL -- The friction stress tests (2x fees + 20bps, 1-candle-later) provide some protection against marginal false positives. However, no formal multiple-testing correction is applied. The champion's P&L of $4,114 should be interpreted as the best-case outcome from 1280 trials, not as the expected future P&L.

---

### 6.3 Champion H2 very close to GRID_BEST -- is this just noise?

**Attack vector**: Champion H2 (vs3.0/rsi45/tp12/sl8/tm15, P&L $4,114) is extremely similar to GRID_BEST (vs2.5/rsi45/tp12/sl10/tm15, P&L $4,718). They differ only in vol_spike_mult (3.0 vs 2.5) and sl_pct (8 vs 10). With 31 vs 32 trades, the difference of ~$600 in P&L could easily be noise (1-2 trades going differently).

**Evidence**: The top 4 configs in the H2 sweep have IDENTICAL results (31 trades, $4,114, PF 2.73) across rsi_max values of 45, 50, 55, and 60. This means rsi_max has zero discriminative power in this range -- all these configs produce the exact same trade set. The vol_spike_mult=3.0 filter is so strict that the RSI filter never binds.

**Severity**: HIGH

**Status**: OPEN -- The RSI insensitivity zone (45-60 all identical) is a red flag indicating the parameter surface is flat. The champion is not meaningfully distinct from GRID_BEST. The H2 "hypothesis" of momentum burst did not discover a new signal -- it found a slightly worse version of the same signal with tighter stops.

---

## 7. "HF" Labeling Risk

### 7.1 Currently 4H data -- calling it HF is misleading

**Attack vector**: "HF" (high-frequency) in quantitative finance refers to strategies operating on sub-second to minute-level timeframes, exploiting microstructure effects (bid-ask spread, queue position, order flow). A 4H candle-based strategy is, by definition, low-frequency.

**Evidence**: The strategies/hf/ directory, notes, and documentation use "HF" terminology. The actual data is 4H OHLCV candles with 721 bars (~120 days). Entry signals occur every ~4 days on average.

**Severity**: MED

**Status**: OPEN -- The naming creates false expectations about strategy characteristics. If shared with external stakeholders or in a live deployment context, "HF" labeling could mislead about latency requirements, data infrastructure needs, and expected trade frequency. The `notes.md` file even asks "Define HF timeframe (1m? 5m? 15m?)" suggesting the team is aware this is aspirational, not current.

---

### 7.2 True HF needs 1m-15m data with different microstructure

**Attack vector**: At 4H resolution, microstructure effects (spread, slippage, order book depth, latency) are negligible relative to price moves. True HF strategies exploit these effects. Moving to 1m-15m data would require:
- Tick-level or 1m OHLCV data pipeline
- Spread modeling (4H candles have no bid/ask data)
- Order book depth modeling
- Latency-sensitive execution
- Significantly different fee models (maker rebates)

**Evidence**: The current codebase has no sub-4H data pipeline. `fetch_data_1h.py` exists (1H candles) but the HF research uses 4H candles exclusively.

**Severity**: LOW (informational -- not a backtest bug, but a roadmap risk)

**Status**: OPEN -- No sub-4H data infrastructure exists. Transitioning to true HF would require a fundamentally different data pipeline, indicator computation, and execution model. The current research is better described as "parameter variant research on the existing 4H strategy."

---

### 7.3 Latency model (1 candle = 4 hours) is not realistic for HF

**Attack vector**: The "1-candle-later" friction test models execution delay as 1 candle = 4 hours. In true HF, 1 candle of latency would be 1 minute or less. The 4H latency model is appropriate for the 4H timeframe but would be absurdly generous for HF.

**Evidence**: `FEE_1CANDLE = KRAKEN_FEE * 2 + 0.0050` applies 50bps extra slippage for a 4-hour delay. This is reasonable for 4H trading but irrelevant to HF.

**Severity**: LOW (informational)

**Status**: MITIGATED for the current 4H context. The friction model is appropriate for the actual timeframe used, even if the "HF" label is misleading.

---

## Severity Summary

| Severity | Count | Items |
|----------|-------|-------|
| HIGH     | 4     | 3.2 (stop fill optimism), 5.2 (flat slippage), 6.1 (small N), 6.3 (champion = GRID_BEST noise) |
| MED      | 6     | 1.2 (no embargo in v3 WF), 1.4 (lookback vs embargo), 2.1 (pair naming), 2.3 (survivorship), 3.1 (entry at close), 7.1 (HF label) |
| LOW      | 8     | 1.1 (causal precompute), 1.3 (train/test separation), 3.3 (TP limit fill), 3.4 (TIME MAX), 4.1 (sequencing), 4.2 (same-bar), 4.3 (cooldown), 5.1 (fee rate) |

| Status     | Count |
|------------|-------|
| MITIGATED  | 8     |
| PARTIAL    | 5     |
| OPEN       | 5     |

---

## Top 3 Open Risks Requiring Action

1. **FIXED STOP fill optimism (3.2, HIGH)**: Stop losses fill at the computed stop price, not at the actual low. In volatile 4H bars, the low can gap well below the stop. Recommendation: exit at `min(sl_p, low)` or apply a configurable stop-slippage factor.

2. **Flat slippage model (5.2, HIGH)**: Uniform slippage across 425 coins ignores the enormous variation in liquidity. Recommendation: implement per-coin volume-relative slippage using average daily volume as a denominator.

3. **Small sample size (6.1, HIGH)**: 31 trades is statistically insufficient for reliable inference. Recommendation: extend the backtest window, use 1H candles to increase trade frequency, or apply bootstrap confidence intervals to all reported metrics.

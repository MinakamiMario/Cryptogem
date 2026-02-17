# Red Team Report -- HF 4H Variant Research

**Report ID**: ATTACK-001
**Date**: 2026-02-15
**Agent**: Red Team (Agent 2)
**Scope**: DualConfirm strategy, tp_sl exit, 4H candles, 425-526 coins, Kraken

---

## Executive Summary

- The HF 4H variant research reuses the validated DualConfirm backtest engine with different parameter regimes. Core engine mechanics (causal indicators, sequential exit-then-entry processing, correct fee application) are sound and previously validated through a 6-test robustness battery. However, the HF-specific sweep (1280 configs) applies NO walk-forward validation and NO multiple-testing correction, relying solely on friction gates as a proxy for robustness.

- Three HIGH-severity issues threaten the reliability of reported P&L: (1) stop-loss fills are credited at the computed stop price rather than the actual bar low, optimistically ignoring slippage on 7/31 champion trades; (2) a flat slippage model of 20-50 bps is applied uniformly across 425 coins regardless of vastly different liquidity profiles; (3) with only 31 trades, confidence intervals on win rate and profit factor are too wide for actionable conclusions.

- The champion H2 (vs3.0/rsi45/tp12/sl8/tm15) is statistically indistinguishable from GRID_BEST (vs2.5/rsi45/tp12/sl10/tm15). The top 4 sweep results are identical across RSI thresholds 45-60, revealing a flat parameter surface. The "HF" label is misleading for a 4H strategy and should be reframed as "parameter variant research."

---

## Severity Distribution

| Severity | Count | Percentage |
|----------|-------|------------|
| HIGH     | 4     | 22%        |
| MEDIUM   | 6     | 33%        |
| LOW      | 8     | 44%        |
| **Total**| **18**| 100%       |

| Mitigation Status | Count | Percentage |
|-------------------|-------|------------|
| MITIGATED         | 8     | 44%        |
| PARTIAL           | 5     | 28%        |
| OPEN              | 5     | 28%        |

---

## Top 3 Open Risks

### Risk 1: Stop-Loss Fill Price Optimism
**Severity**: HIGH | **Checklist Item**: 3.2

The backtest credits FIXED STOP exits at the exact stop price (`sl_p`) even when the bar's low is below that level. In volatile crypto markets with 4H candles, the low can gap significantly below the stop. With 7 out of 31 champion trades exiting via FIXED STOP, the cumulative P&L impact could be $200-$800 depending on gap severity.

**Recommended Action**: Modify the tp_sl exit logic to use `exit_price = min(sl_p, low)` for a pessimistic fill model, or apply a configurable stop-slippage multiplier (e.g., 1.5x the gap between sl_p and low). Re-run the champion and grid to measure P&L impact.

---

### Risk 2: Uniform Slippage Across Heterogeneous Liquidity
**Severity**: HIGH | **Checklist Item**: 5.2

The friction tests apply flat additional basis points (20-50 bps) uniformly across all coins. The 425-coin tradeable universe spans from highly liquid pairs (BTC, ETH) to micro-cap tokens where a $2,000 order could represent a significant fraction of the 4H bar volume. Actual slippage on illiquid coins can be 10-50x the modeled amount.

**Recommended Action**: Implement a per-coin slippage model based on average dollar volume. For example: `slippage_bps = base_bps * (position_size / avg_bar_volume)^0.5`. Filter out coins where modeled slippage exceeds a threshold (e.g., 100 bps). Re-run the champion with volume-adjusted slippage to obtain a realistic P&L estimate.

---

### Risk 3: Insufficient Trade Count for Statistical Confidence
**Severity**: HIGH | **Checklist Item**: 6.1

The champion produces 31 trades over 721 bars (~120 days). A 95% binomial confidence interval for the observed 67.7% win rate spans roughly [49%, 83%]. The true win rate could plausibly be near 50% (no edge). Similarly, the profit factor of 2.73 has a wide confidence interval that includes values below 1.5. Combined with the 1280-config grid search (multiple testing), the champion result is consistent with selection bias from a parameter sweep over noise.

**Recommended Action**: (a) Extend the backtest to a longer data window if available. (b) Apply bootstrap confidence intervals to P&L, PF, and win rate. (c) Run a formal Bonferroni or BH-FDR correction on the grid results. (d) Consider using 1H candles to increase trade frequency by ~4x, though this changes the strategy dynamics.

---

## Overall Risk Rating

**MEDIUM**

**Rationale**: The core backtest engine is well-constructed and has passed a thorough 6-test robustness battery on the GRID_BEST config (leakage check, nested holdout, window sweep, slippage regimes, long horizon, rolling regime sweep). The HIGH-severity issues are concentrated in (a) execution realism details (stop fills, slippage) that affect P&L magnitude but not directionality, and (b) statistical power limitations inherent to the 4H timeframe. The strategy likely has a real but modest edge that the backtest overstates by $500-$1,500 due to optimistic execution modeling. The champion H2 does not represent a meaningfully new discovery beyond GRID_BEST.

---

## Recommendations Summary

| Priority | Action | Effort |
|----------|--------|--------|
| P0 | Fix stop-loss fill to use min(stop, low) | 1 hour |
| P0 | Add per-coin volume-relative slippage | 4 hours |
| P1 | Bootstrap confidence intervals on champion metrics | 2 hours |
| P1 | Apply multiple-testing correction to grid results | 2 hours |
| P2 | Rename "HF" to "parameter variant" in docs and paths | 30 min |
| P2 | Add Kraken pair-name validation check | 1 hour |
| P2 | Add survivorship bias assessment (delisted coins) | 4 hours |
| P3 | Run HF champion through full robustness battery (make robustness) | 4 hours |

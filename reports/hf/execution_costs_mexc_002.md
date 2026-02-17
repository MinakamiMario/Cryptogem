# Execution Costs MEXC v2 -- Canonical Cost Reference

**Date**: 2026-02-15
**Source module**: `strategies/hf/screening/costs_mexc_v2.py`
**Depends on**: `reports/hf/mexc_costs_001.json`, MEXC official fee schedule

## Cost Regimes

### MEXC Taker (Market Orders)

| Percentile | Tier | Exch Fee | Spread | Slippage | Total/Side | Round Trip |
|------------|------|----------|--------|----------|------------|------------|
| P50        | T1   | 10.0     | 1.7    | 0.8      | **12.5**   | 25.0       |
| P50        | T2   | 10.0     | 9.2    | 4.3      | **23.5**   | 47.0       |
| P90        | T1   | 10.0     | 3.8    | 1.8      | **15.6**   | 31.2       |
| P90        | T2   | 10.0     | 21.3   | 10.1     | **41.4**   | 82.8       |
| P95        | T1   | 10.0     | 6.7    | 2.5      | **19.2**   | 38.4       |
| P95        | T2   | 10.0     | 33.5   | 15.8     | **59.3**   | 118.6      |

All values in basis points (bps). Trade size: $200.

### MEXC Maker (Limit Orders)

| Percentile | Tier | Exch Fee | Adverse Sel. | Total/Side | Round Trip |
|------------|------|----------|--------------|------------|------------|
| P50        | T1   | 0.0      | 2.5          | **2.5**    | 5.0        |
| P50        | T2   | 0.0      | 13.5         | **13.5**   | 27.0       |

Maker fee is 0% (promotional, active since Q4 2022). Adverse selection
replaces spread/slippage for limit orders (winner's curse).

### Kraken Baseline (Reference)

| Tier | Exch Fee | Slippage | Total/Side | Round Trip |
|------|----------|----------|------------|------------|
| T1   | 26.0     | 5.0      | **31.0**   | 62.0       |
| T2   | 26.0     | 30.0     | **56.0**   | 112.0      |

## What Changed vs v1

### vs `fill_model.py` (current module)

| Field            | fill_model.py (v1) | costs_mexc_v2 (v2) | Delta    |
|------------------|--------------------|--------------------|----------|
| MEXC taker fee   | **0 bps (WRONG)**  | 10 bps             | +10 bps  |
| T1 spread        | 4.0 bps            | 1.7 bps (P50)      | -2.3 bps |
| T2 spread        | 15.0 bps           | 9.2 bps (P50)      | -5.8 bps |
| T1 slippage      | 2.0 bps            | 0.8 bps (P50)      | -1.2 bps |
| T2 slippage      | 10.0 bps           | 4.3 bps (P50)      | -5.7 bps |
| T1 total (mkt)   | 6.0 bps            | 12.5 bps           | +6.5 bps |
| T2 total (mkt)   | 25.0 bps           | 23.5 bps           | -1.5 bps |

Root cause: fill_model.py used MEXC taker = 0 bps, which is incorrect.
MEXC taker has always been 10 bps; only maker is 0 bps (promotion).
Spread/slippage were also rough estimates, now replaced by volume-model.

### vs `run_h20_robustness.py` (current constants)

| Constant       | run_h20_robustness | costs_mexc_v2 (P50) | Delta    |
|----------------|--------------------|--------------------|----------|
| MEXC_MARKET_T1 | 5 bps              | 12.5 bps           | +7.5 bps |
| MEXC_MARKET_T2 | 20 bps             | 23.5 bps           | +3.5 bps |
| STRESS_2X_T1   | 10 bps             | 25.0 bps (2x)      | +15 bps  |
| STRESS_2X_T2   | 40 bps             | 47.0 bps (2x)      | +7 bps   |

The robustness script underestimates T1 costs significantly (5 vs 12.5 bps).
T2 is closer but still low. All downstream robustness results are optimistic.

## GO/NO-GO Recommendation

**Use `mexc_market` (P50) as the primary cost regime for GO/NO-GO.**

Rationale:
- P50 represents the median execution quality across the tier.
- Half of trades will execute better, half worse.
- P90/P95 regimes are for stress testing, not baseline evaluation.
- The current baseline (H20 v5, PF=1.25 at old costs) should be re-tested
  at the corrected 12.5/23.5 bps to confirm the edge survives.

Stress protocol:
1. Baseline GO/NO-GO at `mexc_market` (P50): T1=12.5, T2=23.5 bps.
2. Survivability check at `mexc_market_p95`: T1=19.2, T2=59.3 bps.
3. Fee-doubling stress at `stress_multiplier('mexc_market', 2.0)`.

## Risk Factors

1. **Maker promotion end**: The 0% maker fee is promotional. If MEXC reverts
   to 10 bps maker, all maker-based scenarios add 10 bps/side. Taker
   regimes are unaffected.

2. **Spread model is theoretical**: The k=150 calibration is based on
   published CEX benchmarks, not live MEXC order book snapshots. Real
   spreads may differ, especially for T2 coins during low-volume hours.

3. **Slippage is size-dependent**: The model assumes $200/trade. Scaling
   to larger sizes will increase slippage non-linearly.

4. **Volume decay**: T2 coins can lose liquidity rapidly. The P50 volume
   used for T2 ($269K/day) represents the current median; individual coins
   may drop below this during bear markets.

5. **No MX token discount modeled**: MEXC offers 20% taker discount with
   MX token (8 bps instead of 10 bps). Not included in default regimes.

## Usage

```python
from strategies.hf.screening.costs_mexc_v2 import (
    get_harness_fee, get_cost_breakdown, stress_multiplier,
)

# For harness.run_backtest()
fee_t1 = get_harness_fee('mexc_market', 'tier1')  # 0.00125
fee_t2 = get_harness_fee('mexc_market', 'tier2')  # 0.00235

# Full breakdown
breakdown = get_cost_breakdown('mexc_market_p90', 'tier1')

# Stress test at 2x
stressed = stress_multiplier('mexc_market', 2.0)
fee_t1_2x = stressed['tier1']['total_per_side_bps'] / 10000  # 0.0025
```

---
*Generated for HF Part 2 sprint, 2026-02-15.*

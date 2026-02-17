# HF Allocator Experiment — 4H Variant Research

> **Question**: Can max_pos>1 + tier quotas + correlation guardrails
> increase throughput without destroying risk-adjusted returns?

**Date**: 2026-02-15 14:23
**Universe**: tradeable (T1+T2 only, 316 coins)
**Data**: `candle_cache_tradeable.json`
**Bars**: 721 (4H, ~120 days)
**Correlation window**: 20 bars, threshold=0.7
**Runtime**: 3.4s

---

## GRID_BEST

### Method A: Native max_pos (per-tier fees, no quotas/corr)

| max_pos | Trades | P&L | PF | WR% | DD% | Trades/wk | 0-day% |
|---------|--------|-----|----|-----|-----|-----------|--------|
| 1 | 40 | $+1,572 | 1.53 | 62.5% | 27.8% | 2.22 | 70.5% |
| 2 | 52 | $+993 | 1.57 | 63.5% | 24.6% | 2.89 | 70.5% |
| 3 | 8 | $-1,975 | 0.06 | 25.0% | 98.8% | 0.44 | 98.2% |

**Tier breakdown (Method A)**:

| max_pos | T1 trades | T1 P&L | T2 trades | T2 P&L |
|---------|-----------|--------|-----------|--------|
| 1 | 18 | $+243 | 22 | $+1,329 |
| 2 | 24 | $+326 | 28 | $+667 |
| 3 | 4 | $-876 | 4 | $-1,099 |

### Method B: Quota-Aware Allocator (per-tier fees + quotas + corr guard)

| Policy | max_pos | T1 min | T2 max | Corr | Trades | P&L | PF | DD% | Tr/wk | 0-day% | CorrBlk | QuotaBlk |
|--------|---------|--------|--------|------|--------|-----|----|-----|-------|--------|---------|----------|
| baseline_mp1 | 1 | 0 | 1 | N | 29 | $+2,114 | 1.84 | 17.5% | 1.61 | 74.1% | 0 | 0 |
| mp2_no_quota | 2 | 0 | 2 | N | 37 | $+1,339 | 2.08 | 12.5% | 2.06 | 74.1% | 0 | 0 |
| mp2_t1_reserve | 2 | 1 | 1 | N | 35 | $+1,245 | 2.02 | 12.5% | 1.94 | 74.1% | 0 | 6 |
| mp2_corr_guard | 2 | 0 | 2 | Y | 35 | $+1,185 | 2.01 | 12.8% | 1.94 | 74.1% | 11 | 0 |
| mp2_full | 2 | 1 | 1 | Y | 32 | $+757 | 1.59 | 11.0% | 1.78 | 74.1% | 10 | 20 |
| mp3_no_quota | 3 | 0 | 3 | N | 38 | $+41 | 1.04 | 11.9% | 2.11 | 78.6% | 0 | 0 |
| mp3_t1_reserve | 3 | 1 | 2 | N | 36 | $+78 | 1.08 | 11.9% | 2.0 | 78.6% | 0 | 5 |
| mp3_corr_guard | 3 | 0 | 3 | Y | 48 | $+885 | 1.96 | 10.2% | 2.67 | 69.6% | 27 | 0 |
| mp3_full | 3 | 1 | 2 | Y | 48 | $+697 | 1.69 | 10.2% | 2.67 | 69.6% | 27 | 16 |

**Tier mix (Method B)**:

| Policy | T1 trades (%) | T1 P&L | T2 trades (%) | T2 P&L |
|--------|---------------|--------|---------------|--------|
| baseline_mp1 | 10 (34.5%) | $+677 | 19 (65.5%) | $+1,437 |
| mp2_no_quota | 13 (35.1%) | $+409 | 24 (64.9%) | $+930 |
| mp2_t1_reserve | 15 (42.9%) | $+485 | 20 (57.1%) | $+760 |
| mp2_corr_guard | 11 (31.4%) | $+315 | 24 (68.6%) | $+870 |
| mp2_full | 12 (37.5%) | $+21 | 20 (62.5%) | $+736 |
| mp3_no_quota | 13 (34.2%) | $+191 | 25 (65.8%) | $-149 |
| mp3_t1_reserve | 14 (38.9%) | $+198 | 22 (61.1%) | $-119 |
| mp3_corr_guard | 17 (35.4%) | $+322 | 31 (64.6%) | $+563 |
| mp3_full | 18 (37.5%) | $+223 | 30 (62.5%) | $+474 |

---

## Champion_H2

### Method A: Native max_pos (per-tier fees, no quotas/corr)

| max_pos | Trades | P&L | PF | WR% | DD% | Trades/wk | 0-day% |
|---------|--------|-----|----|-----|-----|-----------|--------|
| 1 | 40 | $+1,226 | 1.41 | 57.5% | 46.5% | 2.22 | 73.2% |
| 2 | 54 | $+543 | 1.28 | 57.4% | 31.1% | 3.0 | 72.3% |
| 3 | 40 | $-1,317 | 0.4 | 50.0% | 68.9% | 2.22 | 82.1% |

**Tier breakdown (Method A)**:

| max_pos | T1 trades | T1 P&L | T2 trades | T2 P&L |
|---------|-----------|--------|-----------|--------|
| 1 | 17 | $+4 | 23 | $+1,222 |
| 2 | 22 | $+314 | 32 | $+229 |
| 3 | 5 | $-978 | 35 | $-340 |

### Method B: Quota-Aware Allocator (per-tier fees + quotas + corr guard)

| Policy | max_pos | T1 min | T2 max | Corr | Trades | P&L | PF | DD% | Tr/wk | 0-day% | CorrBlk | QuotaBlk |
|--------|---------|--------|--------|------|--------|-----|----|-----|-------|--------|---------|----------|
| baseline_mp1 | 1 | 0 | 1 | N | 30 | $+1,816 | 1.81 | 31.2% | 1.67 | 75.9% | 0 | 0 |
| mp2_no_quota | 2 | 0 | 2 | N | 41 | $+458 | 1.31 | 22.0% | 2.28 | 75.9% | 0 | 0 |
| mp2_t1_reserve | 2 | 1 | 1 | N | 36 | $+933 | 1.73 | 22.0% | 2.0 | 75.9% | 0 | 11 |
| mp2_corr_guard | 2 | 0 | 2 | Y | 36 | $+567 | 1.4 | 20.6% | 2.0 | 75.9% | 13 | 0 |
| mp2_full | 2 | 1 | 1 | Y | 34 | $+859 | 1.7 | 20.6% | 1.89 | 75.9% | 10 | 24 |
| mp3_no_quota | 3 | 0 | 3 | N | 42 | $-282 | 0.78 | 17.7% | 2.33 | 78.6% | 0 | 0 |
| mp3_t1_reserve | 3 | 1 | 2 | N | 20 | $-734 | 0.27 | 17.7% | 1.11 | 91.1% | 0 | 1 |
| mp3_corr_guard | 3 | 0 | 3 | Y | 7 | $-969 | 0.12 | 5.9% | 0.39 | 98.2% | 1 | 0 |
| mp3_full | 3 | 1 | 2 | Y | 7 | $-969 | 0.12 | 5.9% | 0.39 | 98.2% | 1 | 0 |

**Tier mix (Method B)**:

| Policy | T1 trades (%) | T1 P&L | T2 trades (%) | T2 P&L |
|--------|---------------|--------|---------------|--------|
| baseline_mp1 | 10 (33.3%) | $+528 | 20 (66.7%) | $+1,288 |
| mp2_no_quota | 12 (29.3%) | $+98 | 29 (70.7%) | $+360 |
| mp2_t1_reserve | 14 (38.9%) | $+287 | 22 (61.1%) | $+646 |
| mp2_corr_guard | 10 (27.8%) | $+156 | 26 (72.2%) | $+411 |
| mp2_full | 12 (35.3%) | $+191 | 22 (64.7%) | $+668 |
| mp3_no_quota | 11 (26.2%) | $+104 | 31 (73.8%) | $-387 |
| mp3_t1_reserve | 10 (50.0%) | $-514 | 10 (50.0%) | $-220 |
| mp3_corr_guard | 4 (57.1%) | $-598 | 3 (42.9%) | $-371 |
| mp3_full | 4 (57.1%) | $-598 | 3 (42.9%) | $-371 |

---

## Key Findings

**GRID_BEST**:
- Baseline (mp=1): 40 trades, $+1,572
- Best quota policy (baseline_mp1): 29 trades (0.7x), $+2,114, DD=17.5%

**Champion_H2**:
- Baseline (mp=1): 40 trades, $+1,226
- Best quota policy (baseline_mp1): 30 trades (0.8x), $+1,816, DD=31.2%

---
*Generated by hf_allocator.py — 4H variant research*
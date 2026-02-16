# P0-1: Universe Policy Sweep

**Date**: 2026-02-16 01:27
**Commit**: 427d5e0
**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)
**Fees**: MEXC Market (T1=12.5bps, T2=23.5bps)
**Stress**: 2x (T1=25.0bps, T2=47.0bps)
**Data**: 722 bars (4.3 weeks)
**Variants tested**: 14
**Runtime**: 31.3s

## Gate Thresholds (STRICT)

| Gate | Metric | Threshold |
|------|--------|-----------|
| G1 | Trades/week | >= 10 |
| G2 | Max gap | <= 2.5 days |
| G3 | Exp/week (market) | > $0 |
| G4 | Exp/week (stress 2x) | > $0 |
| G5 | Max DD | <= 20% |
| G6 | WF positive folds | >= 4/5 |
| G8 | Top-1 fold concentration | < 35% |

## Summary Comparison

| Variant | Coins | T1 | T2 | Trades | PF | WR% | Exp/wk | DD% | StressExp | WF | FoldConc | Gates |
|---------|-------|----|----|--------|-----|------|--------|------|-----------|-----|----------|-------|
| T1_only | 100 | 100 | 0 | 21 | 1.875 | 66.7 | $141.57 | 24.2 | $110.63 | 3/5 | 67% | 2/7 |
| T1+T2_50pct | 208 | 100 | 108 | 35 | 1.343 | 48.6 | $97.50 | 31.8 | $39.50 | 3/5 | 76% | 2/7 |
| T1+T2_70pct | 251 | 100 | 151 | 46 | 0.933 | 39.1 | $-25.10 | 42.4 | $-89.60 | 2/5 | 64% | 2/7 |
| T1+T2_90pct | 294 | 100 | 194 | 64 | 1.070 | 46.9 | $39.54 | 45.6 | $-58.38 | 4/5 | 48% | 4/7 |
| vol_floor_50K | 88 | 40 | 48 | 3 | 0.000 | 0.0 | $-34.88 | 7.5 | $-40.27 | 0/5 | 100% | 1/7 |
| vol_floor_100K | 61 | 32 | 29 | 0 | 0.000 | 0.0 | $0.00 | 0.0 | $0.00 | 0/5 | 100% | 1/7 |
| vol_floor_200K | 45 | 27 | 18 | 0 | 0.000 | 0.0 | $0.00 | 0.0 | $0.00 | 0/5 | 100% | 1/7 |
| vol_floor_500K | 18 | 12 | 6 | 0 | 0.000 | 0.0 | $0.00 | 0.0 | $0.00 | 0/5 | 100% | 1/7 |
| top50_by_vol | 50 | 28 | 22 | 0 | 0.000 | 0.0 | $0.00 | 0.0 | $0.00 | 0/5 | 100% | 1/7 |
| top100_by_vol | 100 | 44 | 56 | 3 | 0.000 | 0.0 | $-33.20 | 7.1 | $-38.60 | 0/5 | 100% | 1/7 |
| top150_by_vol | 150 | 60 | 90 | 12 | 0.913 | 25.0 | $-7.78 | 11.2 | $-32.85 | 2/5 | 53% | 1/7 |
| full_316 | 316 | 100 | 216 | 72 | 1.138 | 47.2 | $86.07 | 53.1 | $-32.74 | 3/5 | 49% | 3/7 |
| excl_worst12_304 | 304 | 98 | 206 | 58 | 2.518 | 58.6 | $559.17 | 11.8 | $391.74 | 4/5 | 34% | 7/7 **ALL** |
| excl_neg21_295 | 295 | 96 | 199 | 56 | 2.834 | 64.3 | $761.38 | 8.6 | $570.62 | 4/5 | 34% | 7/7 **ALL** |

## Gate Pass/Fail Matrix

| Variant | G1 | G2 | G3 | G4 | G5 | G6 | G8 | Total |
|---------|------|------|------|------|------|------|------|-------|
| T1_only | **FAIL** | **FAIL** | PASS | PASS | **FAIL** | **FAIL** | **FAIL** | 2/7 |
| T1+T2_50pct | **FAIL** | **FAIL** | PASS | PASS | **FAIL** | **FAIL** | **FAIL** | 2/7 |
| T1+T2_70pct | PASS | PASS | **FAIL** | **FAIL** | **FAIL** | **FAIL** | **FAIL** | 2/7 |
| T1+T2_90pct | PASS | PASS | PASS | **FAIL** | **FAIL** | PASS | **FAIL** | 4/7 |
| vol_floor_50K | **FAIL** | **FAIL** | **FAIL** | **FAIL** | PASS | **FAIL** | **FAIL** | 1/7 |
| vol_floor_100K | **FAIL** | **FAIL** | **FAIL** | **FAIL** | PASS | **FAIL** | **FAIL** | 1/7 |
| vol_floor_200K | **FAIL** | **FAIL** | **FAIL** | **FAIL** | PASS | **FAIL** | **FAIL** | 1/7 |
| vol_floor_500K | **FAIL** | **FAIL** | **FAIL** | **FAIL** | PASS | **FAIL** | **FAIL** | 1/7 |
| top50_by_vol | **FAIL** | **FAIL** | **FAIL** | **FAIL** | PASS | **FAIL** | **FAIL** | 1/7 |
| top100_by_vol | **FAIL** | **FAIL** | **FAIL** | **FAIL** | PASS | **FAIL** | **FAIL** | 1/7 |
| top150_by_vol | **FAIL** | **FAIL** | **FAIL** | **FAIL** | PASS | **FAIL** | **FAIL** | 1/7 |
| full_316 | PASS | PASS | PASS | **FAIL** | **FAIL** | **FAIL** | **FAIL** | 3/7 |
| excl_worst12_304 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 7/7 |
| excl_neg21_295 | PASS | PASS | PASS | PASS | PASS | PASS | PASS | 7/7 |

## Walk-Forward Detail (5-Fold)

| Variant | F1 | F2 | F3 | F4 | F5 | Positive | Conc |
|---------|----|----|----|----|-----|----------|------|
| T1_only | $200 | $-224 | $-97 | $123 | $645 | 3/5 | 67% |
| T1+T2_50pct | $183 | $-50 | $-274 | $14 | $626 | 3/5 | 76% |
| T1+T2_70pct | $223 | $-113 | $-468 | $-160 | $392 | 2/5 | 64% |
| T1+T2_90pct | $261 | $85 | $-489 | $80 | $398 | 4/5 | 48% |
| vol_floor_50K | $0 | $-85 | $0 | $0 | $-66 | 0/5 | 100% |
| vol_floor_100K | $0 | $0 | $0 | $0 | $0 | 0/5 | 100% |
| vol_floor_200K | $0 | $0 | $0 | $0 | $0 | 0/5 | 100% |
| vol_floor_500K | $0 | $0 | $0 | $0 | $0 | 0/5 | 100% |
| top50_by_vol | $0 | $0 | $0 | $0 | $0 | 0/5 | 100% |
| top100_by_vol | $0 | $-77 | $0 | $0 | $-66 | 0/5 | 100% |
| top150_by_vol | $-17 | $108 | $-171 | $0 | $95 | 2/5 | 53% |
| full_316 | $416 | $-199 | $-499 | $227 | $608 | 3/5 | 49% |
| excl_worst12_304 | $732 | $27 | $-48 | $668 | $723 | 4/5 | 34% |
| excl_neg21_295 | $909 | $58 | $-18 | $792 | $913 | 4/5 | 34% |

## Tier P&L Breakdown

| Variant | T1 Trades | T1 P&L | T2 Trades | T2 P&L | Total P&L |
|---------|-----------|--------|-----------|--------|-----------|
| T1_only | 21 | $608 | 0 | $0 | $608 |
| T1+T2_50pct | 21 | $608 | 14 | $-189 | $419 |
| T1+T2_70pct | 21 | $608 | 25 | $-716 | $-108 |
| T1+T2_90pct | 21 | $608 | 43 | $-439 | $170 |
| vol_floor_50K | 1 | $-73 | 2 | $-77 | $-150 |
| vol_floor_100K | 0 | $0 | 0 | $0 | $0 |
| vol_floor_200K | 0 | $0 | 0 | $0 | $0 |
| vol_floor_500K | 0 | $0 | 0 | $0 | $0 |
| top50_by_vol | 0 | $0 | 0 | $0 | $0 |
| top100_by_vol | 1 | $-66 | 2 | $-77 | $-143 |
| top150_by_vol | 1 | $-66 | 11 | $33 | $-33 |
| full_316 | 21 | $608 | 51 | $-239 | $370 |
| excl_worst12_304 | 19 | $898 | 39 | $1505 | $2403 |
| excl_neg21_295 | 18 | $1058 | 38 | $2214 | $3272 |

## Best Feasible Region Analysis

**2 variants pass all 7 gates:**

- **excl_worst12_304** (304 coins): PF=2.518, Exp/wk=$559.17, DD=11.8%, WF=4/5
- **excl_neg21_295** (295 coins): PF=2.834, Exp/wk=$761.38, DD=8.6%, WF=4/5

**Optimal (largest passing universe)**: excl_worst12_304 (304 coins)
**Best edge (highest Exp/wk)**: excl_neg21_295 ($761.38/wk)

## Verdict

**FEASIBLE REGION FOUND**: 2 of 14 variants pass all 7 strict gates.

Recommended universe policy:
- **Largest passing**: excl_worst12_304 (304 coins) -- maximizes trade count
- **Best edge**: excl_neg21_295 ($761.38/wk) -- maximizes expected profit

---
*Generated by strategies/hf/screening/run_part2_universe_sweep_001.py at 2026-02-16 01:27*
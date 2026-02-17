# HF Per-Tier Friction Report (v2) -- 4H Variant Research

> **Key question**: How much P&L evaporates under realistic per-tier friction?

**Date**: 2026-02-15 13:55
**Universe**: tradeable
**Data**: `candle_cache_tradeable.json`
**Total coins**: 425
**Tier source**: `universe_tiering_001.json`
**Runtime**: 191.2s

## 1. Fee Model

| Tier | Base Fee (bps) | Slippage (bps) | Total Per Side (bps) | Round Trip (bps) |
|------|---------------|----------------|---------------------|-----------------|
| Tier 1 (Liquid) | 26.0 | 5.0 | 31.0 | 62.0 |
| Tier 2 (Mid) | 26.0 | 30.0 | 56.0 | 112.0 |
| Tier 3 (Illiquid) | 26.0 | 75.0 | 101.0 | 202.0 |
| Flat (Sprint 1) | 26.0 | 20.0 | 46.0 | 92.0 |
| Flat baseline | 26.0 | 0.0 | 26.0 | 52.0 |

### 2x Stress Fees (double slippage)

| Tier | Slippage (bps) | Total Per Side (bps) | Round Trip (bps) |
|------|----------------|---------------------|-----------------|
| Tier 1 (Liquid) | 10.0 | 36.0 | 72.0 |
| Tier 2 (Mid) | 60.0 | 86.0 | 172.0 |
| Tier 3 (Illiquid) | 150.0 | 176.0 | 352.0 |

**Tier coin counts**: T1=100, T2=216, T3=109

---

## 2. Results: Champion_H2

**Config**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 8, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 3.0}`

### Overall Comparison

| Model | Trades | P&L | PF | WR% | DD% |
|-------|--------|-----|----|-----|-----|
| Flat baseline (KRAKEN_FEE) | 31 | $+4,113.50 | 2.73 | 67.7% | 24.7% |
| Flat 20bps (Sprint 1) | 31 | $+3,408.26 | 2.45 | 67.7% | 25.6% |
| Per-tier composite | 56 | $+1,346.33 | 1.34 | 55.4% | 52.2% |
| Per-tier 2x stress | 56 | $+437.49 | 1.11 | 55.4% | 59.6% |

### P&L Delta vs Flat Baseline

| Model | P&L | Delta | Delta % |
|-------|-----|-------|---------|
| Flat baseline | $+4,113.50 | $+0.00 | +0.0% |
| Flat 20bps | $+3,408.26 | $-705.24 | -17.1% |
| Per-tier composite | $+1,346.33 | $-2,767.17 | -67.3% |
| Per-tier 2x stress | $+437.49 | $-3,676.01 | -89.4% |

### Per-Tier Breakdown (composite model)

| Tier | Coins | Fee (bps) | Trades | P&L | PF | WR% | DD% |
|------|-------|-----------|--------|-----|----|-----|-----|
| Tier 1 (Liquid) | 100 | 31.0 | 17 | $+3.88 | 1.0 | 47.1% | 35.7% |
| Tier 2 (Mid) | 216 | 56.0 | 23 | $+1,221.69 | 1.71 | 65.2% | 21.5% |
| Tier 3 (Illiquid) | 109 | 101.0 | 16 | $+120.76 | 1.12 | 50.0% | 26.4% |

### Per-Tier Breakdown (2x stress)

| Tier | Coins | Fee (bps) | Trades | P&L | PF | WR% | DD% |
|------|-------|-----------|--------|-----|----|-----|-----|
| Tier 1 (Liquid) | 100 | 36.0 | 17 | $-30.08 | 0.98 | 47.1% | 36.1% |
| Tier 2 (Mid) | 216 | 86.0 | 23 | $+806.33 | 1.47 | 65.2% | 23.4% |
| Tier 3 (Illiquid) | 109 | 176.0 | 16 | $-338.77 | 0.7 | 50.0% | 31.9% |

---

## 2. Results: GRID_BEST

**Config**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 10, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 2.5}`

### Overall Comparison

| Model | Trades | P&L | PF | WR% | DD% |
|-------|--------|-----|----|-----|-----|
| Flat baseline (KRAKEN_FEE) | 32 | $+4,718.27 | 2.61 | 68.8% | 16.4% |
| Flat 20bps (Sprint 1) | 32 | $+3,920.36 | 2.37 | 68.8% | 17.1% |
| Per-tier composite | 57 | $+1,769.59 | 1.43 | 59.6% | 37.7% |
| Per-tier 2x stress | 57 | $+816.27 | 1.19 | 59.6% | 46.9% |

### P&L Delta vs Flat Baseline

| Model | P&L | Delta | Delta % |
|-------|-----|-------|---------|
| Flat baseline | $+4,718.27 | $+0.00 | +0.0% |
| Flat 20bps | $+3,920.36 | $-797.91 | -16.9% |
| Per-tier composite | $+1,769.59 | $-2,948.68 | -62.5% |
| Per-tier 2x stress | $+816.27 | $-3,902.00 | -82.7% |

### Per-Tier Breakdown (composite model)

| Tier | Coins | Fee (bps) | Trades | P&L | PF | WR% | DD% |
|------|-------|-----------|--------|-----|----|-----|-----|
| Tier 1 (Liquid) | 100 | 31.0 | 18 | $+242.80 | 1.16 | 55.6% | 36.8% |
| Tier 2 (Mid) | 216 | 56.0 | 22 | $+1,329.19 | 1.91 | 68.2% | 22.2% |
| Tier 3 (Illiquid) | 109 | 101.0 | 17 | $+197.61 | 1.17 | 52.9% | 29.6% |

### Per-Tier Breakdown (2x stress)

| Tier | Coins | Fee (bps) | Trades | P&L | PF | WR% | DD% |
|------|-------|-----------|--------|-----|----|-----|-----|
| Tier 1 (Liquid) | 100 | 36.0 | 18 | $+202.68 | 1.13 | 55.6% | 37.2% |
| Tier 2 (Mid) | 216 | 86.0 | 22 | $+917.93 | 1.62 | 68.2% | 23.7% |
| Tier 3 (Illiquid) | 109 | 176.0 | 17 | $-304.34 | 0.76 | 52.9% | 34.9% |

---

## 3. Tier 2 Alpha Survival Under Friction

> From Sprint 1.5 (universe tiering), Tier 2 (Mid) was identified as the
> primary alpha source. Does this survive per-tier friction?

| Config | T2 P&L (per-tier) | T2 Trades | T2 Best Alpha? | Survives? |
|--------|-------------------|-----------|----------------|-----------|
| Champion_H2 | $+1,221.69 | 23 | YES | YES |
| GRID_BEST | $+1,329.19 | 22 | YES | YES |

---

## 4. Verdicts

### Verdict Logic

- **VIABLE**: Per-tier composite P&L > $0 AND >= 50% of flat baseline
- **MARGINAL**: Per-tier composite P&L > $0 but < 50% of flat baseline
- **NOT_VIABLE**: Per-tier composite P&L <= $0

### Per-Config Verdicts

| Config | Verdict | Composite P&L | Baseline P&L | Retained % |
|--------|---------|--------------|-------------|------------|
| Champion_H2 | **MARGINAL** | $+1,346.33 | $+4,113.50 | +32.7% |
| GRID_BEST | **MARGINAL** | $+1,769.59 | $+4,718.27 | +37.5% |

**Champion_H2**: Per-tier composite P&L=$+1,346.33 retains only 32.7% of flat baseline (< 50%). Strategy is MARGINAL — friction substantially erodes edge.

**GRID_BEST**: Per-tier composite P&L=$+1,769.59 retains only 37.5% of flat baseline (< 50%). Strategy is MARGINAL — friction substantially erodes edge.

---

## 5. Overall Assessment

**Strategy viability is MARGINAL under per-tier friction.** Edge 
survives but is substantially reduced. Consider restricting to 
more liquid tiers or optimizing for lower turnover.

**Tier 2 alpha finding SURVIVES per-tier friction.** The Tier 2 (Mid) 
universe remains profitable even with 30bps slippage.

---
*Generated by hf_friction_v2.py -- 4H variant research*
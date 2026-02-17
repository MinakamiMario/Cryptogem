# HF Latency Stress Report -- 4H Variant Research

> **Monte Carlo latency fragility test**: simulates random entry delays
> of 0, 1, or 2 candles per trade via fee-based proxy.

**Date**: 2026-02-15 13:30
**Universe**: tradeable
**Data**: `candle_cache_tradeable.json`
**Coins**: 425
**Trials per config**: 50
**Random seed**: 42
**Runtime**: 26.1s

## Fee Model

| Delay | Fee | Fee (bps) | Weight |
|-------|-----|-----------|--------|
| 0-candle (on-time) | 0.0026 | 26.0 | 50% |
| 1-candle delay | 0.0102 | 102.0 | 35% |
| 2-candle delay | 0.0152 | 152.0 | 15% |

## Verdict Thresholds

- **FRAGILE**: survival rate < 70%
- **MODERATE**: survival rate 70%--90%
- **ROBUST**: survival rate >= 90%

---

## Champion_H2

**Config**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 8, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 3.0}`

### 1. Deterministic Delay Tests

| Delay | Fee (bps) | Trades | P&L | PF | DD% | WR% | Delta | Delta% |
|-------|-----------|--------|-----|----|-----|-----|-------|--------|
| 0-candle (on-time) | 26.0 | 31 | $+4,113.50 | 2.73 | 24.7% | 67.7% | $+0.00 | +0.0% |
| 1-candle delay | 102.0 | 31 | $+1,827.13 | 1.81 | 28.2% | 64.5% | $-2,286.37 | -55.6% |
| 2-candle delay | 152.0 | 31 | $+801.22 | 1.36 | 30.5% | 64.5% | $-3,312.28 | -80.5% |

**Most damaging delay**: 2-candle delay (P&L=$+801.22, delta=-80.5%)

### 2. Monte Carlo Distribution

**Trials**: 50 | **Seed**: 42

#### P&L Distribution

| Statistic | Value |
|-----------|-------|
| Mean | $+2,888.24 |
| Median | $+2,970.32 |
| Std Dev | $1,266.52 |
| P5 (worst 5%) | $+801.22 |
| P25 | $+1,827.13 |
| P75 | $+4,113.50 |
| P95 (best 5%) | $+4,113.50 |
| Min | $+801.22 |
| Max | $+4,113.50 |

#### PF Distribution

| Statistic | Value |
|-----------|-------|
| Mean | 2.23 |
| Median | 2.27 |
| Min | 1.36 |
| Max | 2.73 |

#### Drawdown Distribution

| Statistic | Value |
|-----------|-------|
| Mean DD | 26.6% |
| Median DD | 26.4% |
| P95 DD | 30.5% |
| Max DD | 30.5% |

#### Fee Sample Counts

| Fee | Count | Pct |
|-----|-------|-----|
| 0.0026 | 25 | 50.0% |
| 0.0102 | 21 | 42.0% |
| 0.0152 | 4 | 8.0% |

### 3. Survival Rate

| Metric | Value |
|--------|-------|
| Profitable trials | 50/50 |
| Unprofitable trials | 0/50 |
| **Survival rate** | **100.0%** |

### 4. Key Finding

- The **2-candle delay** causes the biggest absolute damage: P&L delta of $-3,312.28 (-80.5% vs baseline).
- Moving from 1-candle to 2-candle delay adds $-1,025.91 additional damage.
- **Live execution implication**: Strategy shows good resilience to random latency. Live execution with occasional 1-2 candle delays is unlikely to destroy profitability.

### 5. Verdict

**ROBUST** (survival rate: 100.0%)

---

## GRID_BEST

**Config**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 10, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 2.5}`

### 1. Deterministic Delay Tests

| Delay | Fee (bps) | Trades | P&L | PF | DD% | WR% | Delta | Delta% |
|-------|-----------|--------|-----|----|-----|-----|-------|--------|
| 0-candle (on-time) | 26.0 | 32 | $+4,718.27 | 2.61 | 16.4% | 68.8% | $+0.00 | +0.0% |
| 1-candle delay | 102.0 | 32 | $+2,144.16 | 1.8 | 19.8% | 65.6% | $-2,574.11 | -54.6% |
| 2-candle delay | 152.0 | 32 | $+1,003.62 | 1.39 | 23.8% | 65.6% | $-3,714.65 | -78.7% |

**Most damaging delay**: 2-candle delay (P&L=$+1,003.62, delta=-78.7%)

### 2. Monte Carlo Distribution

**Trials**: 50 | **Seed**: 42

#### P&L Distribution

| Statistic | Value |
|-----------|-------|
| Mean | $+3,203.11 |
| Median | $+3,431.22 |
| Std Dev | $1,581.73 |
| P5 (worst 5%) | $+1,003.62 |
| P25 | $+2,144.16 |
| P75 | $+4,718.27 |
| P95 (best 5%) | $+4,718.27 |
| Min | $+1,003.62 |
| Max | $+4,718.27 |

#### PF Distribution

| Statistic | Value |
|-----------|-------|
| Mean | 2.12 |
| Median | 2.21 |
| Min | 1.39 |
| Max | 2.61 |

#### Drawdown Distribution

| Statistic | Value |
|-----------|-------|
| Mean DD | 18.9% |
| Median DD | 18.1% |
| P95 DD | 23.8% |
| Max DD | 23.8% |

#### Fee Sample Counts

| Fee | Count | Pct |
|-----|-------|-----|
| 0.0026 | 25 | 50.0% |
| 0.0102 | 15 | 30.0% |
| 0.0152 | 10 | 20.0% |

### 3. Survival Rate

| Metric | Value |
|--------|-------|
| Profitable trials | 50/50 |
| Unprofitable trials | 0/50 |
| **Survival rate** | **100.0%** |

### 4. Key Finding

- The **2-candle delay** causes the biggest absolute damage: P&L delta of $-3,714.65 (-78.7% vs baseline).
- Moving from 1-candle to 2-candle delay adds $-1,140.54 additional damage.
- **Live execution implication**: Strategy shows good resilience to random latency. Live execution with occasional 1-2 candle delays is unlikely to destroy profitability.

### 5. Verdict

**ROBUST** (survival rate: 100.0%)

---

## Comparative Summary

| Metric | Champion_H2 | GRID_BEST |
|--------|------------------------|------------------------|
| Baseline P&L | $+4,113.50 | $+4,718.27 |
| 1-candle P&L | $+1,827.13 | $+2,144.16 |
| 2-candle P&L | $+801.22 | $+1,003.62 |
| MC mean P&L | $+2,888.24 | $+3,203.11 |
| MC P5 P&L | $+801.22 | $+1,003.62 |
| Survival rate | 100.0% | 100.0% |
| **Verdict** | **ROBUST** | **ROBUST** |

---

*Generated by hf_latency_stress.py -- 4H variant research*
# HF Validate — 4H Variant Research Validation

> **NOTE**: This is 4H variant research, NOT true HF. No sub-4H data exists yet.

**Date**: 2026-02-15 12:52
**Universe**: tradeable
**Data**: `candle_cache_tradeable.json`
**Coins**: 425
**Total runtime**: 209.8s

## Verdict Summary

| Config | Verdict | WF | Rolling | Friction | Latency | Concentration | Sufficiency |
|--------|---------|----|---------|----------|---------|---------------|-------------|
| Champion_H2 | **GO** | PASS | PASS | PASS | PASS | PASS | PASS |
| GRID_BEST | **GO** | PASS | PASS | PASS | PASS | PASS | PASS |

---

## Champion_H2

**Config**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 8, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 3.0}`
**Verdict**: **GO** — All 6 gates passed

### 1. Purged Walk-Forward (5-fold, embargo=2)

**Result**: 5/5 positive folds, 5/5 PF>1 folds -> **PASS**

| Fold | Bars | Trades | P&L | PF | WR% | DD% | Positive |
|------|------|--------|-----|----|-----|-----|----------|
| 1 | 50-184 | 7 | $+54 | 1.08 | 42.9% | 21.7% | YES |
| 2 | 184-318 | 5 | $+766 | 99.0 | 100.0% | 8.1% | YES |
| 3 | 318-452 | 4 | $+41 | 1.17 | 50.0% | 12.1% | YES |
| 4 | 452-586 | 6 | $+636 | 2.58 | 66.7% | 14.6% | YES |
| 5 | 586-721 | 9 | $+1,107 | 3.87 | 77.8% | 11.4% | YES |

### 2. Rolling Windows (180-bar)

**Result**: 4/4 positive (100%, gate >= 70%) -> **PASS**

| Window | Bars | Trades | P&L | PF | WR% | Positive |
|--------|------|--------|-----|----|-----|----------|
| 1 | 50-230 | 9 | $+141 | 1.21 | 55.6% | YES |
| 2 | 230-410 | 5 | $+592 | 3.55 | 80.0% | YES |
| 3 | 410-590 | 8 | $+837 | 2.64 | 62.5% | YES |
| 4 | 590-721 | 9 | $+1,107 | 3.87 | 77.8% | YES |

### 3. Friction Stress

**Gate**: Both regimes P&L > $0 -> **PASS**

| Regime | Fee | Trades | P&L | PF | WR% | DD% | Pass |
|--------|-----|--------|-----|----|-----|-----|------|
| 2x+20bps | 0.0072 | 31 | $+2,608 | 2.13 | 67.7% | 26.9% | YES |
| 1-candle | 0.0102 | 31 | $+1,827 | 1.81 | 64.5% | 28.2% | YES |

### 4. Latency Proxy

**Note**: Covered by 1-candle-later fee regime in friction stress test
**Result**: P&L=$+1,827 at fee=0.0102 -> **PASS**

### 5. Concentration

**Denominator**: sum(max(0, coin_pnl)) = $+6,497
**Coins traded**: 30

| Metric | Value | Gate | Pass |
|--------|-------|------|------|
| Top-1 (MF/USD) | 11.5% | < 40% | YES |
| Top-3 (MF/USD, U/USD, CHEEMS/USD) | 29.8% | < 70% | YES |
| **Overall** | | | **PASS** |

### 6. Trade Sufficiency

**Total trades**: 31 (minimum: 20)
**P&L**: $+4,114 | **WR**: 67.7%
**Result**: **PASS**

---

## GRID_BEST

**Config**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 10, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 2.5}`
**Verdict**: **GO** — All 6 gates passed

### 1. Purged Walk-Forward (5-fold, embargo=2)

**Result**: 5/5 positive folds, 5/5 PF>1 folds -> **PASS**

| Fold | Bars | Trades | P&L | PF | WR% | DD% | Positive |
|------|------|--------|-----|----|-----|-----|----------|
| 1 | 50-184 | 7 | $+280 | 1.41 | 57.1% | 12.2% | YES |
| 2 | 184-318 | 5 | $+766 | 99.0 | 100.0% | 8.1% | YES |
| 3 | 318-452 | 5 | $+429 | 3.09 | 60.0% | 8.0% | YES |
| 4 | 452-586 | 6 | $+291 | 1.68 | 50.0% | 16.4% | YES |
| 5 | 586-721 | 9 | $+973 | 3.07 | 77.8% | 13.3% | YES |

### 2. Rolling Windows (180-bar)

**Result**: 4/4 positive (100%, gate >= 70%) -> **PASS**

| Window | Bars | Trades | P&L | PF | WR% | Positive |
|--------|------|--------|-----|----|-----|----------|
| 1 | 50-230 | 9 | $+377 | 1.55 | 66.7% | YES |
| 2 | 230-410 | 6 | $+1,084 | 7.63 | 83.3% | YES |
| 3 | 410-590 | 8 | $+466 | 1.87 | 50.0% | YES |
| 4 | 590-721 | 9 | $+973 | 3.07 | 77.8% | YES |

### 3. Friction Stress

**Gate**: Both regimes P&L > $0 -> **PASS**

| Regime | Fee | Trades | P&L | PF | WR% | DD% | Pass |
|--------|-----|--------|-----|----|-----|-----|------|
| 2x+20bps | 0.0072 | 32 | $+3,019 | 2.08 | 68.8% | 18.0% | YES |
| 1-candle | 0.0102 | 32 | $+2,144 | 1.8 | 65.6% | 19.8% | YES |

### 4. Latency Proxy

**Note**: Covered by 1-candle-later fee regime in friction stress test
**Result**: P&L=$+2,144 at fee=0.0102 -> **PASS**

### 5. Concentration

**Denominator**: sum(max(0, coin_pnl)) = $+7,640
**Coins traded**: 30

| Metric | Value | Gate | Pass |
|--------|-------|------|------|
| Top-1 (MF/USD) | 12.0% | < 40% | YES |
| Top-3 (MF/USD, CHEEMS/USD, U/USD) | 32.5% | < 70% | YES |
| **Overall** | | | **PASS** |

### 6. Trade Sufficiency

**Total trades**: 32 (minimum: 20)
**P&L**: $+4,718 | **WR**: 68.8%
**Result**: **PASS**

---

## Gate Thresholds

| Gate | Threshold |
|------|-----------|
| Walk-Forward | >= 4/5 folds positive (or PF>1) |
| Rolling Windows | >= 70% positive P&L |
| Friction Stress | P&L > $0 at 2x+20bps AND 1-candle-later |
| Latency Proxy | (same as 1-candle-later friction) |
| Concentration | top1 < 40%, top3 < 70% |
| Trade Sufficiency | >= 20 trades |

## Verdict Logic

- `INSUFFICIENT_SAMPLE`: trades < 20
- `GO`: all gates pass
- `SOFT-GO`: WF 3/5 and all other gates pass
- `NO-GO`: any gate fails (beyond soft WF)

*Generated by hf_validate.py at 2026-02-15 12:52*
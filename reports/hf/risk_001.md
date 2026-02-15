# HF Tail Risk Report — 4H Variant Research

**Date**: 2026-02-15 12:53
**Universe**: tradeable
**Data**: `candle_cache_tradeable.json`
**Coins**: 425
**Bars**: 721
**Window size**: 180 bars (~30 days)
**Runtime**: 25.7s

---

## Champion_H2

**Config**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 8, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 3.0}`

### Baseline Performance

| Metric | Value |
|--------|-------|
| Trades | 31 |
| Win Rate | 67.7% |
| P&L | $+4,113.50 |
| Final Equity | $6,113.50 |
| Profit Factor | 2.73 |
| Max Drawdown | 24.7% |
| Broke | False |

### 1. Drawdown Per Window

| Window | Bars | Trades | P&L | Max DD% | Flagged |
|--------|------|--------|-----|---------|---------|
| 1 | 50-230 | 9 | $+140.67 | 18.9% |  |
| 2 | 230-410 | 5 | $+633.11 | 8.5% |  |
| 3 | 410-590 | 8 | $+1,161.09 | 14.6% |  |
| 4 | 590-771 | 9 | $+2,178.63 | 8.5% |  |

**Flagged windows (DD>30%)**: 0/4

### 2. Worst-Coin Contribution

**Coins traded**: 30

**Worst 5 coins**:

| Coin | P&L | Trades | % of Total |
|------|-----|--------|------------|
| COQ/USD | $-410.22 | 1 | -10.0% |
| APR/USD | $-351.23 | 1 | -8.5% |
| BERA/USD | $-347.95 | 1 | -8.5% |
| AI3/USD | $-250.65 | 1 | -6.1% |
| BLUR/USD | $-248.59 | 1 | -6.0% |

**Best 5 coins**:

| Coin | P&L | Trades | % of Total |
|------|-----|--------|------------|
| MF/USD | $+746.00 | 2 | 18.1% |
| U/USD | $+628.02 | 1 | 15.3% |
| CHEEMS/USD | $+563.51 | 1 | 13.7% |
| MOODENG/USD | $+505.62 | 1 | 12.3% |
| ZEUS/USD | $+495.82 | 1 | 12.1% |

**Removal impact**:

| Scenario | P&L | Delta |
|----------|-----|-------|
| Baseline | $+4,113.50 | — |
| Remove worst 1 (COQ/USD) | $+4,523.73 | $+410.22 |
| Remove worst 3 (COQ/USD, APR/USD, BERA/USD) | $+5,222.91 | $+1,109.40 |

### 3. Friction Ladder

| Level | Fee (bps) | P&L | Trades | DD% | Profitable |
|-------|-----------|-----|--------|-----|------------|
| baseline | 26.0 | $+4,113.50 | 31 | 24.7% | YES |
| 1.5x_fees | 39.0 | $+3,645.63 | 31 | 25.3% | YES |
| 2x_fees | 52.0 | $+3,212.50 | 31 | 25.9% | YES |
| 2x+10bps | 62.0 | $+2,901.38 | 31 | 26.4% | YES |
| 2x+20bps | 72.0 | $+2,608.27 | 31 | 26.9% | YES |
| 2x+35bps | 87.0 | $+2,200.16 | 31 | 27.5% | YES |
| 1_candle_later | 102.0 | $+1,827.13 | 31 | 28.2% | YES |

**Breakeven**: Still profitable at max tested friction

### 4. Latency Sensitivity (1-Candle-Later Entry)

| Metric | Value |
|--------|-------|
| Baseline P&L | $+4,113.50 |
| 1-candle-later P&L | $+1,827.13 |
| Delta | $-2,286.37 (-55.6%) |
| Still profitable | True |
| Fee modeled | 102.0 bps |

### 5. Consecutive Loss Analysis

| Metric | Value |
|--------|-------|
| Max consecutive losses | 3 |
| Total losing streaks | 7 |
| Equity impact of worst streak | 14.6% |
| Equity before worst streak | $4,132.54 |
| Equity after worst streak | $3,530.66 |
| Worst streak (by length) | 3 trades, $-479.20 |
| Worst streak (by P&L) | 2 trades, $-601.88 |

**Losing streak distribution**:

| Streak Length | Count |
|--------------|-------|
| 1 | 5 |
| 2 | 1 |
| 3 | 1 |

---

## GRID_BEST

**Config**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 10, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 2.5}`

### Baseline Performance

| Metric | Value |
|--------|-------|
| Trades | 32 |
| Win Rate | 68.8% |
| P&L | $+4,718.27 |
| Final Equity | $6,718.27 |
| Profit Factor | 2.61 |
| Max Drawdown | 16.4% |
| Broke | False |

### 1. Drawdown Per Window

| Window | Bars | Trades | P&L | Max DD% | Flagged |
|--------|------|--------|-----|---------|---------|
| 1 | 50-230 | 9 | $+376.57 | 10.5% |  |
| 2 | 230-410 | 6 | $+1,288.18 | 5.4% |  |
| 3 | 410-590 | 8 | $+854.25 | 16.4% |  |
| 4 | 590-771 | 9 | $+2,199.26 | 10.5% |  |

**Flagged windows (DD>30%)**: 0/4

### 2. Worst-Coin Contribution

**Coins traded**: 30

**Worst 5 coins**:

| Coin | P&L | Trades | % of Total |
|------|-----|--------|------------|
| COQ/USD | $-569.01 | 1 | -12.1% |
| APR/USD | $-509.15 | 1 | -10.8% |
| BERA/USD | $-493.39 | 1 | -10.5% |
| AI3/USD | $-287.86 | 1 | -6.1% |
| AKE/USD | $-260.05 | 1 | -5.5% |

**Best 5 coins**:

| Coin | P&L | Trades | % of Total |
|------|-----|--------|------------|
| MF/USD | $+915.79 | 2 | 19.4% |
| CHEEMS/USD | $+873.18 | 2 | 18.5% |
| U/USD | $+690.15 | 1 | 14.6% |
| ZEUS/USD | $+557.01 | 1 | 11.8% |
| MOODENG/USD | $+555.64 | 1 | 11.8% |

**Removal impact**:

| Scenario | P&L | Delta |
|----------|-----|-------|
| Baseline | $+4,718.27 | — |
| Remove worst 1 (COQ/USD) | $+5,287.28 | $+569.01 |
| Remove worst 3 (COQ/USD, APR/USD, BERA/USD) | $+6,289.81 | $+1,571.55 |

### 3. Friction Ladder

| Level | Fee (bps) | P&L | Trades | DD% | Profitable |
|-------|-----------|-----|--------|-----|------------|
| baseline | 26.0 | $+4,718.27 | 32 | 16.4% | YES |
| 1.5x_fees | 39.0 | $+4,188.58 | 32 | 16.9% | YES |
| 2x_fees | 52.0 | $+3,699.45 | 32 | 17.3% | YES |
| 2x+10bps | 62.0 | $+3,348.89 | 32 | 17.7% | YES |
| 2x+20bps | 72.0 | $+3,019.26 | 32 | 18.0% | YES |
| 2x+35bps | 87.0 | $+2,561.42 | 32 | 18.6% | YES |
| 1_candle_later | 102.0 | $+2,144.16 | 32 | 19.8% | YES |

**Breakeven**: Still profitable at max tested friction

### 4. Latency Sensitivity (1-Candle-Later Entry)

| Metric | Value |
|--------|-------|
| Baseline P&L | $+4,718.27 |
| 1-candle-later P&L | $+2,144.16 |
| Delta | $-2,574.11 (-54.6%) |
| Still profitable | True |
| Fee modeled | 102.0 bps |

### 5. Consecutive Loss Analysis

| Metric | Value |
|--------|-------|
| Max consecutive losses | 2 |
| Total losing streaks | 9 |
| Equity impact of worst streak | 16.4% |
| Equity before worst streak | $4,851.79 |
| Equity after worst streak | $4,054.78 |
| Worst streak (by length) | 2 trades, $-797.01 |
| Worst streak (by P&L) | 2 trades, $-797.01 |

**Losing streak distribution**:

| Streak Length | Count |
|--------------|-------|
| 1 | 8 |
| 2 | 1 |

---

## Comparative Summary

| Metric | Champion_H2 | GRID_BEST |
|--------|---------------|---------------|
| Trades | 31 | 32 |
| P&L | $+4,113.50 | $+4,718.27 |
| Max DD | 24.7% | 16.4% |
| PF | 2.73 | 2.61 |
| Breakeven friction | Still profitable at max tested friction | Still profitable at max tested friction |
| 1-candle P&L delta | $-2,286.37 | $-2,574.11 |
| Max consec. losses | 3 | 2 |


---
*Generated by hf_tail_risk.py — 4H variant research*
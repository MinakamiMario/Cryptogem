# MEXC Combined Deploy Candidate — Report

**Date**: 2026-02-18
**Git**: `9a606d9`
**Universe**: Top 200 by volume, >=2160 bars (200 coins)
**Full range**: ~467 days, 2853 bars
**Fee**: MEXC 10bps
**Sizing**: Fixed $2,000/trade (no compounding)

## Configuration

| Layer | Parameter | Value |
|-------|-----------|-------|
| Entry | Signal | Vol Capitulation (H4S4-G05) |
| Entry | vol_mult | 3.5 |
| Entry | rsi_max | 35 |
| Exit | max_stop_pct | 15.0 |
| Exit | time_max_bars | 15 |
| Exit | rsi_rec_target | 45.0 |
| Exit | rsi_rec_min_bars | **5** (was 2) |
| Wrapper | dd_throttle | >5% → 0.25x |
| Wrapper | adaptive_maxpos | 2/1/1 |

---

## Results Summary

| Metric | Baseline (no wrapper) | Combined | Delta |
|--------|----------------------:|--------:|------:|
| PF | 1.3867 | 1.5556 | +0.1689 |
| P&L | $+9,281 | $+3,362 | $-5,919 |
| Trades | 328 | 238 | -90 |
| DD | 52.6% | 16.2% | -36.4pp |
| WR | 54.3% | 55.5% | +1.2pp |
| EV/trade | | $14.13 | |
| Trades/day | | 0.55 | |

## Exit Attribution (Combined)

| Exit Reason | Class | Count | P&L | WR |
|-------------|-------|------:|----:|---:|
| RSI RECOVERY | A | 69 | $+5,152 | 77% |
| DC TARGET | A | 79 | $+3,892 | 94% |
| BB TARGET | A | 5 | $+167 | 100% |
| TIME MAX | B | 47 | $-1,826 | 0% |
| FIXED STOP | B | 38 | $-4,024 | 0% |

---

## Acceptance Gates

| Gate | Threshold | Value | Status |
|------|-----------|------:|-------:|
| PF >= 1.3 | | 1.5556 | ✅ PASS |
| DD <= 20.0% | | 16.16 | ✅ PASS |
| Boot P5 PF >= 0.85 | | 1.0831 | ✅ PASS |
| Boot %prof >= 80.0% | | 97.3 | ✅ PASS |
| Window >= 4/5 | | 5 | ✅ PASS |
| Trades >= 250 | | 238 | ❌ FAIL |
| Determinism | | PASS | ✅ PASS |

**Gates passed**: 6/7
**Deploy ready**: NO

---

## Truth-Pass: VERIFIED (3/3)

### 5-Way Window Split

| Window | Bars | Trades | PF | P&L | DD | Status |
|--------|-----:|-------:|---:|----:|---:|-------:|
| w1 | 50-610 | 67 | 1.99 | $+1,942 | 16.2% | ✅ |
| w2 | 610-1170 | 51 | 1.18 | $+294 | 17.9% | ✅ |
| w3 | 1170-1730 | 29 | 1.14 | $+118 | 19.8% | ✅ |
| w4 | 1730-2290 | 38 | 1.18 | $+185 | 17.5% | ✅ |
| w5 | 2290-2853 | 13 | 1.01 | $+3 | 19.0% | ✅ |

**5/5 PASS** (gate: >=4/5)

### Walk-Forward

- **Split A (cal=early, test=mid+late)** [PASS]: cal=112tr PF=2.04, test=86tr PF=1.17
- **Split B (cal=early+mid, test=late)** [PASS]: cal=186tr PF=1.60, test=37tr PF=1.13

### Bootstrap

- P5 PF: 1.08 (gate: >=0.85)
- Median PF: 1.54
- %Profitable: 97.3% (gate: >=80.0%)
- **PASS**

### Determinism: **PASS**

---

## Verdict

### ❌ NOT DEPLOY-READY

Failed gates: trades

# Sprint 4 Truth-Pass: sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5

- **Verdict**: **FAILED** (1/3 tests passed)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Universe**: universe_sprint1
- **Fee model**: kraken_spot_26bps
- **Git**: 9a606d9
- **Timestamp**: 2026-02-17T21:08:12.288866+00:00

## Full Run Baseline

| Metric | Value |
|--------|-------|
| Trades | 101 |
| PF | 1.25 |
| P&L | $+537.94 |
| WR | 54.5% |
| DD | 40.8% |

## Test 1: 3-Way Window Split [PASS]

Windows profitable: 2/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 33 | 0.38 | $-622.21 | 45.5% | 40.8% |
| mid | 273-496 | 35 | 1.67 * | $+438.74 | 54.3% | 12.3% |
| late | 496-721 | 34 | 1.81 * | $+722.63 | 55.9% | 23.1% |

## Test 2: Walk-Forward [FAIL]

### Cal=Early, Test=Mid+Late [FAIL]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 33 | 0.38 | $-622.21 | 45.5% |
| Test | 273-721 | 68 | 2.00 | $+1,684.06 | 58.8% |

### Cal=Early+Mid, Test=Late [FAIL]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 68 | 0.78 | $-319.96 | 50.0% |
| Test | 496-721 | 34 | 1.81 | $+722.63 | 55.9% |

## Test 3: Bootstrap Monte Carlo [FAIL]

- Resamples: 1000 (seed=42)
- Trades per resample: 101

| Metric | Value |
|--------|-------|
| Median PF | 1.17 |
| P5 PF | 0.62 |
| P95 PF | 2.18 |
| Median P&L | $+360.36 |
| P5 P&L | $-913.20 |
| % Profitable | 64.6% |


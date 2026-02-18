# Sprint 4 Truth-Pass: sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35

- **Verdict**: **CONDITIONAL** (2/3 tests passed)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Universe**: universe_sprint1
- **Fee model**: kraken_spot_26bps
- **Git**: 9a606d9
- **Timestamp**: 2026-02-17T21:08:11.599025+00:00

## Full Run Baseline

| Metric | Value |
|--------|-------|
| Trades | 214 |
| PF | 1.28 |
| P&L | $+823.92 |
| WR | 53.3% |
| DD | 59.1% |

## Test 1: 3-Way Window Split [PASS]

Windows profitable: 3/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 72 | 1.02 * | $+48.18 | 52.8% | 25.7% |
| mid | 273-496 | 74 | 1.00 * | $-0.03 | 56.8% | 26.4% |
| late | 496-721 | 67 | 1.18 * | $-141.68 | 40.3% | 60.7% |

## Test 2: Walk-Forward [PASS]

### Cal=Early, Test=Mid+Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 72 | 1.02 | $+48.18 | 52.8% |
| Test | 273-721 | 141 | 1.40 | $+693.05 | 52.5% |

### Cal=Early+Mid, Test=Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 147 | 1.02 | $+97.16 | 55.8% |
| Test | 496-721 | 67 | 1.18 | $-141.68 | 40.3% |

## Test 3: Bootstrap Monte Carlo [FAIL]

- Resamples: 1000 (seed=42)
- Trades per resample: 214

| Metric | Value |
|--------|-------|
| Median PF | 1.26 |
| P5 PF | 0.78 |
| P95 PF | 2.09 |
| Median P&L | $+1,647.11 |
| P5 P&L | $-1,642.95 |
| % Profitable | 78.0% |


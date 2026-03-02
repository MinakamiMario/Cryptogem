# MS Sprint 2 Truth-Pass: ms_017_mse_fib618

- **Verdict**: **VERIFIED** (3/3 tests passed)
- **Family**: shift_pb
- **Dataset**: 4h_default
- **Coins**: 487
- **Fee model**: kraken_spot_26bps
- **Git**: 22d5149
- **Timestamp**: 2026-03-02T22:19:01.061604+00:00

## Full Run Baseline

| Metric | Value |
|--------|-------|
| Trades | 475 |
| PF | 1.80 |
| P&L | $+27,497.56 |
| WR | 57.0% |
| DD | 28.0% |

## Test 1: 3-Way Window Split [PASS]

Windows profitable: 3/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 155 | 1.62 * | $+1,419.87 | 58.1% | 19.0% |
| mid | 273-496 | 174 | 5.06 * | $+9,164.25 | 62.1% | 13.4% |
| late | 496-721 | 149 | 1.35 * | $+1,008.91 | 49.7% | 28.0% |

## Test 2: Walk-Forward [PASS]

### Cal=Early, Test=Mid+Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 155 | 1.62 | $+1,419.87 | 58.1% |
| Test | 273-721 | 325 | 1.82 | $+15,683.11 | 56.3% |

### Cal=Early+Mid, Test=Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 324 | 3.73 | $+16,623.31 | 60.5% |
| Test | 496-721 | 149 | 1.35 | $+1,008.91 | 49.7% |

## Test 3: Bootstrap Monte Carlo [PASS]

- Resamples: 1000 (seed=42)
- Trades per resample: 475

| Metric | Value |
|--------|-------|
| Median PF | 1.83 |
| P5 PF | 1.28 |
| P95 PF | 2.61 |
| Median P&L | $+28,265.88 |
| P5 P&L | $+11,001.67 |
| % Profitable | 99.9% |


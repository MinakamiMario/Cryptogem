# Sprint 4 Truth-Pass: sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol

- **Verdict**: **FAILED** (1/3 tests passed)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Universe**: universe_sprint1
- **Fee model**: kraken_spot_26bps
- **Git**: 9a606d9
- **Timestamp**: 2026-02-17T21:08:12.795309+00:00

## Full Run Baseline

| Metric | Value |
|--------|-------|
| Trades | 206 |
| PF | 1.16 |
| P&L | $+810.21 |
| WR | 49.5% |
| DD | 53.2% |

## Test 1: 3-Way Window Split [PASS]

Windows profitable: 2/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 74 | 0.47 | $-974.14 | 46.0% | 53.2% |
| mid | 273-496 | 67 | 1.10 * | $+192.82 | 52.2% | 34.9% |
| late | 496-721 | 75 | 1.64 * | $+2,056.81 | 53.3% | 25.8% |

## Test 2: Walk-Forward [FAIL]

### Cal=Early, Test=Mid+Late [FAIL]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 74 | 0.47 | $-974.14 | 46.0% |
| Test | 273-721 | 135 | 1.53 | $+3,040.53 | 51.9% |

### Cal=Early+Mid, Test=Late [FAIL]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 138 | 0.73 | $-777.03 | 48.5% |
| Test | 496-721 | 75 | 1.64 | $+2,056.81 | 53.3% |

## Test 3: Bootstrap Monte Carlo [FAIL]

- Resamples: 1000 (seed=42)
- Trades per resample: 206

| Metric | Value |
|--------|-------|
| Median PF | 1.13 |
| P5 PF | 0.56 |
| P95 PF | 2.15 |
| Median P&L | $+637.22 |
| P5 P&L | $-2,395.86 |
| % Profitable | 59.8% |


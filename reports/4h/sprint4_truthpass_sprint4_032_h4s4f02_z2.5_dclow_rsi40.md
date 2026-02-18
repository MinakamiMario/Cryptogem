# Sprint 4 Truth-Pass: sprint4_032_h4s4f02_z2.5_dclow_rsi40

- **Verdict**: **FAILED** (0/3 tests passed)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Universe**: universe_sprint1
- **Fee model**: kraken_spot_26bps
- **Git**: 9a606d9
- **Timestamp**: 2026-02-17T21:08:11.266366+00:00

## Full Run Baseline

| Metric | Value |
|--------|-------|
| Trades | 206 |
| PF | 1.35 |
| P&L | $+4,915.03 |
| WR | 52.9% |
| DD | 44.0% |

## Test 1: 3-Way Window Split [FAIL]

Windows profitable: 1/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 66 | 0.71 | $-491.26 | 48.5% | 33.9% |
| mid | 273-496 | 72 | 2.51 * | $+9,858.20 | 62.5% | 18.6% |
| late | 496-721 | 67 | 0.63 | $-608.16 | 44.8% | 39.3% |

## Test 2: Walk-Forward [FAIL]

### Cal=Early, Test=Mid+Late [FAIL]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 66 | 0.71 | $-491.26 | 48.5% |
| Test | 273-721 | 144 | 1.46 | $+7,947.51 | 58.3% |

### Cal=Early+Mid, Test=Late [FAIL]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 134 | 1.97 | $+6,243.26 | 52.2% |
| Test | 496-721 | 67 | 0.63 | $-608.16 | 44.8% |

## Test 3: Bootstrap Monte Carlo [FAIL]

- Resamples: 1000 (seed=42)
- Trades per resample: 206

| Metric | Value |
|--------|-------|
| Median PF | 1.32 |
| P5 PF | 0.74 |
| P95 PF | 2.36 |
| Median P&L | $+4,463.22 |
| P5 P&L | $-4,060.93 |
| % Profitable | 73.6% |


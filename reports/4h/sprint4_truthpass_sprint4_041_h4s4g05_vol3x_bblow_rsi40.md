# Sprint 4 Truth-Pass: sprint4_041_h4s4g05_vol3x_bblow_rsi40

- **Verdict**: **VERIFIED** (3/3 tests passed)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Universe**: universe_sprint1
- **Fee model**: kraken_spot_26bps
- **Git**: 9a606d9
- **Timestamp**: 2026-02-17T21:08:10.790703+00:00

## Full Run Baseline

| Metric | Value |
|--------|-------|
| Trades | 216 |
| PF | 1.41 |
| P&L | $+2,283.84 |
| WR | 54.6% |
| DD | 49.8% |

## Test 1: 3-Way Window Split [PASS]

Windows profitable: 2/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 71 | 1.38 * | $+874.96 | 56.3% | 33.2% |
| mid | 273-496 | 72 | 0.88 | $-189.32 | 51.4% | 38.7% |
| late | 496-721 | 75 | 1.39 * | $+276.63 | 50.7% | 51.0% |

## Test 2: Walk-Forward [PASS]

### Cal=Early, Test=Mid+Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 71 | 1.38 | $+874.96 | 56.3% |
| Test | 273-721 | 144 | 1.37 | $+754.80 | 52.8% |

### Cal=Early+Mid, Test=Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 144 | 1.17 | $+815.50 | 54.9% |
| Test | 496-721 | 75 | 1.39 | $+276.63 | 50.7% |

## Test 3: Bootstrap Monte Carlo [PASS]

- Resamples: 1000 (seed=42)
- Trades per resample: 216

| Metric | Value |
|--------|-------|
| Median PF | 1.38 |
| P5 PF | 0.92 |
| P95 PF | 2.12 |
| Median P&L | $+3,103.22 |
| P5 P&L | $-637.30 |
| % Profitable | 90.9% |


# Sweep v1 Truth-Pass: sweep_v1_005_sv1a05_rsi40_p8_atr1.0_volhigh

- **Verdict**: **FAILED** (0/3 tests passed)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Universe**: sweep_v1_487coins_min360bars
- **Fee model**: kraken_spot_26bps
- **Git**: 57a688e
- **Timestamp**: 2026-02-26T05:21:59.424312+00:00

## Full Run Baseline

| Metric | Value |
|--------|-------|
| Trades | 313 |
| PF | 1.24 |
| P&L | $+2,847.68 |
| WR | 53.4% |
| DD | 41.9% |

## Test 1: 3-Way Window Split [FAIL]

Windows profitable: 1/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 109 | 0.91 | $-269.06 | 53.2% | 38.6% |
| mid | 273-496 | 99 | 2.86 * | $+5,095.55 | 55.6% | 20.9% |
| late | 496-721 | 110 | 0.80 | $-449.34 | 50.9% | 40.1% |

## Test 2: Walk-Forward [FAIL]

### Cal=Early, Test=Mid+Late [FAIL]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 109 | 0.91 | $-269.06 | 53.2% |
| Test | 273-721 | 206 | 1.35 | $+3,814.59 | 53.9% |

### Cal=Early+Mid, Test=Late [FAIL]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 206 | 1.75 | $+3,915.63 | 53.9% |
| Test | 496-721 | 110 | 0.80 | $-449.34 | 50.9% |

## Test 3: Bootstrap Monte Carlo [FAIL]

- Resamples: 1000 (seed=42)
- Trades per resample: 313

| Metric | Value |
|--------|-------|
| Median PF | 1.20 |
| P5 PF | 0.76 |
| P95 PF | 1.88 |
| Median P&L | $+2,353.71 |
| P5 P&L | $-3,108.36 |
| % Profitable | 73.9% |


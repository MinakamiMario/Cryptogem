# Sweep v1 Truth-Pass: sweep_v1_006_sv1a06_rsi45_p8_atr2.0

- **Verdict**: **VERIFIED** (3/3 tests passed)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Universe**: sweep_v1_487coins_min360bars
- **Fee model**: kraken_spot_26bps
- **Git**: 57a688e
- **Timestamp**: 2026-02-26T05:21:58.610147+00:00

## Full Run Baseline

| Metric | Value |
|--------|-------|
| Trades | 347 |
| PF | 1.52 |
| P&L | $+3,425.19 |
| WR | 58.8% |
| DD | 63.1% |

## Test 1: 3-Way Window Split [PASS]

Windows profitable: 2/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 112 | 0.79 | $-382.41 | 59.8% | 34.7% |
| mid | 273-496 | 119 | 4.41 * | $+7,654.50 | 61.3% | 14.2% |
| late | 496-721 | 124 | 1.15 * | $-414.68 | 55.6% | 63.1% |

## Test 2: Walk-Forward [PASS]

### Cal=Early, Test=Mid+Late [FAIL]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 112 | 0.79 | $-382.41 | 59.8% |
| Test | 273-721 | 236 | 1.69 | $+5,556.23 | 58.5% |

### Cal=Early+Mid, Test=Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 230 | 2.36 | $+4,931.70 | 60.4% |
| Test | 496-721 | 124 | 1.15 | $-414.68 | 55.6% |

## Test 3: Bootstrap Monte Carlo [PASS]

- Resamples: 1000 (seed=42)
- Trades per resample: 347

| Metric | Value |
|--------|-------|
| Median PF | 1.51 |
| P5 PF | 0.98 |
| P95 PF | 2.42 |
| Median P&L | $+5,921.17 |
| P5 P&L | $-251.29 |
| % Profitable | 94.0% |


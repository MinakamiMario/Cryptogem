# Sweep v1 Truth-Pass: sweep_v1_002_sv1a02_rsi40_p5_atr1.5

- **Verdict**: **CONDITIONAL** (2/3 tests passed)
- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Universe**: sweep_v1_487coins_min360bars
- **Fee model**: kraken_spot_26bps
- **Git**: 57a688e
- **Timestamp**: 2026-02-26T05:21:59.015237+00:00

## Full Run Baseline

| Metric | Value |
|--------|-------|
| Trades | 306 |
| PF | 1.35 |
| P&L | $+744.52 |
| WR | 57.8% |
| DD | 56.8% |

## Test 1: 3-Way Window Split [PASS]

Windows profitable: 2/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 103 | 0.89 | $-260.60 | 56.3% | 30.3% |
| mid | 273-496 | 102 | 3.58 * | $+4,528.85 | 59.8% | 27.4% |
| late | 496-721 | 105 | 1.19 * | $-676.16 | 58.1% | 57.0% |

## Test 2: Walk-Forward [PASS]

### Cal=Early, Test=Mid+Late [FAIL]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 103 | 0.89 | $-260.60 | 56.3% |
| Test | 273-721 | 205 | 1.58 | $+1,406.73 | 59.0% |

### Cal=Early+Mid, Test=Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 203 | 1.83 | $+3,259.75 | 57.6% |
| Test | 496-721 | 105 | 1.19 | $-676.16 | 58.1% |

## Test 3: Bootstrap Monte Carlo [FAIL]

- Resamples: 1000 (seed=42)
- Trades per resample: 306

| Metric | Value |
|--------|-------|
| Median PF | 1.34 |
| P5 PF | 0.82 |
| P95 PF | 2.19 |
| Median P&L | $+2,773.93 |
| P5 P&L | $-1,653.99 |
| % Profitable | 82.3% |


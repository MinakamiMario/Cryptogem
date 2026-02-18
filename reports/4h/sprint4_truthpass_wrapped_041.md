# Sprint 4 Truth-Pass (Vol-Scale Wrapped): sprint4_041_h4s4g05_vol3x_bblow_rsi40

- **Verdict**: **CONDITIONAL** (2/3 tests passed)
- **Wrapper**: vol_scale (ATR14, pctl=25, cap=[0.25x, 2.0x])
- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Fee model**: kraken_spot_26bps
- **Git**: 9a606d9
- **Timestamp**: 2026-02-17T21:36:50.114502+00:00

## Wrapper Effect

| Metric | Raw | Wrapped | Delta |
|--------|-----|---------|-------|
| Trades | 216 | 216 | -- |
| PF | 1.41 | 1.59 | +0.18 |
| P&L | $+3,349.79 | $+3,557.30 | $+207.51 |
| WR | 54.6% | 54.6% | +0.0pp |
| DD | 36.4% | 28.1% | -8.3pp |

- Target ATR (P25): 0.000171
- Trades with ATR data: 216/216
- Scale range: 0.250 - 2.000 (median: 0.250)

## Test 1: 3-Way Window Split [PASS]

Windows profitable: 2/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 71 | 1.70 * | $+968.46 | 56.3% | 27.9% |
| mid | 273-496 | 73 | 0.87 | $-209.56 | 53.4% | 39.1% |
| late | 496-721 | 72 | 1.93 * | $+2,798.39 | 54.2% | 18.8% |

## Test 2: Walk-Forward [PASS]

Gate: at least 1 split with cal PF >= 1.0 AND test PF >= 1.0

### Cal=Early, Test=Mid+Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 71 | 1.70 | $+968.46 | 56.3% |
| Test | 273-721 | 145 | 1.56 | $+2,588.84 | 53.8% |

### Cal=Early+Mid, Test=Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 144 | 1.25 | $+758.91 | 54.9% |
| Test | 496-721 | 72 | 1.93 | $+2,798.39 | 54.2% |

## Test 3: Bootstrap Monte Carlo [FAIL]

- Resamples: 1000 (seed=42)
- Trades per resample: 216
- Gate: P5 PF >= 0.85 AND >= 80% profitable

| Metric | Value |
|--------|-------|
| Median PF | 1.54 |
| P5 PF | 0.83 |
| P95 PF | 2.75 |
| Median P&L | $+3,197.96 |
| P5 P&L | $-1,131.58 |
| % Profitable | 87.4% |


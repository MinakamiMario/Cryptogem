# Sprint 4 Truth-Pass (Vol-Scale Wrapped): sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35

- **Verdict**: **CONDITIONAL** (2/3 tests passed)
- **Wrapper**: vol_scale (ATR14, pctl=25, cap=[0.25x, 2.0x])
- **Dataset**: ohlcv_4h_kraken_spot_usd_526
- **Fee model**: kraken_spot_26bps
- **Git**: 9a606d9
- **Timestamp**: 2026-02-17T21:29:58.255984+00:00

## Wrapper Effect

| Metric | Raw | Wrapped | Delta |
|--------|-----|---------|-------|
| Trades | 214 | 214 | -- |
| PF | 1.28 | 1.51 | +0.23 |
| P&L | $+1,817.28 | $+2,246.43 | $+429.15 |
| WR | 53.3% | 53.3% | +0.0pp |
| DD | 31.8% | 20.3% | -11.4pp |

- Target ATR (P25): 0.000179
- Trades with ATR data: 214/214
- Scale range: 0.250 - 2.000 (median: 0.272)

## Test 1: 3-Way Window Split [PASS]

Windows profitable: 3/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 72 | 1.09 * | $+132.43 | 52.8% | 20.3% |
| mid | 273-496 | 75 | 1.45 * | $+385.98 | 60.0% | 13.4% |
| late | 496-721 | 67 | 1.82 * | $+1,728.02 | 46.3% | 23.3% |

## Test 2: Walk-Forward [PASS]

Gate: at least 1 split with cal PF >= 1.0 AND test PF >= 1.0

### Cal=Early, Test=Mid+Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 72 | 1.09 | $+132.43 | 52.8% |
| Test | 273-721 | 142 | 1.71 | $+2,114.00 | 53.5% |

### Cal=Early+Mid, Test=Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 147 | 1.22 | $+518.41 | 56.5% |
| Test | 496-721 | 67 | 1.82 | $+1,728.02 | 46.3% |

## Test 3: Bootstrap Monte Carlo [FAIL]

- Resamples: 1000 (seed=42)
- Trades per resample: 214
- Gate: P5 PF >= 0.85 AND >= 80% profitable

| Metric | Value |
|--------|-------|
| Median PF | 1.42 |
| P5 PF | 0.71 |
| P95 PF | 2.99 |
| Median P&L | $+1,941.92 |
| P5 P&L | $-1,619.29 |
| % Profitable | 76.7% |


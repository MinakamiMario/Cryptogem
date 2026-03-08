# MS Sprint 2 Truth-Pass: ms_018_mse_shallow

- **Verdict**: **VERIFIED** (3/3 tests passed)
- **Family**: shift_pb
- **Dataset**: 4h_default
- **Coins**: 487
- **Fee model**: kraken_spot_26bps
- **Git**: 22d5149
- **Timestamp**: 2026-03-02T22:18:56.957045+00:00

## Full Run Baseline

| Metric | Value |
|--------|-------|
| Trades | 697 |
| PF | 2.08 |
| P&L | $+46,016.70 |
| WR | 54.5% |
| DD | 21.3% |

## Test 1: 3-Way Window Split [PASS]

Windows profitable: 3/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 232 | 1.71 * | $+1,991.32 | 53.0% | 15.4% |
| mid | 273-496 | 255 | 2.65 * | $+5,035.60 | 57.6% | 14.4% |
| late | 496-721 | 220 | 2.01 * | $+5,117.75 | 52.3% | 21.3% |

## Test 2: Walk-Forward [PASS]

### Cal=Early, Test=Mid+Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 232 | 1.71 | $+1,991.32 | 53.0% |
| Test | 273-721 | 472 | 2.11 | $+23,169.92 | 55.1% |

### Cal=Early+Mid, Test=Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 480 | 2.32 | $+11,421.82 | 55.6% |
| Test | 496-721 | 220 | 2.01 | $+5,117.75 | 52.3% |

## Test 3: Bootstrap Monte Carlo [PASS]

- Resamples: 1000 (seed=42)
- Trades per resample: 697

| Metric | Value |
|--------|-------|
| Median PF | 2.08 |
| P5 PF | 1.48 |
| P95 PF | 2.98 |
| Median P&L | $+45,096.54 |
| P5 P&L | $+23,935.98 |
| % Profitable | 100.0% |


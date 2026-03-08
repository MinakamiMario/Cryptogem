# MS Sprint 2 Truth-Pass: ms_005_msb_base

- **Verdict**: **VERIFIED** (3/3 tests passed)
- **Family**: fvg_fill
- **Dataset**: 4h_default
- **Coins**: 487
- **Fee model**: kraken_spot_26bps
- **Git**: 22d5149
- **Timestamp**: 2026-03-02T22:18:58.073037+00:00

## Full Run Baseline

| Metric | Value |
|--------|-------|
| Trades | 429 |
| PF | 1.65 |
| P&L | $+18,755.99 |
| WR | 56.2% |
| DD | 19.5% |

## Test 1: 3-Way Window Split [PASS]

Windows profitable: 3/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 148 | 2.05 * | $+4,228.19 | 59.5% | 16.1% |
| mid | 273-496 | 138 | 2.21 * | $+1,910.56 | 56.5% | 16.4% |
| late | 496-721 | 143 | 1.56 * | $+2,234.36 | 57.3% | 19.5% |

## Test 2: Walk-Forward [PASS]

### Cal=Early, Test=Mid+Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 148 | 2.05 | $+4,228.19 | 59.5% |
| Test | 273-721 | 282 | 1.62 | $+5,378.78 | 55.0% |

### Cal=Early+Mid, Test=Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 285 | 2.01 | $+9,000.12 | 57.5% |
| Test | 496-721 | 143 | 1.56 | $+2,234.36 | 57.3% |

## Test 3: Bootstrap Monte Carlo [PASS]

- Resamples: 1000 (seed=42)
- Trades per resample: 429

| Metric | Value |
|--------|-------|
| Median PF | 1.65 |
| P5 PF | 1.19 |
| P95 PF | 2.25 |
| Median P&L | $+18,560.28 |
| P5 P&L | $+6,336.76 |
| % Profitable | 99.5% |


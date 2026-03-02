# MS Sprint 2 Truth-Pass: ms_007_msb_deep

- **Verdict**: **VERIFIED** (3/3 tests passed)
- **Family**: fvg_fill
- **Dataset**: 4h_default
- **Coins**: 487
- **Fee model**: kraken_spot_26bps
- **Git**: 22d5149
- **Timestamp**: 2026-03-02T22:19:02.166786+00:00

## Full Run Baseline

| Metric | Value |
|--------|-------|
| Trades | 344 |
| PF | 1.66 |
| P&L | $+9,337.95 |
| WR | 57.0% |
| DD | 22.9% |

## Test 1: 3-Way Window Split [PASS]

Windows profitable: 3/3 (need >= 2)

| Window | Bars | Trades | PF | P&L | WR | DD |
|--------|------|--------|-----|------|-----|-----|
| early | 50-273 | 115 | 1.78 * | $+2,969.65 | 56.5% | 22.9% |
| mid | 273-496 | 113 | 1.40 * | $+632.60 | 54.9% | 17.3% |
| late | 496-721 | 123 | 1.95 * | $+2,256.88 | 61.8% | 18.2% |

## Test 2: Walk-Forward [PASS]

### Cal=Early, Test=Mid+Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-273 | 115 | 1.78 | $+2,969.65 | 56.5% |
| Test | 273-721 | 233 | 1.68 | $+3,078.56 | 57.9% |

### Cal=Early+Mid, Test=Late [PASS]

| Phase | Bars | Trades | PF | P&L | WR |
|-------|------|--------|-----|------|-----|
| Cal | 50-496 | 224 | 1.51 | $+3,877.32 | 54.9% |
| Test | 496-721 | 123 | 1.95 | $+2,256.88 | 61.8% |

## Test 3: Bootstrap Monte Carlo [PASS]

- Resamples: 1000 (seed=42)
- Trades per resample: 344

| Metric | Value |
|--------|-------|
| Median PF | 1.65 |
| P5 PF | 1.24 |
| P95 PF | 2.25 |
| Median P&L | $+9,237.10 |
| P5 P&L | $+3,855.87 |
| % Profitable | 99.4% |


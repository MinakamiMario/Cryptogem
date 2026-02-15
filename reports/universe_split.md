# Universe Split Report
**Date**: 2026-02-15 01:11:21 CET
**Config**: `C1_TPSL_RSI45`
**Harness**: robustness_harness.py v2 (5 tests: WF, Friction, MC, Jitter, Universe)

## Universe Overview

| Universe | Coins | Description |
|----------|------:|-------------|
| LIVE_CURRENT | 526 | Live Kraken 532 cache (production set) |
| KRAKEN_ONLY | 522 | Kraken coins extracted from research_all cache |
| MEXC_ONLY | 1568 | MEXC-exclusive coins (not available on Kraken) |
| MEXC_TOP | 200 | Top 200 MEXC coins by median volume |

## Results Comparison

| Metric | LIVE_CURRENT | KRAKEN_ONLY | MEXC_ONLY | MEXC_TOP |
|--------|------------:|------------:|------------:|------------:|
| Coins | 526 | 522 | 1568 | 200 |
| Trades | 30 | 30 | 30 | 10 |
| P&L ($) | $3,746 | $1,612 | $1,566 | $-358 |
| Win Rate (%) | 70.0% | 60.0% | 53.3% | 40.0% |
| Max DD (%) | 27.9% | 32.3% | 28.4% | 34.3% |
| Profit Factor | 3.31 | 1.9 | 1.56 | 0 |
| Walk-Forward | 4/5 | 3/5 | 4/5 | ? |
| Friction 2x+20bps ($) | $2,370 | $741 | $706 | $0 |
| MC Ruin (%) | 0.0% | 0.2% | 0.5% | 100.0% |
| Jitter pos (%) | 98% | 98% | 58% | 0% |
| Universe Shift | 4/4 | 3/4 | 3/4 | 0/4 |
| Top1 (%) | 16.9% | 18.0% | 11.0% | 0.0% |
| **Verdict** | **GO** | **SOFT-GO** | **NO-GO** | **NO-GO** |
| Runtime (s) | 0 | 0 | 0 | 0 |

## Analysis

**GO universes (1)**: LIVE_CURRENT
**SOFT-GO universes (1)**: KRAKEN_ONLY
**NO-GO universes (2)**: MEXC_ONLY, MEXC_TOP

- P&L sign consistency: MIXED (some negative)
- P&L range: $-358 to $3,746
- Win rate range: 40.0% to 70.0%
- Trade count range: 10 to 30

## Conclusion

Strategy passes on 2/4 universes. Mixed results -- universe-dependent performance.

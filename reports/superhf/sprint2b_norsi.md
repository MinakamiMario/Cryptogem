# SuperHF Sprint 2B — RSI Recovery Disabled

**Date**: 2026-02-23 05:17
**Change**: rsi_recovery=False for all configs. Exit chain: STOP → TIME MAX → DC TARGET → BB TARGET
**Rationale**: RSI Recovery on 15m fires when price < dc_mid AND < bb_mid (17% WR, -$4K to -$7.5K). Exits don't overlap with DC/BB targets.
**Universe**: 163 coins
**Configs**: 12 total, **0 PASS**

## Scoreboard (sorted by PF)

| # | Config | Family | Trades | PF | ΔPF | P&L | ΔP&L | WR | DD | ΔDD | WF | Gates |
|---|--------|--------|-------:|---:|----:|----:|-----:|---:|---:|----:|---:|:-----:|
| 1 | SHF-A01 | pivot_reclaim | 942 | 0.955 | +0.013 | $-917 | $+121 | 58.5% | 83.5% | +0.5 | 1/3 | ❌ |
| 2 | SHF-A06 | pivot_reclaim | 885 | 0.891 | +0.009 | $-965 | $+218 | 60.5% | 71.4% | -6.7 | 0/3 | ❌ |
| 3 | SHF-A03 | pivot_reclaim | 1108 | 0.855 | +0.006 | $-1334 | $+134 | 58.8% | 75.6% | -4.7 | 1/3 | ❌ |
| 4 | SHF-A05 | pivot_reclaim | 681 | 0.818 | +0.030 | $-1446 | $+70 | 56.2% | 81.8% | -0.2 | 1/3 | ❌ |
| 5 | SHF-A02 | pivot_reclaim | 955 | 0.793 | -0.019 | $-1753 | $+124 | 57.2% | 91.2% | -5.0 | 0/3 | ❌ |
| 6 | SHF-B02 | sweep_reclaim | 712 | 0.714 | +0.060 | $-1715 | $+79 | 55.8% | 87.2% | -3.0 | 0/3 | ❌ |
| 7 | SHF-B01 | sweep_reclaim | 542 | 0.711 | -0.028 | $-1633 | $-64 | 53.9% | 84.2% | +1.4 | 0/3 | ❌ |
| 8 | SHF-A04 | pivot_reclaim | 1049 | 0.680 | -0.131 | $-1870 | $-78 | 56.6% | 94.8% | +3.2 | 0/3 | ❌ |
| 9 | SHF-B04 | sweep_reclaim | 522 | 0.664 | +0.103 | $-1438 | $+195 | 57.3% | 72.8% | -9.5 | 1/3 | ❌ |
| 10 | SHF-B05 | sweep_reclaim | 326 | 0.651 | +0.017 | $-1209 | $+38 | 53.7% | 62.5% | -1.1 | 0/3 | ❌ |
| 11 | SHF-B03 | sweep_reclaim | 378 | 0.638 | +0.003 | $-1405 | $-66 | 56.3% | 74.4% | +3.1 | 0/3 | ❌ |
| 12 | SHF-B06 | sweep_reclaim | 281 | 0.440 | +0.010 | $-1233 | $+21 | 50.9% | 62.5% | -0.6 | 0/3 | ❌ |

## Exit Breakdown (top-3 by PF)

| Config | Exit | Class | Trades | P&L | WR |
|--------|------|:-----:|-------:|----:|---:|
| SHF-A01 | DC TARGET | A | 625 | $6018 | 62.1% |
| SHF-A01 | TIME MAX | B | 5 | $-1439 | 0.0% |
| SHF-A01 | BB TARGET | A | 303 | $-1883 | 53.8% |
| SHF-A01 | FIXED STOP | B | 9 | $-3614 | 0.0% |
| SHF-A06 | DC TARGET | A | 624 | $2355 | 66.3% |
| SHF-A06 | END | B | 1 | $-13 | 0.0% |
| SHF-A06 | TIME MAX | B | 3 | $-247 | 0.0% |
| SHF-A06 | FIXED STOP | B | 3 | $-878 | 0.0% |
| SHF-A06 | BB TARGET | A | 254 | $-2182 | 47.6% |
| SHF-A03 | DC TARGET | A | 746 | $1317 | 62.7% |
| SHF-A03 | END | B | 1 | $-1 | 0.0% |
| SHF-A03 | TIME MAX | B | 5 | $-575 | 0.0% |
| SHF-A03 | BB TARGET | A | 350 | $-829 | 52.6% |
| SHF-A03 | FIXED STOP | B | 6 | $-1245 | 0.0% |

## Key Finding

- Average ΔPF: +0.006
- Best config: SHF-A01 PF=0.955 (was 0.942)
- Improved: 9/12 configs
- PF ≥ 1.0: 0/12 configs

# SuperHF Sprint 2 — Exit Priority Reorder

**Date**: 2026-02-23 05:06
**Change**: STOP/TM → DC TARGET → BB TARGET → RSI RECOVERY (was: STOP/TM → RSI → DC → BB)
**Universe**: superhf_mexc_top200 (163 coins)

## Results vs Sprint 1 Baseline

| Config | Metric | Sprint 1 | Sprint 2 | Delta |
|--------|--------|:--------:|:--------:|:-----:|
| **SHF-A01** | PF | 0.942 | 0.942 | +0.000 |
| | P&L | $-1038 | $-1038 | $-0 |
| | Trades | 1071 | 1071 | +0 |
| | WR | 55.7% | 55.7% | +0.0pp |
| | DD | 83.0% | 83.0% | -0.0pp |
| | WF | 1/3 | 1/3 | |
| **SHF-A03** | PF | 0.849 | 0.849 | -0.000 |
| | P&L | $-1468 | $-1468 | $+0 |
| | Trades | 1296 | 1296 | +0 |
| | WR | 56.0% | 56.0% | +0.0pp |
| | DD | 80.3% | 80.3% | +0.0pp |
| | WF | 1/3 | 1/3 | |
| **SHF-A06** | PF | 0.882 | 0.882 | +0.000 |
| | P&L | $-1183 | $-1183 | $-0 |
| | Trades | 974 | 974 | +0 |
| | WR | 58.4% | 58.4% | +0.0pp |
| | DD | 78.1% | 78.1% | -0.0pp |
| | WF | 0/3 | 0/3 | |

## Exit Class Breakdown (Sprint 2)

| Config | Exit Reason | Class | Trades | P&L | WR |
|--------|------------|:-----:|-------:|----:|---:|
| SHF-A01 | DC TARGET | A | 585 | $8083 | 69.4% |
| SHF-A01 | BB TARGET | A | 225 | $1892 | 64.9% |
| SHF-A01 | TIME MAX | B | 1 | $-634 | 0.0% |
| SHF-A01 | FIXED STOP | B | 8 | $-2887 | 0.0% |
| SHF-A01 | RSI RECOVERY | A | 252 | $-7492 | 17.9% |
| SHF-A03 | DC TARGET | A | 741 | $4017 | 70.2% |
| SHF-A03 | BB TARGET | A | 275 | $306 | 59.6% |
| SHF-A03 | END | B | 1 | $-1 | 0.0% |
| SHF-A03 | TIME MAX | B | 1 | $-267 | 0.0% |
| SHF-A03 | FIXED STOP | B | 7 | $-1431 | 0.0% |
| SHF-A03 | RSI RECOVERY | A | 271 | $-4092 | 15.5% |
| SHF-A06 | DC TARGET | A | 579 | $4906 | 72.9% |
| SHF-A06 | BB TARGET | A | 173 | $236 | 64.7% |
| SHF-A06 | END | B | 1 | $-10 | 0.0% |
| SHF-A06 | TIME MAX | B | 1 | $-127 | 0.0% |
| SHF-A06 | FIXED STOP | B | 6 | $-1330 | 0.0% |
| SHF-A06 | RSI RECOVERY | A | 214 | $-4859 | 16.4% |

## Gate Status

| Config | S1 trades | S2 PF≥1.10 | S3 WF≥2/3 | S4 conc | Overall |
|--------|:---------:|:----------:|:---------:|:-------:|:-------:|
| SHF-A01 | ✅ 1071 | ❌ 0.942 | ❌ 1/3 | ✅ | ❌ |
| SHF-A03 | ✅ 1296 | ❌ 0.849 | ❌ 1/3 | ✅ | ❌ |
| SHF-A06 | ✅ 974 | ❌ 0.882 | ❌ 0/3 | ✅ | ❌ |

## Conclusion

**Exit priority reorder did not improve results.**

## Next Steps

- If PF improved but < 1.0: test RSI strict variant (rsi_rec_target≥55 or rsi_rec_min_bars=20)
- If PF ≥ 1.0: proceed to Sprint 3 execution validation
- If no improvement: reconsider signal families

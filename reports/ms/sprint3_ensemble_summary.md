# MS Sprint 3 — Ensemble Analysis Summary

- **Timestamp**: 2026-03-02T22:43:00.468549+00:00
- **Ensembles tested**: 3

## Scoreboard

| # | Ensemble | Mode | Trades | PF | P&L | DD | A/B Split | Overlap | Verdict |
|---|----------|------|--------|-----|------|-----|-----------|---------|---------|
| 1 | ens_ms_018_mse_shallow+ms_005_msb_base | priority | 454 | 1.89 | $+17,380.89 | 24.2% | 2505/2827 | 4.1% | VERIFIED |
| 2 | ens_ms_018_mse_shallow+ms_007_msb_deep | priority | 417 | 1.55 | $+12,360.12 | 24.5% | 2371/1646 | 1.9% | VERIFIED |
| 3 | ens_ms_017_mse_fib618+ms_005_msb_base | priority | 445 | 1.66 | $+10,619.57 | 21.9% | 1573/2770 | 4.0% | VERIFIED |

### ens_ms_018_mse_shallow+ms_005_msb_base (priority)

- **Components**: ms_018_mse_shallow (A) + ms_005_msb_base (B)
- **Full run**: 454tr PF=1.89 P&L=$+17,380.89 DD=24.2%

- **Source A** (ms_018_mse_shallow): 2505 entries
- **Source B** (ms_005_msb_base): 2827 entries
- **Both fired**: 224 times

- **Signal overlap**: 4.1% (A-only=4377, B-only=6030, both=441)
- **Signal rate**: 34.2 per 1000 bars

- **vs ms_018_mse_shallow**: PF 2.08→1.89, DD 21.3%→24.2%, trades 697→454
- **vs ms_005_msb_base**: PF 1.65→1.89, DD 19.5%→24.2%, trades 429→454

- **Truth-pass**: **VERIFIED** (3/3)
  - Window: PASS
  - WF: PASS
  - Bootstrap: PASS (P5_PF=1.24, %prof=100%)

### ens_ms_018_mse_shallow+ms_007_msb_deep (priority)

- **Components**: ms_018_mse_shallow (A) + ms_007_msb_deep (B)
- **Full run**: 417tr PF=1.55 P&L=$+12,360.12 DD=24.5%

- **Source A** (ms_018_mse_shallow): 2371 entries
- **Source B** (ms_007_msb_deep): 1646 entries
- **Both fired**: 72 times

- **Signal overlap**: 1.9% (A-only=4659, B-only=3724, both=159)
- **Signal rate**: 26.9 per 1000 bars

- **vs ms_018_mse_shallow**: PF 2.08→1.55, DD 21.3%→24.5%, trades 697→417
- **vs ms_007_msb_deep**: PF 1.66→1.55, DD 22.9%→24.5%, trades 344→417

- **Truth-pass**: **VERIFIED** (3/3)
  - Window: PASS
  - WF: PASS
  - Bootstrap: PASS (P5_PF=1.18, %prof=99%)

### ens_ms_017_mse_fib618+ms_005_msb_base (priority)

- **Components**: ms_017_mse_fib618 (A) + ms_005_msb_base (B)
- **Full run**: 445tr PF=1.66 P&L=$+10,619.57 DD=21.9%

- **Source A** (ms_017_mse_fib618): 1573 entries
- **Source B** (ms_005_msb_base): 2770 entries
- **Both fired**: 175 times

- **Signal overlap**: 4.0% (A-only=3004, B-only=6094, both=377)
- **Signal rate**: 29.9 per 1000 bars

- **vs ms_017_mse_fib618**: PF 1.80→1.66, DD 28.0%→21.9%, trades 475→445
- **vs ms_005_msb_base**: PF 1.65→1.66, DD 19.5%→21.9%, trades 429→445

- **Truth-pass**: **VERIFIED** (3/3)
  - Window: PASS
  - WF: PASS
  - Bootstrap: PASS (P5_PF=1.17, %prof=99%)


# MS Sprint 1 — Scoreboard

**Date**: 2026-03-02 22:05 UTC
**Configs**: 18
**Dataset**: 4H Kraken (4h_default)

**GO**: 7/18
**PF >= 1.0**: 7/18

| # | Config | Family | Trades | PF | P&L | DD% | Verdict | Exits |
|---|--------|--------|--------|----|-----|-----|---------|-------|
| 18 | ms_018_mse_shallow | shift_pb | 697 | 2.08 | $46,017 | 21.3 | GO | RSI RECOVERY:383(55%) DC TARGET:143(21%) BB TARGET:126(18%) FIXED STOP:22(3%) TIME MAX:20(3%) END:3(0%) |
| 17 | ms_017_mse_fib618 | shift_pb | 475 | 1.80 | $27,498 | 28.0 | GO | RSI RECOVERY:306(64%) DC TARGET:62(13%) BB TARGET:49(10%) TIME MAX:32(7%) FIXED STOP:23(5%) END:3(1%) |
| 16 | ms_016_mse_base | shift_pb | 568 | 1.68 | $11,976 | 35.2 | GO | RSI RECOVERY:379(67%) BB TARGET:71(12%) DC TARGET:70(12%) TIME MAX:25(4%) FIXED STOP:20(4%) END:3(1%) |
| 7 | ms_007_msb_deep | fvg_fill | 344 | 1.66 | $9,338 | 22.9 | GO | RSI RECOVERY:209(61%) DC TARGET:51(15%) TIME MAX:38(11%) FIXED STOP:23(7%) BB TARGET:21(6%) END:2(1%) |
| 5 | ms_005_msb_base | fvg_fill | 429 | 1.65 | $18,756 | 19.5 | GO | RSI RECOVERY:254(59%) DC TARGET:80(19%) TIME MAX:37(9%) BB TARGET:33(8%) FIXED STOP:23(5%) END:2(0%) |
| 8 | ms_008_msb_wide | fvg_fill | 295 | 1.60 | $3,728 | 37.5 | GO | RSI RECOVERY:172(58%) DC TARGET:44(15%) TIME MAX:42(14%) FIXED STOP:23(8%) BB TARGET:12(4%) END:2(1%) |
| 6 | ms_006_msb_norsi | fvg_fill | 548 | 1.46 | $3,930 | 29.8 | GO | RSI RECOVERY:236(43%) DC TARGET:179(33%) BB TARGET:74(14%) FIXED STOP:29(5%) TIME MAX:27(5%) END:3(1%) |
| 2 | ms_002_msa_wide | liq_sweep | 492 | 0.76 | $-1,603 | 81.5 | NO-GO | DC TARGET:192(39%) RSI RECOVERY:187(38%) FIXED STOP:55(11%) BB TARGET:36(7%) TIME MAX:19(4%) END:3(1%) |
| 3 | ms_003_msa_vol | liq_sweep | 450 | 0.75 | $-1,682 | 86.3 | NO-GO | DC TARGET:182(40%) RSI RECOVERY:161(36%) FIXED STOP:46(10%) TIME MAX:32(7%) BB TARGET:27(6%) END:2(0%) |
| 11 | ms_011_msc_vol | ob_touch | 650 | 0.72 | $-1,801 | 93.7 | NO-GO | DC TARGET:218(34%) RSI RECOVERY:193(30%) BB TARGET:153(24%) FIXED STOP:56(9%) TIME MAX:28(4%) END:2(0%) |
| 10 | ms_010_msc_strict | ob_touch | 680 | 0.70 | $-1,495 | 85.2 | NO-GO | DC TARGET:237(35%) RSI RECOVERY:215(32%) BB TARGET:149(22%) FIXED STOP:44(6%) TIME MAX:32(5%) END:3(0%) |
| 12 | ms_012_msc_tight | ob_touch | 736 | 0.65 | $-1,763 | 91.8 | NO-GO | DC TARGET:269(37%) RSI RECOVERY:214(29%) BB TARGET:169(23%) FIXED STOP:51(7%) TIME MAX:30(4%) END:3(0%) |
| 14 | ms_014_msd_strict | sfp | 525 | 0.63 | $-1,603 | 82.7 | NO-GO | DC TARGET:216(41%) RSI RECOVERY:200(38%) FIXED STOP:43(8%) BB TARGET:35(7%) TIME MAX:29(6%) END:2(0%) |
| 9 | ms_009_msc_base | ob_touch | 672 | 0.62 | $-1,730 | 91.4 | NO-GO | DC TARGET:231(34%) RSI RECOVERY:208(31%) BB TARGET:149(22%) FIXED STOP:47(7%) TIME MAX:34(5%) END:3(0%) |
| 4 | ms_004_msa_relax | liq_sweep | 501 | 0.59 | $-1,789 | 90.2 | NO-GO | DC TARGET:206(41%) RSI RECOVERY:177(35%) FIXED STOP:51(10%) BB TARGET:36(7%) TIME MAX:28(6%) END:3(1%) |
| 13 | ms_013_msd_base | sfp | 519 | 0.59 | $-1,660 | 84.3 | NO-GO | DC TARGET:209(40%) RSI RECOVERY:201(39%) FIXED STOP:45(9%) BB TARGET:35(7%) TIME MAX:27(5%) END:2(0%) |
| 1 | ms_001_msa_base | liq_sweep | 504 | 0.58 | $-1,827 | 91.6 | NO-GO | RSI RECOVERY:207(41%) DC TARGET:182(36%) FIXED STOP:63(12%) BB TARGET:33(7%) TIME MAX:16(3%) END:3(1%) |
| 15 | ms_015_msd_relax | sfp | 521 | 0.54 | $-1,742 | 87.8 | NO-GO | DC TARGET:209(40%) RSI RECOVERY:198(38%) FIXED STOP:47(9%) BB TARGET:37(7%) TIME MAX:27(5%) END:3(1%) |

## Family Summary

- **fvg_fill** (4 configs): best PF=1.66, avg PF=1.59, 4 GO
- **liq_sweep** (4 configs): best PF=0.76, avg PF=0.67, 0 GO
- **ob_touch** (4 configs): best PF=0.72, avg PF=0.67, 0 GO
- **sfp** (3 configs): best PF=0.63, avg PF=0.59, 0 GO
- **shift_pb** (3 configs): best PF=2.08, avg PF=1.85, 3 GO

## DC-Geometry Compliance

| Config | Avg Score | Full Compliance % |
|--------|-----------|-------------------|
| ms_018_mse_shallow | 0.59 | 6% |
| ms_017_mse_fib618 | 0.70 | 14% |
| ms_016_mse_base | 0.66 | 9% |
| ms_007_msb_deep | 0.87 | 64% |
| ms_005_msb_base | 0.78 | 44% |
| ms_008_msb_wide | 0.99 | 98% |
| ms_006_msb_norsi | 0.51 | 23% |
| ms_002_msa_wide | 0.67 | 41% |
| ms_003_msa_vol | 0.62 | 38% |
| ms_011_msc_vol | 0.45 | 24% |
| ms_010_msc_strict | 0.44 | 21% |
| ms_012_msc_tight | 0.43 | 20% |
| ms_014_msd_strict | 0.61 | 36% |
| ms_009_msc_base | 0.44 | 21% |
| ms_004_msa_relax | 0.71 | 43% |
| ms_013_msd_base | 0.71 | 43% |
| ms_001_msa_base | 0.68 | 40% |
| ms_015_msd_relax | 0.71 | 44% |
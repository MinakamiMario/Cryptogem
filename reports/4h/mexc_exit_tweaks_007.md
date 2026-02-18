# MEXC Exit Tweaks Sweep -- Config 041 (Vol Cap 3.5x RSI35)

**Date**: 2026-02-18
**Git**: `9a606d9`
**Universe**: Top 200 by volume, >= 2160 bars (200 coins)
**Full range**: ~467 days, 2853 bars
**Fee**: MEXC 10bps
**Sizing**: Fixed $2,000/trade (no compounding)
**Baseline**: PF=1.36, P&L=$+8,697, 330 trades, DD=52.6%, WR=53.9%

---

## Stopout Anatomy

### P&L Attribution by Exit Reason

| Exit Reason | Class | Count | P&L | WR | Avg P&L |
|-------------|-------|------:|----:|---:|--------:|
| RSI RECOVERY | A | 106 | $+17,041 | 80% | $+161 |
| DC TARGET | A | 95 | $+14,487 | 92% | $+152 |
| BB TARGET | A | 6 | $+323 | 83% | $+54 |
| END | B | 0 | $+0 | -- | $+0 |
| TIME MAX | B | 71 | $-7,362 | -- | $-104 |
| FIXED STOP | B | 52 | $-15,792 | -- | $-304 |

### FIXED STOP Deep Dive

- **Count**: 52 (15.8% of trades)
- **Total loss**: $-15,792
- **Avg loss**: $-304
- **Median bars to stop**: 7.0
- **Avg MFE (went up before crashing)**: 4.86%
- **MFE quartiles**: P25=0.79%, P50=2.45%, P75=5.74%
- **Bars to stop quartiles**: P25=3, P50=7, P75=10
- **Avg RSI at exit**: 16.6
- **Saveable (MFE > 0.5%)**: 43/52 (82.7%)
- **Saveable lost P&L**: $-13,059

---

## Full Leaderboard (sorted by PF)

| # | Label | Description | PF | P&L | Trades | DD | WR |
|--:|-------|-------------|---:|----:|-------:|---:|---:|
| 1 | D_rsimin_5 | rsi_rec_min_bars=5 | 1.39 | $+9,281 | 328 | 52.6% | 54.3% |
| 2 | D_rsimin_4 | rsi_rec_min_bars=4 | 1.38 | $+9,102 | 329 | 52.6% | 54.4% |
| 3 | D_rsimin_3 | rsi_rec_min_bars=3 | 1.37 | $+8,987 | 330 | 52.6% | 54.2% |
| 4 | BASELINE **[B]** | Baseline (msp=15, tmb=15, rrt=45, rmb=2) | 1.36 | $+8,697 | 330 | 52.6% | 53.9% |
| 5 | C_rsitarget_42 | rsi_rec_target=42 | 1.36 | $+8,674 | 336 | 50.4% | 55.6% |
| 6 | D_rsimin_1 | rsi_rec_min_bars=1 | 1.36 | $+8,585 | 330 | 52.6% | 53.9% |
| 7 | C_rsitarget_40 | rsi_rec_target=40 | 1.36 | $+8,480 | 336 | 50.4% | 55.1% |
| 8 | C_rsitarget_50 | rsi_rec_target=50 | 1.35 | $+8,580 | 325 | 53.7% | 54.8% |
| 9 | C_rsitarget_48 | rsi_rec_target=48 | 1.34 | $+8,218 | 326 | 52.5% | 53.4% |
| 10 | B_timemax_25 | time_max_bars=25 | 1.31 | $+7,404 | 318 | 77.3% | 53.5% |
| 11 | B_timemax_10 | time_max_bars=10 | 1.31 | $+7,767 | 356 | 72.2% | 51.7% |
| 12 | B_timemax_20 | time_max_bars=20 | 1.31 | $+7,373 | 321 | 62.0% | 53.6% |
| 13 | C_rsitarget_35 | rsi_rec_target=35 | 1.27 | $+6,538 | 371 | 48.5% | 59.3% |
| 14 | B_timemax_30 | time_max_bars=30 | 1.27 | $+6,499 | 316 | 70.1% | 52.5% |
| 15 | E6_stop7_tm25_rsi40 | Tight stop (7%) + wider TM (25) + RSI target (40) | 1.25 | $+6,644 | 417 | 73.5% | 48.7% |
| 16 | E1_combined_best | Combined best: msp=7, tmb=25, rrt=42, rmb=5 | 1.21 | $+5,695 | 408 | 73.5% | 47.3% |
| 17 | E5_stop7_tm20 | Tight stop (7%) + wider TM (20 bars) | 1.19 | $+5,043 | 408 | 73.4% | 45.8% |
| 18 | A_maxstop_7 | max_stop_pct=7 | 1.16 | $+4,535 | 414 | 73.4% | 45.6% |
| 19 | A_maxstop_12 | max_stop_pct=12 | 1.16 | $+4,164 | 346 | 78.4% | 51.7% |
| 20 | E3_tight_stop_low_rsi | Tighter stop (10%) + lower RSI target (40) | 1.13 | $+3,499 | 375 | 86.6% | 50.9% |
| 21 | E4_all_three | All three: msp=10, tmb=25, rrt=40 | 1.13 | $+3,284 | 370 | 96.9% | 51.6% |
| 22 | A_maxstop_10 | max_stop_pct=10 | 1.12 | $+3,085 | 364 | 89.2% | 49.2% |
| 23 | E2_tight_stop_wide_tm | Tighter stop (10%) + wider TM (25 bars) | 1.12 | $+2,999 | 359 | 100.4% | 50.4% |
| 24 | A_maxstop_5 | max_stop_pct=5 | 1.10 | $+2,538 | 443 | 89.6% | 38.8% |

### A. max_stop_pct Sweep

| Value | PF | P&L | Trades | DD | WR |
|------:|---:|----:|-------:|---:|---:|
| **baseline** | 1.36 | $+8,697 | 330 | 52.6% | 53.9% |
| 5 | 1.10 | $+2,538 | 443 | 89.6% | 38.8% |
| 7 | 1.16 | $+4,535 | 414 | 73.4% | 45.6% |
| 10 | 1.12 | $+3,085 | 364 | 89.2% | 49.2% |
| 12 | 1.16 | $+4,164 | 346 | 78.4% | 51.7% |

### B. time_max_bars Sweep

| Value | PF | P&L | Trades | DD | WR |
|------:|---:|----:|-------:|---:|---:|
| **baseline** | 1.36 | $+8,697 | 330 | 52.6% | 53.9% |
| 10 | 1.31 | $+7,767 | 356 | 72.2% | 51.7% |
| 20 | 1.31 | $+7,373 | 321 | 62.0% | 53.6% |
| 25 | 1.31 | $+7,404 | 318 | 77.3% | 53.5% |
| 30 | 1.27 | $+6,499 | 316 | 70.1% | 52.5% |

### C. rsi_rec_target Sweep

| Value | PF | P&L | Trades | DD | WR |
|------:|---:|----:|-------:|---:|---:|
| **baseline** | 1.36 | $+8,697 | 330 | 52.6% | 53.9% |
| 35 | 1.27 | $+6,538 | 371 | 48.5% | 59.3% |
| 40 | 1.36 | $+8,480 | 336 | 50.4% | 55.1% |
| 42 | 1.36 | $+8,674 | 336 | 50.4% | 55.6% |
| 48 | 1.34 | $+8,218 | 326 | 52.5% | 53.4% |
| 50 | 1.35 | $+8,580 | 325 | 53.7% | 54.8% |

### D. rsi_rec_min_bars Sweep

| Value | PF | P&L | Trades | DD | WR |
|------:|---:|----:|-------:|---:|---:|
| **baseline** | 1.36 | $+8,697 | 330 | 52.6% | 53.9% |
| 1 | 1.36 | $+8,585 | 330 | 52.6% | 53.9% |
| 3 | 1.37 | $+8,987 | 330 | 52.6% | 54.2% |
| 4 | 1.38 | $+9,102 | 329 | 52.6% | 54.4% |
| 5 | 1.39 | $+9,281 | 328 | 52.6% | 54.3% |

### Combined Tweaks

| Label | Description | PF | P&L | Trades | DD | WR |
|-------|-------------|---:|----:|-------:|---:|---:|
| BASELINE | baseline | 1.36 | $+8,697 | 330 | 52.6% | 53.9% |
| E1_combined_best | Combined best: msp=7, tmb=25, rrt=42, rmb=5 | 1.21 | $+5,695 | 408 | 73.5% | 47.3% |
| E2_tight_stop_wide_tm | Tighter stop (10%) + wider TM (25 bars) | 1.12 | $+2,999 | 359 | 100.4% | 50.4% |
| E3_tight_stop_low_rsi | Tighter stop (10%) + lower RSI target (40) | 1.13 | $+3,499 | 375 | 86.6% | 50.9% |
| E4_all_three | All three: msp=10, tmb=25, rrt=40 | 1.13 | $+3,284 | 370 | 96.9% | 51.6% |
| E5_stop7_tm20 | Tight stop (7%) + wider TM (20 bars) | 1.19 | $+5,043 | 408 | 73.4% | 45.8% |
| E6_stop7_tm25_rsi40 | Tight stop (7%) + wider TM (25) + RSI target (40) | 1.25 | $+6,644 | 417 | 73.5% | 48.7% |

---

## Top-3 Exit Tweaks (PF >= 1.15)

| # | Label | Description | PF | P&L | Trades | DD | WR |
|--:|-------|-------------|---:|----:|-------:|---:|---:|
| 1 | D_rsimin_5 | rsi_rec_min_bars=5 | 1.39 | $+9,281 | 328 | 52.6% | 54.3% |
| 2 | D_rsimin_4 | rsi_rec_min_bars=4 | 1.38 | $+9,102 | 329 | 52.6% | 54.4% |
| 3 | D_rsimin_3 | rsi_rec_min_bars=3 | 1.37 | $+8,987 | 330 | 52.6% | 54.2% |

### Exit Attribution: Baseline vs Top-1

| Exit Reason | Baseline Count | Baseline P&L | Top-1 Count | Top-1 P&L |
|-------------|---------------:|---------:|------------:|------:|
| BB TARGET | 6 | $+323 | 6 | $+427 |
| DC TARGET | 95 | $+14,487 | 106 | $+17,327 |
| FIXED STOP | 52 | $-15,792 | 53 | $-16,096 |
| RSI RECOVERY | 106 | $+17,041 | 93 | $+14,744 |
| TIME MAX | 71 | $-7,362 | 70 | $-7,121 |

## Deploy Recommendation

**INVESTIGATE**: `D_rsimin_5` beats baseline on PF (1.39 vs 1.36) but DD is worse (52.6% vs 52.6%).

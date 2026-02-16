# Part 2 -- Drawdown Duration Analysis (Agent C5-A4)

**Date**: 2026-02-16 00:57
**Commit**: d689875
**Data**: 722 bars (4.3 weeks) of 1H candles
**Fees**: T1=12.5bps, T2=23.5bps (MEXC market)
**Runtime**: 28.0s

## Question

How long do drawdown periods last? What is the max time underwater?
How does this compare across the three production configs?

## 1. Cross-Config Comparison

### 1a. Basic Metrics

| Metric | v5 sl=5 (295) | sl=7 (295) | v5 sl=5 (304) |
|--------|---------------|------------|---------------|
| Trades | 56 | 55 | **58** |
| P&L | **$3272** | $3196 | $2403 |
| PF | **2.834** | 2.715 | 2.518 |
| WR% | **64.3%** | 63.6% | 58.6% |
| Trades/wk | 13.03 | 12.80 | **13.50** |
| Exp/wk | **$761.38** | $743.58 | $559.17 |
| Max DD% | **8.6%** | 9.8% | 11.8% |

### 1b. Drawdown Duration Comparison

| Metric | v5 sl=5 (295) | sl=7 (295) | v5 sl=5 (304) |
|--------|---------------|------------|---------------|
| DD episodes | 8 | 9 | **7** |
| Max DD duration (trades) | 17 | **8** | 25 |
| Max DD duration (days) | 8.62 | **3.75** | 11.71 |
| Avg DD duration (trades) | 3.88 | **3.11** | 5.29 |
| Avg DD duration (days) | 2.24 | **1.91** | 2.72 |
| Recovered episodes | 7 | **8** | 7 |
| Unrecovered episodes | 1 | 1 | **0** |
| Recovery from max DD (trades) | **2** | 4 | 3 |
| Recovery from max DD (days) | 2.08 | 3.42 | **1.08** |
| Deepest DD% | **8.63%** | 9.82% | 11.83% |
| Longest episode DD% | 8.60% | **6.49%** | 11.83% |

### 1c. Consecutive Loss Comparison

| Metric | v5 sl=5 (295) | sl=7 (295) | v5 sl=5 (304) |
|--------|---------------|------------|---------------|
| Max consec losses | **4** | 5 | 5 |
| Avg consec losses | **1.54** | 1.67 | 1.71 |
| Losing streaks count | 13 | **12** | 14 |
| Longest streak P&L | $-231 | **$-171** | $-267 |

### 1d. Inter-Trade Gap Comparison

| Metric | v5 sl=5 (295) | sl=7 (295) | v5 sl=5 (304) |
|--------|---------------|------------|---------------|
| Max gap (days) | **1.50d** | 1.50d | 1.50d |
| Avg gap (days) | 0.49d | 0.50d | **0.48d** |
| Median gap (days) | **0.46d** | 0.50d | 0.46d |
| Max gap (bars/hours) | **36h** | 36h | 36h |
| Avg gap (bars/hours) | 11.9h | 12.1h | **11.6h** |

**Gap Distribution (entry-to-entry):**

| Bucket | v5 sl=5 (295) | sl=7 (295) | v5 sl=5 (304) |
|--------|---------------|------------|---------------|
| 0-6h | 15 | 14 | 16 |
| 6-12h | 18 | 18 | 17 |
| 12-24h | 16 | 16 | 20 |
| 24-48h | 6 | 6 | 4 |
| 48h+ | 0 | 0 | 0 |

## 2. Detail: v5 (sl=5) on 295 coins -- LEADER

**Params**: {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10}
**Universe**: 295 coins
**Trades**: 56 | PF=2.834 | WR=64.3% | P&L=$3272

### Drawdown Episodes (8 total)

| # | Start Bar | End Bar | Duration (trades) | Duration (days) | Max DD% | Recovered |
|---|-----------|---------|-------------------|-----------------|---------|-----------|
| 1 | 139 | 167 | 1 | 1.17 | 4.50% | YES |
| 2 | 173 | 197 | 1 | 1.00 | 1.23% | YES |
| 3 | 219 | 426 | 17 | 8.62 | 8.60% | YES |
| 4 | 426 | 497 | 3 | 2.96 | 8.63% | YES |
| 5 | 520 | 572 | 3 | 2.17 | 4.68% | YES |
| 6 | 622 | 634 | 1 | 0.50 | 2.19% | YES |
| 7 | 660 | 691 | 3 | 1.29 | 4.71% | YES |
| 8 | 715 | 720 | 2 | 0.21 | 4.59% | NO |

### Consecutive Loss Streaks

- Max consecutive losses: **4**
- Avg consecutive losses: 1.54
- Number of losing streaks: 13
- Longest streak P&L impact: $-231

**Streak length distribution:**

| Streak Length | Count |
|--------------|-------|
| 1 | 8 |
| 2 | 4 |
| 4 | 1 |

**All losing streaks:**

| # | Length | P&L | Start Bar | End Bar |
|---|--------|-----|-----------|---------|
| 1 | 4 | $-231 | 225 | 250 |
| 2 | 2 | $-208 | 311 | 331 |
| 3 | 2 | $-55 | 386 | 421 |
| 4 | 2 | $-285 | 435 | 447 |
| 5 | 2 | $-185 | 538 | 561 |
| 6 | 1 | $-113 | 160 | 161 |
| 7 | 1 | $-36 | 175 | 185 |
| 8 | 1 | $-11 | 257 | 267 |
| 9 | 1 | $-53 | 281 | 291 |
| 10 | 1 | $-53 | 334 | 344 |
| 11 | 1 | $-96 | 616 | 626 |
| 12 | 1 | $-215 | 653 | 654 |
| 13 | 1 | $-243 | 718 | 720 |

### Top 5 Largest Inter-Trade Gaps

| # | From | To | Gap (h) | Gap (d) |
|---|------|----|---------|---------|
| 1 | AUDIO/USD | ARPA/USD | 36h | 1.50d |
| 2 | KOBAN/USD | BILLY/USD | 33h | 1.38d |
| 3 | ALPHA/USD | NOBODY/USD | 28h | 1.17d |
| 4 | CVC/USD | SAROS/USD | 28h | 1.17d |
| 5 | TOKEN/USD | ELX/USD | 26h | 1.08d |

**Largest gap**: 36h (1.50d) between AUDIO/USD and ARPA/USD, bars 350-386 (approx fold 2)

## 2. Detail: sl=7 on 295 coins -- Robustness Alt

**Params**: {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 7, 'time_limit': 10}
**Universe**: 295 coins
**Trades**: 55 | PF=2.715 | WR=63.6% | P&L=$3196

### Drawdown Episodes (9 total)

| # | Start Bar | End Bar | Duration (trades) | Duration (days) | Max DD% | Recovered |
|---|-----------|---------|-------------------|-----------------|---------|-----------|
| 1 | 139 | 166 | 1 | 1.12 | 6.21% | YES |
| 2 | 172 | 197 | 1 | 1.04 | 1.25% | YES |
| 3 | 219 | 309 | 8 | 3.75 | 6.49% | YES |
| 4 | 309 | 426 | 7 | 4.88 | 9.82% | YES |
| 5 | 426 | 480 | 2 | 2.25 | 5.87% | YES |
| 6 | 520 | 572 | 3 | 2.17 | 4.70% | YES |
| 7 | 622 | 634 | 1 | 0.50 | 2.21% | YES |
| 8 | 660 | 691 | 3 | 1.29 | 6.49% | YES |
| 9 | 715 | 720 | 2 | 0.21 | 5.58% | NO |

### Consecutive Loss Streaks

- Max consecutive losses: **5**
- Avg consecutive losses: 1.67
- Number of losing streaks: 12
- Longest streak P&L impact: $-171

**Streak length distribution:**

| Streak Length | Count |
|--------------|-------|
| 1 | 7 |
| 2 | 4 |
| 5 | 1 |

**All losing streaks:**

| # | Length | P&L | Start Bar | End Bar |
|---|--------|-----|-----------|---------|
| 1 | 5 | $-171 | 225 | 267 |
| 2 | 2 | $-270 | 311 | 331 |
| 3 | 2 | $-53 | 386 | 421 |
| 4 | 2 | $-191 | 435 | 447 |
| 5 | 2 | $-189 | 538 | 561 |
| 6 | 1 | $-156 | 160 | 166 |
| 7 | 1 | $-36 | 175 | 185 |
| 8 | 1 | $-53 | 281 | 291 |
| 9 | 1 | $-52 | 334 | 344 |
| 10 | 1 | $-98 | 616 | 626 |
| 11 | 1 | $-300 | 653 | 655 |
| 12 | 1 | $-294 | 718 | 721 |

### Top 5 Largest Inter-Trade Gaps

| # | From | To | Gap (h) | Gap (d) |
|---|------|----|---------|---------|
| 1 | AUDIO/USD | ARPA/USD | 36h | 1.50d |
| 2 | KOBAN/USD | BILLY/USD | 33h | 1.38d |
| 3 | ALPHA/USD | NOBODY/USD | 28h | 1.17d |
| 4 | CVC/USD | SAROS/USD | 28h | 1.17d |
| 5 | TOKEN/USD | ELX/USD | 26h | 1.08d |

**Largest gap**: 36h (1.50d) between AUDIO/USD and ARPA/USD, bars 350-386 (approx fold 2)

## 2. Detail: v5 (sl=5) on 304 coins -- Conservative Alt

**Params**: {'dev_thresh': 2.0, 'tp_pct': 8, 'sl_pct': 5, 'time_limit': 10}
**Universe**: 304 coins
**Trades**: 58 | PF=2.518 | WR=58.6% | P&L=$2403

### Drawdown Episodes (7 total)

| # | Start Bar | End Bar | Duration (trades) | Duration (days) | Max DD% | Recovered |
|---|-----------|---------|-------------------|-----------------|---------|-----------|
| 1 | 139 | 167 | 1 | 1.17 | 4.79% | YES |
| 2 | 173 | 197 | 1 | 1.00 | 1.23% | YES |
| 3 | 219 | 500 | 25 | 11.71 | 11.83% | YES |
| 4 | 520 | 572 | 3 | 2.17 | 4.81% | YES |
| 5 | 622 | 634 | 1 | 0.50 | 0.70% | YES |
| 6 | 660 | 693 | 4 | 1.38 | 4.81% | YES |
| 7 | 693 | 720 | 2 | 1.12 | 0.47% | YES |

### Consecutive Loss Streaks

- Max consecutive losses: **5**
- Avg consecutive losses: 1.71
- Number of losing streaks: 14
- Longest streak P&L impact: $-267

**Streak length distribution:**

| Streak Length | Count |
|--------------|-------|
| 1 | 9 |
| 2 | 2 |
| 3 | 2 |
| 5 | 1 |

**All losing streaks:**

| # | Length | P&L | Start Bar | End Bar |
|---|--------|-----|-----------|---------|
| 1 | 5 | $-267 | 225 | 250 |
| 2 | 3 | $-202 | 386 | 421 |
| 3 | 3 | $-252 | 430 | 474 |
| 4 | 2 | $-192 | 311 | 331 |
| 5 | 2 | $-168 | 538 | 561 |
| 6 | 1 | $-113 | 160 | 161 |
| 7 | 1 | $-34 | 175 | 185 |
| 8 | 1 | $-10 | 257 | 267 |
| 9 | 1 | $-49 | 281 | 291 |
| 10 | 1 | $-49 | 334 | 344 |
| 11 | 1 | $-27 | 615 | 625 |
| 12 | 1 | $-199 | 653 | 654 |
| 13 | 1 | $-2 | 682 | 692 |
| 14 | 1 | $-20 | 700 | 710 |

### Top 5 Largest Inter-Trade Gaps

| # | From | To | Gap (h) | Gap (d) |
|---|------|----|---------|---------|
| 1 | AUDIO/USD | ARPA/USD | 36h | 1.50d |
| 2 | ALPHA/USD | NOBODY/USD | 28h | 1.17d |
| 3 | CVC/USD | SAROS/USD | 28h | 1.17d |
| 4 | TOKEN/USD | ELX/USD | 26h | 1.08d |
| 5 | XYO/USD | BLZ/USD | 23h | 0.96d |

**Largest gap**: 36h (1.50d) between AUDIO/USD and ARPA/USD, bars 350-386 (approx fold 2)

## 3. Key Insights

### Drawdown Duration

1. **Max time underwater**: v5(295)=8.6d, sl7(295)=3.8d, v5(304)=11.7d
2. **Average drawdown duration**: v5(295)=2.2d, sl7(295)=1.9d, v5(304)=2.7d
3. **DD episodes**: v5(295)=8, sl7(295)=9, v5(304)=7
4. **Recovered episodes**: v5(295)=7/8, sl7(295)=8/9, v5(304)=7/7

### Consecutive Losses

5. **Max consecutive losses**: v5(295)=4, sl7(295)=5, v5(304)=5
6. **Longest losing streak P&L**: v5(295)=$-231, sl7(295)=$-171, v5(304)=$-267

### Inter-Trade Gaps

7. **Max gap**: v5(295)=1.50d, sl7(295)=1.50d, v5(304)=1.50d
8. **Avg gap**: v5(295)=0.49d, sl7(295)=0.50d, v5(304)=0.48d

### Overall Assessment

- **Best max DD duration**: sl7(295) at 3.8 days
- **Worst max DD duration**: v5(304) at 11.7 days
- **Total observation period**: 30.1 days
- **Leader max underwater**: 8.6d = 29% of observation period

---
*Generated by run_part2_dd_duration.py at 2026-02-16 00:57*
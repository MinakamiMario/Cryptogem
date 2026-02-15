# Nested Holdout Validation Report

## Method

- **Outer split**: Last 20%% of bars = holdout test (true OOS). First 80%% = development set.
- **Inner loop**: 4-fold purged walk-forward on development set only (embargo=2 bars).
- **Selection**: Config with highest average inner-fold test P&L.
- **Validation**: All configs run on holdout to verify selection quality.
- **Grid**: 3x4x3 = 36 configs (tp_pct=[10, 12, 15], sl_pct=[8, 10, 12, 15], vol_spike_mult=[2.0, 2.5, 3.0])
- **Fixed params**: exit_type=tp_sl, max_pos=1, rsi_max=45, time_max_bars=15, vol_confirm=True
- **OOS Gates**: trades >= 5, P&L > $0, WR >= 40.0%

## Universe: TRADEABLE

- **Coins**: 425
- **Max bars**: 721 (median: 721)
- **MD5 verified**: True
- **Dev set**: bars [50, 586) = 536 bars
- **Holdout**: bars [586, 721) = 135 bars

### Inner Walk-Forward Folds

- Fold 1: train [50, 155) -> test [157, 264)
- Fold 2: train [50, 262) -> test [264, 371)
- Fold 3: train [50, 369) -> test [371, 478)
- Fold 4: train [50, 476) -> test [478, 586)

### Inner Grid Search Winner

- **Config**: `tp15_sl15_vs3.0`
- **Avg inner-fold P&L**: $425.15
- **Positive folds**: 4/4

| Fold | P&L | Trades | WR |
|------|-----|--------|-----|
| 1 | $265.47 | 4 | 75.0% |
| 2 | $51.48 | 3 | 66.7% |
| 3 | $229.11 | 3 | 66.7% |
| 4 | $1154.53 | 6 | 66.7% |

### Inner Rankings (top 10)

| # | Config | Avg P&L | Trades | PosFolds |
|---|--------|---------|--------|----------|
| 1 | tp15_sl15_vs3.0 | $425.15 | 16 | 4/4 |
| 2 | tp12_sl15_vs2.5 | $404.23 | 17 | 4/4 |
| 3 | tp12_sl15_vs3.0 | $385.39 | 16 | 4/4 |
| 4 | tp15_sl8_vs3.0 | $384.82 | 17 | 4/4 |
| 5 | tp12_sl15_vs2.0 | $366.88 | 20 | 4/4 |
| 6 | tp15_sl10_vs3.0 | $353.26 | 16 | 4/4 |
| 7 | tp12_sl8_vs3.0 | $351.77 | 17 | 4/4 |
| 8 | tp15_sl15_vs2.5 | $348.37 | 16 | 4/4 |
| 9 | tp12_sl10_vs2.5 | $346.77 | 17 | 4/4 |
| 10 | tp12_sl8_vs2.5 | $338.13 | 17 | 4/4 |

### Holdout Results (TRUE OOS)

| # | Config | OOS P&L | Tr | WR | DD | PF | Gates | Inner# |
|---|--------|---------|----|----|----|----|-------|--------|
| 1 | tp12_sl8_vs2.5 | $1107.35 | 9 | 77.8% | 11.4% | 3.87 | PASS | 10 |
| 2 | tp12_sl8_vs3.0 | $1107.35 | 9 | 77.8% | 11.4% | 3.87 | PASS | 7 |
| 3 | tp12_sl10_vs2.5 | $973.34 | 9 | 77.8% | 13.3% | 3.07 | PASS | 9 |
| 4 | tp12_sl10_vs3.0 | $973.34 | 9 | 77.8% | 13.3% | 3.07 | PASS | 13 |
| 5 | tp15_sl8_vs2.5 | $950.60 | 8 | 75.0% | 11.4% | 3.51 | PASS | 21 |
| 6 | tp15_sl8_vs3.0 | $950.60 | 8 | 75.0% | 11.4% | 3.51 | PASS | 4 |
| 7 | tp12_sl8_vs2.0 | $843.25 | 10 | 70.0% | 18.2% | 2.46 | PASS | 17 |
| 8 | tp10_sl8_vs2.5 | $839.03 | 9 | 77.8% | 11.4% | 3.22 | PASS | 28 |
| 9 | tp10_sl8_vs3.0 | $839.03 | 9 | 77.8% | 11.4% | 3.22 | PASS | 27 |
| 10 | tp15_sl10_vs2.5 | $823.35 | 8 | 75.0% | 13.3% | 2.78 | PASS | 20 |
| 11 | tp15_sl10_vs3.0 | $823.35 | 8 | 75.0% | 13.3% | 2.78 | PASS | 6 |
| 12 | tp10_sl10_vs2.5 | $716.60 | 9 | 77.8% | 13.3% | 2.55 | PASS | 29 |
| 13 | tp10_sl10_vs3.0 | $716.60 | 9 | 77.8% | 13.3% | 2.55 | PASS | 32 |
| 14 | tp15_sl8_vs2.0 | $699.82 | 9 | 66.7% | 18.2% | 2.24 | PASS | 24 |
| 15 | tp12_sl10_vs2.0 | $661.31 | 10 | 70.0% | 21.7% | 1.95 | PASS | 14 |
| 16 | tp12_sl15_vs2.0 | $651.24 | 9 | 77.8% | 18.1% | 1.97 | PASS | 5 |
| 17 | tp10_sl8_vs2.0 | $597.74 | 10 | 70.0% | 18.2% | 2.06 | PASS | 33 |
| 18 | tp12_sl12_vs2.5 | $550.30 | 8 | 75.0% | 15.5% | 2.00 | PASS | 12 |
| 19 | tp12_sl12_vs3.0 | $550.30 | 8 | 75.0% | 15.5% | 2.00 | PASS | 16 |
| 20 | tp15_sl12_vs2.5 | $531.16 | 7 | 71.4% | 15.5% | 1.98 | PASS | 22 |
| 21 | tp15_sl12_vs3.0 | $531.16 | 7 | 71.4% | 15.5% | 1.98 | PASS | 11 |
| 22 | tp15_sl10_vs2.0 | $527.07 | 9 | 66.7% | 21.7% | 1.78 | PASS | 23 |
| 23 | tp15_sl15_vs2.0 | $517.50 | 8 | 75.0% | 18.1% | 1.78 | PASS | 18 |
| 24 | tp10_sl10_vs2.0 | $431.52 | 10 | 70.0% | 21.7% | 1.64 | PASS | 35 |
| 25 | tp10_sl15_vs2.0 | $422.31 | 9 | 77.8% | 18.1% | 1.64 | PASS | 19 |
| 26 | tp12_sl15_vs2.5 | $378.88 | 8 | 75.0% | 18.4% | 1.56 | PASS | 2 |
| 27 | tp12_sl15_vs3.0 | $378.88 | 8 | 75.0% | 18.4% | 1.56 | PASS | 3 |
| 28 | tp10_sl12_vs2.5 | $372.56 | 8 | 75.0% | 15.5% | 1.69 | PASS | 31 |
| 29 | tp10_sl12_vs3.0 | $372.56 | 8 | 75.0% | 15.5% | 1.69 | PASS | 34 |
| 30 | tp15_sl15_vs2.5 | $361.03 | 7 | 71.4% | 18.4% | 1.55 | PASS | 8 |
| 31 | tp15_sl15_vs3.0 **SEL** | $361.03 | 7 | 71.4% | 18.4% | 1.55 | PASS | 1 |
| 32 | tp12_sl12_vs2.0 | $231.80 | 9 | 66.7% | 27.2% | 1.29 | PASS | 15 |
| 33 | tp15_sl12_vs2.0 | $215.05 | 8 | 62.5% | 27.2% | 1.27 | PASS | 25 |
| 34 | tp10_sl15_vs2.5 | $213.08 | 8 | 75.0% | 18.4% | 1.32 | PASS | 26 |
| 35 | tp10_sl15_vs3.0 | $213.08 | 8 | 75.0% | 18.4% | 1.32 | PASS | 30 |
| 36 | tp10_sl12_vs2.0 | $76.25 | 9 | 66.7% | 27.2% | 1.10 | PASS | 36 |

### Selection Analysis

- **Selected**: `tp15_sl15_vs3.0`
- **Sel OOS P&L**: $361.03 (trades=7)
- **Sel gates**: PASS
- **Best OOS**: `tp12_sl8_vs2.5` ($1107.35)
- **Optimal**: NO
- **Passing gates**: 36/36

### Timing

- Precompute: 30.3s
- Inner grid: 5.1s
- Holdout: 1.7s

## Universe: LIVE_CURRENT

- **Coins**: 518
- **Max bars**: 721 (median: 721)
- **MD5 verified**: True
- **Dev set**: bars [50, 586) = 536 bars
- **Holdout**: bars [586, 721) = 135 bars

### Inner Walk-Forward Folds

- Fold 1: train [50, 155) -> test [157, 264)
- Fold 2: train [50, 262) -> test [264, 371)
- Fold 3: train [50, 369) -> test [371, 478)
- Fold 4: train [50, 476) -> test [478, 586)

### Inner Grid Search Winner

- **Config**: `tp15_sl10_vs2.0`
- **Avg inner-fold P&L**: $286.15
- **Positive folds**: 4/4

| Fold | P&L | Trades | WR |
|------|-----|--------|-----|
| 1 | $557.18 | 6 | 83.3% |
| 2 | $214.44 | 3 | 66.7% |
| 3 | $46.03 | 5 | 40.0% |
| 4 | $326.97 | 5 | 40.0% |

### Inner Rankings (top 10)

| # | Config | Avg P&L | Trades | PosFolds |
|---|--------|---------|--------|----------|
| 1 | tp15_sl10_vs2.0 | $286.15 | 19 | 4/4 |
| 2 | tp15_sl12_vs2.0 | $286.15 | 19 | 4/4 |
| 3 | tp15_sl15_vs2.0 | $286.15 | 19 | 4/4 |
| 4 | tp15_sl10_vs2.5 | $250.16 | 17 | 4/4 |
| 5 | tp15_sl10_vs3.0 | $250.16 | 17 | 4/4 |
| 6 | tp15_sl12_vs2.5 | $250.16 | 17 | 4/4 |
| 7 | tp15_sl12_vs3.0 | $250.16 | 17 | 4/4 |
| 8 | tp15_sl15_vs2.5 | $250.16 | 17 | 4/4 |
| 9 | tp15_sl15_vs3.0 | $250.16 | 17 | 4/4 |
| 10 | tp10_sl15_vs2.0 | $244.57 | 19 | 3/4 |

### Holdout Results (TRUE OOS)

| # | Config | OOS P&L | Tr | WR | DD | PF | Gates | Inner# |
|---|--------|---------|----|----|----|----|-------|--------|
| 1 | tp12_sl12_vs2.5 | $1216.44 | 9 | 88.9% | 15.3% | 5.68 | PASS | 21 |
| 2 | tp12_sl12_vs3.0 | $1216.44 | 9 | 88.9% | 15.3% | 5.68 | PASS | 22 |
| 3 | tp12_sl15_vs2.5 | $1106.46 | 9 | 88.9% | 18.1% | 4.43 | PASS | 14 |
| 4 | tp12_sl15_vs3.0 | $1106.46 | 9 | 88.9% | 18.1% | 4.43 | PASS | 15 |
| 5 | tp15_sl12_vs2.5 | $1053.79 | 8 | 87.5% | 15.3% | 5.06 | PASS | 6 |
| 6 | tp15_sl12_vs3.0 | $1053.79 | 8 | 87.5% | 15.3% | 5.06 | PASS | 7 |
| 7 | tp15_sl15_vs2.5 | $949.37 | 8 | 87.5% | 18.1% | 3.95 | PASS | 8 |
| 8 | tp15_sl15_vs3.0 | $949.37 | 8 | 87.5% | 18.1% | 3.95 | PASS | 9 |
| 9 | tp10_sl12_vs2.5 | $938.71 | 9 | 88.9% | 15.3% | 4.61 | PASS | 34 |
| 10 | tp10_sl12_vs3.0 | $938.71 | 9 | 88.9% | 15.3% | 4.61 | PASS | 35 |
| 11 | tp10_sl15_vs2.5 | $838.23 | 9 | 88.9% | 18.1% | 3.60 | PASS | 25 |
| 12 | tp10_sl15_vs3.0 | $838.23 | 9 | 88.9% | 18.1% | 3.60 | PASS | 26 |
| 13 | tp12_sl12_vs2.0 | $814.74 | 10 | 80.0% | 15.3% | 2.42 | PASS | 18 |
| 14 | tp12_sl8_vs2.5 | $761.12 | 9 | 77.8% | 15.8% | 2.77 | PASS | 23 |
| 15 | tp12_sl8_vs3.0 | $761.12 | 9 | 77.8% | 15.8% | 2.77 | PASS | 24 |
| 16 | tp15_sl12_vs2.0 | $672.41 | 9 | 77.8% | 15.3% | 2.24 | PASS | 2 |
| 17 | tp12_sl10_vs2.5 | $642.05 | 9 | 77.8% | 17.6% | 2.22 | PASS | 19 |
| 18 | tp12_sl10_vs3.0 | $642.05 | 9 | 77.8% | 17.6% | 2.22 | PASS | 20 |
| 19 | tp10_sl12_vs2.0 | $571.70 | 10 | 80.0% | 15.3% | 2.02 | PASS | 31 |
| 20 | tp10_sl8_vs2.5 | $568.68 | 9 | 77.8% | 15.8% | 2.38 | PASS | 32 |
| 21 | tp10_sl8_vs3.0 | $568.68 | 9 | 77.8% | 15.8% | 2.38 | PASS | 33 |
| 22 | tp15_sl8_vs2.5 | $552.96 | 8 | 75.0% | 15.8% | 2.35 | PASS | 11 |
| 23 | tp15_sl8_vs3.0 | $552.96 | 8 | 75.0% | 15.8% | 2.35 | PASS | 12 |
| 24 | tp12_sl8_vs2.0 | $526.45 | 10 | 70.0% | 15.8% | 1.83 | PASS | 28 |
| 25 | tp10_sl10_vs2.5 | $457.91 | 9 | 77.8% | 17.6% | 1.91 | PASS | 29 |
| 26 | tp10_sl10_vs3.0 | $457.91 | 9 | 77.8% | 17.6% | 1.91 | PASS | 30 |
| 27 | tp15_sl10_vs2.5 | $442.86 | 8 | 75.0% | 17.6% | 1.88 | PASS | 4 |
| 28 | tp15_sl10_vs3.0 | $442.86 | 8 | 75.0% | 17.6% | 1.88 | PASS | 5 |
| 29 | tp12_sl10_vs2.0 | $364.79 | 10 | 70.0% | 17.6% | 1.48 | PASS | 17 |
| 30 | tp12_sl15_vs2.0 | $355.83 | 9 | 77.8% | 18.1% | 1.51 | PASS | 13 |
| 31 | tp10_sl8_vs2.0 | $350.37 | 10 | 70.0% | 15.8% | 1.58 | PASS | 36 |
| 32 | tp15_sl8_vs2.0 | $335.98 | 9 | 66.7% | 15.8% | 1.57 | PASS | 16 |
| 33 | tp10_sl10_vs2.0 | $199.97 | 10 | 70.0% | 17.6% | 1.27 | PASS | 27 |
| 34 | tp10_sl15_vs2.0 | $191.64 | 9 | 77.8% | 18.1% | 1.28 | PASS | 10 |
| 35 | tp15_sl10_vs2.0 **SEL** | $186.50 | 9 | 66.7% | 17.6% | 1.26 | PASS | 1 |
| 36 | tp15_sl15_vs2.0 | $178.22 | 8 | 75.0% | 18.1% | 1.27 | PASS | 3 |

### Selection Analysis

- **Selected**: `tp15_sl10_vs2.0`
- **Sel OOS P&L**: $186.50 (trades=9)
- **Sel gates**: PASS
- **Best OOS**: `tp12_sl12_vs2.5` ($1216.44)
- **Optimal**: NO
- **Passing gates**: 36/36

### Timing

- Precompute: 29.9s
- Inner grid: 7.8s
- Holdout: 2.2s

## Verdict

### TRADEABLE: **PASS**

Selected `tp15_sl15_vs3.0` passes OOS gates (P&L=$361.03).
Inner selection did NOT find best OOS. Best was `tp12_sl8_vs2.5` ($1107.35).

### LIVE_CURRENT: **PASS**

Selected `tp15_sl10_vs2.0` passes OOS gates (P&L=$186.50).
Inner selection did NOT find best OOS. Best was `tp12_sl12_vs2.5` ($1216.44).

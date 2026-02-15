# Part 2 Robustness Sweep - 295-coin Universe (excl_all_negative)

**Date**: 2026-02-16 00:23
**Commit**: ad313f6
**Universe**: T1(96) + T2(199) = 295 coins (excl 21 net-negative)
**Full universe**: T1(100) + T2(216) = 316 coins
**Timeframe**: 1H
**Cost Regime**: MEXC Market (costs_mexc_v2)
**Fees**: T1=12.5bps, T2=23.5bps
**Stress**: 2x (T1=25.0bps, T2=47.0bps)
**Runtime**: 31.9s
**Baseline**: v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10)

## Excluded Coins (21)

Source: `part2_loss_cluster_001.json`

```
AI3/USD, ALKIMI/USD, ANIME/USD, CFG/USD, DBR/USD, ESX/USD, GST/USD, HOUSE/USD, KET/USD, LMWR/USD, MXC/USD, ODOS/USD, PERP/USD, PNUT/USD, POLIS/USD, RARI/USD, SUKU/USD, TANSSI/USD, TITCOIN/USD, TOSHI/USD, WMTX/USD
```

## G7 Gate: Neighbor Stability

| Metric | Value | Threshold | Verdict |
|--------|-------|-----------|---------|
| Profitable neighbors (PF>1.0) | 12/12 | >=8/12 | **PASS** |
| Stress profitable (2x fees PF>1.0) | 12/12 | info | - |
| Stress positive exp/wk | 12/12 | info | - |
| WF >= 3/5 folds | 12/12 | info | - |

## All Variants (MEXC Market)

| # | Label | dev | tp | sl | tl | Trades | T1 | T2 | PF | WR%% | Exp/Wk | DD%% | Fee%% | WF | Score |
|---|-------|-----|----|----|----|----|----|----|-----|------|--------|------|------|-----|-------|
| 0 | v5 baseline | 2.0 | 8 | 5 | 10 | 56 | 18 | 38 | 2.834 | 64.3 | $762.44 | 8.6 | 12.3 | 4/5 | 609.9506 |
| 1 | dev_thresh -0.2 | 1.8 | 8 | 5 | 10 | 68 | 26 | 42 | 2.547 | 61.8 | $811.92 | 14.1 | 12.6 | 4/5 | 649.5344 |
| 2 | dev_thresh +0.2 | 2.2 | 8 | 5 | 10 | 48 | 16 | 32 | 2.654 | 60.4 | $493.56 | 9.8 | 12.8 | 3/5 | 284.2922 |
| 3 | dev_thresh +0.5 | 2.5 | 8 | 5 | 10 | 35 | 10 | 25 | 2.306 | 54.3 | $273.65 | 11.8 | 15.7 | 3/5 | 114.9340 |
| 4 | tp_pct -2 | 2.0 | 6 | 5 | 10 | 56 | 18 | 38 | 2.650 | 66.1 | $533.15 | 9.1 | 14.8 | 4/5 | 426.5190 |
| 5 | tp_pct +2 | 2.0 | 10 | 5 | 10 | 55 | 18 | 37 | 2.831 | 60.0 | $733.42 | 9.1 | 12.1 | 4/5 | 586.7345 |
| 6 | tp_pct +4 | 2.0 | 12 | 5 | 10 | 55 | 18 | 37 | 2.867 | 58.2 | $830.34 | 13.7 | 11.1 | 4/5 | 664.2731 |
| 7 | sl_pct -2 | 2.0 | 8 | 3 | 10 | 58 | 19 | 39 | 2.749 | 60.3 | $634.92 | 15.2 | 13.2 | 4/5 | 507.9388 |
| 8 | sl_pct +2 | 2.0 | 8 | 7 | 10 | 55 | 17 | 38 | 2.715 | 63.6 | $744.61 | 9.8 | 12.2 | 5/5 | 744.6071 |
| 9 | time_limit -2 | 2.0 | 8 | 5 | 8 | 59 | 18 | 41 | 2.949 | 62.7 | $725.13 | 11.4 | 13.6 | 4/5 | 580.1026 |
| 10 | time_limit +2 | 2.0 | 8 | 5 | 12 | 55 | 18 | 37 | 2.678 | 60.0 | $725.71 | 11.6 | 12.2 | 3/5 | 435.4234 |
| 11 | time_limit +5 | 2.0 | 8 | 5 | 15 | 50 | 18 | 32 | 2.730 | 64.0 | $723.57 | 9.3 | 11.1 | 4/5 | 578.8526 |

## Stress Test (2x Fees)

| # | Label | PF | Exp/Wk | P&L | Trades | WR%% | DD%% |
|---|-------|----|--------|------|--------|------|------|
| 0 | v5 baseline | 2.306 | $571.41 | $2452 | 56 | 62.5 | 13.1 |
| 1 | dev_thresh -0.2 | 2.074 | $586.37 | $2516 | 68 | 58.8 | 19.4 |
| 2 | dev_thresh +0.2 | 2.112 | $360.16 | $1546 | 48 | 58.3 | 13.5 |
| 3 | dev_thresh +0.5 | 1.788 | $188.39 | $808 | 35 | 51.4 | 15.5 |
| 4 | tp_pct -2 | 2.059 | $371.30 | $1594 | 56 | 62.5 | 15.9 |
| 5 | tp_pct +2 | 2.254 | $545.27 | $2340 | 55 | 56.4 | 12.0 |
| 6 | tp_pct +4 | 2.321 | $634.12 | $2721 | 55 | 54.5 | 17.5 |
| 7 | sl_pct -2 | 2.181 | $462.22 | $1984 | 58 | 58.6 | 22.2 |
| 8 | sl_pct +2 | 2.232 | $557.34 | $2392 | 55 | 63.6 | 12.7 |
| 9 | time_limit -2 | 2.294 | $528.15 | $2267 | 59 | 54.2 | 16.6 |
| 10 | time_limit +2 | 2.177 | $538.99 | $2313 | 55 | 58.2 | 16.1 |
| 11 | time_limit +5 | 2.264 | $556.99 | $2390 | 50 | 62.0 | 10.6 |

## Walk-Forward Detail (5-Fold)

| # | Label | F1 P&L | F2 P&L | F3 P&L | F4 P&L | F5 P&L | Positive |
|---|-------|--------|--------|--------|--------|--------|----------|
| 0 | v5 baseline | $909 | $58 | $-18 | $792 | $913 | 4/5 |
| 1 | dev_thresh -0.2 | $1151 | $-170 | $191 | $945 | $847 | 4/5 |
| 2 | dev_thresh +0.2 | $377 | $-90 | $-18 | $580 | $1044 | 3/5 |
| 3 | dev_thresh +0.5 | $747 | $-120 | $-51 | $291 | $374 | 3/5 |
| 4 | tp_pct -2 | $633 | $92 | $-94 | $573 | $770 | 4/5 |
| 5 | tp_pct +2 | $870 | $-9 | $60 | $684 | $930 | 4/5 |
| 6 | tp_pct +4 | $1098 | $30 | $-201 | $865 | $1112 | 4/5 |
| 7 | sl_pct -2 | $679 | $35 | $-192 | $799 | $1029 | 4/5 |
| 8 | sl_pct +2 | $863 | $74 | $35 | $792 | $839 | 5/5 |
| 9 | time_limit -2 | $851 | $-26 | $82 | $756 | $893 | 4/5 |
| 10 | time_limit +2 | $905 | $-13 | $-55 | $705 | $1009 | 3/5 |
| 11 | time_limit +5 | $874 | $-47 | $21 | $790 | $870 | 4/5 |

## Ranking (Composite Score)

```
score = exp_per_week * (wf_folds_positive / 5) * min(1.0, trades / 50)
```

### #1: sl_pct +2 (variant 8)

- **Params**: dev_thresh=2.0, tp_pct=8, sl_pct=7, time_limit=10
- **Composite Score**: 744.6071
- **Baseline**: 55 trades, PF=2.715, WR=63.6%, Exp/Wk=$744.61, DD=9.8%
- **Walk-Forward**: 5/5 positive folds
- **Stress 2x**: PF=2.232, Exp/Wk=$557.34

### #2: tp_pct +4 (variant 6)

- **Params**: dev_thresh=2.0, tp_pct=12, sl_pct=5, time_limit=10
- **Composite Score**: 664.2731
- **Baseline**: 55 trades, PF=2.867, WR=58.2%, Exp/Wk=$830.34, DD=13.7%
- **Walk-Forward**: 4/5 positive folds
- **Stress 2x**: PF=2.321, Exp/Wk=$634.12

### #3: dev_thresh -0.2 (variant 1)

- **Params**: dev_thresh=1.8, tp_pct=8, sl_pct=5, time_limit=10
- **Composite Score**: 649.5344
- **Baseline**: 68 trades, PF=2.547, WR=61.8%, Exp/Wk=$811.92, DD=14.1%
- **Walk-Forward**: 4/5 positive folds
- **Stress 2x**: PF=2.074, Exp/Wk=$586.37

### Full Ranking

| Rank | # | Label | Score | Exp/Wk | WF | Trades |
|------|---|-------|-------|--------|----|--------|
| 1 | 8 | sl_pct +2 | 744.6071 | $744.61 | 5/5 | 55 |
| 2 | 6 | tp_pct +4 | 664.2731 | $830.34 | 4/5 | 55 |
| 3 | 1 | dev_thresh -0.2 | 649.5344 | $811.92 | 4/5 | 68 |
| 4 | 0 | v5 baseline | 609.9506 | $762.44 | 4/5 | 56 |
| 5 | 5 | tp_pct +2 | 586.7345 | $733.42 | 4/5 | 55 |
| 6 | 9 | time_limit -2 | 580.1026 | $725.13 | 4/5 | 59 |
| 7 | 11 | time_limit +5 | 578.8526 | $723.57 | 4/5 | 50 |
| 8 | 7 | sl_pct -2 | 507.9388 | $634.92 | 4/5 | 58 |
| 9 | 10 | time_limit +2 | 435.4234 | $725.71 | 3/5 | 55 |
| 10 | 4 | tp_pct -2 | 426.5190 | $533.15 | 4/5 | 56 |
| 11 | 2 | dev_thresh +0.2 | 284.2922 | $493.56 | 3/5 | 48 |
| 12 | 3 | dev_thresh +0.5 | 114.9340 | $273.65 | 3/5 | 35 |

## Comparison: 295 vs 316 coins

| Metric | 316 coins | 295 coins | Delta |
|--------|-----------|-----------|-------|
| G7 profitable | 9/12 | 12/12 | +3 |
| Stress profitable | - | 12/12 | - |
| WF >= 3/5 | - | 12/12 | - |

**Note**: 316-coin G7 was 9/12 PASS (from part2_robustness_316_001).
Excluding 21 net-negative coins should improve edge across all variants.

## Parameter Sensitivity Summary

Comparing each perturbation to v5 baseline (variant 0):

| Param | Change | Trades | Exp/Wk | Score | Delta Score |
|-------|--------|--------|--------|-------|-------------|
| v5 baseline | vs baseline | 56 | $762.44 | 609.9506 | +0.0000 |
| dev_thresh -0.2 | vs baseline | 68 | $811.92 | 649.5344 | +39.5838 |
| dev_thresh +0.2 | vs baseline | 48 | $493.56 | 284.2922 | -325.6584 |
| dev_thresh +0.5 | vs baseline | 35 | $273.65 | 114.9340 | -495.0166 |
| tp_pct -2 | vs baseline | 56 | $533.15 | 426.5190 | -183.4316 |
| tp_pct +2 | vs baseline | 55 | $733.42 | 586.7345 | -23.2161 |
| tp_pct +4 | vs baseline | 55 | $830.34 | 664.2731 | +54.3225 |
| sl_pct -2 | vs baseline | 58 | $634.92 | 507.9388 | -102.0118 |
| sl_pct +2 | vs baseline | 55 | $744.61 | 744.6071 | +134.6565 |
| time_limit -2 | vs baseline | 59 | $725.13 | 580.1026 | -29.8480 |
| time_limit +2 | vs baseline | 55 | $725.71 | 435.4234 | -174.5272 |
| time_limit +5 | vs baseline | 50 | $723.57 | 578.8526 | -31.0980 |

---
*Generated by strategies/hf/screening/run_part2_robustness_295.py at 2026-02-16 00:23*
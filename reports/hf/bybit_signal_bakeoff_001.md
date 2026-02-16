# Bybit Signal Bake-Off Scoreboard

**Date**: 2026-02-16 21:29
**Exchange**: Bybit
**Runtime**: 298.3s

## Best Combo per Signal (maker_p50 / $200)

| Signal | Config | Trades | PF | Exp/Wk | DD% | WF | Gates |
|--------|--------|--------|----|--------|-----|----|----|
| H16 | disp_tight | 189 | 0.648 | $-47.87 | 102.4 | 0/5 | 2/7 |
| H17 | wick_wide | 184 | 0.994 | $-0.48 | 42.7 | 2/5 | 2/7 |
| H18 | volexp_5 | 33 | 1.249 | $10.82 | 29.0 | 3/5 | 3/7 |
| H19 | gap_tight | 1 | 0.000 | $-1.54 | 3.3 | 0/5 | 1/7 |
| H20Z | zscore_v5 | 105 | 1.045 | $3.00 | 22.1 | 2/5 | 3/7 |

## H16: DISPLACEMENT_BAR

Passing: 0/24

| Config | Regime | Size | Trades | PF | Exp/Wk | DD% | WF | Gates |
|--------|--------|------|--------|----|--------|-----|----|----|
| disp_tight | measured_ob_maker_p50 | $200 | 189 | 0.648 | $-47.87 | 102.4 | 0/5 | 2/7 |
| disp_tight | measured_ob_maker_p50 | $500 | 189 | 0.648 | $-119.68 | 102.4 | 0/5 | 2/7 |
| disp_tight | measured_ob_maker_p50 | $2000 | 189 | 0.648 | $-478.73 | 102.4 | 0/5 | 2/7 |
| disp_tight | measured_ob_maker_p90 | $200 | 189 | 0.621 | $-51.07 | 108.5 | 0/5 | 2/7 |
| disp_tight | measured_ob_maker_p90 | $500 | 189 | 0.621 | $-127.68 | 108.5 | 0/5 | 2/7 |
| disp_tight | measured_ob_maker_p90 | $2000 | 189 | 0.621 | $-510.72 | 108.5 | 0/5 | 2/7 |
| disp_tight | measured_ob_taker_p50 | $200 | 189 | 0.592 | $-54.45 | 115.1 | 0/5 | 2/7 |
| disp_tight | measured_ob_taker_p50 | $500 | 189 | 0.583 | $-138.56 | 117.1 | 0/5 | 2/7 |
| disp_tight | measured_ob_taker_p50 | $2000 | 189 | 0.563 | $-575.53 | 121.4 | 0/5 | 2/7 |
| disp_tight | measured_ob_taker_p90 | $200 | 189 | 0.504 | $-63.62 | 133.8 | 0/5 | 2/7 |
| disp_tight | measured_ob_taker_p90 | $500 | 189 | 0.482 | $-163.48 | 137.7 | 0/5 | 2/7 |
| disp_tight | measured_ob_taker_p90 | $2000 | 189 | 0.438 | $-692.86 | 146.3 | 0/5 | 2/7 |
| disp_wide | measured_ob_maker_p50 | $200 | 146 | 0.512 | $-60.26 | 125.5 | 0/5 | 2/7 |
| disp_wide | measured_ob_maker_p50 | $500 | 146 | 0.512 | $-150.64 | 125.5 | 0/5 | 2/7 |
| disp_wide | measured_ob_maker_p50 | $2000 | 146 | 0.512 | $-602.57 | 125.5 | 0/5 | 2/7 |
| disp_wide | measured_ob_maker_p90 | $200 | 146 | 0.490 | $-62.71 | 130.2 | 0/5 | 2/7 |
| disp_wide | measured_ob_maker_p90 | $500 | 146 | 0.490 | $-156.77 | 130.2 | 0/5 | 2/7 |
| disp_wide | measured_ob_maker_p90 | $2000 | 146 | 0.490 | $-627.07 | 130.2 | 0/5 | 2/7 |
| disp_wide | measured_ob_taker_p50 | $200 | 146 | 0.465 | $-65.53 | 135.6 | 0/5 | 2/7 |
| disp_wide | measured_ob_taker_p50 | $500 | 146 | 0.455 | $-166.60 | 137.8 | 0/5 | 2/7 |
| disp_wide | measured_ob_taker_p50 | $2000 | 146 | 0.436 | $-687.65 | 142.0 | 0/5 | 2/7 |
| disp_wide | measured_ob_taker_p90 | $200 | 146 | 0.387 | $-73.77 | 152.1 | 0/5 | 2/7 |
| disp_wide | measured_ob_taker_p90 | $500 | 146 | 0.364 | $-190.07 | 156.9 | 0/5 | 2/7 |
| disp_wide | measured_ob_taker_p90 | $2000 | 146 | 0.333 | $-789.47 | 163.2 | 0/5 | 2/7 |

## H17: WICK_REJECTION

Passing: 0/24

| Config | Regime | Size | Trades | PF | Exp/Wk | DD% | WF | Gates |
|--------|--------|------|--------|----|--------|-----|----|----|
| wick_tight | measured_ob_maker_p50 | $200 | 231 | 0.806 | $-19.90 | 61.1 | 1/5 | 2/7 |
| wick_tight | measured_ob_maker_p50 | $500 | 231 | 0.806 | $-49.74 | 61.1 | 1/5 | 2/7 |
| wick_tight | measured_ob_maker_p50 | $2000 | 231 | 0.806 | $-198.95 | 61.1 | 1/5 | 2/7 |
| wick_tight | measured_ob_maker_p90 | $200 | 231 | 0.728 | $-28.23 | 73.8 | 1/5 | 2/7 |
| wick_tight | measured_ob_maker_p90 | $500 | 231 | 0.728 | $-70.58 | 73.8 | 1/5 | 2/7 |
| wick_tight | measured_ob_maker_p90 | $2000 | 231 | 0.728 | $-282.33 | 73.8 | 1/5 | 2/7 |
| wick_tight | measured_ob_taker_p50 | $200 | 231 | 0.646 | $-37.21 | 87.9 | 1/5 | 2/7 |
| wick_tight | measured_ob_taker_p50 | $500 | 231 | 0.617 | $-101.16 | 93.7 | 0/5 | 2/7 |
| wick_tight | measured_ob_taker_p50 | $2000 | 231 | 0.564 | $-464.24 | 104.4 | 0/5 | 2/7 |
| wick_tight | measured_ob_taker_p90 | $200 | 231 | 0.448 | $-59.28 | 128.5 | 0/5 | 2/7 |
| wick_tight | measured_ob_taker_p90 | $500 | 231 | 0.405 | $-159.53 | 137.7 | 0/5 | 2/7 |
| wick_tight | measured_ob_taker_p90 | $2000 | 231 | 0.344 | $-699.81 | 150.8 | 0/5 | 2/7 |
| wick_wide | measured_ob_maker_p50 | $200 | 184 | 0.994 | $-0.48 | 42.7 | 2/5 | 2/7 |
| wick_wide | measured_ob_maker_p50 | $500 | 184 | 0.994 | $-1.21 | 42.7 | 2/5 | 2/7 |
| wick_wide | measured_ob_maker_p50 | $2000 | 184 | 0.994 | $-4.83 | 42.7 | 2/5 | 2/7 |
| wick_wide | measured_ob_maker_p90 | $200 | 184 | 0.902 | $-8.35 | 52.0 | 2/5 | 2/7 |
| wick_wide | measured_ob_maker_p90 | $500 | 184 | 0.902 | $-20.89 | 52.0 | 2/5 | 2/7 |
| wick_wide | measured_ob_maker_p90 | $2000 | 184 | 0.902 | $-83.54 | 52.0 | 2/5 | 2/7 |
| wick_wide | measured_ob_taker_p50 | $200 | 184 | 0.805 | $-16.94 | 62.6 | 1/5 | 2/7 |
| wick_wide | measured_ob_taker_p50 | $500 | 184 | 0.772 | $-49.99 | 66.7 | 1/5 | 2/7 |
| wick_wide | measured_ob_taker_p50 | $2000 | 184 | 0.710 | $-258.06 | 74.5 | 1/5 | 2/7 |
| wick_wide | measured_ob_taker_p90 | $200 | 184 | 0.573 | $-39.36 | 95.4 | 1/5 | 2/7 |
| wick_wide | measured_ob_taker_p90 | $500 | 184 | 0.525 | $-110.51 | 104.1 | 0/5 | 2/7 |
| wick_wide | measured_ob_taker_p90 | $2000 | 184 | 0.453 | $-515.68 | 116.7 | 0/5 | 2/7 |

## H18: VOL_EXPANSION

Passing: 0/24

| Config | Regime | Size | Trades | PF | Exp/Wk | DD% | WF | Gates |
|--------|--------|------|--------|----|--------|-----|----|----|
| volexp_3 | measured_ob_maker_p50 | $200 | 37 | 0.797 | $-8.88 | 51.7 | 2/5 | 1/7 |
| volexp_3 | measured_ob_maker_p50 | $500 | 37 | 0.797 | $-22.21 | 51.7 | 2/5 | 1/7 |
| volexp_3 | measured_ob_maker_p50 | $2000 | 37 | 0.797 | $-88.83 | 51.7 | 2/5 | 1/7 |
| volexp_3 | measured_ob_maker_p90 | $200 | 37 | 0.758 | $-10.73 | 53.1 | 2/5 | 1/7 |
| volexp_3 | measured_ob_maker_p90 | $500 | 37 | 0.758 | $-26.84 | 53.1 | 2/5 | 1/7 |
| volexp_3 | measured_ob_maker_p90 | $2000 | 37 | 0.758 | $-107.35 | 53.1 | 2/5 | 1/7 |
| volexp_3 | measured_ob_taker_p50 | $200 | 37 | 0.709 | $-13.08 | 54.9 | 2/5 | 1/7 |
| volexp_3 | measured_ob_taker_p50 | $500 | 37 | 0.686 | $-35.43 | 55.7 | 2/5 | 1/7 |
| volexp_3 | measured_ob_taker_p50 | $2000 | 37 | 0.644 | $-162.74 | 57.3 | 2/5 | 1/7 |
| volexp_3 | measured_ob_taker_p90 | $200 | 37 | 0.545 | $-21.41 | 62.1 | 1/5 | 1/7 |
| volexp_3 | measured_ob_taker_p90 | $500 | 37 | 0.484 | $-61.58 | 65.3 | 1/5 | 1/7 |
| volexp_3 | measured_ob_taker_p90 | $2000 | 37 | 0.417 | $-284.51 | 69.6 | 0/5 | 1/7 |
| volexp_5 | measured_ob_maker_p50 | $200 | 33 | 1.249 | $10.82 | 29.0 | 3/5 | 3/7 |
| volexp_5 | measured_ob_maker_p50 | $500 | 33 | 1.249 | $27.06 | 29.0 | 3/5 | 3/7 |
| volexp_5 | measured_ob_maker_p50 | $2000 | 33 | 1.249 | $108.25 | 29.0 | 3/5 | 3/7 |
| volexp_5 | measured_ob_maker_p90 | $200 | 33 | 1.198 | $8.67 | 30.3 | 3/5 | 3/7 |
| volexp_5 | measured_ob_maker_p90 | $500 | 33 | 1.198 | $21.68 | 30.3 | 3/5 | 3/7 |
| volexp_5 | measured_ob_maker_p90 | $2000 | 33 | 1.198 | $86.74 | 30.3 | 3/5 | 3/7 |
| volexp_5 | measured_ob_taker_p50 | $200 | 33 | 1.133 | $5.92 | 32.2 | 3/5 | 2/7 |
| volexp_5 | measured_ob_taker_p50 | $500 | 33 | 1.103 | $11.54 | 33.1 | 3/5 | 2/7 |
| volexp_5 | measured_ob_taker_p50 | $2000 | 33 | 1.047 | $21.11 | 34.8 | 3/5 | 2/7 |
| volexp_5 | measured_ob_taker_p90 | $200 | 33 | 0.915 | $-3.96 | 39.1 | 2/5 | 1/7 |
| volexp_5 | measured_ob_taker_p90 | $500 | 33 | 0.834 | $-19.71 | 42.2 | 2/5 | 1/7 |
| volexp_5 | measured_ob_taker_p90 | $2000 | 33 | 0.744 | $-124.41 | 47.3 | 1/5 | 1/7 |

## H19: GAP_PROXY

Passing: 0/24

| Config | Regime | Size | Trades | PF | Exp/Wk | DD% | WF | Gates |
|--------|--------|------|--------|----|--------|-----|----|----|
| gap_tight | measured_ob_maker_p50 | $200 | 1 | 0.000 | $-1.54 | 3.3 | 0/5 | 1/7 |
| gap_tight | measured_ob_maker_p50 | $500 | 1 | 0.000 | $-3.84 | 3.3 | 0/5 | 1/7 |
| gap_tight | measured_ob_maker_p50 | $2000 | 1 | 0.000 | $-15.36 | 3.3 | 0/5 | 1/7 |
| gap_tight | measured_ob_maker_p90 | $200 | 1 | 0.000 | $-1.60 | 3.4 | 0/5 | 1/7 |
| gap_tight | measured_ob_maker_p90 | $500 | 1 | 0.000 | $-4.00 | 3.4 | 0/5 | 1/7 |
| gap_tight | measured_ob_maker_p90 | $2000 | 1 | 0.000 | $-16.00 | 3.4 | 0/5 | 1/7 |
| gap_tight | measured_ob_taker_p50 | $200 | 1 | 0.000 | $-1.69 | 3.6 | 0/5 | 1/7 |
| gap_tight | measured_ob_taker_p50 | $500 | 1 | 0.000 | $-4.33 | 3.7 | 0/5 | 1/7 |
| gap_tight | measured_ob_taker_p50 | $2000 | 1 | 0.000 | $-18.20 | 3.9 | 0/5 | 1/7 |
| gap_tight | measured_ob_taker_p90 | $200 | 1 | 0.000 | $-2.05 | 4.4 | 0/5 | 1/7 |
| gap_tight | measured_ob_taker_p90 | $500 | 1 | 0.000 | $-5.55 | 4.8 | 0/5 | 1/7 |
| gap_tight | measured_ob_taker_p90 | $2000 | 1 | 0.000 | $-24.29 | 5.2 | 0/5 | 1/7 |
| gap_wide | measured_ob_maker_p50 | $200 | 1 | 0.000 | $-2.47 | 5.3 | 0/5 | 1/7 |
| gap_wide | measured_ob_maker_p50 | $500 | 1 | 0.000 | $-6.17 | 5.3 | 0/5 | 1/7 |
| gap_wide | measured_ob_maker_p50 | $2000 | 1 | 0.000 | $-24.66 | 5.3 | 0/5 | 1/7 |
| gap_wide | measured_ob_maker_p90 | $200 | 1 | 0.000 | $-2.53 | 5.4 | 0/5 | 1/7 |
| gap_wide | measured_ob_maker_p90 | $500 | 1 | 0.000 | $-6.33 | 5.4 | 0/5 | 1/7 |
| gap_wide | measured_ob_maker_p90 | $2000 | 1 | 0.000 | $-25.30 | 5.4 | 0/5 | 1/7 |
| gap_wide | measured_ob_taker_p50 | $200 | 1 | 0.000 | $-2.62 | 5.6 | 0/5 | 1/7 |
| gap_wide | measured_ob_taker_p50 | $500 | 1 | 0.000 | $-6.65 | 5.7 | 0/5 | 1/7 |
| gap_wide | measured_ob_taker_p50 | $2000 | 1 | 0.000 | $-27.48 | 5.9 | 0/5 | 1/7 |
| gap_wide | measured_ob_taker_p90 | $200 | 1 | 0.000 | $-2.97 | 6.4 | 0/5 | 1/7 |
| gap_wide | measured_ob_taker_p90 | $500 | 1 | 0.000 | $-7.86 | 6.7 | 0/5 | 1/7 |
| gap_wide | measured_ob_taker_p90 | $2000 | 1 | 0.000 | $-33.51 | 7.2 | 0/5 | 1/7 |

## H20Z: VWAP_DEVIATION_ZSCORE

Passing: 0/24

| Config | Regime | Size | Trades | PF | Exp/Wk | DD% | WF | Gates |
|--------|--------|------|--------|----|--------|-----|----|----|
| zscore_v5 | measured_ob_maker_p50 | $200 | 105 | 1.045 | $3.00 | 22.1 | 2/5 | 3/7 |
| zscore_v5 | measured_ob_maker_p50 | $500 | 105 | 1.045 | $7.50 | 22.1 | 2/5 | 3/7 |
| zscore_v5 | measured_ob_maker_p50 | $2000 | 105 | 1.045 | $30.01 | 22.1 | 2/5 | 3/7 |
| zscore_v5 | measured_ob_maker_p90 | $200 | 105 | 0.968 | $-2.12 | 24.0 | 1/5 | 2/7 |
| zscore_v5 | measured_ob_maker_p90 | $500 | 105 | 0.968 | $-5.29 | 24.0 | 1/5 | 2/7 |
| zscore_v5 | measured_ob_maker_p90 | $2000 | 105 | 0.968 | $-21.18 | 24.0 | 1/5 | 2/7 |
| zscore_v5 | measured_ob_taker_p50 | $200 | 105 | 0.881 | $-8.10 | 28.3 | 1/5 | 2/7 |
| zscore_v5 | measured_ob_taker_p50 | $500 | 105 | 0.847 | $-26.27 | 30.3 | 1/5 | 2/7 |
| zscore_v5 | measured_ob_taker_p50 | $2000 | 105 | 0.782 | $-151.19 | 35.2 | 1/5 | 2/7 |
| zscore_v5 | measured_ob_taker_p90 | $200 | 105 | 0.635 | $-26.05 | 55.9 | 1/5 | 2/7 |
| zscore_v5 | measured_ob_taker_p90 | $500 | 105 | 0.568 | $-77.98 | 66.9 | 1/5 | 2/7 |
| zscore_v5 | measured_ob_taker_p90 | $2000 | 105 | 0.487 | $-378.34 | 81.2 | 1/5 | 2/7 |
| zscore_sl7 | measured_ob_maker_p50 | $200 | 104 | 1.026 | $1.92 | 31.1 | 2/5 | 3/7 |
| zscore_sl7 | measured_ob_maker_p50 | $500 | 104 | 1.026 | $4.79 | 31.1 | 2/5 | 3/7 |
| zscore_sl7 | measured_ob_maker_p50 | $2000 | 104 | 1.026 | $19.17 | 31.1 | 2/5 | 3/7 |
| zscore_sl7 | measured_ob_maker_p90 | $200 | 104 | 0.954 | $-3.42 | 34.4 | 2/5 | 2/7 |
| zscore_sl7 | measured_ob_maker_p90 | $500 | 104 | 0.954 | $-8.55 | 34.4 | 2/5 | 2/7 |
| zscore_sl7 | measured_ob_maker_p90 | $2000 | 104 | 0.954 | $-34.19 | 34.4 | 2/5 | 2/7 |
| zscore_sl7 | measured_ob_taker_p50 | $200 | 104 | 0.871 | $-9.69 | 38.8 | 1/5 | 2/7 |
| zscore_sl7 | measured_ob_taker_p50 | $500 | 104 | 0.837 | $-30.71 | 40.8 | 1/5 | 2/7 |
| zscore_sl7 | measured_ob_taker_p50 | $2000 | 104 | 0.774 | $-171.88 | 45.3 | 1/5 | 2/7 |
| zscore_sl7 | measured_ob_taker_p90 | $200 | 104 | 0.632 | $-28.59 | 63.0 | 1/5 | 2/7 |
| zscore_sl7 | measured_ob_taker_p90 | $500 | 104 | 0.564 | $-85.32 | 73.2 | 1/5 | 2/7 |
| zscore_sl7 | measured_ob_taker_p90 | $2000 | 104 | 0.483 | $-409.61 | 87.9 | 1/5 | 2/7 |

---
*Generated by run_bybit_signal_exploration.py at 2026-02-16 21:29*
# H20 VWAP_DEVIATION Throughput: tp=10 variant

**Date**: 2026-02-15 23:38
**Commit**: da5db72
**Universe**: T1(100) + T2(216)
**Params**: dev_thresh=2.0, tp_pct=10, sl_pct=5, time_limit=10
**Fees**: MEXC Market (T1=12.5bps, T2=23.5bps)
**Runtime**: 29.7s

## Baseline Metrics

| Metric | Value |
|--------|-------|
| trades | 72 |
| pnl | $232.99 |
| pf | 1.085 |
| wr | 44.4% |
| expectancy | $3.24 |
| exp_per_week | $54.21 |
| dd | 52.4% |
| fee_drag_pct | 17.3% |

## Throughput

| Metric | Value |
|--------|-------|
| Trades/week | 16.75 |
| T1 trades | 21 |
| T2 trades | 51 |
| Max gap (bars) | 34 |
| Max gap (days) | 1.42 |
| Utilization | 53.3% |
| Rolling 4wk CV | 0.000 (CONSISTENT) |

## Clustering

- Active weeks: 4/4
- Busiest week: 21 trades
- Weekly: [11, 21, 16, 17]

## Capacity

| max_pos | Trades | PnL | PF | WR% | Exp/Wk | Util% |
|---------|--------|-----|----|-----|--------|-------|
| 1 | 72 | $233 | 1.085 | 44.4 | $54.21 | 53.3 |
| 2 | 76 | $203 | 1.142 | 43.4 | $47.26 | 54.3 |
| 3 | 66 | $-110 | 0.886 | 43.9 | $-25.53 | 76.5 |

## Walk-Forward (5-fold)

**Result: 3/5**

| Fold | Trades | PnL | Positive |
|------|--------|-----|----------|
| 0 | 13 | $360.41 | YES |
| 1 | 16 | $-245.90 | NO |
| 2 | 13 | $-439.06 | NO |
| 3 | 15 | $124.59 | YES |
| 4 | 16 | $651.60 | YES |

## Stress 2x Fees

PF=0.902 | Exp/Wk=$-64.56 | Trades=72 | DD=61.5%

---
*Generated at 2026-02-15 23:38*
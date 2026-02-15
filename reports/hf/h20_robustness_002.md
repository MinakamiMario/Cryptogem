# H20 VWAP_DEVIATION Robustness Grid — PENDING

**Status**: Runner updated, awaiting execution with 1H candle cache.

## How to Run

```bash
python -m strategies.hf.screening.run_h20_robustness          # Full run
python -m strategies.hf.screening.run_h20_robustness --dry-run # Preview only
```

## Grid Design

12 variants perturbing v5 baseline one parameter at a time:
- Baseline: dev_thresh=2.0, tp_pct=8, sl_pct=5, time_limit=10
- 3 dev_thresh variants: 1.8, 2.2, 2.5
- 3 tp_pct variants: 6, 10, 12
- 2 sl_pct variants: 3, 7
- 3 time_limit variants: 8, 12, 15

## Metrics per variant
- Trades, PF, WR, Exp/Trade, Exp/Week, DD%, Fee Drag%
- Walk-forward 5-fold
- Stress test at 2x fees
- Composite score

---
*Placeholder — will be overwritten when run completes*

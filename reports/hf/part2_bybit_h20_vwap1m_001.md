# Bybit Real VWAP Validation Report

**Date**: 2026-02-17 03:26
**Commit**: 63fde0e
**Test**: Apples-to-apples VWAP comparison (real 1m VWAP vs HLC3 proxy)
**Signal**: H20 VWAP_DEVIATION raw (dev_thresh=2.0)
**Exchange**: Bybit SPOT (10/10 bps)
**Runtime**: 55.7s

## Objective

Test whether Bybit H20 failure is caused by HLC3 proxy VWAP (vs real
volume-weighted VWAP). Downloaded 1m candles, computed real VWAP per
1H bar, then ran original H20 signal with same dev_thresh=2.0.

## Guardrails

- **Time Window**: 2025-06-01 00:00 UTC → 2026-02-16 19:00 UTC (721 bars, 6259.0h)
- **VWAP**: `VWAP_1H = sum(tp_1m * vol_1m) / sum(vol_1m)`
- **tp_1m**: `tp_1m = (high_1m + low_1m + close_1m) / 3  [HLC3 of 1m bar]`
- **Missing minutes**: skip (hours with 0 volume fallback to HLC3 of 1H bar)
- **OB file**: `bybit_orderbook_costs_001.json` (MD5: `6d443436f8f9fe71e5cd00e69e4a24b2`)
- **Fees**: maker=10.0bps taker=10.0bps
- **Coverage gate**: ≥90.0% → 166/166 included, 0 excluded, 166 full 721-bar coins

## VWAP Diagnostic

### real_vwap
- Coins with VWAP: 166
- Bars with VWAP: 115536/119686
- Deviation stats: min=-3.4816, med=0.0161, max=2.9236
- Deviations ≥ 2.0 ATR: 17 (0.015%)

### hlc3_proxy
- Coins with VWAP: 166
- Bars with VWAP: 115536/119686
- Deviation stats: min=-2.7587, med=0.014, max=2.4757
- Deviations ≥ 2.0 ATR: 2 (0.002%)

## Trigger Comparison

| Metric | Real VWAP | HLC3 Proxy |
|--------|-----------|------------|
| Total triggers | 3 | 1 |
| Coins with triggers | 2 | 1 |

### Candidates Ignoring Bounce Filter

- Total bars with dev≥2.0: **17**
- Blocked by bounce (close ≤ prev_close): **14**
- Would trigger (dev≥2.0 + bounce): **3**

### Top-10 Coins by Real VWAP Triggers

| Coin | Triggers | Dev≥2.0 bars | Blocked by bounce |
|------|----------|--------------|-------------------|
| SPELL/USD | 2 | 2 | 0 |
| FIDA/USD | 1 | 1 | 0 |
| ZK/USD | 0 | 0 | 0 |
| DEGEN/USD | 0 | 0 | 0 |
| AVNT/USD | 0 | 0 | 0 |
| MEME/USD | 0 | 0 | 0 |
| PONKE/USD | 0 | 0 | 0 |
| JASMY/USD | 0 | 0 | 0 |
| POL/USD | 0 | 0 | 0 |
| BONK/USD | 0 | 0 | 0 |

*164/166 coins have 0 triggers. Full breakdown in bybit_vwap1m_diagnostics report.*

### Top-10 Coins by Max VWAP Deviation

Coins ever exceeding dev≥2.0: **13** | Near (1.5-2.0): 36 | Moderate (1.0-1.5): 113 | Far (<1.0): 4

| Coin | Max Dev | Dev≥2.0 bars | Blocked | Triggers |
|------|---------|--------------|---------|----------|
| BTT/USD | 2.9236 | 3 | 3 | 0 |
| SPELL/USD | 2.5379 | 2 | 0 | 2 |
| NYM/USD | 2.2833 | 1 | 1 | 0 |
| PERP/USD | 2.1710 | 1 | 1 | 0 |
| SCRT/USD | 2.1606 | 1 | 1 | 0 |
| ANIME/USD | 2.1452 | 1 | 1 | 0 |
| XTZ/USD | 2.1274 | 1 | 1 | 0 |
| FLR/USD | 2.1217 | 1 | 1 | 0 |
| FIDA/USD | 2.0994 | 1 | 0 | 1 |
| CAMP/USD | 2.0745 | 1 | 1 | 0 |

## 24-Combo Scoreboard (Real VWAP)

| Config | Regime | Size | Trades | PF | Exp/Wk | DD% | WF | Gates |
|--------|--------|------|--------|----|----|-----|----|----|
| v5 | measured_ob_maker_p50 | $200 | 3 | 0.684 | $-0.45 | 3.0 | 2/5 | 1/7 |
| v5 | measured_ob_maker_p50 | $500 | 3 | 0.684 | $-1.12 | 3.0 | 2/5 | 1/7 |
| v5 | measured_ob_maker_p50 | $2000 | 3 | 0.684 | $-4.47 | 3.0 | 2/5 | 1/7 |
| v5 | measured_ob_maker_p90 | $200 | 3 | 0.566 | $-0.64 | 3.2 | 2/5 | 1/7 |
| v5 | measured_ob_maker_p90 | $500 | 3 | 0.566 | $-1.60 | 3.2 | 2/5 | 1/7 |
| v5 | measured_ob_maker_p90 | $2000 | 3 | 0.566 | $-6.41 | 3.2 | 2/5 | 1/7 |
| v5 | measured_ob_taker_p50 | $200 | 3 | 0.446 | $-0.90 | 3.4 | 1/5 | 1/7 |
| v5 | measured_ob_taker_p50 | $500 | 3 | 0.396 | $-2.60 | 3.5 | 1/5 | 1/7 |
| v5 | measured_ob_taker_p50 | $2000 | 3 | 0.313 | $-13.03 | 3.6 | 1/5 | 1/7 |
| v5 | measured_ob_taker_p90 | $200 | 3 | 0.157 | $-1.97 | 4.2 | 1/5 | 1/7 |
| v5 | measured_ob_taker_p90 | $500 | 3 | 0.074 | $-6.21 | 5.3 | 1/5 | 1/7 |
| v5 | measured_ob_taker_p90 | $2000 | 3 | 0.000 | $-30.97 | 6.6 | 0/5 | 1/7 |
| sl7 | measured_ob_maker_p50 | $200 | 3 | 0.684 | $-0.45 | 3.0 | 2/5 | 1/7 |
| sl7 | measured_ob_maker_p50 | $500 | 3 | 0.684 | $-1.12 | 3.0 | 2/5 | 1/7 |
| sl7 | measured_ob_maker_p50 | $2000 | 3 | 0.684 | $-4.47 | 3.0 | 2/5 | 1/7 |
| sl7 | measured_ob_maker_p90 | $200 | 3 | 0.566 | $-0.64 | 3.2 | 2/5 | 1/7 |
| sl7 | measured_ob_maker_p90 | $500 | 3 | 0.566 | $-1.60 | 3.2 | 2/5 | 1/7 |
| sl7 | measured_ob_maker_p90 | $2000 | 3 | 0.566 | $-6.41 | 3.2 | 2/5 | 1/7 |
| sl7 | measured_ob_taker_p50 | $200 | 3 | 0.446 | $-0.90 | 3.4 | 1/5 | 1/7 |
| sl7 | measured_ob_taker_p50 | $500 | 3 | 0.396 | $-2.60 | 3.5 | 1/5 | 1/7 |
| sl7 | measured_ob_taker_p50 | $2000 | 3 | 0.313 | $-13.03 | 3.6 | 1/5 | 1/7 |
| sl7 | measured_ob_taker_p90 | $200 | 3 | 0.157 | $-1.97 | 4.2 | 1/5 | 1/7 |
| sl7 | measured_ob_taker_p90 | $500 | 3 | 0.074 | $-6.21 | 5.3 | 1/5 | 1/7 |
| sl7 | measured_ob_taker_p90 | $2000 | 3 | 0.000 | $-30.97 | 6.6 | 0/5 | 1/7 |

## Gate Results

- **Passing ALL gates**: 0/24

- **Failing**: 24
  - v5/measured_ob_maker_p50/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p50/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p50/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p90/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p90/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_maker_p90/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p50/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p50/$500: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p50/$2000: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc
  - v5/measured_ob_taker_p90/$200: fails G1_trades_per_week, G2_max_gap_days, G3_exp_per_week, G4_stress_exp_per_week, G6_wf_folds_positive, G8_top1_fold_conc

## Verdict

**0/24 pass, BUT real VWAP generated 3 triggers vs 1 (HLC3).**

Real VWAP enables more triggers but trades are still unprofitable.
Root cause: exchange microstructure (fills, adverse selection), NOT VWAP source.

---
*Generated by run_bybit_vwap_validation.py at 2026-02-17 03:26*
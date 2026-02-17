# GATES.md — Canonical Validation Gate Specification

> Single source of truth. Code (`hf_validate.py`) and docs (`DECISIONS.md`, `README.md`) MUST match this file.
> Label: **4H variant research** — NOT true HF until sub-4H data pipeline exists.

## Gate Summary

| # | Gate | Type | Threshold | Verdict if Fail |
|---|------|------|-----------|-----------------|
| G1 | Trade Sufficiency | HARD | trades ≥ 20 | `INSUFFICIENT_SAMPLE` (blocks all other verdicts) |
| G2 | Purged Walk-Forward | HARD (soft @ 3/5) | ≥ 4/5 folds positive P&L or PF>1 | `NO-GO` (or `SOFT-GO` if 3/5 + all others pass) |
| G3 | Rolling Windows | HARD | ≥ 70% windows with P&L > $0 | `NO-GO` |
| G4 | Friction Stress | HARD | P&L > $0 at BOTH fee regimes | `NO-GO` |
| G5 | Concentration | HARD | top-1 coin < 40% AND top-3 coins < 70% of positive P&L | `NO-GO` |
| G6 | Latency Proxy | INFORMATIONAL | P&L > $0 at 1-candle-later fee (102 bps) | Reported in friction, not independent gate |

## Verdict Logic

```
IF trades < 20:
    verdict = INSUFFICIENT_SAMPLE
    reason = "only N trades (need >= 20)"
    → no GO/NO-GO issued

ELSE IF G2 PASS AND G3 PASS AND G4 PASS AND G5 PASS:
    verdict = GO

ELSE IF G2 soft_pass (3/5) AND G3 PASS AND G4 PASS AND G5 PASS:
    verdict = SOFT-GO

ELSE:
    verdict = NO-GO
    reason = list of failed gates
```

## Gate Definitions

### G1: Trade Sufficiency (HARD)

**Purpose**: Ensure minimum sample size for statistical validity.

- **Metric**: Total trade count from `run_backtest()` over full bar range
- **Threshold**: `trades >= 20`
- **Precedence**: Evaluated FIRST. If fail → `INSUFFICIENT_SAMPLE`, no other gates evaluated for verdict
- **Note**: Threshold is timeframe-relative. 20 trades on 4H/721 bars is marginal. On 1H data with 4x more bars, expect proportionally more trades for the same confidence.

### G2: Purged Walk-Forward (HARD, soft @ 3/5)

**Purpose**: Validate out-of-sample performance across time periods.

- **Construction**:
  - 5 folds, chronological (NOT shuffled)
  - Total bar range: `START_BAR` (50) to `n_bars` (721)
  - Usable bars = 721 - 50 = 671 → fold_size = 671 // 5 = 134 bars each
  - Fold i: test on bars `[start + i*fold_size, start + (i+1)*fold_size)`, last fold gets remainder
  - Embargo: 2 bars purged at each fold boundary (before test_start, after test_end)
  - Indicators precomputed causally up to `end_bar=test_end` per fold
  - Each fold runs `run_backtest(indicators, coins, cfg, start_bar=test_start, end_bar=test_end)`
- **"Positive" definition**: `P&L > $0` (i.e., `result["pnl"] > 0`). Additionally tracks `PF > 1.0`.
- **Threshold**: PASS if `positive_folds >= 4` OR `pf_above1_folds >= 4` (out of 5)
- **Soft pass**: `positive_folds >= 3` OR `pf_above1_folds >= 3`
- **Note**: This is NOT train-then-test. Each fold tests on one segment only. No training/optimization within the harness — the config is fixed.

### G3: Rolling Windows (HARD)

**Purpose**: Validate consistent profitability across non-overlapping time windows.

- **Construction**:
  - Window size: 180 bars (~30 days at 4H)
  - Start from `START_BAR` (50), create non-overlapping windows of 180 bars
  - Leftover bars form a final window if >= 90 bars (50% of window)
  - Indicators precomputed ONCE for full dataset (causal at time of precompute)
  - Each window runs `run_backtest(indicators, coins, cfg, start_bar=w_start, end_bar=w_end)`
- **"Positive" definition**: `P&L > $0`
- **Threshold**: ≥ 70% of windows must be positive
- **Current result**: 4/4 windows = 100% (well above 70%)

### G4: Friction Stress (HARD)

**Purpose**: Verify profitability survives realistic transaction costs.

- **Construction**:
  - Two fee regimes tested independently:
    - `2x+20bps`: `KRAKEN_FEE * 2 + 0.002 = 0.0072` (per side)
    - `1-candle-later`: `KRAKEN_FEE * 2 + 0.005 = 0.0102` (per side)
  - Uses `run_backtest(indicators, coins, cfg, fee_override=fee)`
  - Indicators precomputed once for full dataset
- **Threshold**: `P&L > $0` at BOTH regimes
- **Note**: 1-candle-later doubles as the latency proxy (G6)

### G5: Concentration (HARD)

**Purpose**: Ensure profits are not dominated by a few coins.

- **Construction**:
  - Run full backtest, extract `trade_list`
  - Aggregate P&L per coin (pair)
  - Denominator = `sum(max(0, coin_pnl))` — positive profit attribution only. NEVER use `abs(total_pnl)`.
  - Top-1 share = best coin's positive P&L / denominator
  - Top-3 share = sum of top 3 coins' positive P&L / denominator
- **Threshold**: `top1 < 40%` AND `top3 < 70%`
- **Note**: If no positive P&L exists, gate FAILs automatically

### G6: Latency Proxy (INFORMATIONAL)

**Purpose**: Quantify execution delay risk.

- **Construction**: Reads result from G4's 1-candle-later regime. Not an independent backtest.
- **Threshold**: Informational — reported as PASS/FAIL but does NOT independently cause NO-GO. The friction stress gate (G4) already covers this.
- **Note**: This gate exists for reporting clarity. The P&L at 102 bps effective fee models a scenario where entry is delayed by 1 candle (4H).

## Fee Model Reference

| Label | Fee per side | Effective round-trip | Source |
|-------|-------------|---------------------|--------|
| Baseline | 0.0026 (26 bps) | 52 bps | `KRAKEN_FEE` from `agent_team_v3.py` |
| 2x+20bps | 0.0072 (72 bps) | 144 bps | Stress test |
| 1-candle-later | 0.0102 (102 bps) | 204 bps | Latency proxy |

## Count: 5 Hard Gates + 1 Informational

The system evaluates **5 hard gates** (G1–G5) for verdict. G6 is informational and folded into G4's result.

When we say "6/6 gates passed" in reports, this means all 6 rows in the verdict table show PASS, but only G1–G5 drive the verdict.

## Alignment Checklist

- [ ] `hf_validate.py` constants match this spec (thresholds, fees, fold count, embargo)
- [ ] `DECISIONS.md` references GATES.md as canonical source
- [ ] `README.md` gate table matches this spec
- [ ] Report headers count "5 hard + 1 informational" not just "6 gates"

---
*Canonical spec — any conflict with other docs, this file wins.*

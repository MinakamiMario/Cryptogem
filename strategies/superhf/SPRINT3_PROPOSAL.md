# SuperHF Sprint 3 — Pivot Proposal

**Date**: 2026-02-23
**Status**: PROPOSED
**Scope**: Max 1 sprint, go/no-go decision at end

## Why Pivot

Sprint 1+2: 24 variants (12 configs x 2 exit modes), **0 with PF >= 1.0**.
Root cause: 15m entries at 1H zones are too noisy. RSI/BB exits decorrelated on 15m.

## Chosen Direction: Optie A — 1H Entries + 15m Confirmation

**Rationale**:
- 1H candles have 4x less noise than 15m → stronger zone signals
- Same 1H pivot/DC zones already computed and validated
- 15m used only for CONFIRMATION (precise timing), not signal generation
- DC exits proven on 1H (4H experience + Sprint 1 DC TARGET = 78% WR)

**Key difference vs Sprint 1**:
- Sprint 1: 15m generates entry signal → too noisy
- Sprint 3: 1H generates entry condition, 15m narrows timing → noise filtered by 1H

## Entry Families (3 families x 3-4 variants = 10 configs)

### Family C: 1H Bounce at Pivot Low (4 configs)
1H close touches/reclaims confirmed pivot low. 15m confirms green close + RSI uptick.

| ID | rsi_max_1h | zone_type | 15m_confirm |
|----|:----------:|:---------:|:-----------:|
| SHF-C01 | 35 | pivot_only | green_close |
| SHF-C02 | 40 | pivot_only | green_close |
| SHF-C03 | 35 | dc_bb_stack | green_close |
| SHF-C04 | 40 | dc_bb_stack | green_close |

### Family D: 1H DC Low Reclaim (3 configs)
1H close below Donchian low → next bar close reclaims above. Volume confirmation optional.

| ID | dc_lookback | vol_confirm | rsi_max_1h |
|----|:----------:|:----------:|:----------:|
| SHF-D01 | 20 | off | 40 |
| SHF-D02 | 20 | 1.5x | 40 |
| SHF-D03 | 30 | off | 40 |

### Family E: 1H Volume Capitulation (3 configs)
Adapted from Sprint 4 config 041 (best 4H config). Volume spike + price near BB lower/DC low on 1H.

| ID | vol_mult | bb_condition | rsi_max_1h |
|----|:--------:|:------------:|:----------:|
| SHF-E01 | 2.0 | close < bb_lower | 40 |
| SHF-E02 | 3.0 | close < bb_lower | 40 |
| SHF-E03 | 2.0 | close < bb_mid | 35 |

## Exit Chain

**DC-only exits (no RSI Recovery, no BB TARGET)**:
- FIXED STOP: max_stop_pct (test 10%, 15%)
- TIME MAX: time_max_bars (1H bars, test 10, 15 = 10-15H)
- DC TARGET: close >= dc_mid (1H Donchian mid)

Rationale: Sprint 1+2 proved RSI Recovery and BB TARGET are noise on short timeframes.
DC TARGET is the only consistently profitable exit (78% WR, +$8.8K in Sprint 1).

## Gates (stricter than Sprint 1)

| Gate | Threshold | Rationale |
|------|:---------:|-----------|
| G1 trades | >= 300 | 90 days × 3.3/day minimum |
| G2 PF | >= 1.10 | Minimum viable edge |
| G3 DD | <= 25% | Deployable drawdown (Sprint 1 had 62-96%) |
| G4 WF | >= 2/3 | Temporal stability |
| G5 concentration | top10 trades <= 50%, pnl <= 70% | Diversification |

## Decision Rule

- **>= 1 config passes all 5 gates**: GO to Sprint 4 (paper trading)
- **0 configs pass**: NO-GO, SuperHF project CLOSED
- **No further pivots** — this is the final attempt

## Implementation Notes

- Reuse `strategies/superhf/harness.py` (exit engine)
- Reuse `strategies/superhf/indicators.py` (pivot fractals, zone stacking, vectorized precompute)
- New: `strategies/superhf/hypotheses_s3.py` (10 configs, 3 families)
- New: `scripts/run_superhf_sprint3.py` (runner with stricter gates)
- Same data: `candle_cache_{15m,1h}_mexc_superhf.json` (163 coins)

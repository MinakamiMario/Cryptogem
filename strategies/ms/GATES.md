# MS Sprint 1 — Gate Definitions

## Hard Gates (KILL)

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| G0: TRADES | >= 80 | Minimum statistical significance |
| G1: PF | >= 1.0 | Positive expectancy after fees (26bps Kraken) |

**KILL condition**: 0/18 configs pass G1 → MS Sprint 1 CLOSED.

## Soft Gates (Advance to truth-pass)

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| G2: PF_ADVANCE | >= 1.10 | Buffer above breakeven for truth-pass |
| S1: DD | <= 50% | Drawdown within acceptable bounds |
| S2: WF | 2/3 folds PF >= 0.9 | Walk-forward stability (3 temporal folds) |
| S3: CONC | top1 coin < 30% trades | No single-coin concentration |
| S4: DC_GEO | informational | % entries satisfying close<dc_mid AND close<bb_mid AND rsi<40 |

## Sprint 1 Results (2026-03-02)

**7/18 GO** — 2 families survived:

| Family | GO | Best PF | Avg PF | DC-Geometry |
|--------|-----|---------|--------|-------------|
| shift_pb | 3/3 | 2.08 | 1.85 | Low (6-14%) |
| fvg_fill | 4/4 | 1.66 | 1.59 | Mixed (23-98%) |
| ob_touch | 0/4 | 0.72 | 0.67 | Low (20-24%) |
| liq_sweep | 0/4 | 0.76 | 0.67 | Medium (38-43%) |
| sfp | 0/3 | 0.63 | 0.59 | Medium (36-44%) |

## Walk-Forward (S2) Detail

All 7 GO configs pass S2 (3/3 folds PF >= 0.9):

| Config | F1 | F2 | F3 | Status |
|--------|-----|-----|-----|--------|
| ms_018 (shift_pb shallow) | 1.66 | 2.55 | 2.04 | 3/3 |
| ms_017 (shift_pb fib618) | 1.58 | 4.71 | 1.41 | 3/3 |
| ms_016 (shift_pb base) | 1.26 | 2.71 | 1.56 | 3/3 |
| ms_007 (fvg deep) | 1.61 | 1.29 | 1.91 | 3/3 |
| ms_005 (fvg base) | 1.86 | 2.06 | 1.52 | 3/3 |
| ms_008 (fvg wide) | 1.49 | 1.45 | 1.79 | 3/3 |
| ms_006 (fvg norsi) | 1.25 | 1.29 | 1.66 | 3/3 |

## Sprint 2 Truth-Pass Results (2026-03-02)

**4/4 VERIFIED** — all candidates pass all 3 robustness tests.

### Truth-Pass Gates

| Test | Criterion | Threshold |
|------|-----------|-----------|
| T1: Window Split | PF >= 1.0 in >= 2/3 windows | early/mid/late thirds |
| T2: Walk-Forward | Cal PF >= 1.0 AND Test PF >= 0.9 | Either split passes |
| T3: Bootstrap | P5_PF >= 0.85 AND >= 60% profitable | 1000 trade resamples |

Verdicts: ALL 3 PASS → VERIFIED, 2/3 → CONDITIONAL, ≤1/3 → FAILED

### Window Split Detail (T1)

| Config | Early PF | Mid PF | Late PF | Windows OK | Status |
|--------|----------|--------|---------|------------|--------|
| ms_018 (shift_pb shallow) | 1.71 | 2.65 | 2.01 | 3/3 | PASS |
| ms_005 (fvg base) | 2.05 | 2.21 | 1.56 | 3/3 | PASS |
| ms_017 (shift_pb fib618) | 1.62 | 5.06 | 1.35 | 3/3 | PASS |
| ms_007 (fvg deep) | 1.78 | 1.40 | 1.95 | 3/3 | PASS |

### Walk-Forward Detail (T2)

| Config | Split A (cal→test) | Split B (cal→test) | Status |
|--------|-------------------|-------------------|--------|
| ms_018 | 1.71→2.11 | 2.32→2.01 | 2/2 PASS |
| ms_005 | 2.05→1.62 | 2.01→1.56 | 2/2 PASS |
| ms_017 | 1.62→1.82 | 3.73→1.35 | 2/2 PASS |
| ms_007 | 1.78→1.68 | 1.51→1.95 | 2/2 PASS |

### Bootstrap Detail (T3)

| Config | Median PF | P5 PF | P95 PF | % Profitable | Status |
|--------|-----------|-------|--------|-------------|--------|
| ms_018 | 2.08 | 1.48 | 2.91 | 100% | PASS |
| ms_005 | 1.65 | 1.19 | 2.26 | 100% | PASS |
| ms_017 | 1.83 | 1.28 | 2.56 | 100% | PASS |
| ms_007 | 1.65 | 1.24 | 2.24 | 99% | PASS |

### Combined Verdicts

| Config | Family | Full PF | DD | T1 | T2 | T3 | Verdict |
|--------|--------|---------|-----|-----|-----|-----|---------|
| **ms_018** | shift_pb | 2.08 | 21.3% | PASS | PASS | PASS | **VERIFIED** |
| **ms_005** | fvg_fill | 1.65 | 19.5% | PASS | PASS | PASS | **VERIFIED** |
| **ms_017** | shift_pb | 1.80 | 28.0% | PASS | PASS | PASS | **VERIFIED** |
| **ms_007** | fvg_fill | 1.66 | 22.9% | PASS | PASS | PASS | **VERIFIED** |

## Next: Paper Trading Validation

Priority order:
1. **ms_018** (shift_pb shallow): Primary — PF=2.08, P5_PF=1.48, DD=21.3%, 697 trades
2. **ms_005** (fvg base): Secondary — PF=1.65, P5_PF=1.19, DD=19.5%, 429 trades
3. **ms_017** (shift_pb fib618): Reserve — PF=1.80, P5_PF=1.28, DD=28.0%
4. **ms_007** (fvg deep): Reserve — PF=1.66, P5_PF=1.24, DD=22.9%

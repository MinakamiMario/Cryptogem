# SuperHF — Architectural Decision Records

## ADR-SUPERHF-001: SuperHF Sprint 1 — MTF Mean Reversion Screening

**Date**: 2026-02-23
**Status**: COMPLETED — 0/12 PASS
**Sprint**: 1

### Context
Test 15m mean reversion entries at 1H support/resistance zones on MEXC top 200 coins.
Two entry families (pivot reclaim, sweep+reclaim) with hybrid_notrl exits (DC/BB/RSI targets).

### Decision
Screen 12 configs (2 families x 6 variants) with gates: PF>=1.10, trades>=80, WF>=2/3, concentration.

### Result
- **0/12 configs pass any gate except S1 (trades)**
- Best PF: 0.942 (SHF-A01), all configs PF < 1.0
- RSI RECOVERY is the primary loss source: 448 trades, -$8,340, 28% WR
- DC TARGET is profitable: 458 trades, +$8,816, 78% WR
- BB TARGET is profitable: 65-81% WR

### Root Cause
RSI Recovery on 15m is decorrelated from price recovery — triggers exit when price is still below dc_mid/bb_mid.

### Artifacts
- `reports/superhf/sprint1_scoreboard.json` — full results
- `reports/superhf/sprint1_scoreboard.md` — formatted scoreboard

---

## ADR-SUPERHF-002: Sprint 2 — Exit Optimization + NO-GO Decision

**Date**: 2026-02-23
**Status**: NO-GO — 15m pivot/sweep entry families eliminated
**Sprint**: 2

### Context
Sprint 1 showed RSI Recovery as primary loss driver. Two fixes tested:
1. **Sprint 2A** (exit priority reorder): STOP/TM -> DC -> BB -> RSI (was: STOP/TM -> RSI -> DC -> BB)
2. **Sprint 2B** (disable RSI Recovery): rsi_recovery=False for all 12 configs

### Sprint 2A Result
- **Delta PF = 0.000 on all 3 configs** — exits do NOT overlap
- RSI Recovery fires exclusively when close < dc_mid AND close < bb_mid
- Reordering has zero effect because conditions are mutually exclusive

### Sprint 2B Result (all 12 configs, rsi_recovery=False)
- 9/12 configs improve marginally (+0.003 to +0.103 PF)
- **0/12 configs reach PF >= 1.0** (best: SHF-A01 PF=0.955)
- BB TARGET becomes the new loss source (32-54% WR, up to -$2.3K)
- DD remains extreme: 62-95%
- Trade count drops 7-12% (former RSI exits redistribute to TIME MAX / FIXED STOP)

### Structural Finding
The 15m entries (pivot reclaim / sweep+reclaim) generate **no statistical edge**:
1. Entries trigger too often on noise at 15m resolution
2. BB mid is too close on 15m to serve as profitable exit target
3. RSI-price correlation that works on 4H breaks down on 15m
4. DC TARGET is the only profitable exit, but cannot overcome entry noise

This mirrors the 4H Sprint 1+2 pattern (63 configs, 0 GO): exits cannot compensate for edgeless entries.

### Decision
**NO-GO** for 15m pivot reclaim and sweep+reclaim entry families.
Pivot to Sprint 3 with different entry approach (see ADR-SUPERHF-003).

### Provenance
- **Data**: `candle_cache_15m_mexc_superhf.json` (163 coins, 217 MB), `candle_cache_1h_mexc_superhf.json` (163 coins, 55 MB)
- **Universe**: superhf_mexc_top200, 163 coins with >= 1000 15m bars + >= 50 1H bars
- **Engine**: `strategies/superhf/harness.py` (hybrid_notrl exits, MEXC 10bps/side)
- **Configs**: `strategies/superhf/hypotheses.py` (12 configs, 2 families)
- **Sprint 1 runner**: `scripts/run_superhf_sprint1.py`
- **Sprint 2A runner**: `scripts/run_superhf_sprint2.py`
- **Sprint 2B runner**: `scripts/run_superhf_sprint2b_norsi.py`

### Artifacts
- `reports/superhf/sprint1_scoreboard.{json,md}` — Sprint 1 full results
- `reports/superhf/sprint2_exit_reorder.{json,md}` — Sprint 2A (reorder, 0 delta)
- `reports/superhf/sprint2b_norsi.{json,md}` — Sprint 2B (no RSI, marginal improvement)

---

## ADR-SUPERHF-003: Sprint 3 — Signal R&D + CLOSED Decision

**Date**: 2026-03-02
**Status**: CLOSED — 0/20 configs PF ≥ 1.0, SuperHF project terminated
**Sprint**: 3

### Context
Sprint 2 eliminated the original 15m pivot/sweep entries. Sprint 3 tested 20 new configs across 3 independent signal tracks, incorporating lessons from 4H Sprint 4 (DC-geometry gates) and HF VWAP_DEV (HLC3 VWAP proxy).

### Signal Tracks

**Track 1 — VWAP Deviation on 15m** (6 configs, Family F):
- Ported HF H20 VWAP_DEV to 15m with HLC3 proxy `(H+L+C)/3`
- Raw deviation (F01-F03): `dev_thresh ∈ {0.2, 0.3, 0.5}` + bounce confirmation
- Z-score normalized (F04-F06): `zscore_thresh ∈ {1.0, 1.5, 2.0}`

**Track 2 — 1H Entry + 15m Timing** (10 configs, Families C/D/E):
- Family C (4): Pivot reclaim + mandatory DC-geometry gate
- Family D (3): DC low reclaim on 15m with 1H zone confirmation
- Family E (3): Volume capitulation (ported from 4H sprint4_041)

**Track 3 — DC-Geometry + VWAP Hybrid** (4 configs, Family G):
- Conjunction: DC-geometry gate AND VWAP deviation threshold
- `dev_thresh ∈ {0.3, 0.5}` × `rsi_thresh ∈ {35, 40}`

### Results

| Track | Configs | Best PF | Best Config |
|-------|---------|---------|-------------|
| Track 1 (VWAP) | 6 | 0.908 | SHF-F02 (raw dev≥0.3) |
| Track 2 (1H+15m) | 10 | 0.943 | SHF-C02 (pivot+DC-geo, RSI<35) |
| Track 3 (Hybrid) | 4 | 0.913 | SHF-G02 (DC-geo+VWAP dev≥0.3) |
| **Total** | **20** | **0.943** | **0/20 PF ≥ 1.0** |

### Exit Attribution (all 20 configs aggregated)

| Exit | Count | Share | P&L | WR |
|------|------:|------:|----:|---:|
| DC TARGET | 6,186 | 45% | +$57,928 | 73% |
| RSI RECOVERY | 4,400 | 32% | -$59,415 | 29% |
| BB TARGET | 3,114 | 23% | +$8,340 | 62% |
| FIXED STOP | 90 | 1% | -$22,381 | 0% |
| TIME MAX | 32 | 0% | -$3,883 | 0% |

### Structural Findings

1. **RSI RECOVERY is structurally broken on 15m**: -$59,415 across 4,400 exits (29% WR). RSI recovers to 45 within ~8 bars (2h) on noise, triggering premature exits while price is still below dc_mid/bb_mid.

2. **DC TARGET is the only consistently profitable exit**: +$57,928 across 6,186 exits (73% WR). But it cannot overcome RSI RECOVERY drain + entry noise combined.

3. **VWAP deviation on 15m is weak**: HLC3 proxy structural cap (~0.3 ATR max raw deviation) limits signal strength. Z-score normalization did not rescue performance.

4. **DC-geometry gates help but not enough**: Track 2 (with mandatory DC-geo) outperformed Track 1 (VWAP-only) but still sub-1.0 PF. Geometry is necessary but insufficient on 15m.

5. **Volume capitulation fails on 15m**: Family E (ported from 4H sprint4_041 VERIFIED) did not translate — 15m volume spikes are too noisy to isolate genuine capitulation.

6. **Cross-sprint consistency**: RSI RECOVERY has been the #1 loss source in ALL 3 sprints (Sprint 1: -$8,340; Sprint 2B: redistributed to TIME MAX/STOP; Sprint 3: -$59,415).

### Cumulative SuperHF Assessment

| Sprint | Configs | Families | Best PF | Pass PF≥1.0 |
|--------|---------|----------|---------|-------------|
| Sprint 1 | 12 | 2 (pivot, sweep) | 0.942 | 0 |
| Sprint 2B | 12 | 2 (no RSI) | 0.955 | 0 |
| Sprint 3 | 20 | 5 (VWAP, DC-geo, hybrid) | 0.943 | 0 |
| **Total** | **44** | **7** | **0.955** | **0** |

44 configs across 7 entry families, 3 exit variations, 3 sprints. Zero configs reach PF ≥ 1.0. The 15m + 1H multi-timeframe approach on MEXC has no detectable statistical edge.

### Decision
**CLOSED**. SuperHF project terminated.

KILL gate (PF ≥ 1.0 for any config) triggered with 0/20 pass. Combined with Sprint 1+2 results (0/24 pass), the evidence is conclusive: 15m mean reversion entries at 1H zones do not generate tradeable edge on MEXC top-200 coins.

### Pivot Recommendation
1. **HF VWAP_DEV paper trading** (ADR-HF-034, CONDITIONAL GO, PF=2.86 maker on MEXC) — validated signal, needs paper validation only
2. **4H Vol Capitulation 041** (ADR-4H-010, VERIFIED truth-pass, PF=1.41) — proven on 526 coins

### Provenance
- **Data**: `candle_cache_15m_mexc_superhf.json` (163 coins), `candle_cache_1h_mexc_superhf.json` (163 coins)
- **Universe**: superhf_mexc_top200, 163 coins with >= 1000 15m bars + >= 50 1H bars
- **Engine**: `strategies/superhf/harness.py` (hybrid_notrl exits, MEXC 10bps/side)
- **Configs**: `strategies/superhf/hypotheses_s3.py` (20 configs, 5 families)
- **Runner**: `scripts/run_superhf_sprint3.py`
- **Indicators**: `strategies/superhf/indicators.py` (HLC3 VWAP patch, DC channels, BB)

### Artifacts
- `reports/superhf/sprint3_scoreboard.{json,md}` — full results + exit attribution
- `strategies/superhf/hypotheses_s3.py` — 20 signal configs (families C-G)
- `scripts/run_superhf_sprint3.py` — sweep runner with track filtering

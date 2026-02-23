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

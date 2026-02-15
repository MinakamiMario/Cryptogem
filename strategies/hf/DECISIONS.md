# HF DECISIONS — Architectural Decision Records

> 4H variant research. NOT true HF until sub-4H data pipeline exists.

---

## ADR-HF-001: Champion H2 vs GRID_BEST — No Promotion

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: H2 grid sweep (1280 configs) produced Champion H2 (vs3.0/rsi45/tp12/sl8/tm15). Both Champion H2 and GRID_BEST passed all 6 validation gates (GO verdict). Sprint 1 ran full validation, red-team, data audit, and tail risk analysis.

**Comparison**:

| Metric | Champion H2 | GRID_BEST | Winner |
|--------|-------------|-----------|--------|
| P&L (baseline) | $+4,114 | $+4,718 | GRID_BEST |
| PF | 2.73 | 2.61 | Champion H2 |
| Max DD | 24.7% | 16.4% | GRID_BEST |
| WR | 67.7% | 68.8% | GRID_BEST |
| Trades | 31 | 32 | ~tie |
| WF folds positive | 5/5 | 5/5 | tie |
| Rolling windows positive | 4/4 | 4/4 | tie |
| Friction 2x+20bps P&L | $+2,608 | $+3,019 | GRID_BEST |
| Friction 1-candle P&L | $+1,827 | $+2,144 | GRID_BEST |
| Concentration top1 | 11.5% | 12.0% | ~tie |
| Max consec losses | 3 | 2 | GRID_BEST |
| Breakeven friction | >102bps | >102bps | tie |

**Decision**: Do NOT promote Champion H2. GRID_BEST remains production config.

**Rationale**:
1. Champion H2 is $604 behind GRID_BEST on baseline P&L
2. Champion H2 has 50% higher DD (24.7% vs 16.4%) — worse risk-adjusted returns
3. Champion H2 configs converged to near-GRID_BEST (only diffs: vs3.0→2.5, sl8→10)
4. RSI parameter is insensitive at vs>=3.0 — top 4 configs identical across rsi_max 45-60
5. 31 trades on 721 bars (4H, ~120 days) is marginal sample size
6. Both survive friction stress but GRID_BEST has ~$400 more headroom

**Consequence**: Champion H2 stays as "champion-candidate" in config.json. No production changes.

---

## ADR-HF-002: 4H Parameter Space Exhausted

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: H2 sweep explored 1280 configs across 5 axes. The champion converged back toward GRID_BEST parameters. H1 (mean reversion) was weak (PF 1.18). H3 (vol breakout) had too few trades (15). The 4H timeframe with DualConfirm appears thoroughly explored.

**Evidence**:
- Grid sweep top-10 all share vs3.0/tp12/sl8 — only RSI and time_max vary
- RSI insensitive at vs>=3.0 (scores identical across rsi45-60)
- No config in the grid materially outperformed GRID_BEST on risk-adjusted basis
- Red team finding: Champion H2 "statistically indistinguishable from GRID_BEST"

**Decision**: Stop iterating on 4H DualConfirm parameter grid. Future alpha must come from:
1. New timeframes (1H, 15m) requiring data pipeline
2. New signal families (multi-TF confirmation, microstructure)
3. New exit strategies (trailing stops, volatility-adjusted exits)

**Consequence**: Phase 3 shifts to data pipeline + new timeframe exploration, not more 4H sweeps.

---

## ADR-HF-003: Data Quality — Acceptable with Caveats

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Data audit of 425 tradeable symbols found 152 flags.

**Key findings**:
- 0 OHLCV violations (clean price data)
- 98.1% symbols have full 721-bar coverage
- 6 symbols with consecutive zero-volume bars (max 15 bars = ~2.5 days)
- 140 symbols with extreme volume spikes (>100x median)
- 6 symbols with slightly low bar counts (687-699 vs 721)
- Volume range spans 10 orders of magnitude (P10=645 to P99=6.2B)

**Decision**: Data is acceptable for 4H research. No symbols excluded.

**Rationale**:
1. Zero-vol symbols (6) are rare and don't trigger trades (vol_confirm=True filters them)
2. Volume spikes are expected in crypto — the strategy uses vol_spike_mult as a feature, not a bug
3. Low-bar symbols (6) have >95% coverage — negligible impact on 425-symbol universe
4. COQ/USD is worst coin for both configs ($-410 and $-569) but removing it improves P&L — not a data issue, just a losing trade

**Caveat**: Volume anomalies may become problematic at lower timeframes (15m/1H) where spike detection is more sensitive. Re-audit required when sub-4H data is added.

---

## ADR-HF-004: Tail Risk — Acceptable

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Tail risk analysis ran friction ladder (7 levels), worst-coin removal, consecutive loss analysis, and window-based drawdown for both configs.

**Key findings**:
- Both configs profitable at max tested friction (102 bps)
- Latency sensitivity: ~55% P&L loss at 1-candle-later entry (expected for momentum)
- Max consecutive losses: 3 (Champion H2), 2 (GRID_BEST)
- No windows with DD>30%
- Worst coin (COQ/USD) contributes -10% of total P&L — not concentrated

**Decision**: Tail risk is acceptable for current 4H variant research.

**Open risk from red team**:
- Stop-loss fill optimism (HIGH): backtester uses exact sl_pct, real fills may gap
- Flat slippage model (HIGH): 20bps slippage is uniform, real slippage varies by coin/time
- Small sample N=31 (HIGH): too few trades for statistical confidence on tail behavior

---

## ADR-HF-005: Gate Canon — 5 Hard + 1 Informational

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Sprint 1 reports said "6/6 gates passed" but the gate list was ambiguous — latency proxy was not an independent test (it reused friction stress results). Gate definitions (fold construction, "positive" criteria) were not formally documented.

**Decision**: Create `GATES.md` as canonical single source of truth.

**Gate canon**:

| # | Gate | Type | Threshold |
|---|------|------|-----------|
| G1 | Trade Sufficiency | HARD | trades ≥ 20 (blocks all verdicts if fail → `INSUFFICIENT_SAMPLE`) |
| G2 | Purged Walk-Forward | HARD (soft @ 3/5) | ≥ 4/5 folds with P&L > $0 or PF > 1 |
| G3 | Rolling Windows | HARD | ≥ 70% windows P&L > $0 |
| G4 | Friction Stress | HARD | P&L > $0 at BOTH 72bps and 102bps regimes |
| G5 | Concentration | HARD | top1 < 40% AND top3 < 70% of positive P&L |
| G6 | Latency Proxy | INFO | reads G4 1-candle result; does NOT independently cause NO-GO |

**Definitions locked in GATES.md**: WF = 5 folds, chronological, embargo=2, fold_size=134 bars, indicators causal per fold. Rolling = 180-bar non-overlapping windows, leftover included if ≥ 90 bars. "Positive" = `pnl > 0`.

**Consequence**: Code (`hf_validate.py`) unchanged — already implements this. Reports now say "5 hard + 1 informational" instead of "6/6".

---

## ADR-HF-006: Volume Ablation — Edge MODERATE Dependence on Anomaly Symbols

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Data audit flagged 147/425 symbols (volume spikes, zero-vol runs, low bar count). Entry signal uses `vol_spike_mult`, so edge could lean on "volume noise" coins.

**Evidence** (volume_ablation_001):

| Subset | Champion H2 | GRID_BEST |
|--------|-------------|-----------|
| ALL (425) | $+4,114 / 31 trades / PF 2.73 | $+4,718 / 32 trades / PF 2.61 |
| CLEAN (278) | $+2,374 / 24 trades / PF 2.26 | $+3,058 / 22 trades / PF 3.44 |
| FLAGGED (147) | $+2 / 25 trades / PF 1.00 | $+406 / 26 trades / PF 1.22 |
| Clean ratio | 57.7% | 64.8% |
| Verdict | MODERATE | MODERATE |

**Decision**: Edge survives on clean symbols but is modestly diluted (~35-42% P&L comes from flagged symbols). This is NOT critical — flagged symbols are tradeable on Kraken, and the vol_spike_mult filter is working as designed. However, GRID_BEST is more robust on clean symbols (PF improves from 2.61 → 3.44).

**Action**: Monitor clean-subset performance on future timeframes. Do NOT exclude flagged symbols yet — they are real tradeable assets with real volume events.

---

## ADR-HF-007: Latency Fragility — ROBUST After Proper Stress Test

**Date**: 2026-02-15
**Status**: DECIDED — supersedes initial concern from Sprint 1
**Context**: Sprint 1 showed -55.6% P&L at 1-candle-later entry (fixed fee model). This looked like a red flag. Sprint 1.5 ran proper Monte Carlo stress test with random 0/1/2-candle delays.

**Evidence** (latency_stress_001):

| Config | 0-candle | 1-candle | 2-candle | MC Mean | MC P5 | Survival | Verdict |
|--------|----------|----------|----------|---------|-------|----------|---------|
| Champion H2 | $+4,114 | $+1,827 | $+801 | $+2,888 | $+801 | 100% | ROBUST |
| GRID_BEST | $+4,718 | $+2,144 | $+1,004 | $+3,203 | $+1,004 | 100% | ROBUST |

**Decision**: Latency fragility is NOT a blocking concern. Both configs remain profitable even at worst-case 2-candle delay. 100% survival across 50 Monte Carlo trials. The -55.6% figure was misleading — it's P&L degradation, not P&L destruction.

**Key insight**: At 4H timeframe, a 1-candle delay = 4 hours. Real execution latency is seconds, not hours. Latency risk is primarily relevant at sub-4H timeframes.

---

## ADR-HF-008: Universe Tiering — Edge Depends on Mid-Cap, NOT Liquid Coins

**Date**: 2026-02-15
**Status**: DECIDED — critical finding for live trading
**Context**: Worst coin (COQ/USD) suggested microcap dependency. Universe tiering tested 3 tiers by liquidity.

**Evidence** (universe_tiering_001):

| Tier | Count | Median Vol | Champion H2 P&L | GRID_BEST P&L |
|------|-------|-----------|-----------------|----------------|
| Tier 1 (Liquid, top 25%) | 100 | 1.29M | $+38 (0.9%) | $+284 (6.0%) |
| Tier 2 (Mid, P25-P75) | 216 | 44.8K | $+1,695 (41.2%) | $+1,795 (38.0%) |
| Tier 3 (Illiquid, bottom) | 109 | 2.0K | $+697 (17.0%) | $+837 (17.7%) |
| Full universe | 425 | — | $+4,114 | $+4,718 |

**Decision**: The DualConfirm edge is concentrated in **Tier 2 (mid-cap)** coins. Tier 1 liquid coins contribute almost nothing. This is a structural characteristic of the vol_spike_mult entry filter — liquid coins have less dramatic volume events.

**Implication for live trading**:
1. Strategy cannot run on liquid-only universe — edge collapses
2. Mid-cap + illiquid coins ARE the edge, but carry execution risk (wider spreads, thinner books)
3. The flat slippage model (20bps uniform) is OPTIMISTIC for Tier 2/3 coins
4. This reinforces ADR-HF-002: true alpha requires different signal families or lower timeframes

**Action**: When building 1H/15m pipeline, include a per-coin slippage model calibrated to volume tier. Do NOT assume flat 20bps for Tier 3 coins.

---

## Sprint 1.5 Summary

**Deliverables**:
| Fix | Artifact | Finding |
|-----|----------|---------|
| Gate canon | GATES.md | 5 hard + 1 informational, definitions locked |
| Volume ablation | hf_volume_ablation.py + report | MODERATE — 58-65% edge survives clean |
| Latency stress | hf_latency_stress.py + report | ROBUST — 100% survival, 50 MC trials |
| Universe tiering | hf_universe_tiering.py + report | CRITICAL — edge depends on Tier 2, Tier 1 ≈ 0% |

**Updated Sprint 2 Recommendations** (revised from Sprint 1):
1. Build 1H/15m data pipeline with per-coin volume tier metadata
2. Calibrate slippage model per tier (flat 20bps is optimistic for Tier 2/3)
3. Test whether DualConfirm edge exists at all on Tier 1 coins at lower timeframes
4. Explore new signal families designed for liquid coins (momentum, order flow)
5. Address HIGH red-team risks: stop-loss fill realism + tier-aware slippage

---

## Sprint 1 Summary

**Deliverables**:
| Agent | Artifact | Status |
|-------|----------|--------|
| Builder | hf_validate.py + validate_001 | PASS — both configs GO |
| Red Team | attack_checklist.md + attack_001.md | 4 HIGH, 6 MED, 8 LOW risks |
| Data | hf_data_audit.py + data_audit_001 | 152 flags, 0 critical |
| Risk | hf_tail_risk.py + risk_001 | Acceptable tail risk |
| Researcher | hf_hypotheses.md | 3 HF families identified |

**Sprint 2 Recommendations**:
1. Build 1H/15m data pipeline (Kraken OHLCV fetcher + cache management)
2. Validate DualConfirm on 1H data (same gates, expect more trades)
3. Explore Family B: Multi-TF Confirmation (4H signal + 1H execution)
4. Address HIGH red-team risks: slippage model + stop-loss fill realism

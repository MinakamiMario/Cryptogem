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

## ADR-HF-009: Per-Tier Friction — MARGINAL Under Realistic Costs

**Date**: 2026-02-15
**Status**: DECIDED — key finding for live viability
**Context**: Sprint 1 used flat KRAKEN_FEE (26bps) or flat 20bps slippage. ADR-HF-008 showed edge lives in Tier 2 mid-caps. Sprint 2 built per-tier slippage model to answer: "How much P&L survives realistic execution costs?"

**Fee model (per side)**:

| Tier | Base | Slippage | Total | Rationale |
|------|------|----------|-------|-----------|
| Tier 1 (Liquid) | 26 bps | 5 bps | 31 bps | Tight spreads, deep books |
| Tier 2 (Mid) | 26 bps | 30 bps | 56 bps | Wider spreads, thinner books |
| Tier 3 (Illiquid) | 26 bps | 75 bps | 101 bps | Wide spreads, minimal depth |

**Evidence** (friction_v2_001):

| Model | Champion H2 | GRID_BEST |
|-------|-------------|-----------|
| Flat baseline (26bps) | $+4,114 / PF 2.73 | $+4,718 / PF 2.61 |
| Flat 20bps (46bps) | $+3,408 / PF 2.45 | $+3,920 / PF 2.37 |
| **Per-tier composite** | **$+1,346 / PF 1.34** | **$+1,770 / PF 1.43** |
| Per-tier 2x stress | $+437 / PF 1.11 | $+816 / PF 1.19 |
| Retained (composite/baseline) | 32.7% | 37.5% |

**Per-tier breakdown (composite)**:

| Tier | Champion H2 | GRID_BEST |
|------|-------------|-----------|
| Tier 1 | $+4 / PF 1.00 | $+243 / PF 1.16 |
| Tier 2 | **$+1,222 / PF 1.71** | **$+1,329 / PF 1.91** |
| Tier 3 | $+121 / PF 1.12 | $+198 / PF 1.17 |

**Decision**: Strategy is **MARGINAL** under realistic friction. Both configs retain only 33-38% of flat-baseline P&L. However:
1. Both remain profitable (P&L > $0)
2. Tier 2 is the clear alpha driver under friction too (PF 1.71/1.91)
3. 2x stress still positive for both configs
4. GRID_BEST is more robust than Champion H2 (again)

**Implication**: The "headline" P&L of $4,114/$4,718 was inflated by unrealistic friction. Realistic P&L is ~$1,350–$1,770 over 120 days on $2K capital (67-88% annualized return). Still positive, but margins are thin.

---

## ADR-HF-010: Per-Tier Gate Validation — Tier 1+2 (Live) PASSES All Gates

**Date**: 2026-02-15
**Status**: DECIDED — critical for live eligibility
**Context**: Sprint 2.3 ran all 5 hard gates per tier with tier-appropriate friction.

**Evidence** (validate_per_tier_001):

| Config | Tier 1 | Tier 2 | Tier 3 | **Tier 1+2 (Live)** |
|--------|--------|--------|--------|---------------------|
| Champion H2 | INSUFFICIENT_SAMPLE (17 trades) | **GO** (5/5 gates) | INSUFFICIENT_SAMPLE (16 trades) | **GO** (5/5 gates) |
| GRID_BEST | INSUFFICIENT_SAMPLE (18 trades) | **SOFT-GO** (WF 3/5) | INSUFFICIENT_SAMPLE (17 trades) | **GO** (5/5 gates) |

**Key findings**:
1. **Tier 1 alone**: INSUFFICIENT_SAMPLE for both configs (17-18 trades < 20). Even with enough trades, WF fails (2/5) and concentration is too high (top1 ~40%, top3 ~71%)
2. **Tier 2 alone**: Champion H2 = GO (all gates). GRID_BEST = SOFT-GO (WF 3/5, but all other gates pass). Friction stress passes even at 2x tier fee.
3. **Tier 3 alone**: INSUFFICIENT_SAMPLE. Friction stress fails hard at tier fee.
4. **Tier 1+2 (Live universe, 316 coins)**: Both configs = **GO**. All 5 hard gates pass. This is the recommended live universe.

**Decision**: Live trading universe = Tier 1 + Tier 2 (316 coins). Tier 3 excluded. Conservative fee = 56bps (Tier 2 fee applied to all).

**Live eligibility per UNIVERSE_POLICY.md**:
- [x] All 5 hard gates PASS (Tier 1+2) ✓
- [x] Per-tier friction composite P&L > $0 ✓
- [x] Tier 2 alone P&L > $0 under tier friction ✓
- [x] Per-tier 2x stress P&L > $0 ✓
- [x] No Tier 3 coins ✓

---

## ADR-HF-011: Universe Policy Established

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: `UNIVERSE_POLICY.md` defines inclusion filters, tier assignment, capacity limits, and live eligibility criteria.

**Decision**: See `UNIVERSE_POLICY.md` for full spec. Key rules:
1. Min median volume ≥ P25 (~$8,300) — excludes Tier 3
2. Max zero-volume candles < 20%
3. Min bar coverage ≥ 95%
4. Per-tier fees: T1=31bps, T2=56bps per side
5. Live universe = Tier 1 + Tier 2 = 316 coins

---

## ADR-HF-012: Allocator Experiment — max_pos>1 Does NOT Improve Risk-Adjusted Returns

**Date**: 2026-02-15
**Status**: DECIDED — critical finding, blocks allocator-based throughput path
**Context**: With max_pos=1 producing only ~2 trades/week and 73% zero-trade days, the hypothesis was that max_pos=2 or 3 with tier quotas and correlation guardrails could boost throughput 2-4x without destroying risk-adjusted returns. Two methods tested:
- **Method A**: Native engine max_pos=1/2/3 on T1+T2 with per-tier fees (no quotas)
- **Method B**: Custom allocator with 9 policies (tier quotas, T1 slot reservation, correlation guard at ρ>0.70)

**Evidence** (allocator_001):

Method A — Native max_pos (GRID_BEST):

| max_pos | Trades | P&L | PF | DD% | Tr/wk |
|---------|--------|-----|----|-----|-------|
| 1 | 40 | $+1,572 | 1.53 | 27.8% | 2.22 |
| 2 | 52 | $+993 | 1.57 | 24.6% | 2.89 |
| 3 | 8 | $-1,975 | 0.06 | 98.8% | 0.44 |

Method B — Best policies (GRID_BEST):

| Policy | Trades | P&L | PF | DD% |
|--------|--------|-----|----|-----|
| baseline_mp1 (mp=1, no quota) | 29 | $+2,114 | 1.84 | 17.5% |
| mp2_no_quota (mp=2) | 37 | $+1,339 | 2.08 | 12.5% |
| mp3_corr_guard (mp=3, corr=Y) | 48 | $+885 | 1.96 | 10.2% |

**Key findings**:

1. **max_pos=3 is catastrophic in Method A**: Engine splits equity across 3 slots, smaller position sizes get destroyed by fees. GRID_BEST goes from +$1,572 → -$1,975.

2. **max_pos=2 is marginal**: +30% more trades but P&L drops 37% (Method A). PF slightly improves but absolute returns worse.

3. **Custom allocator (Method B) consistently outperforms engine**: The custom allocator's baseline_mp1 ($+2,114, PF 1.84) beats the engine's mp=1 ($+1,572, PF 1.53). This is because the allocator applies per-trade tier fees correctly (engine per-tier run uses isolation which changes signal crowding).

4. **Correlation guard works**: mp3_corr_guard (48 trades, PF 1.96, DD 10.2%) is the best risk-adjusted mp=3 policy — the guard blocks 27 correlated entries, keeping only diversified ones.

5. **T1 slot reservation reduces P&L**: mp2_full (T1 reserve + corr guard) drops P&L from $1,339 → $757. Reserving T1 slots forces suboptimal entries in a tier with near-zero alpha.

6. **The "throughput problem" is structural**: At 4H with DualConfirm, signals are rare (~2/week). Adding slots doesn't create more signals — it just splits existing capital thinner.

**Decision**: Do NOT pursue allocator-based throughput improvement for 4H DualConfirm. The edge is thin (ADR-HF-009: MARGINAL) and adding positions dilutes per-trade returns faster than throughput gains compensate.

**Implication for next steps**:
- Throughput improvement requires **more signals** (sub-4H pipeline or new signal families), not more position slots
- If mp=2 is ever reconsidered, use quota-aware allocator with correlation guard (best DD profile at 10-12%)
- The correlation guard is the one genuine contribution: it filters out correlated entries effectively (27 blocks at mp=3)

---

## Sprint 3 Summary — 1H/15m Data Pipeline + MTF Validation

**Deliverables**:
| Task | Artifact | Description |
|------|----------|-------------|
| Data pipeline | scripts/build_hf_cache.py | Paginated 1H/15m fetcher (Kraken + MEXC) |
| Data audit MTF | hf_data_audit_mtf.py | Timeframe-aware OHLCV integrity checks |
| Alignment tests | hf_alignment_tests.py (35 tests) | No-leak + MTF mapping verification |
| MTF rules | hf_mtf_rules.md | Close-bar rules + wall-clock semantics |
| Friction v3 | hf_friction_v3.py | Per-tier fees + capacity proxy metrics |
| Latency stress MTF | hf_latency_stress_mtf.py | MC stress with TF-aware delay model |
| MTF validation | hf_validate_mtf.py | A/B config (as-is vs scaled) + full gate suite |
| Gates MTF | GATES_MTF.md | Timeframe-scaled gate parameters |
| Correlation | hf_correlation.py | Rolling pairwise Pearson on signal-generating coins |
| Exposure caps | hf_exposure_caps.py | Log-only at mp=1, hard-gate at mp>1 |
| ADRs | ADR-HF-013 through ADR-HF-017 | 5 architecture decisions |

**Key design decisions**:
- Engine is timeframe-agnostic (bar-count based) — no modifications needed
- A/B config methodology prevents false-negative verdicts at lower TFs
- Data manifests gitignored; committed snapshots in reports/hf/
- Alignment tests integrated into `make hf-check` (35 tests green)

**Sprint 4 Recommendations** (after 1H/15m data available):
1. Run `build_hf_cache.py --timeframe 1h` to fetch 1H data (~23 min)
2. Run MTF validation with A/B configs: `hf_validate_mtf.py --timeframe 1h`
3. If 1H passes → repeat for 15m
4. If 1H passes with scaled params → grid-search TF-appropriate parameters
5. If 1H fails → explore new signal families for lower timeframes

---

## ADR-HF-013: 1H/15m Data Pipeline — New Script, Import Shared Helpers

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Sprint 3 needs 1H and 15m candle data. Two approaches: (a) parameterize existing `build_research_cache.py` with `--interval`, or (b) new script importing shared helpers.

**Decision**: New script `scripts/build_hf_cache.py`. Imports shared helpers (BASE_MAP, EXCLUDE_BASES) but has its own paginated fetch logic since Kraken returns max 720 candles/call.

**Rationale**:
1. Existing script has no pagination — 4H gets 720 bars in 1 call, but 1H needs ~4 calls, 15m needs ~16
2. Parameterizing would add complexity to a working script without benefit
3. New script has `--timeframe` arg, manifest per TF, and snapshot to `reports/hf/`
4. Runtime manifests (`data/manifest_hf_*.json`) gitignored; committed snapshots in `reports/hf/data_manifest_*.json`

---

## ADR-HF-014: No-Leak Verification via External Tests (Engine Read-Only)

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: The backtest engine (`agent_team_v3.py`) is read-only. We cannot add leak-detection instrumentation inside it. Need external tests to verify causal correctness.

**Decision**: `hf_alignment_tests.py` runs 7 test categories:
1. Indicator causality (precompute_all end_bar independence)
2. Signal determinism (check_entry_at_bar consistency)
3. Walk-forward isolation (fold result independence)
4. Cooldown semantics documentation (wall-clock table)
5. Window scaling sanity (fold sizes in days)
6. MTF data alignment (tests 1-3 on 1H/15m when available)
7. MTF mapping (last_closed_4h_bar correctness + no-lookahead proof)

**Evidence**: 35/35 tests pass on 4H data. MTF mapping test proves no look-ahead with mathematical invariant: `(N+1)*4 - 1 <= K` for all mapped pairs.

**Consequence**: `make hf-check` now runs alignment tests as gate. Tests 6 re-run on 1H/15m once data pipeline delivers.

---

## ADR-HF-015: Per-Trade Fees Unchanged, Capacity Proxy Added

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Moving to lower timeframes means more trades. Need to understand whether increased trade count erodes edge through fee drag.

**Decision**: Keep per-trade fee model from v2 (T1=31bps, T2=56bps per side). Add new metrics in v3:
- `fee_drag_pct = total_estimated_fees / gross_profit` — how much fees eat into raw profits
- `trades_below_breakeven` — trades where |pnl| < round_trip_fee
- `capacity_proxy` — average trade size relative to daily volume

**Rationale**: Fee-per-trade is correct because slippage scales with trade execution, not with time-between-trades. The new metrics help identify when higher trade frequency becomes counterproductive.

---

## ADR-HF-016: Timeframe Scaling — Window/Embargo Preserve 30-Day Semantics + A/B Methodology

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Engine is bar-count based. time_max_bars=15 at 1H means 15h hold (vs 60h at 4H). Testing with unchanged config may produce false negative if the parameter mismatch kills edge, not the timeframe.

**Decision**: A/B config methodology for all lower-TF validations:
- **Config A**: Run with GRID_BEST unchanged (time_max_bars=15)
- **Config B**: Scale time_max_bars to preserve wall-clock semantics (1H: 60, 15m: 240)

**Interpretation**:
| A | B | Conclusion |
|---|---|-----------|
| PASS | PASS | Strong edge — works with any params |
| PASS | FAIL | Edge exists but sensitive to hold time |
| FAIL | PASS | Edge exists only with TF-scaled params; grid-search needed |
| FAIL | FAIL | No edge at this timeframe |

**Window scaling**: ROLLING_WINDOW_BARS scales to 30 days (1H: 720, 15m: 2880). WF_EMBARGO scales to ~2h wall-clock. start_bar kept at 50 for 1H (2.1 days warmup), 200 for 15m (12.5h warmup).

**Note**: COOLDOWN_BARS=4 is an engine constant, cannot be scaled. This is a known limitation documented in `hf_mtf_rules.md`.

---

## ADR-HF-017: Correlation Guard as Standalone Module, Hard-Gate Only When mp>1

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Sprint 2.5 (ADR-012) showed correlation guard effectively blocks 27 correlated entries at mp=3, producing best DD profile (10.2%). Need to make this reusable across timeframes.

**Decision**: Extract correlation analysis into `hf_correlation.py` (standalone module). Exposure cap rules in `hf_exposure_caps.py`:
- At max_pos=1: LOG-ONLY mode — compute and report correlations but don't block trades
- At max_pos>1: HARD-GATE mode — block second entry if rolling correlation ρ > 0.70

**Rationale**:
1. At mp=1, there's only one position — correlation guard is meaningless (nothing to be correlated WITH)
2. At mp>1, guard prevents capital concentration in correlated assets
3. Standalone module enables reuse across 4H/1H/15m without code duplication
4. Pre-filter to signal-generating coins (~50) keeps computation tractable (~1225 pairs)

---

## Sprint 2.5 Summary

**Deliverables**:
| Task | Artifact | Finding |
|------|----------|---------|
| Allocator experiment | hf_allocator.py + allocator_001 | max_pos>1 does NOT improve risk-adjusted returns at 4H |
| ADR | ADR-HF-012 | Blocks allocator-based throughput path |

**Updated Sprint 3 Recommendations** (revised from Sprint 2):
1. **Sub-4H pipeline**: Build 1H/15m data fetcher — this is now the ONLY viable throughput path
2. **New signal families**: Multi-TF confirmation (4H trigger + 1H entry), order flow signals
3. **Correlation guard**: Keep for future multi-position configs at lower timeframes
4. **No more 4H parameter iteration**: Space exhausted (ADR-002), allocator exhausted (ADR-012)

---

## Sprint 2 Summary

**Deliverables**:
| Task | Artifact | Finding |
|------|----------|---------|
| Friction v2 | hf_friction_v2.py + report | MARGINAL — 33-38% P&L retained under realistic friction |
| Universe policy | UNIVERSE_POLICY.md | Tier 3 excluded, T1+T2 = 316 coins for live |
| Per-tier validation | hf_validate_per_tier.py + report | T1+2 = GO for both configs at conservative 56bps fee |
| ADRs | DECISIONS.md | ADR-009 through ADR-011 |

**Updated Sprint 3 Recommendations**:
1. **Data pipeline**: Build 1H/15m Kraken OHLCV fetcher with tier metadata
2. **Signal exploration**: Test DualConfirm on 1H (expect more trades → better sample size)
3. **New signals for Tier 1**: vol_spike_mult doesn't work on liquid coins — need different entry (momentum, orderbook, multi-TF)
4. **Stop-loss realism**: Model gap risk / slippage on stop-loss fills (currently exact sl_pct)
5. **Paper trading**: Consider running T1+2 universe with per-tier fees on paper before live

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

## ADR-HF-018: HALT — DualConfirm Has No Edge at 1H Frequency

**Date**: 2026-02-15
**Status**: DECIDED — **HALT** (no 15m build)
**Context**: Sprint 3 STOP-CHECK. The 1H data pipeline delivered 1903 coins (96.8% coverage, 0 OHLCV violations). Both A/B configs were tested through the full 6-gate validation suite per GATES_MTF.md.

**STOP-CHECK rule**: "Als trades ↑ maar expectancy/trade ≤ 0 (net, Tier 1+2) → HALT + ADR (geen 15m build)."

**Evidence** (validate_1h_001):

| Metric | Config A (tmb=15) | Config B (tmb=60) |
|--------|-------------------|-------------------|
| Trades | 32 | 22 |
| P&L | $-1,037.80 | $-1,246.88 |
| PF | 0.43 | 0.36 |
| Win Rate | 31.2% | 22.7% |
| Max DD | 57.3% | 73.3% |
| Expectancy/trade | **-$32.43** | **-$56.68** |
| WF folds positive | 1/5 | 1/5 |
| Gates passed | 2/6 (G1, G6) | 2/6 (G1, G6) |
| Gates failed | G2, G3, G4, G5 | G2, G3, G4, G5 |

Per-tier breakdown (Config A):

| Tier | Trades | P&L | PF | Fee (bps) |
|------|--------|-----|----|-----------|
| T1 (Liquid) | 13 | $-261.95 | 0.63 | 31.0 |
| T2 (Mid) | 19 | $-775.85 | 0.31 | 56.0 |

Per-tier breakdown (Config B):

| Tier | Trades | P&L | PF | Fee (bps) |
|------|--------|-----|----|-----------|
| T1 (Liquid) | 11 | $-174.73 | 0.78 | 31.0 |
| T2 (Mid) | 11 | $-1,072.15 | 0.05 | 56.0 |

**Decision**: **HALT**. Do NOT build 15m data pipeline. DualConfirm has zero edge at 1H.

**Rationale**:
1. **Both configs deeply negative**: PF 0.43 and 0.36 — not even close to breakeven (PF 1.0)
2. **Expectancy/trade ≤ 0**: -$32.43 (A) and -$56.68 (B). STOP-CHECK rule triggers.
3. **Trades did NOT increase meaningfully**: 32 at 1H vs 32 at 4H — the DualConfirm signal fires at roughly the same bar-count rate regardless of timeframe. The hypothesis "more frequent candles → more signals → cumulative profit" is falsified.
4. **T2 collapses at 1H**: PF 0.31 (A) and 0.05 (B). At 4H, T2 alone was GO. 1H noise destroys the signal.
5. **Walk-forward catastrophic**: Only 1/5 folds profitable in both configs. No temporal stability.
6. **Config B (scaled) is WORSE**: Longer hold time at 1H just extends exposure to noise, increasing DD from 57.3% → 73.3%.
7. **A/B methodology worked as designed**: Prevented false-negative attribution ("maybe the params are wrong"). Both interpretations fail — the signal itself is broken at this frequency.

**Root cause analysis**:
- DualConfirm is a **4H-frequency-specific signal**. The Donchian + Bollinger touch pattern requires multi-day price structure that simply doesn't exist at 1H resolution.
- At 1H, the Donchian low and Bollinger lower band are compressed (30-day window = 720 1H bars vs 180 4H bars). The bands move more smoothly, triggering more false touches.
- Volume spike confirmation (vol_spike_mult × 20-bar avg) at 1H captures intra-day noise rather than multi-day conviction.
- COOLDOWN_BARS=4 at 1H = 4 hours. This is actually favorable (faster re-entry) but irrelevant when every entry loses money.

**Consequence**:
1. **No 15m pipeline build** — if 1H has zero edge, 15m would be worse (more noise, higher fee drag)
2. **DualConfirm is validated as 4H-only** — the strategy stays at 4H with T1+T2 universe
3. **Sub-4H throughput requires NEW signal families** (multi-TF confirmation, momentum, order flow — see hf_hypotheses.md)
4. **Sprint 3 deliverables (infrastructure) remain valuable** — the pipeline, validation framework, and A/B methodology are reusable for future signal research

---

## Sprint 3 Execution Results — 1H HALT

**Phase 1 (Data Pipeline)**: ✅ COMPLETE
| Artifact | Result |
|----------|--------|
| candle_cache_1h.json | 1903 coins, 129MB |
| data_manifest_1h.json | Snapshotted to reports/hf/ |
| data_audit_1h_001 | Coverage 96.8% (≥95% ✅), OHLCV violations 0 (=0 ✅) |
| hf-check | 35/35 green |
| make check | 66/66 green |

**Phase 2 (Validation)**: ❌ NO_EDGE
| Run | Verdict |
|-----|---------|
| Config A (as-is, tmb=15) | FAIL — G2, G3, G4, G5 |
| Config B (scaled, tmb=60) | FAIL — G2, G3, G4, G5 |
| A/B conclusion | NO_EDGE — both fail |

**Phase 3 (STOP-CHECK)**: 🛑 HALT
| Check | Result |
|-------|--------|
| Trades ↑ vs 4H? | NO — 32 trades at 1H ≈ 32 at 4H |
| Expectancy/trade > 0? | NO — -$32.43 (A), -$56.68 (B) |
| Verdict | **HALT** — geen 15m build |

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

---

## ADR-HF-019: Standalone Screening Harness (Not Engine Extension)

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Sprint 3 HALT established DualConfirm has no edge at 1H. Sprint 4 needed to screen 15 alternative hypotheses across 5 categories. The existing engine (`agent_team_v3.py`) has hardcoded DualConfirm entry logic with no plugin system.

**Options considered**:
1. Extend engine with plugin-based signal dispatch (modify `check_entry_at_bar()`)
2. Build standalone harness replicating engine equity/fee model but with signal_fn parameter

**Decision**: Option 2 — standalone harness in `strategies/hf/screening/harness.py`.

**Rationale**:
1. Engine is READ-ONLY production code — modifying it risks breaking validated 4H behavior
2. Screening framework needs ~2,400 lines of new code (15 hypotheses, 90 configs, 2-layer gates) — this is research infrastructure, not production code
3. Fee model parity is critical and verifiable: every harness line has `# Parity: engine line NNN` comments
4. test_harness.py includes DualConfirm parity test (trade count, P&L, DD within ±5%)
5. Standalone harness is disposable — if no hypothesis has edge, the framework is archived with results

**Consequence**: Harness is research-only. Any hypothesis that passes Layer 2 promotion would need a live execution layer (engine extension or new engine) for production deployment.

---

## ADR-HF-020: T1+T2 Screening Universe with Per-Tier Friction

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Need to decide which coins to screen. Universe tiering (ADR-HF-008) showed edge depends on Tier 2 mid-caps.

**Decision**: Screen on T1 (98 coins, fee=31bps/side) + T2 (216 coins, fee=56bps/side) = 314 coins. Tier 3 excluded per UNIVERSE_POLICY.md.

**Fee model**:
| Tier | Base (Kraken) | Slippage | Total per side |
|------|---------------|----------|----------------|
| T1 (Liquid) | 26 bps | 5 bps | 31 bps |
| T2 (Mid) | 26 bps | 30 bps | 56 bps |

**Rationale**:
1. Per-tier friction prevents false-positive from unrealistic flat fees
2. Layer 2 stress test uses 2× fees (T1: 36bps, T2: 86bps) for additional margin
3. Results combine T1+T2 for composite metrics but per-tier breakdown is preserved

---

## ADR-HF-021: Fixed Exit Taxonomy (TP/SL/TIME)

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Engine supports 3 exit types (tp_sl, trail, hybrid_notrl). For screening 15 hypotheses fairly, need a standardized exit mechanism.

**Decision**: All hypotheses use the same 3-mechanism exit: SL check first (low <= stop_price), then TP (high >= target_price), then TIME (bars_in >= time_limit). Each signal_fn provides stop_price, target_price, and time_limit per trade.

**Rationale**:
1. **Fair comparison**: Different exit mechanisms would confound signal quality with exit quality
2. **Signal provides prices**: The signal_fn returns absolute stop/target prices (not percentages), giving each hypothesis control over risk/reward
3. **Priority order matters**: SL before TP (engine parity, line 368 before 370) — conservative assumption when both trigger in same bar
4. **TIME as safety valve**: Prevents zombie positions — every hypothesis must declare max hold time

**Consequence**: Hypotheses like H05 (DC breakout) that naturally suit trailing stops are constrained to fixed TP/SL. If a hypothesis survives screening with fixed exits, adding trailing stops would likely improve it further.

---

## ADR-HF-022: Two-Layer Progressive Filtering

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Testing 15 hypotheses × 6 variants = 90 configs needs systematic filtering to avoid overfitting.

**Decision**: Two-layer approach:
- **Layer 1 (Screening)**: Loose gates, high throughput. KILL gates = trades ≥ 60 AND expectancy > $0. Soft gates for PF, walk-forward, concentration. Run on all 90 configs.
- **Layer 2 (Promotion)**: Strict gates on top 1-2 survivors. Stress fees, PF ≥ 1.2, WF ≥ 3/5, rolling windows ≥ 60%, DD ≤ 30%, latency stress, capacity check.

**Gate spec**: `strategies/hf/GATES_SCREENING.md`

**Rationale**:
1. Layer 1 KILL gates are intentionally loose — S2 (expectancy > $0) is the minimum bar
2. Layer 2 applies strict operational gates only to survivors, preventing premature rejection
3. Scoring formula `expectancy × sqrt(trades) × (PF - 1)` with throughput bonus balances edge strength with sample size
4. Walk-forward at both layers (2/5 at L1, 3/5 at L2) ensures temporal stability

**Trade gate design** (per user requirement):
- S1: trades ≥ 60 = KILL (hard floor for statistical significance)
- S1b: trades ≥ 120 = soft bonus (+20% score) — throughput goal, not gate

---

## ADR-HF-023: Deployability — Harness is Research-Only

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Per user requirement, clarify that the screening harness is a research tool, not a live execution system.

**Decision**: The screening framework (`strategies/hf/screening/`) is explicitly research-only:
1. **No live execution**: Harness simulates fills at bar close/stop/target prices — no order book interaction
2. **No real-time data**: Works on cached historical candles only
3. **No position management**: Simplified single-position model (max_pos=1)
4. **No risk management**: No circuit breakers, no real-time exposure monitoring

**Path to production** (if a hypothesis passes Layer 2):
1. Build signal adapter that implements the winning signal_fn in the live engine
2. Add the signal to `check_entry_at_bar()` or build new entry dispatch
3. Run paper trading validation with real-time data for ≥ 30 days
4. Validate with live execution metrics (fill quality, latency, slippage)

**Consequence**: Layer 2 promotion is necessary but NOT sufficient for live deployment.

---

## ADR-HF-024: Sprint 4 Screening Results — NO SURVIVORS (HALT)

**Date**: 2026-02-15
**Status**: DECIDED — **HALT** (no Layer 2 promotion)
**Context**: Sprint 4 screened 15 hypotheses × 6 variants = 90 configs through Layer 1 gates on 1H data (T1: 98 coins, T2: 216 coins). Runtime: 304s.

**Result**: **0 survivors out of 90 configs.** Every configuration failed the S2 KILL gate (expectancy > $0).

**Evidence** (screen_001.json / screen_001.md):

| Gate | Pass | Fail | Rate |
|------|------|------|------|
| S1 (trades ≥ 60) | 89 | 1 | 99% |
| S2 (expectancy > $0) | 0 | 90 | **0%** |
| S3 (PF ≥ 1.1) | 0 | 90 | 0% |
| S4 (WF ≥ 2/5) | 17 | 73 | 19% |
| S5 (concentration) | 71 | 19 | 79% |

Best variants per hypothesis:

| ID | Category | Best PF | Best Exp/Trade | Trades |
|----|----------|---------|----------------|--------|
| H03 STOCH_CROSS | mean_reversion | 0.95 | -$2.00 | 154 |
| H11 SQUEEZE_BREAK | volume | 0.95 | -$2.77 | 89 |
| H14 RSI_MACD_AGREE | multi_indicator | 0.90 | -$3.32 | 123 |
| H02 BB_REVERT | mean_reversion | 0.81 | -$4.99 | 88 |
| H05 DC_BREAKOUT_UP | momentum | 0.82 | -$7.67 | 221 |

**Key findings**:
1. **Universal negative expectancy**: ALL 15 hypotheses across ALL 5 categories (mean reversion, momentum, volume, price action, multi-indicator) have negative expectancy at 1H
2. **Sufficient trade counts**: 89/90 configs pass S1 (≥ 60 trades) — the signals DO fire, they just lose money
3. **Best PF = 0.95** (H03, H11): Even the closest-to-breakeven configs are still losing $2-3/trade after fees
4. **Fee drag is dominant**: PF range 0.06-0.95 — no config even reaches breakeven (PF = 1.0)
5. **Walk-forward has some positives**: 17/90 pass WF (≥ 2/5 folds positive), indicating temporal pockets of profitability that don't survive aggregate analysis
6. **Concentration is fine**: 71/90 pass S5, confirming signals are well-diversified — the problem is not concentration but universal negative alpha

**Root cause analysis**:
- **1H crypto is friction-dominated**: At T2 fees (56bps/side = 112bps round trip), a trade needs >1.12% gross return to be positive. 1H candle ranges are typically 1-3%, leaving almost no room for edge after fees.
- **Signal diversity doesn't help**: 5 distinct signal families (15 hypotheses) all fail. This suggests the problem is structural (1H timeframe + fee structure) not signal-specific.
- **Comparison with DualConfirm HALT** (ADR-HF-018): DualConfirm at 1H had PF 0.43/0.36. The best new hypotheses (PF 0.95) are significantly better but still underwater.
- **Volume-based signals perform worst**: H09 (PF 0.55 best) and H08 (PF 0.35 best) — 1H volume patterns are noisier than expected.
- **Multi-indicator signals perform best**: H14 (PF 0.90) suggests that combining filters helps, but not enough to overcome fee drag.

**Decision**: **HALT**. No Layer 2 promotion. No further 1H signal exploration.

**Recommendations for future work**:
1. **Accept 4H-only deployment**: DualConfirm at 4H with T1+T2 remains the only validated edge
2. **Different market structure**: Consider market-making or order flow signals that benefit FROM spreads rather than suffering from them
3. **Different asset universe**: Crypto majors (BTC, ETH) may have better 1H signal-to-noise but insufficient Kraken liquidity for the strategy style
4. **Different timeframe approach**: Multi-TF confirmation (4H signal → 1H entry timing) rather than pure 1H signals
5. **Fee reduction**: If Kraken maker fees decrease or the bot qualifies for fee tiers, re-screen at lower friction

**Consequence**:
- Sprint 4 screening framework is archived with results in `reports/hf/screening/`
- Screening infrastructure (`strategies/hf/screening/`) is reusable for future signal research
- 30 new unit tests added (test_harness.py: 16 pass + 3 parity skipped, test_hypotheses.py: 14 pass)
- Next sprint should focus on live deployment preparation for 4H DualConfirm (T1+T2)

---

## Sprint 4 Summary — Indicator-Agnostic Hypothesis Screening

**Deliverables**:
| Artifact | Lines | Purpose |
|----------|-------|---------|
| strategies/hf/screening/harness.py | ~390 | Signal-agnostic backtest engine with engine fee parity |
| strategies/hf/screening/indicators.py | ~440 | Extended indicator library (11 new + 4 reused) |
| strategies/hf/screening/hypotheses.py | ~800 | 15 hypotheses × 6 variants = 90 configs |
| strategies/hf/screening/screener.py | ~280 | Layer 1 screening pipeline |
| strategies/hf/screening/promoter.py | ~260 | Layer 2 promotion pipeline |
| strategies/hf/screening/report.py | ~280 | JSON + Markdown report writer |
| strategies/hf/screening/run_screen.py | ~190 | Layer 1 CLI orchestrator |
| strategies/hf/screening/run_promote.py | ~170 | Layer 2 CLI orchestrator |
| strategies/hf/screening/test_harness.py | ~430 | 19 tests (16 pass + 3 parity skipped) |
| strategies/hf/screening/test_hypotheses.py | ~270 | 14 tests (all pass) |
| strategies/hf/GATES_SCREENING.md | ~120 | Layer 1 + Layer 2 gate specification |
| reports/hf/screening/screen_001.json | — | Full raw results |
| reports/hf/screening/screen_001.md | — | Human-readable summary |
| ADRs HF-019 through HF-024 | — | 6 architecture decisions |
| **Total new code** | **~3,630** | |
| **Total new tests** | **33** | 30 pass, 3 skipped (parity, no 4H data) |

**Result**: **HALT** — 0/90 configs survive Layer 1. No hypothesis has positive expectancy at 1H.

**Test status**: make check 66/66 green. Screening tests: 30/30 pass + 3 skip.

---

## ADR-HF-025: Market Context Injection (Harness Untouched)

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Sprint 5 needed cross-coin data (BTC regime, market breadth, cross-sectional rankings) inside per-coin signal functions. The harness calls `signal_fn(candles, bar, ind, params)` per-coin. Modifying harness was ruled out (engine parity, Sprint 4 test stability).

**Decision**: Precompute cross-coin context per-bar in `market_context.py`, inject into `params['__market__']` before backtesting. Signal functions read `params['__market__']` for cross-coin data. Per-coin identity is injected into `indicators['__coin__']` since `ind` is per-coin while `params` is shared.

**Architecture**:
```
precompute_market_context(data, coins) → {
    btc_atr_ratio: [float/bar],
    breadth_up: [float/bar],
    momentum_rank: {coin: [int/bar]},
    mean_revert_rank: {coin: [int/bar]}
}
# Injection: enriched_params = {**params, '__market__': market_ctx}
# Per-coin: indicators[coin]['__coin__'] = coin
```

**Causality guarantee**: All context at bar N uses data up to bar N-1 only. Proven by truncation tests in `test_market_context.py::TestNoLookahead` — compute with N bars, then with N+K bars, values at 0..N-1 must be identical.

**Key bug found during screening**: BTC/USD must be explicitly included in the coin list passed to `precompute_market_context`, even if BTC is not in any trading tier. Without this, `btc_atr_ratio` defaults to 1.0 and H21 (BTC_REGIME_MR) generates 0 trades.

**Consequence**: Harness remains unmodified. Sprint 4 tests unchanged (30 pass + 3 skip). Pattern is extensible to future cross-coin features.

---

## ADR-HF-026: Cross-Sectional via strength + max_pos (No Harness Change)

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Cross-sectional hypotheses (H24 MOMENTUM_RANK, H25 MEAN_REVERT_RANK) need to rank all coins per bar and trade only top-N. The harness already sorts buys by `strength` (line 176) and respects `max_pos` parameter.

**Decision**: Cross-sectional signals return rank-based strength scores and run with `max_pos=5`. The harness naturally selects top-5 by sorting on strength. No harness modification needed.

**Implementation**:
- H24/H25 signal functions return `strength = (total_coins - rank + 1) / total_coins`
- `screener_s5.py` overrides `max_pos=5` for `category == 'cross_sectional'`
- Rankings precomputed in `market_context.py` (momentum: vol-adjusted 10-bar return; mean_revert: z-score oversold)

**Key bug found**: Signal functions initially read `params.get('__coin__')` but `__coin__` was injected into `indicators[coin]`. Since `params` is shared across all coins in the harness bar loop while `ind` is per-coin, the fix was to change signals to read `indicators.get('__coin__')`.

**Consequence**: Harness untouched. Cross-sectional signals generate 380-576 trades per config (high throughput). However, all configs have negative expectancy — the ranking signal alone doesn't overcome fee drag.

---

## ADR-HF-027: Sprint 5 Screening Results — NO SURVIVORS (HALT)

**Date**: 2026-02-15
**Status**: DECIDED — **HALT** (no Layer 2 promotion)
**Context**: Sprint 5 screened 10 hypotheses × 6 variants = 60 configs across 3 new signal families: microstructure (H16-H20), market state (H21-H23), and cross-sectional (H24-H25). Updated KILL gates: exp/week > $0 AND trades/week ≥ 7 AND be_trade_ratio < 40%.

**Result**: **0 survivors out of 60 configs.** Every configuration failed K1 (exp_per_week > $0).

**Evidence** (screen_s5_001.json / screen_s5_001.md):

| Gate | Pass | Fail | Rate |
|------|------|------|------|
| K1 (exp/week > $0) | 0 | 60 | **0%** |
| K2 (trades/week ≥ 7) | 59 | 1 | 98% |
| K3 (BE ratio < 40%) | 60 | 0 | 100% |
| S3 (PF ≥ 1.1) | 0 | 60 | 0% |
| S4 (WF ≥ 2/5) | 9 | 51 | 15% |
| S5 (concentration) | 47 | 13 | 78% |

Best variants per hypothesis family:

| ID | Category | Best PF | Best Exp/Week | Trades |
|----|----------|---------|---------------|--------|
| H20 VWAP_DEVIATION | microstructure | **0.90** | **-$64/wk** | 70 |
| H23 DECORRELATION | market_state | 0.67 | -$564/wk | 166 |
| H24 MOMENTUM_RANK | cross_sectional | 0.60 | -$322/wk | 448 |
| H25 MEAN_REVERT_RANK | cross_sectional | 0.52 | -$313/wk | 473 |
| H22 BREADTH_MOMENTUM | market_state | 0.40 | -$468/wk | 100 |
| H21 BTC_REGIME_MR | market_state | 0.60 | -$159/wk | 56 |

**Closest-to-viable**: H20 VWAP_DEVIATION v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5) achieved PF=0.90 with only -$64/week — the closest any Sprint 4 or Sprint 5 hypothesis has come to breakeven. This suggests VWAP-based mean reversion has a real signal, but 10% gross profit still lost to fees.

**Key findings**:
1. **Microstructure came closest**: H20 (VWAP deviation + bounce) nearly breaks even (PF 0.90). This is significantly better than Sprint 4's best (PF 0.95 at -$2/trade but much more negative exp/week).
2. **Cross-sectional generates massive throughput**: H25 produced 576 trades (134 tr/week!) — selectivity from ranking doesn't overcome fee drag but the throughput is there.
3. **Market state filtering reduces trades but doesn't improve PF**: H21 (BTC calm + RSI oversold) fires rarely (29-72 trades across all variants) and still loses.
4. **BE ratio is universally low** (3-21%): Break-even trades are NOT the problem. Trades clearly win or lose; they just lose more often than they win at these fee levels.
5. **Breadth-based timing doesn't help**: H22 had the worst PF (0.27-0.40). Market-wide recovery detection is too lagging at 1H.

**Root cause analysis**:
Sprint 5 tested 3 structurally different signal families that were specifically designed to overcome Sprint 4's fee-drag problem:
- **Microstructure** targeted larger per-trade gross returns (displacement bars = big candles). Result: signals fire on big candles but subsequent moves don't follow through enough.
- **Market state** tried to trade only in favorable conditions. Result: filtering reduces trade count but remaining trades have same negative expectancy.
- **Cross-sectional** tried selectivity (trade only the best-ranked coins). Result: ranking doesn't identify coins with genuine 1H alpha.

The conclusion is now definitive: **1H crypto at these fee levels (T1=31bps, T2=56bps per side) does not support positive expectancy for any tested signal family.** Five categories tested in Sprint 4 (15 hypotheses) and three categories in Sprint 5 (10 hypotheses) — 25 total hypothesis families, 150 total configs — all fail.

**Decision**: **HALT**. No further 1H signal exploration. The problem is structural.

**Recommendations**:
1. **Accept 4H-only deployment** for DualConfirm
2. **If 1H is revisited**: Focus exclusively on H20-style VWAP deviation (PF 0.90, closest to edge) but only after Kraken fee tier improvement brings RT cost below ~80bps
3. **Alternative**: Maker-fee strategies or higher-timeframe signals (4H trigger → 1H timing)

---

## ADR-HF-028: Sprint 5 Scoreboard Design

**Date**: 2026-02-15
**Status**: DECIDED
**Context**: Sprint 4 scoring used expectancy × sqrt(trades) × (PF-1). Sprint 5 needed throughput-oriented metrics and execution realism.

**Decision**: Sprint 5 scoreboard adds 5 new metrics and 3 updated KILL gates:

| Metric | Formula | Purpose |
|--------|---------|---------|
| trades_per_week | n_trades / (total_bars / 168) | Throughput |
| exp_per_week | expectancy × trades_per_week | Sustainable profit rate |
| fee_drag_pct | total_fees / gross_profit × 100 | Fee erosion |
| be_trade_ratio | trades where \|pnl\| < RT_fee / n_trades × 100 | Noise detection |
| stress_2x_pnl | P&L at 2× tier fees | Stress robustness |

**Updated KILL gates** (from Sprint 4's S1+S2):
- K1: exp_per_week > $0 (replaces S2 expectancy > $0 per trade)
- K2: trades_per_week ≥ 7 (replaces S1 trades ≥ 60)
- K3: be_trade_ratio < 40% (new — reject noise-dominated signals)

**Rationale**:
1. exp_per_week is the primary metric — a signal that profits $1/trade but trades once/week is useless
2. trades_per_week captures frequency at human scale (not bar count)
3. be_trade_ratio detects signals where most trades are within the fee band (noise, not alpha)
4. fee_drag_pct quantifies how much gross profit fees consume
5. stress_2x_pnl provides execution headroom check

**Consequence**: All 60 Sprint 5 configs passed K2 (98%) and K3 (100%) but none passed K1 (0%). The bottleneck is universally negative alpha, not trade frequency or noise.

---

## Sprint 5 Summary — Microstructure, Market State & Cross-Sectional Screening

**Deliverables**:
| Artifact | Lines | Purpose |
|----------|-------|---------|
| strategies/hf/screening/market_context.py | ~300 | BTC regime, breadth, cross-sectional rankings |
| strategies/hf/screening/indicators_extended.py | ~120 | VWAP, count, body_pct, atr_ratio |
| strategies/hf/screening/hypotheses_s5.py | ~890 | H16-H25 signal functions + grids |
| strategies/hf/screening/screener_s5.py | ~490 | Sprint 5 screening wrapper |
| strategies/hf/screening/run_screen_s5.py | ~395 | Sprint 5 CLI |
| strategies/hf/screening/test_market_context.py | ~240 | 14 tests (causality proof) |
| strategies/hf/screening/test_hypotheses_s5.py | ~980 | 31 tests |
| strategies/hf/screening/report.py (modified) | +120 | S5 report functions |
| reports/hf/screening/screen_s5_001.json | — | Full raw results |
| reports/hf/screening/screen_s5_001.md | — | Human-readable summary |
| ADRs HF-025 through HF-028 | — | 4 architecture decisions |
| **Total new code** | **~3,535** | |
| **Total new tests** | **45** | 45 pass (14 market_context + 31 hypotheses_s5) |

**Result**: **HALT** — 0/60 configs survive. No hypothesis has positive weekly expectancy at 1H.

**Cumulative result across Sprints 3-5**: 0/150 configs survive across 25 hypothesis families tested at 1H. The 1H crypto trading timeframe at current fee levels is structurally unprofitable for directional signals.

**Test status**: make check 66/66 green. Sprint 5 tests: 45/45 pass.

---

## ADR-HF-029: Reality Check — MEXC Costs Flip H20 VWAP_DEVIATION to Positive Edge

**Date**: 2026-02-15
**Status**: DECIDED — **CONDITIONAL GO** (MEXC-only, needs live validation)
**Context**: Sprint 5 ended with H20 VWAP_DEVIATION as "closest to viable" (PF=0.90, -$64/wk at Kraken fees). The question: is the failure due to signal quality or fee structure? This sprint measured MEXC all-in costs and re-ran H20 under 4 cost regimes.

**MEXC cost analysis** (mexc_costs_001):

| Tier | Kraken (current) | MEXC Taker P50 | MEXC Maker P50 | Savings |
|------|-----------------|----------------|----------------|---------|
| T1 (Liquid) | 31.0 bps/side | 12.5 bps/side | 2.5 bps/side | 60-92% |
| T2 (Mid) | 56.0 bps/side | 23.5 bps/side | 13.5 bps/side | 58-76% |

Key MEXC advantage: 0% maker fee (promotional since Q4 2022) + 10bps taker (vs Kraken 26bps).

**Fill model** (fill_model_001):

| Mode | T1 Cost | T2 Cost | Fill Rate | Adverse Selection |
|------|---------|---------|-----------|-------------------|
| MARKET (taker) | 6 bps | 25 bps | 100% | None |
| LIMIT_OPTIMISTIC | 3 bps | 3 bps | 80% | 3 bps (mild) |
| LIMIT_REALISTIC | 8 bps | 8 bps | 55% | 8 bps (winner's curse) |
| Kraken Baseline | 31 bps | 56 bps | 100% | None |

**H20 VWAP_DEVIATION re-run results** (reality_check_001):

| Regime | Best Variant | PF | Exp/Week | DD% | Trades | Verdict |
|--------|-------------|-----|----------|-----|--------|---------|
| Kraken Baseline | v5 | 0.895 | -$64.43 | 60.4% | 70 | **NO EDGE** |
| MEXC Market | v5 | 1.250 | +$142.80 | 44.6% | 70 | **POSITIVE** |
| MEXC Limit Optimistic | v5 | 1.396 | +$171.47 | 31.8% | 57 | **POSITIVE** |
| MEXC Limit Realistic | v3 | 1.202 | +$86.30 | 37.3% | 56 | **POSITIVE** |

**Stress test results**:

| Stress Level | MEXC Market | Limit Optimistic | Limit Realistic |
|-------------|-------------|------------------|-----------------|
| P90 (1.5× spread+slip) | PF=1.155, +$90/wk | PF=1.344, +$150/wk | PF=0.655, -$84/wk |
| P95 (2.0× spread+slip) | PF=1.070, +$42/wk | PF=1.296, +$130/wk | PF=0.547, -$117/wk |

**Decision**: **CONDITIONAL GO** for MEXC execution, with caveats.

**Key findings**:
1. **Fee structure IS the bottleneck**: Same signal (H20 v5) flips from PF=0.895 → PF=1.250 just by changing fee regime. The signal quality is real.
2. **MEXC Market is the safest bet**: 100% fill rate, survives P95 stress (PF=1.070, +$42/wk). No fill-rate risk.
3. **Limit Optimistic is best on paper** (PF=1.396) but assumes 80% fill rate — needs live validation.
4. **Limit Realistic fails stress test**: P90 PF=0.655, P95 PF=0.547. Winner's curse + 55% fill rate too punishing under adverse conditions.
5. **Best variant shifts by regime**: v5 (dev=2.0, tp=8, sl=5) for market/optimistic, v3 (dev=1.5, tp=8, sl=5) for realistic — wider deviation threshold helps when fills are selective.

**Risk factors**:
1. **MEXC promotional rate risk**: 0% maker is promotional. If reverted to 10bps, maker all-in costs increase 10bps. Even then, still cheaper than Kraken.
2. **Spread/slippage model uncertainty**: Estimates are volume-based, not live order book measurements. Must validate with paper trading.
3. **Volume authenticity**: MEXC has faced wash trading questions. If true volumes are 30-50% lower, costs increase 20-40%.
4. **Regulatory risk**: MEXC is less regulated than Kraken. Capital deployment decision.
5. **Sample size**: 56-70 trades across 4.3 weeks of 1H data. Statistically marginal.

**Consequence**:
1. H20 VWAP_DEVIATION is the **first hypothesis to show positive expectancy** across 5 sprints (150+ configs tested)
2. Next step: Paper trade 10-20 round trips on MEXC to validate fill quality, actual spread, and slippage
3. Live deployment requires: paper trading validation + MEXC account setup + monitoring infrastructure
4. The screening framework has found its first candidate — but it's exchange-dependent, not a universal edge

---

## Reality Check Sprint Summary — MEXC Cost Analysis + Fill Model + H20 Re-Run

**Deliverables**:
| Artifact | Purpose |
|----------|---------|
| reports/hf/mexc_costs_001.json + .md | MEXC all-in cost measurement (fee + spread + slippage model) |
| reports/hf/fill_model_001.json + .md | 3-mode limit fill model design |
| strategies/hf/screening/fill_model.py | Fill model implementation (market/optimistic/realistic) |
| strategies/hf/screening/run_reality_check.py | H20 re-run under 4 cost regimes + stress tests |
| reports/hf/reality_check_001.json + .md | H20 VWAP_DEVIATION results under all regimes |
| ADR-HF-029 | Reality Check decision record |

**Result**: **CONDITIONAL GO** — H20 VWAP_DEVIATION shows positive edge at MEXC costs (PF=1.25, +$143/wk market; PF=1.40, +$171/wk limit-optimistic). Survives P95 stress in market and limit-optimistic modes.

**Cumulative sprint results**:
- Sprints 3-5: 0/150 configs profitable at Kraken fees → structural fee problem confirmed
- Reality Check: Same signal profitable at MEXC fees → **fee structure was the bottleneck**
- First positive-expectancy hypothesis found after 25 signal families tested

**Test status**: make check 66/66 green. All previous tests unchanged.

---

### ADR-HF-030: GO/NO-GO — H20 Throughput + Robustness Validation

**Date**: 2026-02-15
**Status**: **CONDITIONAL GO** (confirms HF-029)
**Commit**: 2246e21
**Reports**: `reports/hf/h20_throughput_002.json`, `reports/hf/h20_robustness_002.json`

**Context**: ADR-HF-029 gave CONDITIONAL GO for H20 VWAP_DEVIATION on MEXC. Before paper trading, we need to verify: (1) sufficient trade throughput for a viable strategy, (2) parameter robustness — the v5 baseline isn't a fragile overfitted peak.

**Gate Thresholds**:

| Gate | Metric | Threshold | Result | Verdict |
|------|--------|-----------|--------|---------|
| G1 | Trades/week | >= 10 | 10.01/wk | PASS |
| G2 | Exp/week (baseline) | > $0 | +$250/wk | PASS |
| G3 | Exp/week (2x stress) | > $0 | +$178/wk | PASS |
| G4 | Max drawdown | <= 20% | 11.4% | PASS |
| G5 | Walk-forward (baseline) | >= 4/5 | 5/5 | PASS |
| G6 | Neighbor stability | >= 8/12 profitable | 11/12 | PASS |
| G7 | Max gap (days) | <= 7 | 1.75 | PASS |
| G8 | Empty weeks | 0 | 0 | PASS |

**All 8 gates PASS.**

**Throughput Evidence** (from `h20_throughput_002`):
- 43 trades over 4.3 weeks = 10.01/week (just above G1 threshold)
- T1: 9, T2: 34 (79% from T2 tier — higher-cost coins drive volume)
- Max gap: 42 bars (1.75 days), median gap: 16 bars — no prolonged dry spells
- Utilization: 41.6% (bot is idle 58% of time — room for additional strategies)
- Weekly distribution: 8, 11, 9, 11 — consistent, no empty weeks
- Peak activity: 13:00 + 19:00 UTC, Fridays busiest (11 trades)
- Capacity: mp=1→43 trades, mp=2→44 (+1), mp=3→55 (+12). Max_pos=1 is optimal — minimal missed signals.

**Robustness Evidence** (from `h20_robustness_002`):
- 12 neighborhood variants (±1 step per parameter from v5 baseline)
- v5 baseline ranks #2 with score 215.0, confirming it is NOT a fragile peak
- **tp_pct=10% (variant 5) is strictly better**: score 280.6, PF=1.96, $326/wk, 5/5 WF, stress PF=1.68
- 11/12 variants profitable at baseline fees, 11/12 profitable at 2x stress (only dev=2.5 fails)
- Parameter sensitivity (ordered by impact):
  1. **dev_thresh**: most sensitive. Raising from 2.0→2.5 kills edge (PF=1.12→0.95 under stress). Lowering to 1.8 adds trades but loses 1 WF fold. Sweet spot confirmed at 2.0.
  2. **tp_pct**: tp=10% is better than tp=8% (score +65.5). tp=12% overshoots (WF 3/5). Optimal range: 8-10%.
  3. **sl_pct**: sl=3% has highest PF (2.03) but loses 1 WF fold. sl=5% is balanced. Range 3-5% works.
  4. **time_limit**: tl=8 adds 4 trades but halves expectancy. tl=12-15 loses WF folds. tl=10 optimal.
- Walk-forward detail: Fold 4 (bars ~432-576) dominates P&L across all variants — this is the ZEUS-equivalent period. But even excluding Fold 4, baseline has 4 positive folds.

**Decision**: **CONDITIONAL GO** — proceed to paper trading.

**Rationale**:
1. Throughput is borderline but sufficient (10/wk). With partial universe coverage (43% T1, 43% T2), full universe may yield 15-20+/wk.
2. Robustness is strong — baseline is not overfitted. The v5 neighborhood is a plateau, not a spike.
3. tp_pct=10% should be evaluated as the new baseline candidate (v6) in paper trading alongside v5.
4. All metrics survive 2x fee stress — the edge is real, not a fee-precision artifact.

**Risk factors**:
1. **Partial data coverage**: Only 135/316 tier coins (43%). Results may shift with full universe — both ways. More coins = more trades but also more noise.
2. **Short sample**: 4.3 weeks (722 bars). Walk-forward 5/5 is encouraging but still limited.
3. **Fold 4 concentration**: One fold contributes disproportionately. Without it, edge shrinks but remains positive.
4. **MEXC promotional rates**: If 0% maker reverts, market costs rise ~10bps. Strategy survives at 2x stress so this is manageable.

**Consequence**:
1. **Paper trading scope**: Run H20 VWAP_DEVIATION on MEXC for 2-4 weeks (target: 40-80 round trips)
2. **Two configs**: v5 (tp=8%) as baseline, tp=10% as challenger
3. **Validation criteria**: Live PF > 1.2, live Exp/trade within 50% of backtest, fill rate > 90%
4. **Data action**: Resume 1H download (Kraken K-Z, then MEXC) to expand universe coverage before next backtest iteration
5. **Abort trigger**: If paper trading PF < 1.0 after 20 trades, HALT and reassess


---

### ADR-HF-031: GO/NO-GO — Full Universe (316 coins) Throughput + Fill Model + Stress Validation

**Date**: 2026-02-15
**Status**: **CONDITIONAL HALT**
**Commit**: da5db72
**Reports**: `reports/hf/h20_fill_analysis_003.json`, `reports/hf/h20_throughput_tp10_003.json`
**Supersedes partial data in**: `reports/hf/h20_throughput_002.json`, `reports/hf/h20_robustness_002.json` (135-coin subset)

**Context**: ADR-HF-030 showed a CONDITIONAL GO on a 135-coin subset (43% of tier universe). This ADR reruns the same gates on the **full 316-coin tier universe** (T1=100 + T2=216) after completing the K-Z Kraken downloads. The expanded universe reveals that the edge is concentrated in the first ~135 coins and dilutes substantially when lower-volume T2 coins are included. The fill model (fill_model_002) adverse selection analysis remains valid and is incorporated unchanged.

**Hard Gates (full 316-coin universe)**:

| Gate | Metric | Threshold | v5 (tp=8) | tp=10 | Verdict |
|------|--------|-----------|-----------|-------|---------|
| G1 | Trades/week | >= 10 | 16.75 | 16.75 | **PASS** |
| G2 | Max gap | <= 2.5d | 1.42d | 1.42d | **PASS** |
| G3 | Exp/week (market fills) | > $0 | +$86/wk | +$54/wk | **PASS** |
| G4 | Exp/week (P95 stress, 2x fees) | > $0 | -$33/wk | -$65/wk | **FAIL** |
| G5 | Max DD | <= 20% | 53.1% | 52.4% | **FAIL** |
| G6 | Walk-forward | >= 4/5 | 3/5 | 3/5 | **FAIL** |
| G7 | Neighbor stability | >= 8/12 | 11/12 | n/a (002 data) | **PASS** |
| G8 | Top-1 fold concentration | < 35% | 48.6% | 57.3% | **FAIL** |

G4 note: Both configs go negative under 2x fee stress. v5 stress PF=0.949 (-$33/wk), tp=10 stress PF=0.902 (-$65/wk). This is a hard failure — no margin of safety under adverse cost scenarios.

G5 note: DD exploded from 11% (135 coins) to 53% (316 coins). The extra T2 coins add losing trades that deepen drawdowns without proportional winners.

G6 note: WF dropped from 5/5 (135 coins) to 3/5 (316 coins). Folds 1 and 2 are now negative: v5 folds = [+$416, -$199, -$499, +$227, +$608]. Two consecutive losing folds represent ~6 weeks of losses.

G8 note: v5 fold concentration = 607.76 / (415.88+226.57+607.76) = 48.6%. tp=10 = 651.60 / (360.41+124.59+651.60) = 57.3%. Both fail; tp=10 is now worse than v5 (reversed from 002).

**Gate summary**: 4/8 PASS, 4/8 FAIL (G4, G5, G6, G8). Three failures are hard disqualifiers (stress, DD, WF). The strategy does not survive the full tier universe test.

**135-coin vs 316-coin comparison — why the edge diluted**:

| Metric | 135 coins (002) | 316 coins (003) | Delta |
|--------|----------------|----------------|-------|
| v5 PF | 1.847 | 1.138 | -0.709 |
| v5 Exp/wk | +$250 | +$86 | -$164 |
| v5 DD | 11.4% | 53.1% | +41.7pp |
| v5 WF | 5/5 | 3/5 | -2 folds |
| v5 Stress PF | 1.58 | 0.949 | -0.63 |
| tp=10 PF | 1.956 | 1.085 | -0.871 |
| tp=10 Exp/wk | +$326 | +$54 | -$272 |
| Trades | 43 | 72 | +29 |

The 29 extra trades (from 181 newly added coins) are net-negative. The signal works on higher-volume coins but generates noise on lower-volume T2 coins with wider spreads.

**v5 (tp=8) vs tp=10 on full universe — reversal from 002**:

| Metric | v5 (tp=8) | tp=10 | Winner |
|--------|-----------|-------|--------|
| PnL | $370 | $233 | v5 |
| PF | 1.138 | 1.085 | v5 |
| Exp/wk | $86 | $54 | v5 |
| Composite | 51.6 | 32.5 | v5 |
| Stress PF | 0.949 | 0.902 | v5 |
| DD | 53.1% | 52.4% | tp=10 |

v5 is now strictly better than tp=10 on the full universe (opposite of 002 findings). tp=10's wider target hurts on the noisier T2 coins.

**Fill model evidence** (from fill_model_002, unchanged):
- **Market execution**: Only profitable mode. v5 T1: +$778, T2: +$233. tp=10 T1: +$625, T2: +$98.
- **Hybrid optimistic**: Marginal. v5 T1: +$109 (positive), v5 T2: -$162 (negative). tp=10: negative on both tiers.
- **Pure limit**: Deeply negative on all tiers. Ruled out.
- **Adverse selection fragility**: PF<1.0 when ~15% top winners missed. Edge is narrow.

**Decision**: **CONDITIONAL HALT** — do not proceed to paper trading on the full 316-coin universe. The signal has edge but it is concentrated in higher-volume coins.

**Evidence**:
- 4/8 hard gates fail on the full universe. Three are hard disqualifiers (stress negative, DD 53%, WF 3/5).
- The edge is real but concentrated: 135 higher-volume coins produce strong results (PF 1.85, 5/5 WF), but adding 181 lower-volume T2 coins dilutes the edge below profitability under stress.
- tp=10 is no longer the preferred variant — v5 (tp=8) wins on the full universe.
- Fill model confirms market-only execution regardless of universe size.

**Consequence — path forward**:
1. **Tighten the universe**: Redefine tier boundaries to exclude low-volume T2 coins that add losing trades. Target: find the volume cutoff where WF >= 4/5 and stress PF > 1.0.
2. **Volume-filter sweep**: Run the strategy with progressively tighter T2 volume floors (e.g., T2 minimum 4H volume from $8K to $50K, $100K, $200K) and find the breakeven cutoff.
3. **T1-only test**: Run v5 on T1 (100 coins) only to see if the edge is isolated to high-volume coins.
4. **Do NOT paper trade the full 316-coin universe** — the strategy loses money under any cost stress scenario on this universe.
5. **Retain v5 (tp=8) as baseline** — tp=10 no longer dominates on the full universe.
6. **Future ADR**: After volume-filter sweep, write ADR-HF-032 with refined universe and updated GO/NO-GO.

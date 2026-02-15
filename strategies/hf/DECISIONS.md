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

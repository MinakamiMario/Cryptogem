# Screening & Promotion Gates — Sprint 4

> **Purpose**: Two-layer progressive filtering for indicator-agnostic hypothesis screening.
> **Scope**: 1H timeframe, T1+T2 universe (314 coins).
> **Date**: 2026-02-15

---

## Layer 1 — Screening Gates (1H)

Run all 15 hypotheses × ≤6 variants = ≤90 configs through Layer 1.

| Gate | ID | Threshold | Kill? | Rationale |
|------|----|-----------|-------|-----------|
| Min Trades | S1 | ≥ 60 | **KILL** | Hard sample-size floor for statistical validity |
| Throughput Goal | S1b | ≥ 120 (~1/day) | soft | +20% score bonus; not auto-kill |
| Net Expectancy/Trade | S2 | > $0 (after per-tier friction) | **KILL** | Negative expectancy = no edge |
| Profit Factor | S3 | ≥ 1.1 | soft | Marginal edge threshold |
| Walk-Forward | S4 | ≥ 2/5 folds positive | soft | Loose temporal stability check |
| Concentration | S5 | top1 < 40%, top3 < 70% | soft | Avoid single-coin dependency |

### Kill Logic
- **Fail S1 OR S2** → immediately eliminated ("KILL")
- **Fail S3/S4/S5** → penalized in ranking but not eliminated
- Survivors ranked by score (secondary to gate pass/fail)

### Scoring (secondary to gates)
```
score = expectancy_per_trade × sqrt(trades) × max(PF - 1, 0.01)
```
- +20% bonus if trades ≥ 120 (throughput goal S1b)
- Ranking used ONLY to pick top 1-2 for Layer 2
- Gates are primary; score is tiebreaker

### Universe & Fees
| Tier | Coins | Per-Side Fee | Source |
|------|-------|-------------|--------|
| Tier 1 (Liquid) | 98 | 31.0 bps (0.0031) | `universe_tiering_001.json` |
| Tier 2 (Mid) | 216 | 56.0 bps (0.0056) | `universe_tiering_001.json` |

Run per tier, combine for composite metrics.

---

## Layer 2 — Promotion Gates (top 1-2 survivors)

| Gate | ID | Threshold | Rationale |
|------|----|-----------|-----------|
| Stress Expectancy | P1 | > $0 at 2× stress fees | Edge survives doubled friction |
| Profit Factor | P2 | ≥ 1.2 | Stronger edge than screening |
| Walk-Forward | P3 | ≥ 3/5 folds positive | Stricter temporal stability |
| Rolling Windows | P4 | ≥ 60% positive (180-bar non-overlapping) | Consistent across sub-periods |
| Max Drawdown | P5 | ≤ 30% | Capital preservation |
| Latency Stress | P6 | expectancy > 0 OR max 20% degradation | Survives execution delay |
| Capacity Proxy | P7 | break-even fee trades < 40% | Not dependent on marginal trades |
| Corr/Exposure | P8 | hard-gate only if max_pos > 1 | Multi-position risk (N/A for max_pos=1) |

### Stress Fee Model
| Tier | Normal Fee | 2× Stress Fee |
|------|-----------|----------------|
| Tier 1 | 31.0 bps | 36.0 bps |
| Tier 2 | 56.0 bps | 86.0 bps |

### Latency Stress Protocol
- Delay entry by 0, 1, 2 bars
- Use close[bar+delay] as entry price (simulates execution lag)
- P6 passes if expectancy stays > $0 or degrades ≤ 20% from baseline

### Promotion Verdict
- **PASS all P1-P7** → candidate for 15m build (Sprint 5)
- **FAIL any** → document in ADR, no promotion

---

## Backtest Parameters (identical to engine)

| Parameter | Value | Source |
|-----------|-------|--------|
| INITIAL_CAPITAL | $2,000 | `agent_team_v3.py:77` |
| START_BAR | 50 | `agent_team_v3.py:73` |
| COOLDOWN_BARS | 4 | `agent_team_v3.py:75` |
| COOLDOWN_AFTER_STOP | 8 | `agent_team_v3.py:76` |
| MAX_POS | 1 | Screening default |
| Walk-Forward Folds | 5 | Standard |
| WF Embargo | 2 bars | Prevent leakage |

---

## Decision Trail
- ADR-HF-019: Standalone harness (not engine extension)
- ADR-HF-020: T1+T2 screening universe
- ADR-HF-021: Fixed exit taxonomy (TP/SL/TIME)
- ADR-HF-022: Two-layer progressive filtering
- ADR-HF-023: Deployability (harness = research-only)

---

*Generated for Sprint 4 hypothesis screening — 2026-02-15*

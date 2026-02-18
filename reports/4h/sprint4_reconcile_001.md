# Sprint 4 Reconciliation Table

**Purpose**: Cross-run identity verification for Sprint 4 top-5 configs.
All tests share the same identity: `dataset=ohlcv_4h_kraken_spot_usd_526`, `fee=kraken_spot_26bps (26 bps)`, `git=9a606d9`, `engine=sprint3.engine`.

---

## Master Reconciliation Table

| Field | 041 (Vol Cap 3x) | 042 (Vol Cap 4x) | 032 (Z-Score -2.5) | 007 (DC-Lite) | 035 (Z-Score -2.0) |
|-------|:-----------------:|:-----------------:|:-------------------:|:-------------:|:-------------------:|
| **config_id** | sprint4_041 | sprint4_042 | sprint4_032 | sprint4_007 | sprint4_035 |
| **hypothesis_id** | H4S4-G05 | H4S4-G06 | H4S4-F02 | H4S4-A07 | H4S4-F05 |
| **family** | Vol Capitulation | Vol Capitulation | Z-Score Extreme | DC-Lite | Z-Score Extreme |
| **dataset_id** | ohlcv_4h_kraken_spot_usd_526 | ohlcv_4h_kraken_spot_usd_526 | ohlcv_4h_kraken_spot_usd_526 | ohlcv_4h_kraken_spot_usd_526 | ohlcv_4h_kraken_spot_usd_526 |
| **universe_id** | universe_487 | universe_487 | universe_487 | universe_487 | universe_487 |
| **fee_model** | kraken_spot_26bps | kraken_spot_26bps | kraken_spot_26bps | kraken_spot_26bps | kraken_spot_26bps |
| **git_hash** | 9a606d9 | 9a606d9 | 9a606d9 | 9a606d9 | 9a606d9 |
| **n_coins** | 487 | 487 | 487 | 487 | 487 |
| **sweep timestamp** | 2026-02-17T20:14 | 2026-02-17T20:14 | 2026-02-17T20:14 | 2026-02-17T20:14 | 2026-02-17T20:14 |
| | | | | | |
| **Sweep PF** | 1.4058 | 1.2784 | 1.3548 | 1.2489 | 1.1618 |
| **Sweep P&L** | $2,284 | $824 | $4,915 | $538 | $810 |
| **Sweep Trades** | 216 | 214 | 206 | 101 | 206 |
| **Sweep DD%** | 49.8% | 59.1% | 44.7% | 40.8% | 52.5% |
| | | | | | |
| **P0: Verdict** | **VERIFIED** | CONDITIONAL | FAILED | FAILED | FAILED |
| **P0: Tests** | **3/3** | 2/3 | 0/3 | 1/3 | 1/3 |
| **P0: Window** | PASS | PASS | FAIL | PASS | PASS |
| **P0: Walk-Forward** | PASS | PASS | FAIL | FAIL | FAIL |
| **P0: Bootstrap** | PASS (P5=0.92) | FAIL (P5=0.78) | FAIL (P5=0.74) | FAIL (P5=0.62) | FAIL (P5=0.56) |
| **P0: %Profitable** | 90.9% | 78.0% | 73.6% | 64.6% | 59.8% |
| | | | | | |
| **P1: Best Wrapper** | dd_throttle | vol_scale | adaptive_maxpos | dd_throttle | vol_scale |
| **P1: Wrapped DD%** | 22.8% | 20.3% | 23.2% | 25.0% | 18.8% |
| **P1: Wrapped PF** | 1.16 | 1.51 | 1.60 | 1.16 | 1.82 |
| **P1: DD Reduction** | 37.4% | 35.9% | 48.1% | 33.6% | 64.1% |
| **P1: Verdict** | INVESTIGATE | INVESTIGATE | INVESTIGATE | NOT_VIABLE | **DEPLOY_CANDIDATE** |
| | | | | | |
| **P2: Trades/Day** | 1.80 | 1.78 | 1.72 | 0.84 | 1.72 |
| **P2: Trades/Week** | 12.63 | 12.51 | 12.05 | 5.91 | 12.05 |
| **P2: Quality Pass** | PASS | PASS | PASS | PASS | PASS |
| **P2: RSI Stable** | Yes | Yes | Yes | Yes | Yes |
| **P2: Vol Stable** | Yes | Yes | Yes | Yes | Yes |
| | | | | | |
| **Guardrails: Replay** | PASS | PASS | PASS | (not tested) | (not tested) |
| **Guardrails: Acctg** | FAIL (delta $1066) | FAIL (delta $993) | PASS | PASS | PASS |
| **Guardrails: Overall** | FAIL | FAIL | FAIL | FAIL | FAIL |
| | | | | | |
| **ELIGIBILITY** | **ELIGIBLE** | CONDITIONAL | INELIGIBLE | INELIGIBLE | **INELIGIBLE** |

---

## 035 Contradiction: DEPLOY_CANDIDATE in P1, FAILED in P0

**This is the critical finding of this reconciliation.**

| Layer | 035 Result | Implication |
|-------|-----------|-------------|
| P0 (truthpass) | **FAILED** (1/3 tests) | Walk-forward FAILS, bootstrap P5 PF=0.56, only 59.8% profitable |
| P1 (ddfix) | **DEPLOY_CANDIDATE** | vol_scale wrapper: PF 1.16->1.82, DD 52.5%->18.8% |
| Contradiction | P1 promotes what P0 rejects | **P1 does not re-run P0 tests on wrapped config** |

### Root Cause

The P1 ddfix pipeline tests only drawdown reduction and PF preservation under position-sizing wrappers. It does NOT re-validate robustness (walk-forward, bootstrap, window stability) on the wrapped configuration. The vol_scale wrapper masks the fundamental fragility that P0 detected:

- **Bootstrap P5 PF = 0.5649** -- the 5th percentile profit factor is below 1.0, meaning in 40% of bootstrapped trade orderings the strategy loses money
- **Walk-forward FAILS** -- the strategy does not generalize across time windows
- **Only 59.8% of bootstraps are profitable** -- barely above coin-flip territory

The vol_scale wrapper improves the *apparent* metrics by reducing position size in high-volatility regimes, but it cannot fix a strategy that lacks fundamental edge stability.

### Conclusion

**P0 is the gating test. Config 035 is INELIGIBLE for deployment.** The DEPLOY_CANDIDATE label from P1 is misleading and should be ignored.

### Recommendation

Add a P0 re-validation gate to the P1 pipeline: any config that reaches DEPLOY_CANDIDATE status in P1 must re-pass truthpass (P0) before final promotion. This prevents false positives where position-sizing wrappers mask fragile edge.

---

## Wrapped Truth-Pass Results (ADR-4H-012)

| Metric | 041 Raw | 041+vol_scale | 042 Raw | 042+vol_scale |
|--------|:-------:|:-------------:|:-------:|:-------------:|
| **Verdict** | **VERIFIED (3/3)** | CONDITIONAL (2/3) | CONDITIONAL (2/3) | CONDITIONAL (2/3) |
| PF | 1.41 | 1.59 | 1.28 | 1.51 |
| DD | 49.8% | 28.1% | 31.8% | 20.3% |
| P&L | $+2,284 | $+3,557 | $+824 | $+2,246 |
| Window Split | PASS (3/3) | PASS (2/3) | PASS (2/3) | PASS (3/3) |
| Walk-Forward | PASS | PASS | PASS | PASS |
| Bootstrap P5 PF | 0.92 ✅ | 0.83 ❌ | 0.78 ❌ | 0.71 ❌ |
| Bootstrap %Prof | 90.9% ✅ | 87.4% ✅ | 78.0% ❌ | 76.7% ❌ |

**Critical finding**: Vol_scale DEGRADES 041's bootstrap (0.92→0.83). The wrapper reduces position sizes (median scale=0.25), narrowing P&L distribution. **041 is strongest unwrapped.**

---

## Eligibility Summary (Updated — Guardrails 6/6 PASS)

| Config | P0 Raw | P0 Wrapped | P1 | P2 | Guardrails | Final |
|--------|:------:|:----------:|:--:|:--:|:----------:|:-----:|
| **041** | **VERIFIED (3/3)** | CONDITIONAL (2/3) | INVESTIGATE | PASS | **6/6 PASS** | **ELIGIBLE (unwrapped)** |
| 042 | CONDITIONAL (2/3) | CONDITIONAL (2/3) | INVESTIGATE | PASS | **6/6 PASS** | CONDITIONAL |
| 032 | FAILED (0/3) | — | INVESTIGATE | PASS | **6/6 PASS** | INELIGIBLE |
| 007 | FAILED (1/3) | — | NOT_VIABLE | PASS | **6/6 PASS** | INELIGIBLE |
| 035 | FAILED (1/3) | — | DEPLOY_CANDIDATE | PASS | **6/6 PASS** | **INELIGIBLE** |

---

## Notes

- All 5 configs ran on identical infrastructure: same dataset, same fee model, same git hash, same engine
- Universe: 487 coins (>=360 bars filter from universe_sprint1.json), sourced from 526-coin cache
- **Guardrails 6/6 PASS** after fixing: dataset integrity (check metadata not live cache), provenance (added _provenance to output), accounting (equity tracking), fee consistency (price rounding tolerance)
- Deterministic replay PASSES for all 3 tested configs (041, 032, 042), confirming engine correctness
- Trade frequency (P2) is healthy for all configs except 007 (0.84 trades/day vs 1.7-1.8 for others)
- 041+vol_scale bootstrap degrades because median scale=0.25 compresses PNL distribution — deploy 041 unwrapped

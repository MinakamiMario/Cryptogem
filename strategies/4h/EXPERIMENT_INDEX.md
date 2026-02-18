# 4H DualConfirm — Experiment Index

Quick-lookup: experiment → dataset → scoreboard → verdict → ADR.

Generated: 2026-02-17 | Git: 2659755

## Experiments

| ID | Name | Dataset | Universe | Fee Model | Scoreboard | Verdict | ADR |
|----|------|---------|----------|-----------|------------|---------|-----|
| v1 | Sweep V1 (30 configs, trail/notrl/tpsl) | `ohlcv_4h_kraken_spot_usd_526` | `kraken_4h_526_v1` (526 coins) | `kraken_spot_26bps` | `scoreboard_sweep_v1.json` | **3 GO** | 4H-002 |
| v1b | Time Window Split (EARLY/LATE 360 bars) | `ohlcv_4h_kraken_spot_usd_526` (windowed) | `kraken_4h_526_v1` (487 coins) | `kraken_spot_26bps` | — (inline in ADR) | 1/3 GO (LATE only) | 4H-003 |
| v1b-regime | Regime Filter (SMA50 slope) | `ohlcv_4h_kraken_spot_usd_526` (windowed) | `kraken_4h_526_v1` (487 coins) | `kraken_spot_26bps` | — (inline in ADR) | DIAGNOSTIC only | 4H-004 |
| v2 | Extended 360d Proxy (6 configs) | `ohlcv_4h_kraken_spot_usd_v2` | `kraken_4h_cohortA_170_v1` / `cohortB_242_v1` | `kraken_spot_26bps` | `scoreboard_sweep_v2.json` | **0 GO** | 4H-005 |
| confirm | Kraken Native Confirm (6 configs) | `ohlcv_4h_kraken_spot_usd_native_confirm` | `kraken_4h_native_62_v1` (62 coins) | `kraken_spot_26bps` | `scoreboard_confirm.json` | **2 GO** | 4H-005-A |
| mexc | MEXC Portability (4 configs) | `ohlcv_4h_mexc_spot_usdt_v1` | `mexc_4h_cohortA_144_v1` (144 coins) | `mexc_spot_10bps` / `kraken_spot_26bps` | `scoreboard_sweep_v2.json` (combined) | **0 GO** | 4H-006 |
| sprint1 | Sprint 1 All-Weather (21 configs, 5 families) | `ohlcv_4h_kraken_spot_usd_526` | `universe_sprint1` (487 coins) | `kraken_spot_26bps` | `scoreboard_sprint1.json` | **0 GO** | 4H-007 |
| sprint2 | Sprint 2 Entry-Edge Discovery (24 configs, 4 families) | `ohlcv_4h_kraken_spot_usd_526` | `universe_sprint1` (487 coins) | `kraken_spot_26bps` | `scoreboard_sprint2.json` | **0 GO** | 4H-008 |
| sprint3 | Sprint 3 Exit-Intelligence Porting (18 configs, DC exits) | `ohlcv_4h_kraken_spot_usd_526` | `universe_sprint1` (487 coins) | `kraken_spot_26bps` | `scoreboard_sprint3.json` | **0 GO** | 4H-009 |
| sprint4 | Sprint 4 DC-Compatible Entry Mining (42→10 configs, 7 families) | `ohlcv_4h_kraken_spot_usd_526` | `universe_sprint1` (487 coins) | `kraken_spot_26bps` | `scoreboard_sprint4_strict.json` | **7/10 PF>1.05** (8 STRONG) | 4H-010 |
| sprint4_val | Sprint 4 P0/P1/P2 Validation Pipeline | `ohlcv_4h_kraken_spot_usd_526` | `universe_sprint1` (487 coins) | `kraken_spot_26bps` | `sprint4_truthpass_summary.json` | **1 VERIFIED, 1 CONDITIONAL** | 4H-011 |

## Scoreboards

| File | Experiments | Runs | GO | Created |
|------|------------|------|-----|---------|
| `reports/4h/scoreboard_sweep_v1.json` | v1 | 30 | 3 | 2026-02-17 |
| `reports/4h/scoreboard_confirm.json` | confirm | 6 | 2 | 2026-02-17 |
| `reports/4h/scoreboard_sweep_v2.json` | v2 + mexc | 10 | 0 | 2026-02-17 |
| `reports/4h/scoreboard_sprint1.json` | sprint1 | 21 | 0 | 2026-02-17 |
| `reports/4h/scoreboard_sprint2.json` | sprint2 | 24 | 0 | 2026-02-17 |
| `reports/4h/scoreboard_sprint3.json` | sprint3 | 18 | 0 | 2026-02-17 |
| `reports/4h/scoreboard_sprint4_strict.json` | sprint4 | 10 | 7 (PF>1.05) | 2026-02-17 |
| `reports/4h/scoreboard_sprint4_research.json` | sprint4 | 10 | 7 (PF>1.0) | 2026-02-17 |
| `reports/4h/sprint4_edge_decomposition.json` | sprint4 | 10 | 8 STRONG | 2026-02-17 |
| `reports/4h/sprint4_truthpass_summary.json` | sprint4_val (P0) | 5 | 1 VERIFIED + 1 CONDITIONAL | 2026-02-17 |
| `reports/4h/sprint4_ddfix_scoreboard.json` | sprint4_val (P1) | 55 | 1 DEPLOY + 3 INVESTIGATE | 2026-02-17 |
| `reports/4h/sprint4_dd_analysis.json` | sprint4_val (P1) | 5 | FIXED STOP=71% DD | 2026-02-17 |
| `reports/4h/sprint4_tradefreq.json` | sprint4_val (P2) | 40 | 40/40 pass, 32/40 ≥1/day | 2026-02-17 |
| `reports/4h/sprint4_guardrails.json` | sprint4_val (E) | 6 | 2/6 pass | 2026-02-17 |

## Datasets (frozen, with SHA256)

| Registry ID | Exchange | Source | Coins | Bars | Status | SHA256 prefix |
|-------------|----------|--------|-------|------|--------|---------------|
| `ohlcv_4h_kraken_spot_usd_526` | Kraken | native | 526 | ~721 | frozen | `f7c70e7a` |
| `ohlcv_4h_kraken_spot_usd_v2` | Kraken | CC proxy | 336 | 2183 | frozen | `084da932` |
| `ohlcv_4h_kraken_spot_usd_native_confirm` | Kraken | native | 62 | 721 | frozen | `db88a213` |
| `ohlcv_4h_mexc_spot_usdt_v1` | MEXC | CC proxy | 146 | 2501 | frozen | `f7801b8d` |

## Fee Models

| ID | Exchange | Maker | Taker | Note |
|----|----------|-------|-------|------|
| `kraken_spot_26bps` | Kraken | 26 bps | 26 bps | Standard tier, taker-only assumption |
| `mexc_spot_10bps` | MEXC | 0 bps | 10 bps | Conservative taker-only |

## Universes

| ID | Exchange | Coins | Selection | Dataset |
|----|----------|-------|-----------|---------|
| `kraken_4h_526_v1` | Kraken | 526 | All active SPOT (baseline) | `ohlcv_4h_kraken_spot_usd_526` |
| `kraken_4h_cohortA_170_v1` | Kraken | 170 | ≥2160 bars from v2 | `ohlcv_4h_kraken_spot_usd_v2` |
| `kraken_4h_cohortB_242_v1` | Kraken | 242 | ≥1080 bars from v2 | `ohlcv_4h_kraken_spot_usd_v2` |
| `kraken_4h_native_62_v1` | Kraken | 62 | Traded coins + BTC/ETH | `ohlcv_4h_kraken_spot_usd_native_confirm` |
| `mexc_4h_200_v1` | MEXC | 200 | Top-200 by volume, ≥2160 bars | — (200 selected, 146 downloaded) |
| `mexc_4h_cohortA_144_v1` | MEXC | 144 | ≥2160 bars from downloaded | `ohlcv_4h_mexc_spot_usdt_v1` |

## ADR Quick Reference

| ADR | Title | Status | Key Finding |
|-----|-------|--------|-------------|
| 4H-001 | Gates-Lite Framework | ACCEPTED | 5-gate pre-filter for sweep screening |
| 4H-002 | Sweep V1 Results | ACCEPTED | 3 GO configs, all hybrid_notrl, G5 hardest gate |
| 4H-003 | Time Window Split | ACCEPTED | EARLY break-even, LATE explosive — edge is regime-dependent |
| 4H-004 | Regime Diagnose | ACCEPTED | SMA50 slope is #1 discriminator, filter not deployable on 120d |
| 4H-005 | Extended 360d + Slope-sizing | ACCEPTED | Baseline negative, slope-sizing helps but not enough (PF 1.09) |
| 4H-005-A | Kraken Native Confirm | ACCEPTED | Native GO (PF 2.52 baseline, 4.24 slope), proxy is pessimistic |
| 4H-006 | MEXC Portability | ACCEPTED (NO-GO) | 70% fewer trades, fee delta modest, portability disproven |
| 4H-007 | Sprint 1 All-Weather Screening | ACCEPTED (NO-GO) | 0/21 configs pass, best PF=0.89, smart exits essential |
| 4H-008 | Sprint 2 Entry-Edge Discovery | ACCEPTED (NO-GO) | 0/24 configs pass (relaxed PF>1.05), best PF=0.85, multi-condition entries still no edge |
| 4H-009 | Sprint 3 Exit-Intelligence Porting | ACCEPTED (NO-GO) | 0/18 pass, DC exits NOT portable (best PF=0.95), entry+exit co-dependent |
| 4H-010 | Sprint 4 DC-Compatible Entry Mining | ACCEPTED | 7/10 PF>1.05, 8 STRONG LEADs, Class A 100% dominant, geometric compatibility validated |
| 4H-011 | Sprint 4 P0/P1/P2 Validation | ACCEPTED | 1 VERIFIED (041), 1 CONDITIONAL (042). Vol-scale best wrapper. Z-Score/DC-Lite eliminated. |

## Key Conclusions

1. **DualConfirm bounce is a conditional strategy** — profitable only in steep downtrend (SMA50 slope < -8%)
2. **Slope-as-sizing is essential** — converts negative baseline to positive on both exchanges
3. **hybrid_notrl dominates** — trail and tp_sl exits fail gate pipeline
4. **Portability is limited** — works on Kraken, not MEXC (different microstructure)
5. **Native Kraken data > proxy data** — proxy is conservative (6 ghost trades in 62-coin subset)
6. **Simple entries + fixed TP/SL don't generate edge** — 9 signal families, 45 configs (Sprint 1+2), all PF < 1.05 on 487 coins
7. **Smart exits are the profit generator** — DC TARGET + RSI RECOVERY (100% WR) can't be replaced by fixed TP/SL
8. **Multi-condition entries don't help either** — Sprint 2 added volume confirmation, regime filters, cross-sectional momentum, anti-fakeout logic; still 0 GO
9. **Breakout strategies catastrophically fail** — PF 0.38-0.47, DD 98-99%; continuation-based entries don't work at 4H resolution on crypto
10. **DualConfirm exits are NOT portable to arbitrary entries** — Sprint 3 showed DC exits fail on entries without geometric compatibility (best PF=0.95)
11. **DualConfirm exits ARE portable to geometrically compatible entries** — Sprint 4 proved DC exits work when entries enforce: close < dc_mid AND close < bb_mid AND RSI has headroom. 7/10 PF > 1.05, 8/10 STRONG LEADs.
12. **Geometric compatibility is the key insight** — Sprint 3's failure was entry selection, not exit portability. Entries must place trades where DC exits have room to fire.
13. **RSI RECOVERY is the #1 profit source** — $48K total across 856 exits (all 10 Sprint 4 configs), 100% Class A dominance
14. **Z-Score Extreme and Volume Capitulation are best families** — Z-Score avg PF=1.26, Vol Capitulation best PF=1.41
15. **High drawdown remains** — All Sprint 4 configs have DD 40-90% (vs Sprint 1 hard gate G2 ≤15%). Entries are directionally correct but sizing/risk management needs work.
16. **Only Volume Capitulation survives truth-pass** — Z-Score Extreme and DC-Lite families fail temporal stability (early window PF < 0.5). Sprint4_041 = VERIFIED (3/3), sprint4_042 = CONDITIONAL (2/3).
17. **Vol-scaling is the best risk wrapper** — DD -64% on sprint4_035, -36% on sprint4_042. DD throttle halves DD but also halves PF. Cooldown extension = 0% effect (max_pos=1).
18. **FIXED STOP = 71.1% of drawdown** — TIME MAX = 24.6%. Stop distance reduction and vol-scaling sizing are the primary DD reduction levers.
19. **Trade frequency is robust** — 40/40 sensitivity tests pass quality gates. RSI and volume thresholds stable. Full pool adds 0 trades.
20. **Sprint4_041 is the primary production candidate** — VERIFIED truth-pass, PF=1.41, bootstrap P5=0.92, 90.9% profitable shuffles, 1.8 trades/day. DD=49.8% (needs risk wrapper).

---

*Last updated: 2026-02-17 | Git: 9a606d9 | Source: `strategies/4h/DECISIONS_4H.md`*

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

## Scoreboards

| File | Experiments | Runs | GO | Created |
|------|------------|------|-----|---------|
| `reports/4h/scoreboard_sweep_v1.json` | v1 | 30 | 3 | 2026-02-17 |
| `reports/4h/scoreboard_confirm.json` | confirm | 6 | 2 | 2026-02-17 |
| `reports/4h/scoreboard_sweep_v2.json` | v2 + mexc | 10 | 0 | 2026-02-17 |

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

## Key Conclusions

1. **DualConfirm bounce is a conditional strategy** — profitable only in steep downtrend (SMA50 slope < -8%)
2. **Slope-as-sizing is essential** — converts negative baseline to positive on both exchanges
3. **hybrid_notrl dominates** — trail and tp_sl exits fail gate pipeline
4. **Portability is limited** — works on Kraken, not MEXC (different microstructure)
5. **Native Kraken data > proxy data** — proxy is conservative (6 ghost trades in 62-coin subset)

---

*Last updated: 2026-02-17 | Source: `strategies/4h/DECISIONS_4H.md`*

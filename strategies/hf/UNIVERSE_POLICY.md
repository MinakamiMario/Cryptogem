# UNIVERSE_POLICY.md — Tradability & Universe Policy

> 4H variant research. This policy defines which coins are eligible for live trading.

## Inclusion Filters

A coin must pass ALL of the following to be included:

| Filter | Threshold | Rationale |
|--------|-----------|-----------|
| Min median daily volume | ≥ P25 of universe (~$8,300) | Excludes dust-volume coins untradeable on Kraken |
| Max zero-volume candles | < 20% of bars | Coins with extended zero-vol periods may be delisted/frozen |
| Min bar coverage | ≥ 95% of max bars | Ensures sufficient data for indicator computation |
| OHLCV integrity | 0 violations | No negative prices, no high < close, etc. |

**Effect**: Filters Tier 3 (illiquid) out. Tiers 1 + 2 survive (316 of 425 coins).

## Tier Assignment

Based on `hf_universe_tiering.py` output:

| Tier | Criteria | Coins | Median Vol | Role |
|------|----------|-------|-----------|------|
| Tier 1 (Liquid) | Vol ≥ P75, zero_vol < 5%, coverage ≥ 99% | ~100 | ~1.3M | Low execution risk, low alpha |
| Tier 2 (Mid) | Vol ≥ P25, zero_vol < 20%, coverage ≥ 95% | ~216 | ~44.8K | Primary alpha source, moderate execution risk |
| Tier 3 (Illiquid) | Below Tier 2 thresholds | ~109 | ~2.0K | EXCLUDED from live trading |

## Per-Tier Fee Model (from `hf_friction_v2.py`)

| Tier | Base Fee | Slippage | Total Per Side | Round Trip |
|------|----------|----------|---------------|------------|
| Tier 1 | 26 bps | 5 bps | 31 bps | 62 bps |
| Tier 2 | 26 bps | 30 bps | 56 bps | 112 bps |
| Tier 3 | 26 bps | 75 bps | 101 bps | 202 bps |

## Capacity Limits

For a $2,000 account (INITIAL_CAPITAL):

| Constraint | Value | Rationale |
|------------|-------|-----------|
| Max simultaneous positions | 1 | DualConfirm config `max_pos=1` |
| Max position size | 100% of equity | Single-position strategy, full allocation |
| Max per-coin exposure | No limit (single pos) | Strategy holds 1 position at a time |
| Min trade P&L to cover friction | ~$22 (Tier 2 round-trip on $2K) | Break-even threshold per trade |

## Tier-Based Sizing (future)

Currently `max_pos=1` so sizing is binary. When/if `max_pos > 1`:

| Tier | Max allocation % | Rationale |
|------|-----------------|-----------|
| Tier 1 | 100% | Low execution risk |
| Tier 2 | 75% | Higher slippage, reduce exposure |
| Tier 3 | 0% | EXCLUDED |

## Live Trading Eligibility

A config is eligible for live trading ONLY if:
1. All 5 hard gates PASS (see `GATES.md`)
2. Per-tier friction composite P&L > $0 (see `hf_friction_v2.py`)
3. Tier 2 alone has P&L > $0 under per-tier friction
4. Per-tier 2x stress P&L > $0 (safety margin)
5. Universe policy filters applied (no Tier 3 coins)

---
*Canonical universe policy. Updates require ADR entry in DECISIONS.md.*

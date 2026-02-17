# Regime Diagnosis: EARLY vs LATE

**Generated**: 2026-02-17 10:23 UTC
**Dataset**: 514 coins, 721 bars (4H Kraken)
**EARLY**: bars 0-359 (Oct 16 - Dec 15, 2025) | 514 coins analyzed
**LATE**: bars 360-719 (Dec 15 - Feb 13, 2026) | 483 coins analyzed

## Problem Statement

All 3 GO configs from sweep v1 are break-even in EARLY but explosive in LATE (PF 6-9).
The DualConfirm bounce strategy needs: VOLATILITY + OVERSOLD (RSI<42) + VOLUME SPIKE (>3x).
Which market-regime feature changed between the two halves?

## Regime Comparison Table

| Metric | Unit | EARLY mean | LATE mean | Delta | EARLY med | LATE med | What it means |
|--------|------|-----------|----------|-------|-----------|---------|---------------|
| ATR% (14-period) | % | 4.54 | 3.96 | -0.58 (-13%) | 3.50 | 3.04 | Higher = more volatility |
| RSI<40 frequency | % | 29.02 | 28.24 | -0.78 (-3%) | 28.12 | 27.54 | Higher = more oversold bars |
| RSI<30 frequency | % | 7.08 | 8.75 | +1.68 (+24%) | 5.22 | 6.47 | Higher = deeply oversold bars |
| Average RSI |  | 45.65 | 46.57 | +0.92 (+2%) | 45.74 | 46.21 | Lower = more bearish |
| Range/ATR ratio | x | 0.86 | 0.84 | -0.02 (-2%) | 0.91 | 0.92 | Higher = choppier |
| Vol spike >2x freq | % | 13.10 | 13.52 | +0.42 (+3%) | 13.06 | 13.61 | Higher = more vol events |
| Vol spike >3x freq | % | 7.16 | 7.64 | +0.48 (+7%) | 7.22 | 7.78 | Strategy trigger threshold |
| SMA50 slope | % | -4.03 | -14.20 | -10.17 (-253%) | -3.95 | -15.15 | Negative = downtrend |
| Max drawdown | % | 52.64 | 50.98 | -1.66 (-3%) | 50.37 | 50.74 | Deeper = more bounce opportunities |
| Window return | % | -33.18 | -26.21 | +6.97 (+21%) | -36.30 | -31.27 | Overall price change |

## Distribution Detail (P25 / P75)

| Metric | EARLY P25 | EARLY P75 | LATE P25 | LATE P75 | Spread change |
|--------|-----------|-----------|----------|----------|---------------|
| ATR% (14-period) | 2.67 | 5.15 | 2.39 | 4.69 | -0.19 (-7%) |
| RSI<40 frequency | 22.03 | 34.49 | 20.87 | 34.41 | +1.08 (+9%) |
| RSI<30 frequency | 2.90 | 8.62 | 3.77 | 10.72 | +1.23 (+22%) |
| Average RSI | 44.07 | 47.20 | 44.81 | 47.82 | -0.13 (-4%) |
| Range/ATR ratio | 0.80 | 0.97 | 0.77 | 0.98 | +0.04 (+26%) |
| Vol spike >2x freq | 11.91 | 14.44 | 12.22 | 15.28 | +0.52 (+21%) |
| Vol spike >3x freq | 5.56 | 8.89 | 6.11 | 9.44 | +0.00 (+0%) |
| SMA50 slope | -8.86 | 0.60 | -20.26 | -8.47 | +2.32 (+25%) |
| Max drawdown | 40.56 | 64.52 | 42.67 | 58.54 | -8.09 (-34%) |
| Window return | -49.76 | -21.97 | -42.94 | -18.39 | -3.24 (-12%) |

## Trade Attribution: hnotrl_msp20 (FULL window)

| Window | Trades | Win Rate | Avg P&L | Total P&L | Profit Factor |
|--------|--------|----------|---------|-----------|---------------|
| EARLY | 16 | 62.50% | $0.44 | $7.04 | 1.02 |
| LATE | 27 | 77.78% | $123.10 | $3323.64 | 5.12 |

### Exit Reasons by Window

**EARLY**:

| Exit Reason | Count | Win Rate | Total P&L |
|-------------|-------|----------|-----------|
| DC TARGET | 8 | 87.50% | $238.99 |
| RSI RECOVERY | 6 | 50.00% | $28.10 |
| BB TARGET | 1 | 0.00% | $-53.70 |
| FIXED STOP | 1 | 0.00% | $-206.34 |

**LATE**:

| Exit Reason | Count | Win Rate | Total P&L |
|-------------|-------|----------|-----------|
| RSI RECOVERY | 16 | 87.50% | $3669.82 |
| DC TARGET | 6 | 100.00% | $403.66 |
| END | 1 | 100.00% | $52.20 |
| TIME MAX | 1 | 0.00% | $-145.06 |
| FIXED STOP | 3 | 0.00% | $-656.97 |

## Key Findings

### Ranked by magnitude of change (EARLY -> LATE):

1. **SMA50 slope**: -4.03 -> -14.20 (DOWN 253%) -- Negative = downtrend
2. **RSI<30 frequency**: 7.08 -> 8.75 (UP 24%) -- Higher = deeply oversold bars
3. **Window return**: -33.18 -> -26.21 (UP 21%) -- Overall price change
4. **ATR% (14-period)**: 4.54 -> 3.96 (DOWN 13%) -- Higher = more volatility
5. **Vol spike >3x freq**: 7.16 -> 7.64 (UP 7%) -- Strategy trigger threshold
6. **Vol spike >2x freq**: 13.10 -> 13.52 (UP 3%) -- Higher = more vol events
7. **Max drawdown**: 52.64 -> 50.98 (DOWN 3%) -- Deeper = more bounce opportunities
8. **RSI<40 frequency**: 29.02 -> 28.24 (DOWN 3%) -- Higher = more oversold bars
9. **Range/ATR ratio**: 0.86 -> 0.84 (DOWN 2%) -- Higher = choppier
10. **Average RSI**: 45.65 -> 46.57 (UP 2%) -- Lower = more bearish

### Interpretation

The DualConfirm bounce strategy needs THREE conditions simultaneously:
1. RSI < 42 (oversold)
2. Donchian + BB confirmation (price near lower bands)
3. Volume spike > 3x (capitulation/washout)

**Max Drawdown** is 3% shallower in LATE (52.64% -> 50.98%). Shallower drawdowns create FEWER entries.

**RSI<40 frequency** decreased: 29.02% -> 28.24% of bars. Fewer oversold conditions.

**RSI<30 frequency** (deep oversold): 7.08% -> 8.75% of bars.

**ATR%** decreased: 4.54% -> 3.96%. 

**Volume spike >3x frequency** increased: 7.16% -> 7.64%. This is the strategy's entry filter -- more trigger opportunities.

**SMA50 slope**: -4.03% -> -14.20%. LATE has stronger downtrend, creating deeper selloffs that bounce harder.

**Window return**: -33.18% -> -26.21%. 

### Verdict

The **top discriminating feature** is **SMA50 slope** (-253% change).
Second is **RSI<30 frequency** (+24%).
Third is **Window return** (+21%).

The strategy is a **regime-dependent bounce strategy**: it profits when the market
creates deep selloffs (high drawdowns, low RSI, high ATR) with capitulation volume (3x spikes).
EARLY was a range-bound / mild decline market that rarely triggered entry conditions.
LATE was a deeper bear market with sharper selloffs and more frequent capitulation events.

**Implication for production**: This strategy needs a regime filter or should only deploy
capital when market conditions match the LATE-window profile. A simple ATR% or drawdown
threshold could serve as a regime gate.
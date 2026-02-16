# Part 2 -- Monte Carlo Trade Shuffle (Agent C8-C, P2-8)

**Date**: 2026-02-16 01:42
**Commit**: 1787377
**Universe**: T1(96) + T2(199) = 295 coins (excl 21 net-negative)
**Params**: v5 (dev=2.0, tp=8, sl=5, tl=10)
**Fees**: T1=12.5bps, T2=23.5bps
**Shuffles**: 10,000 (seed=42)
**Initial Capital**: $2,000
**Runtime**: 27.7s (MC: 0.1s)

## Verdict

**PASS**: P&L=$3272 always positive, P95 DD=22.7% < 30%, zero ruin probability

## 1. Baseline (295 coins, original order)

| Metric | Value |
|--------|-------|
| Trades | 56 (T1:18, T2:38) |
| Total P&L | $3272.13 |
| Profit Factor | 2.834 |
| Win Rate | 64.3% |
| Max DD (original) | 8.6% |
| Winners / Losers | 36 / 20 |
| Exp/trade | $58.43 |
| Exp/week | $762.44 |

### Exit Reasons

| Reason | Count | P&L | Avg P&L |
|--------|-------|-----|---------|
| FIXED STOP | 7 | $-1137.58 | $-162.51 |
| PROFIT TARGET | 21 | $4397.68 | $209.41 |
| TIME MAX | 28 | $12.03 | $0.43 |

## 2. Monte Carlo P&L Distribution

> **Note**: Since we shuffle the same set of trades, the total P&L is always $3272.13 (sum is commutative). The real test is drawdown.

| Statistic | Value |
|-----------|-------|
| Mean | $3272.13 |
| Median | $3272.13 |
| Std Dev | $0.00 |
| P5 | $3272.13 |
| P25 | $3272.13 |
| P75 | $3272.13 |
| P95 | $3272.13 |

### Win Probabilities

| Threshold | Probability |
|-----------|-------------|
| P&L >$0 | 100.0% |
| P&L >$500 | 100.0% |
| P&L >$1000 | 100.0% |
| P&L >$2000 | 100.0% |

## 3. Max Drawdown Distribution (KEY RESULT)

This is the core insight from trade-order shuffling: how much does drawdown vary with the sequence of trades?

| Statistic | DD% |
|-----------|-----|
| Mean | 13.2% |
| Median | 12.2% |
| Std Dev | 4.9% |
| P5 (best) | 7.5% |
| P25 | 9.8% |
| P75 | 15.5% |
| P95 (stress) | 22.7% |
| P99 (extreme) | 30.2% |
| Min (luckiest) | 4.5% |
| Max (unluckiest) | 47.8% |
| **Original order** | **8.6%** (percentile: 14%) |

### Drawdown Exceedance Probabilities

| DD Threshold | P(DD > threshold) |
|-------------|-------------------|
| >5% | 100.0% |
| >10% | 73.1% |
| >15% | 27.7% |
| >20% | 9.2% |
| >25% | 3.1% |
| >30% | 1.0% |
| >50% | 0.0% |

## 4. Risk Metrics

| Metric | Value |
|--------|-------|
| Sharpe-like (P&L/std) | inf |
| Risk-adjusted (P&L/mean_DD) | 247.0689 |
| Prob of ruin (equity<=0) | 0.00% |

### Minimum Equity Distribution (worst point in curve)

| Statistic | Value |
|-----------|-------|
| Mean | $1972.79 |
| Median | $1988.79 |
| P5 (worst 5%) | $1642.22 |
| P95 (best 5%) | $2245.71 |

## 5. Trade List (sorted by entry)

Total: 56 trades

| # | Pair | P&L | P&L% | Reason | Bars | Tier |
|---|------|-----|------|--------|------|------|
| 1 | JUNO/USD | $150.22 | 7.5% | PROFIT TARGET | 6 | tier2 |
| 2 | REKT/USD | $154.80 | 7.7% | PROFIT TARGET | 1 | tier1 |
| 3 | XYO/USD | $33.01 | 1.5% | TIME MAX | 10 | tier2 |
| 4 | BLZ/USD | $10.35 | 0.5% | TIME MAX | 10 | tier2 |
| 5 | TOKEN/USD | $164.76 | 7.5% | PROFIT TARGET | 5 | tier2 |
| 6 | ELX/USD | $-112.99 | -5.2% | FIXED STOP | 1 | tier1 |
| 7 | GHIBLI/USD | $158.04 | 7.7% | PROFIT TARGET | 3 | tier1 |
| 8 | SIGMA/USD | $177.14 | 7.5% | PROFIT TARGET | 1 | tier2 |
| 9 | NYM/USD | $190.45 | 7.5% | PROFIT TARGET | 7 | tier2 |
| 10 | CAMP/USD | $-36.12 | -1.3% | TIME MAX | 10 | tier2 |
| 11 | ALPHA/USD | $83.36 | 3.1% | TIME MAX | 10 | tier2 |
| 12 | NOBODY/USD | $208.30 | 7.5% | PROFIT TARGET | 4 | tier2 |
| 13 | SGB/USD | $-77.99 | -3.5% | TIME MAX | 10 | tier1 |
| 14 | AURA/USD | $-7.54 | -0.2% | TIME MAX | 10 | tier2 |
| 15 | SIGMA/USD | $-34.38 | -1.2% | TIME MAX | 10 | tier2 |
| 16 | REKT/USD | $-111.26 | -5.2% | FIXED STOP | 2 | tier1 |
| 17 | BTT/USD | $1.51 | 0.1% | TIME MAX | 10 | tier1 |
| 18 | XYO/USD | $-11.21 | -0.4% | TIME MAX | 10 | tier2 |
| 19 | AURA/USD | $20.31 | 0.7% | TIME MAX | 10 | tier2 |
| 20 | NYM/USD | $-52.96 | -1.8% | TIME MAX | 10 | tier2 |
| 21 | SBR/USD | $43.75 | 2.2% | TIME MAX | 10 | tier1 |
| 22 | GOMINING/USD | $217.50 | 7.5% | PROFIT TARGET | 5 | tier2 |
| 23 | SIGMA/USD | $-169.93 | -5.5% | FIXED STOP | 4 | tier2 |
| 24 | SAMO/USD | $-38.34 | -1.3% | TIME MAX | 10 | tier2 |
| 25 | BANANAS31/USD | $8.04 | 0.4% | TIME MAX | 10 | tier1 |
| 26 | GOMINING/USD | $-53.20 | -1.8% | TIME MAX | 10 | tier2 |
| 27 | AUDIO/USD | $214.20 | 7.5% | PROFIT TARGET | 2 | tier2 |
| 28 | ARPA/USD | $-44.37 | -1.4% | TIME MAX | 10 | tier2 |
| 29 | DEEP/USD | $-10.19 | -0.3% | TIME MAX | 10 | tier2 |
| 30 | AURA/USD | $226.19 | 7.5% | PROFIT TARGET | 2 | tier2 |
| 31 | MF/USD | $-176.71 | -5.5% | FIXED STOP | 3 | tier2 |
| 32 | KOBAN/USD | $-108.23 | -5.2% | FIXED STOP | 1 | tier1 |
| 33 | BILLY/USD | $229.90 | 7.5% | PROFIT TARGET | 1 | tier2 |
| 34 | ELX/USD | $151.37 | 7.7% | PROFIT TARGET | 1 | tier1 |
| 35 | AURA/USD | $247.17 | 7.5% | PROFIT TARGET | 2 | tier2 |
| 36 | DOGS/USD | $39.30 | 1.9% | TIME MAX | 10 | tier1 |
| 37 | CVC/USD | $265.74 | 7.5% | PROFIT TARGET | 10 | tier2 |
| 38 | SAROS/USD | $-45.37 | -1.2% | TIME MAX | 10 | tier2 |
| 39 | DRV/USD | $-139.32 | -3.7% | TIME MAX | 10 | tier2 |
| 40 | BODEN/USD | $96.21 | 2.7% | TIME MAX | 10 | tier2 |
| 41 | XL1/USD | $166.13 | 7.7% | PROFIT TARGET | 2 | tier1 |
| 42 | OGN/USD | $47.35 | 1.3% | TIME MAX | 10 | tier2 |
| 43 | XL1/USD | $178.99 | 7.7% | PROFIT TARGET | 2 | tier1 |
| 44 | XAN/USD | $126.63 | 5.1% | TIME MAX | 10 | tier1 |
| 45 | SUSHI/USD | $-95.89 | -2.5% | TIME MAX | 10 | tier2 |
| 46 | SPICE/USD | $275.41 | 7.5% | PROFIT TARGET | 1 | tier2 |
| 47 | BTT/USD | $7.98 | 0.3% | TIME MAX | 10 | tier1 |
| 48 | PUPS/USD | $-215.17 | -5.5% | FIXED STOP | 1 | tier2 |
| 49 | MEME/USD | $8.40 | 0.3% | TIME MAX | 10 | tier1 |
| 50 | ALT/USD | $85.76 | 2.3% | TIME MAX | 10 | tier2 |
| 51 | SIGMA/USD | $286.37 | 7.5% | PROFIT TARGET | 9 | tier2 |
| 52 | XL1/USD | $203.91 | 7.7% | PROFIT TARGET | 4 | tier1 |
| 53 | PHA/USD | $46.96 | 1.1% | TIME MAX | 10 | tier2 |
| 54 | INIT/USD | $311.41 | 7.5% | PROFIT TARGET | 9 | tier2 |
| 55 | GLMR/USD | $-243.29 | -5.5% | FIXED STOP | 2 | tier2 |
| 56 | KOBAN/USD | $219.69 | 7.7% | PROFIT TARGET | 1 | tier1 |

## 6. Interpretation

**What this test shows**: The Monte Carlo trade-order shuffle takes the 56 actual trades and randomly reorders them 10,000 times. Since the total P&L is the sum of all trade P&Ls (commutative), the final P&L is always the same. However, the **maximum drawdown** changes with ordering because a streak of losers early creates a deeper trough than the same losers spread out.

**Key findings**:
- The strategy is **always profitable** ($3272.13) regardless of trade order
- Median max drawdown: 12.2% (half of orderings are better than this)
- P95 worst-case DD: 22.7% (only 5% of orderings are worse)
- Original order DD (8.6%) sits at the 14th percentile
- Zero probability of ruin (equity never hits $0 in any ordering)

---
*Generated by strategies/hf/screening/run_part2_monte_carlo_001.py at 2026-02-16 01:42*
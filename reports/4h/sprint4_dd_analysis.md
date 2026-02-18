# Sprint 4 — Drawdown Attribution Analysis

**Generated**: 2026-02-17T20:41:38.379806+00:00
**Git hash**: 9a606d9
**Configs analyzed**: 5
**Initial capital**: $2,000

## Executive Summary

- **Primary DD driver across all configs**: {'FIXED STOP': 5}
- **Average worst episode depth**: 88.3%
- **Compounding amplification**: 4/5 configs affected
- **Average max loss streak**: 5.6 trades
- **Full recovery from max DD**: 3/5 configs
- **Loss coin HHI (avg)**: 0.0260 (low = well-dispersed)

### Exit Reason DD Attribution (average across configs)

| Exit Reason | Avg DD Share |
|-------------|-------------|
| FIXED STOP | 71.1% |
| TIME MAX | 24.6% |
| RSI RECOVERY | 2.1% |
| END | 1.2% |
| DC TARGET | 0.7% |
| BB TARGET | 0.4% |

### DD Reduction Levers (ranked by prevalence)

1. **reduce max_stop_pct** (5/5 configs)
1. **vol-scale stop distance by ATR** (5/5 configs)
1. **reduce time_max_bars or add mid-hold exit** (5/5 configs)
1. **portfolio-level DD circuit breaker at 25%** (5/5 configs)
1. **regime filter: skip entries during sustained downtrend** (5/5 configs)
1. **cap position size or vol-scale sizing** (4/5 configs)
1. **cooldown period after consecutive stops** (4/5 configs)
1. **streak breaker: pause after 5 consecutive losses** (2/5 configs)

### Coins Causing Losses in Multiple Configs

| Coin | Configs |
|------|---------|
| VULT/USD | 2/5 |
| SGB/USD | 2/5 |
| HDX/USD | 2/5 |
| MYX/USD | 2/5 |
| AB/USD | 2/5 |

---

## Per-Config Analysis

### sprint4_041_h4s4g05_vol3x_bblow_rsi40
**Vol Capitulation 3x BBlow RSI40** (Volume Capitulation)
- Trades: 216 | WR: 54.63% | PF: 1.4058 | P&L: $2,283.84 | DD: 49.82%

**Primary DD driver**: FIXED STOP losses (71%) + compounding amplification
**Secondary DD driver**: TIME MAX (25%)

**Exit Attribution**:

| Exit Reason | Trades | Losing | WR | Total Loss | Avg Loss | DD Share | Avg Size |
|-------------|--------|--------|-----|-----------|----------|---------|----------|
| FIXED STOP | 39 | 39 | 0.0% | $-5,826.31 | $-149.39 | 70.6% | $965.01 |
| TIME MAX | 40 | 38 | 5.0% | $-2,084.63 | $-54.86 | 25.2% | $943.24 |
| END | 3 | 3 | 0.0% | $-183.63 | $-61.21 | 2.2% | $1,489.16 |
| RSI RECOVERY | 93 | 14 | 84.9% | $-129.62 | $-9.26 | 1.6% | $908.14 |
| DC TARGET | 32 | 3 | 90.6% | $-18.89 | $-6.30 | 0.2% | $940.75 |
| BB TARGET | 9 | 1 | 88.9% | $-12.10 | $-12.10 | 0.1% | $894.17 |

**Top DD Episodes**:

- Episode #3: **87.62%** depth (peak bar 663 -> trough bar 672 -> bar 720, 57 bars, 20 trades)
  - Worst trade: SGB/USD $-299.90 (FIXED STOP)
  - Exit reasons: {'RSI RECOVERY': 8, 'FIXED STOP': 5, 'DC TARGET': 2, 'TIME MAX': 1, 'BB TARGET': 1, 'END': 3}
- Episode #1: **83.78%** depth (peak bar 56 -> trough bar 181 -> bar 282, 226 bars, 74 trades)
  - Worst trade: LOCKIN/USD $-227.30 (FIXED STOP)
  - Exit reasons: {'RSI RECOVERY': 33, 'DC TARGET': 10, 'TIME MAX': 14, 'FIXED STOP': 14, 'BB TARGET': 3}
- Episode #2: **81.77%** depth (peak bar 286 -> trough bar 458 -> bar 662, 376 bars, 122 trades)
  - Worst trade: VSN/USD $-200.26 (FIXED STOP)
  - Exit reasons: {'DC TARGET': 20, 'RSI RECOVERY': 52, 'FIXED STOP': 20, 'TIME MAX': 25, 'BB TARGET': 5}

**Loss Streaks**: max=7, avg=3.08, count=25
- Worst streak: 7 trades, $-663.28, bars 564-589

**Most Toxic Window**: bars 606-720 (42 trades, $+2,029.67 P&L, $-2,305.60 losses)

**Sizing Impact**: avg winner size $908.69, avg loser size $971.59, corr=-0.1380, compounding_amp=YES

| Size Quartile | Avg Size | Avg P&L | WR | N |
|---------------|----------|---------|-----|---|
| Q1 | $578.50 | $+46.68 | 59.3% | 54 |
| Q2 | $820.16 | $+31.35 | 55.6% | 54 |
| Q3 | $1,005.14 | $-0.45 | 55.6% | 54 |
| Q4 | $1,345.11 | $-15.54 | 48.1% | 54 |

**Recovery**: max DD 87.62% at bar 672 (equity $457.58 from peak $3,696.18) — **RECOVERED**
- Recovery at bar 720, 17 trades, driven by RSI RECOVERY
- Recovery style: concentrated (few big wins)

**DD Reduction Levers**:
- reduce max_stop_pct (currently 15%)
- vol-scale stop distance by ATR
- reduce time_max_bars or add mid-hold exit
- cap position size or vol-scale sizing
- cooldown period after consecutive stops
- streak breaker: pause after 6 consecutive losses
- portfolio-level DD circuit breaker at 25%
- regime filter: skip entries during sustained downtrend

---

### sprint4_032_h4s4f02_z2.5_dclow_rsi40
**Z-Score -2.5 DClow RSI40** (Z-Score Extreme)
- Trades: 206 | WR: 52.91% | PF: 1.3548 | P&L: $4,915.03 | DD: 44.0%

**Primary DD driver**: FIXED STOP losses (65%) + compounding amplification
**Secondary DD driver**: TIME MAX (29%)

**Exit Attribution**:

| Exit Reason | Trades | Losing | WR | Total Loss | Avg Loss | DD Share | Avg Size |
|-------------|--------|--------|-----|-----------|----------|---------|----------|
| FIXED STOP | 34 | 34 | 0.0% | $-8,954.40 | $-263.36 | 64.6% | $1,701.21 |
| TIME MAX | 45 | 45 | 0.0% | $-3,968.28 | $-88.18 | 28.6% | $1,482.20 |
| RSI RECOVERY | 90 | 10 | 88.9% | $-392.53 | $-39.25 | 2.8% | $1,555.24 |
| DC TARGET | 29 | 5 | 82.8% | $-316.15 | $-63.23 | 2.3% | $1,691.26 |
| END | 3 | 3 | 0.0% | $-223.11 | $-74.37 | 1.6% | $2,379.38 |
| BB TARGET | 5 | 0 | 100.0% | $0.00 | $0.00 | 0.0% | $1,886.92 |

**Top DD Episodes**:

- Episode #3: **90.69%** depth (peak bar 383 -> trough bar 386 -> NOT RECOVERED, ongoing, 108 trades)
  - Worst trade: WEN/USD $-557.40 (FIXED STOP)
  - Exit reasons: {'RSI RECOVERY': 46, 'TIME MAX': 21, 'DC TARGET': 16, 'FIXED STOP': 19, 'BB TARGET': 3, 'END': 3}
- Episode #1: **80.83%** depth (peak bar 58 -> trough bar 243 -> bar 303, 245 bars, 73 trades)
  - Worst trade: OBOL/USD $-115.48 (FIXED STOP)
  - Exit reasons: {'RSI RECOVERY': 31, 'DC TARGET': 9, 'FIXED STOP': 12, 'TIME MAX': 19, 'BB TARGET': 2}
- Episode #2: **73.55%** depth (peak bar 317 -> trough bar 343 -> bar 378, 61 bars, 24 trades)
  - Worst trade: US/USD $-146.71 (FIXED STOP)
  - Exit reasons: {'RSI RECOVERY': 13, 'TIME MAX': 4, 'FIXED STOP': 3, 'DC TARGET': 4}

**Loss Streaks**: max=5, avg=2.75, count=24
- Worst streak: 3 trades, $-1,241.00, bars 402-410

**Most Toxic Window**: bars 498-607 (36 trades, $-1,835.06 P&L, $-4,065.93 losses)

**Sizing Impact**: avg winner size $1,578.85, avg loser size $1,629.24, corr=-0.0926, compounding_amp=YES

| Size Quartile | Avg Size | Avg P&L | WR | N |
|---------------|----------|---------|-----|---|
| Q1 | $517.81 | $+6.19 | 54.9% | 51 |
| Q2 | $760.84 | $+135.00 | 52.9% | 51 |
| Q3 | $2,150.24 | $+11.82 | 47.1% | 51 |
| Q4 | $2,929.38 | $-54.50 | 56.6% | 53 |

**Recovery**: max DD 90.69% at bar 386 (equity $764.14 from peak $8,204.25) — **NOT RECOVERED**
- Recovery style: distributed (many small wins)

**DD Reduction Levers**:
- reduce max_stop_pct (currently 15%)
- vol-scale stop distance by ATR
- reduce time_max_bars or add mid-hold exit
- cap position size or vol-scale sizing
- cooldown period after consecutive stops
- streak breaker: pause after 4 consecutive losses
- portfolio-level DD circuit breaker at 25%
- regime filter: skip entries during sustained downtrend

---

### sprint4_042_h4s4g06_vol4x_dczone_bblow_rsi35
**Vol Capitulation 4x DCzone+BBlow RSI35** (Volume Capitulation)
- Trades: 214 | WR: 53.27% | PF: 1.2784 | P&L: $823.92 | DD: 59.09%

**Primary DD driver**: FIXED STOP losses (78%) + compounding amplification
**Secondary DD driver**: TIME MAX (19%)

**Exit Attribution**:

| Exit Reason | Trades | Losing | WR | Total Loss | Avg Loss | DD Share | Avg Size |
|-------------|--------|--------|-----|-----------|----------|---------|----------|
| FIXED STOP | 44 | 44 | 0.0% | $-5,109.42 | $-116.12 | 78.3% | $750.10 |
| TIME MAX | 40 | 38 | 5.0% | $-1,214.74 | $-31.97 | 18.6% | $687.82 |
| RSI RECOVERY | 84 | 13 | 84.5% | $-98.14 | $-7.55 | 1.5% | $690.86 |
| END | 3 | 2 | 33.3% | $-77.30 | $-38.65 | 1.2% | $955.10 |
| DC TARGET | 36 | 2 | 94.4% | $-17.52 | $-8.76 | 0.3% | $642.59 |
| BB TARGET | 7 | 1 | 85.7% | $-10.69 | $-10.69 | 0.2% | $646.14 |

**Top DD Episodes**:

- Episode #3: **92.55%** depth (peak bar 669 -> trough bar 669 -> bar 720, 51 bars, 16 trades)
  - Worst trade: HDX/USD $-406.87 (FIXED STOP)
  - Exit reasons: {'FIXED STOP': 4, 'RSI RECOVERY': 5, 'DC TARGET': 2, 'TIME MAX': 2, 'END': 3}
- Episode #2: **92.08%** depth (peak bar 285 -> trough bar 646 -> bar 662, 377 bars, 123 trades)
  - Worst trade: MERL/USD $-196.12 (FIXED STOP)
  - Exit reasons: {'DC TARGET': 23, 'RSI RECOVERY': 49, 'FIXED STOP': 25, 'TIME MAX': 21, 'BB TARGET': 5}
- Episode #1: **80.03%** depth (peak bar 65 -> trough bar 181 -> bar 282, 217 bars, 75 trades)
  - Worst trade: ELX/USD $-142.58 (FIXED STOP)
  - Exit reasons: {'RSI RECOVERY': 30, 'DC TARGET': 11, 'TIME MAX': 17, 'FIXED STOP': 15, 'BB TARGET': 2}

**Loss Streaks**: max=6, avg=2.88, count=25
- Worst streak: 5 trades, $-555.93, bars 567-584

**Most Toxic Window**: bars 610-720 (36 trades, $+1,257.69 P&L, $-1,633.55 losses)

**Sizing Impact**: avg winner size $679.59, avg loser size $715.98, corr=-0.1347, compounding_amp=YES

| Size Quartile | Avg Size | Avg P&L | WR | N |
|---------------|----------|---------|-----|---|
| Q1 | $429.64 | $+43.65 | 54.7% | 53 |
| Q2 | $632.99 | $+7.99 | 54.7% | 53 |
| Q3 | $704.92 | $-3.42 | 50.9% | 53 |
| Q4 | $1,007.11 | $-13.42 | 52.7% | 55 |

**Recovery**: max DD 92.55% at bar 669 (equity $195.71 from peak $2,628.17) — **RECOVERED**
- Recovery at bar 720, 15 trades, driven by RSI RECOVERY
- Recovery style: concentrated (few big wins)

**DD Reduction Levers**:
- reduce max_stop_pct (currently 15%)
- vol-scale stop distance by ATR
- reduce time_max_bars or add mid-hold exit
- cap position size or vol-scale sizing
- cooldown period after consecutive stops
- streak breaker: pause after 5 consecutive losses
- portfolio-level DD circuit breaker at 25%
- regime filter: skip entries during sustained downtrend

---

### sprint4_007_h4s4a07_dclow_bblow_rsi40_vol1.5
**DC-Lite DClow+BBlow RSI40 VolSpike1.5** (DC-Lite)
- Trades: 101 | WR: 54.46% | PF: 1.2489 | P&L: $537.94 | DD: 40.83%

**Primary DD driver**: FIXED STOP losses (69%)
**Secondary DD driver**: TIME MAX (26%)

**Exit Attribution**:

| Exit Reason | Trades | Losing | WR | Total Loss | Avg Loss | DD Share | Avg Size |
|-------------|--------|--------|-----|-----------|----------|---------|----------|
| FIXED STOP | 17 | 17 | 0.0% | $-1,485.57 | $-87.39 | 68.8% | $564.47 |
| TIME MAX | 19 | 18 | 5.3% | $-570.08 | $-31.67 | 26.4% | $537.34 |
| RSI RECOVERY | 48 | 10 | 79.2% | $-73.14 | $-7.31 | 3.4% | $557.61 |
| BB TARGET | 4 | 1 | 75.0% | $-32.12 | $-32.12 | 1.5% | $489.45 |
| DC TARGET | 12 | 0 | 100.0% | $0.00 | $0.00 | 0.0% | $510.63 |
| END | 1 | 0 | 100.0% | $0.00 | $0.00 | 0.0% | $840.44 |

**Top DD Episodes**:

- Episode #1: **81.22%** depth (peak bar 65 -> trough bar 214 -> bar 681, 616 bars, 97 trades)
  - Worst trade: AIO/USD $-103.21 (FIXED STOP)
  - Exit reasons: {'FIXED STOP': 16, 'RSI RECOVERY': 46, 'TIME MAX': 19, 'DC TARGET': 12, 'BB TARGET': 4}
- Episode #2: **32.88%** depth (peak bar 714 -> trough bar 714 -> NOT RECOVERED, ongoing, 3 trades)
  - Worst trade: MYX/USD $-136.53 (FIXED STOP)
  - Exit reasons: {'RSI RECOVERY': 1, 'FIXED STOP': 1, 'END': 1}

**Loss Streaks**: max=4, avg=2.69, count=13
- Worst streak: 4 trades, $-261.80, bars 116-127

**Most Toxic Window**: bars 65-173 (15 trades, $-455.73 P&L, $-599.68 losses)

**Sizing Impact**: avg winner size $547.80, avg loser size $551.47, corr=-0.0582, compounding_amp=NO

| Size Quartile | Avg Size | Avg P&L | WR | N |
|---------------|----------|---------|-----|---|
| Q1 | $454.10 | $+18.89 | 72.0% | 25 |
| Q2 | $512.31 | $+1.26 | 56.0% | 25 |
| Q3 | $548.15 | $+15.39 | 40.0% | 25 |
| Q4 | $678.19 | $-13.48 | 50.0% | 26 |

**Recovery**: max DD 81.22% at bar 214 (equity $375.58 from peak $2,000.00) — **RECOVERED**
- Recovery at bar 681, 73 trades, driven by RSI RECOVERY
- Recovery style: concentrated (few big wins)

**DD Reduction Levers**:
- reduce max_stop_pct (currently 15%)
- vol-scale stop distance by ATR
- reduce time_max_bars or add mid-hold exit
- streak breaker: pause after 3 consecutive losses
- portfolio-level DD circuit breaker at 25%
- regime filter: skip entries during sustained downtrend

---

### sprint4_035_h4s4f05_z2.0_dclow_rsi45_highvol
**Z-Score -2.0 DClow RSI45 HighVol** (Z-Score Extreme)
- Trades: 206 | WR: 49.51% | PF: 1.1618 | P&L: $810.21 | DD: 53.2%

**Primary DD driver**: FIXED STOP losses (73%) + compounding amplification
**Secondary DD driver**: TIME MAX (24%)

**Exit Attribution**:

| Exit Reason | Trades | Losing | WR | Total Loss | Avg Loss | DD Share | Avg Size |
|-------------|--------|--------|-----|-----------|----------|---------|----------|
| FIXED STOP | 40 | 40 | 0.0% | $-3,661.33 | $-91.53 | 73.1% | $591.26 |
| TIME MAX | 48 | 48 | 0.0% | $-1,206.06 | $-25.13 | 24.1% | $422.15 |
| RSI RECOVERY | 75 | 10 | 86.7% | $-63.07 | $-6.31 | 1.3% | $448.11 |
| END | 3 | 2 | 33.3% | $-45.58 | $-22.79 | 0.9% | $944.40 |
| DC TARGET | 36 | 4 | 88.9% | $-31.68 | $-7.92 | 0.6% | $503.10 |
| BB TARGET | 4 | 0 | 100.0% | $0.00 | $0.00 | 0.0% | $386.00 |

**Top DD Episodes**:

- Episode #2: **89.62%** depth (peak bar 664 -> trough bar 674 -> NOT RECOVERED, ongoing, 20 trades)
  - Worst trade: SPICE/USD $-244.76 (FIXED STOP)
  - Exit reasons: {'FIXED STOP': 7, 'TIME MAX': 1, 'DC TARGET': 4, 'RSI RECOVERY': 5, 'END': 3}
- Episode #1: **88.11%** depth (peak bar 53 -> trough bar 181 -> bar 662, 609 bars, 186 trades)
  - Worst trade: XNAP/USD $-103.21 (FIXED STOP)
  - Exit reasons: {'FIXED STOP': 33, 'DC TARGET': 32, 'TIME MAX': 47, 'RSI RECOVERY': 70, 'BB TARGET': 4}

**Loss Streaks**: max=6, avg=2.76, count=25
- Worst streak: 4 trades, $-729.63, bars 664-674

**Most Toxic Window**: bars 608-720 (40 trades, $+1,586.30 P&L, $-1,777.92 losses)

**Sizing Impact**: avg winner size $463.86, avg loser size $506.70, corr=-0.0823, compounding_amp=YES

| Size Quartile | Avg Size | Avg P&L | WR | N |
|---------------|----------|---------|-----|---|
| Q1 | $328.65 | $+9.99 | 58.8% | 51 |
| Q2 | $393.91 | $+1.46 | 51.0% | 51 |
| Q3 | $452.89 | $-9.37 | 47.1% | 51 |
| Q4 | $755.90 | $+13.29 | 41.5% | 53 |

**Recovery**: max DD 89.62% at bar 674 (equity $328.23 from peak $3,162.02) — **NOT RECOVERED**
- Recovery style: distributed (many small wins)

**DD Reduction Levers**:
- reduce max_stop_pct (currently 15%)
- vol-scale stop distance by ATR
- reduce time_max_bars or add mid-hold exit
- cap position size or vol-scale sizing
- cooldown period after consecutive stops
- streak breaker: pause after 5 consecutive losses
- portfolio-level DD circuit breaker at 25%
- regime filter: skip entries during sustained downtrend

---

## Recommendations for Agent B (RiskWrapper)

### Priority Actions

1. **Stop Loss Sizing**: FIXED STOP is the dominant DD driver across all configs.
   Current max_stop_pct=15% is too wide. Test 8%, 10%, 12% with ATR-scaling.

2. **Position Size Capping**: Compounding amplification means large wins are
   followed by large position sizes, amplifying subsequent losses.
   Implement: `size = min(equity / max_pos, max_position_cap)`

3. **Portfolio DD Circuit Breaker**: When cumulative DD exceeds 25%,
   reduce position sizes by 50% or pause trading for N bars.

4. **Streak Cooldown**: After 3+ consecutive losses, skip the next entry
   or halve position size for 1 trade.

5. **TIME MAX Exit Improvement**: TIME MAX has near-0% WR. Consider:
   - Closing at mid-point of entry-target range instead of market price
   - Reducing time_max_bars to force earlier exits
   - Adding a mid-hold RSI check for early exit

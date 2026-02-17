# HF Trade Microstructure — 4H Variant Research

> Where do trades come from, how consistent is throughput, how concentrated is activity?

**Date**: 2026-02-15 14:12
**Universe**: tradeable
**Data**: `candle_cache_tradeable.json`
**Coins**: 425
**Bars**: 721 (4H, ~120 days)
**Runtime**: 0.7s

---

## Champion_H2

**Config**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 8, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 3.0}`
**Total trades**: 31

### 1. Trades per Tier

| Tier | Trades | % of Total | Coins | P&L | WR |
|------|--------|-----------|-------|-----|-----|
| Tier 1 (Liquid) | 7 | 22.6% | 7 | $+1,153 | 57.1% |
| Tier 2 (Mid) | 14 | 45.2% | 13 | $+2,881 | 78.6% |
| Tier 3 (Illiquid) | 10 | 32.3% | 10 | $+80 | 60.0% |

### 2. Trades per Coin

**Unique coins traded**: 30

**Top 20 by trade count**:

| # | Coin | Tier | Trades | P&L | WR | Avg P&L | Avg Bars |
|---|------|------|--------|-----|-----|---------|----------|
| 1 | MF/USD | T2 | 2 | $+746 | 100.0% | $+373 | 4.5 |
| 2 | BTT/USD | T1 | 1 | $+229 | 100.0% | $+229 | 3.0 |
| 3 | YGG/USD | T3 | 1 | $-189 | 0.0% | $-189 | 2.0 |
| 4 | SOON/USD | T3 | 1 | $+234 | 100.0% | $+234 | 12.0 |
| 5 | WCT/USD | T2 | 1 | $+260 | 100.0% | $+260 | 6.0 |
| 6 | AKE/USD | T1 | 1 | $-215 | 0.0% | $-215 | 6.0 |
| 7 | GHST/USD | T3 | 1 | $-197 | 0.0% | $-197 | 8.0 |
| 8 | SGB/USD | T1 | 1 | $-67 | 0.0% | $-67 | 15.0 |
| 9 | RPL/USD | T3 | 1 | $+29 | 100.0% | $+29 | 15.0 |
| 10 | OGN/USD | T2 | 1 | $+57 | 100.0% | $+57 | 15.0 |
| 11 | M/USD | T3 | 1 | $+245 | 100.0% | $+245 | 9.0 |
| 12 | BIGTIME/USD | T2 | 1 | $+239 | 100.0% | $+239 | 15.0 |
| 13 | DYDX/USD | T2 | 1 | $+300 | 100.0% | $+300 | 9.0 |
| 14 | BLUR/USD | T2 | 1 | $-249 | 0.0% | $-249 | 11.0 |
| 15 | KNC/USD | T3 | 1 | $+98 | 100.0% | $+98 | 15.0 |
| 16 | LCX/USD | T2 | 1 | $+318 | 100.0% | $+318 | 5.0 |
| 17 | PUFFER/USD | T3 | 1 | $-106 | 0.0% | $-106 | 15.0 |
| 18 | DYM/USD | T2 | 1 | $+381 | 100.0% | $+381 | 8.0 |
| 19 | GHIBLI/USD | T1 | 1 | $+425 | 100.0% | $+425 | 1.0 |
| 20 | APR/USD | T2 | 1 | $-351 | 0.0% | $-351 | 1.0 |

**Bottom 20 by P&L**:

| # | Coin | Tier | Trades | P&L | WR | Avg P&L | Avg Bars |
|---|------|------|--------|-----|-----|---------|----------|
| 1 | COQ/USD | T1 | 1 | $-410 | 0.0% | $-410 | 3.0 |
| 2 | APR/USD | T2 | 1 | $-351 | 0.0% | $-351 | 1.0 |
| 3 | BERA/USD | T3 | 1 | $-348 | 0.0% | $-348 | 13.0 |
| 4 | AI3/USD | T2 | 1 | $-251 | 0.0% | $-251 | 15.0 |
| 5 | BLUR/USD | T2 | 1 | $-249 | 0.0% | $-249 | 11.0 |
| 6 | AKE/USD | T1 | 1 | $-215 | 0.0% | $-215 | 6.0 |
| 7 | GHST/USD | T3 | 1 | $-197 | 0.0% | $-197 | 8.0 |
| 8 | YGG/USD | T3 | 1 | $-189 | 0.0% | $-189 | 2.0 |
| 9 | PUFFER/USD | T3 | 1 | $-106 | 0.0% | $-106 | 15.0 |
| 10 | SGB/USD | T1 | 1 | $-67 | 0.0% | $-67 | 15.0 |
| 11 | RPL/USD | T3 | 1 | $+29 | 100.0% | $+29 | 15.0 |
| 12 | OGN/USD | T2 | 1 | $+57 | 100.0% | $+57 | 15.0 |
| 13 | KNC/USD | T3 | 1 | $+98 | 100.0% | $+98 | 15.0 |
| 14 | KGEN/USD | T3 | 1 | $+156 | 100.0% | $+156 | 15.0 |
| 15 | UMA/USD | T3 | 1 | $+159 | 100.0% | $+159 | 15.0 |
| 16 | BTT/USD | T1 | 1 | $+229 | 100.0% | $+229 | 3.0 |
| 17 | SOON/USD | T3 | 1 | $+234 | 100.0% | $+234 | 12.0 |
| 18 | BIGTIME/USD | T2 | 1 | $+239 | 100.0% | $+239 | 15.0 |
| 19 | M/USD | T3 | 1 | $+245 | 100.0% | $+245 | 9.0 |
| 20 | WCT/USD | T2 | 1 | $+260 | 100.0% | $+260 | 6.0 |

### 3. Throughput per Week

| Metric | Value |
|--------|-------|
| Total weeks | 18 |
| Weeks with ≥1 trade | 16 |
| Weeks with 0 trades | 2 (11.1%) |
| Mean trades/week | 1.72 |
| Median trades/week | 2 |
| Max trades/week | 4 |

**Weekly breakdown**:

| Week | Trades | P&L |
|------|--------|-----|
| 2025-W42 | 0 ⚠️ | $+0 |
| 2025-W43 | 1 | $+229 |
| 2025-W44 | 3 | $+304 |
| 2025-W45 | 3 | $-479 |
| 2025-W46 | 2 | $+87 |
| 2025-W47 | 1 | $+245 |
| 2025-W48 | 1 | $+239 |
| 2025-W49 | 1 | $+300 |
| 2025-W50 | 2 | $-151 |
| 2025-W51 | 1 | $+318 |
| 2025-W52 | 1 | $-106 |
| 2026-W00 | 0 ⚠️ | $+0 |
| 2026-W01 | 1 | $+342 |
| 2026-W02 | 4 | $+204 |
| 2026-W03 | 2 | $+563 |
| 2026-W04 | 3 | $+237 |
| 2026-W05 | 3 | $+591 |
| 2026-W06 | 2 | $+1,192 |

### 4. Daily Consistency

| Metric | Value |
|--------|-------|
| Total calendar days | 112 |
| Days with ≥1 trade | 30 |
| Days with 0 trades | 82 (73.2%) |

### 5. Trade Duration & Exit Reasons

| Metric | Value |
|--------|-------|
| Mean duration | 8.8 bars (35h) |
| Median duration | 8 bars (32h) |
| Min duration | 1 bars (4h) |
| Max duration | 15 bars (60h) |

**Exit reasons**:

| Reason | Count | % |
|--------|-------|---|
| PROFIT TARGET | 15 | 48.4% |
| TIME MAX | 9 | 29.0% |
| FIXED STOP | 7 | 22.6% |

---

## GRID_BEST

**Config**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 10, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 2.5}`
**Total trades**: 32

### 1. Trades per Tier

| Tier | Trades | % of Total | Coins | P&L | WR |
|------|--------|-----------|-------|-----|-----|
| Tier 1 (Liquid) | 7 | 21.9% | 6 | $+1,462 | 71.4% |
| Tier 2 (Mid) | 15 | 46.9% | 14 | $+3,053 | 73.3% |
| Tier 3 (Illiquid) | 10 | 31.2% | 10 | $+204 | 60.0% |

### 2. Trades per Coin

**Unique coins traded**: 30

**Top 20 by trade count**:

| # | Coin | Tier | Trades | P&L | WR | Avg P&L | Avg Bars |
|---|------|------|--------|-----|-----|---------|----------|
| 1 | CHEEMS/USD | T1 | 2 | $+873 | 100.0% | $+437 | 11.0 |
| 2 | MF/USD | T2 | 2 | $+916 | 100.0% | $+458 | 4.5 |
| 3 | BTT/USD | T1 | 1 | $+229 | 100.0% | $+229 | 3.0 |
| 4 | YGG/USD | T3 | 1 | $-234 | 0.0% | $-234 | 2.0 |
| 5 | SOON/USD | T3 | 1 | $+228 | 100.0% | $+228 | 12.0 |
| 6 | WCT/USD | T2 | 1 | $+255 | 100.0% | $+255 | 6.0 |
| 7 | AKE/USD | T1 | 1 | $-260 | 0.0% | $-260 | 6.0 |
| 8 | GHST/USD | T3 | 1 | $-192 | 0.0% | $-192 | 15.0 |
| 9 | RPL/USD | T3 | 1 | $+33 | 100.0% | $+33 | 15.0 |
| 10 | OGN/USD | T2 | 1 | $+64 | 100.0% | $+64 | 15.0 |
| 11 | M/USD | T3 | 1 | $+272 | 100.0% | $+272 | 9.0 |
| 12 | BIGTIME/USD | T2 | 1 | $+265 | 100.0% | $+265 | 15.0 |
| 13 | DYDX/USD | T2 | 1 | $+334 | 100.0% | $+334 | 9.0 |
| 14 | ME/USD | T3 | 1 | $+372 | 100.0% | $+372 | 4.0 |
| 15 | USUAL/USD | T2 | 1 | $-194 | 0.0% | $-194 | 15.0 |
| 16 | TANSSI/USD | T2 | 1 | $+240 | 100.0% | $+240 | 15.0 |
| 17 | LCX/USD | T2 | 1 | $+420 | 100.0% | $+420 | 5.0 |
| 18 | PUFFER/USD | T3 | 1 | $-140 | 0.0% | $-140 | 15.0 |
| 19 | HPOS10I/USD | T2 | 1 | $-42 | 0.0% | $-42 | 15.0 |
| 20 | GHIBLI/USD | T1 | 1 | $+498 | 100.0% | $+498 | 1.0 |

**Bottom 20 by P&L**:

| # | Coin | Tier | Trades | P&L | WR | Avg P&L | Avg Bars |
|---|------|------|--------|-----|-----|---------|----------|
| 1 | COQ/USD | T1 | 1 | $-569 | 0.0% | $-569 | 3.0 |
| 2 | APR/USD | T2 | 1 | $-509 | 0.0% | $-509 | 1.0 |
| 3 | BERA/USD | T3 | 1 | $-493 | 0.0% | $-493 | 14.0 |
| 4 | AI3/USD | T2 | 1 | $-288 | 0.0% | $-288 | 15.0 |
| 5 | AKE/USD | T1 | 1 | $-260 | 0.0% | $-260 | 6.0 |
| 6 | YGG/USD | T3 | 1 | $-234 | 0.0% | $-234 | 2.0 |
| 7 | USUAL/USD | T2 | 1 | $-194 | 0.0% | $-194 | 15.0 |
| 8 | GHST/USD | T3 | 1 | $-192 | 0.0% | $-192 | 15.0 |
| 9 | PUFFER/USD | T3 | 1 | $-140 | 0.0% | $-140 | 15.0 |
| 10 | HPOS10I/USD | T2 | 1 | $-42 | 0.0% | $-42 | 15.0 |
| 11 | RPL/USD | T3 | 1 | $+33 | 100.0% | $+33 | 15.0 |
| 12 | OGN/USD | T2 | 1 | $+64 | 100.0% | $+64 | 15.0 |
| 13 | KGEN/USD | T3 | 1 | $+175 | 100.0% | $+175 | 15.0 |
| 14 | UMA/USD | T3 | 1 | $+183 | 100.0% | $+183 | 15.0 |
| 15 | SOON/USD | T3 | 1 | $+228 | 100.0% | $+228 | 12.0 |
| 16 | BTT/USD | T1 | 1 | $+229 | 100.0% | $+229 | 3.0 |
| 17 | TANSSI/USD | T2 | 1 | $+240 | 100.0% | $+240 | 15.0 |
| 18 | WCT/USD | T2 | 1 | $+255 | 100.0% | $+255 | 6.0 |
| 19 | BIGTIME/USD | T2 | 1 | $+265 | 100.0% | $+265 | 15.0 |
| 20 | M/USD | T3 | 1 | $+272 | 100.0% | $+272 | 9.0 |

### 3. Throughput per Week

| Metric | Value |
|--------|-------|
| Total weeks | 18 |
| Weeks with ≥1 trade | 16 |
| Weeks with 0 trades | 2 (11.1%) |
| Mean trades/week | 1.78 |
| Median trades/week | 2 |
| Max trades/week | 3 |

**Weekly breakdown**:

| Week | Trades | P&L |
|------|--------|-----|
| 2025-W42 | 0 ⚠️ | $+0 |
| 2025-W43 | 1 | $+229 |
| 2025-W44 | 3 | $+249 |
| 2025-W45 | 3 | $-198 |
| 2025-W46 | 2 | $+96 |
| 2025-W47 | 1 | $+272 |
| 2025-W48 | 1 | $+265 |
| 2025-W49 | 2 | $+705 |
| 2025-W50 | 2 | $+46 |
| 2025-W51 | 1 | $+420 |
| 2025-W52 | 1 | $-140 |
| 2026-W00 | 0 ⚠️ | $+0 |
| 2026-W01 | 2 | $+409 |
| 2026-W02 | 3 | $-299 |
| 2026-W03 | 2 | $+647 |
| 2026-W04 | 3 | $+164 |
| 2026-W05 | 3 | $+544 |
| 2026-W06 | 2 | $+1,309 |

### 4. Daily Consistency

| Metric | Value |
|--------|-------|
| Total calendar days | 112 |
| Days with ≥1 trade | 31 |
| Days with 0 trades | 81 (72.3%) |

### 5. Trade Duration & Exit Reasons

| Metric | Value |
|--------|-------|
| Mean duration | 9.0 bars (36h) |
| Median duration | 9 bars (36h) |
| Min duration | 1 bars (4h) |
| Max duration | 15 bars (60h) |

**Exit reasons**:

| Reason | Count | % |
|--------|-------|---|
| PROFIT TARGET | 16 | 50.0% |
| TIME MAX | 11 | 34.4% |
| FIXED STOP | 5 | 15.6% |

---
*Generated by hf_trade_micro.py — 4H variant research*
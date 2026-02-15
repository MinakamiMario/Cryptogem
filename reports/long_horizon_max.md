# Long-Horizon Validation Report

**Generated**: 2026-02-15 09:01
**Target**: 365d | **Actual**: ~112d (max available)
**Runtime**: 150.6s

## Summary

| Universe | Config | Days | Trades | P&L | WR% | PF | DD% | WF | Fric2x20 | 1-candle | Jitter% | MC ruin | Top1% | Top3% | Verdict |
|----------|--------|------|--------|-----|-----|-----|-----|-----|----------|---------|---------|---------|-------|-------|---------|
| TRADEABLE | C1 | 112 | 27 | $1,930 | 66.7 | 1.83 | 29.3 | 3/5 | $1,068 | $607 | 100% | 0.0% | 11.6% | 32.3% | **SOFT-GO** |
| TRADEABLE | GRID_BEST | 112 | 32 | $4,718 | 68.8 | 2.61 | 16.4 | 5/5 | $3,019 | $2,144 | 100% | 0.0% | 9.0% | 24.4% | **GO** |
| LIVE_CURRENT | C1 | 112 | 30 | $3,746 | 70.0 | 3.31 | 27.9 | 4/5 | $2,370 | $1,651 | 96% | 0.0% | 13.3% | 34.9% | **GO** |
| LIVE_CURRENT | GRID_BEST | 112 | 35 | $1,833 | 60.0 | 1.68 | 23.6 | 3/5 | $778 | $248 | 84% | 0.0% | 9.5% | 25.6% | **SOFT-GO** |

## Decision Thresholds

| Gate | Threshold |
|------|-----------|
| WF (GO) | >= 4/5 folds |
| WF (SOFT-GO) | >= 3/5 folds |
| Friction(2x+20bps) | > $0 |
| 1-candle-later | > $0 (for GO) |
| Max DD | < 40% |
| Top1 share | < 40% |

---
## Universe: TRADEABLE

- Cache: `candle_cache_tradeable.json`
- MD5: `f6fd2ca303b677fe67ceede4a6b8f7ba`
- Coins: 425 | Max bars: 721 | ~112d

### Config: C1 — [SOFT-GO]
```json
{
  "exit_type": "tp_sl",
  "max_pos": 1,
  "rsi_max": 45,
  "sl_pct": 15,
  "time_max_bars": 15,
  "tp_pct": 15,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```

#### Walk-Forward (3/5)

| Fold | Test Bars | Trades | P&L | WR% | DD% | Pass |
|------|-----------|--------|-----|-----|-----|------|
| 1 | 50-184 | 5 | $-451.89 | 40.0 | 25.3 | FAIL |
| 2 | 184-318 | 5 | $840.26 | 100.0 | 8.1 | PASS |
| 3 | 318-452 | 4 | $-161.50 | 25.0 | 10.9 | FAIL |
| 4 | 452-586 | 6 | $1,154.53 | 66.7 | 11.9 | PASS |
| 5 | 586-721 | 7 | $361.03 | 71.4 | 18.4 | PASS |

#### Slippage Ladder

| Regime | Eff.Fee | Trades | P&L | WR% | PF | DD% | Pass |
|--------|---------|--------|-----|-----|----|-----|------|
| 1x_fees_0bps | 0.260% | 27 | $1,930.37 | 66.7 | 1.83 | 29.3 | PASS |
| 1x_fees_10bps | 0.360% | 27 | $1,724.96 | 66.7 | 1.75 | 30.0 | PASS |
| 1x_fees_20bps | 0.460% | 27 | $1,529.91 | 66.7 | 1.67 | 30.7 | PASS |
| 1x_fees_35bps | 0.610% | 27 | $1,255.65 | 66.7 | 1.56 | 31.8 | PASS |
| 2x_fees_0bps | 0.520% | 27 | $1,417.63 | 66.7 | 1.62 | 31.1 | PASS |
| 2x_fees_10bps | 0.620% | 27 | $1,238.11 | 66.7 | 1.55 | 31.8 | PASS |
| 2x_fees_20bps | 0.720% | 27 | $1,067.69 | 66.7 | 1.48 | 32.5 | PASS |
| 2x_fees_35bps | 0.870% | 27 | $828.14 | 66.7 | 1.38 | 33.6 | PASS |
| 3x_fees_0bps | 0.780% | 27 | $969.61 | 66.7 | 1.44 | 33.0 | PASS |
| 3x_fees_10bps | 0.880% | 27 | $812.83 | 66.7 | 1.37 | 33.7 | PASS |
| 3x_fees_20bps | 0.980% | 27 | $664.03 | 63.0 | 1.30 | 34.4 | PASS |
| 3x_fees_35bps | 1.130% | 27 | $454.96 | 63.0 | 1.21 | 35.4 | PASS |
| **1-candle-later** | 1.020% | 27 | $606.66 | 63.0 | 1.28 | 34.6 | PASS |

### Config: GRID_BEST — [GO]
```json
{
  "exit_type": "tp_sl",
  "max_pos": 1,
  "rsi_max": 45,
  "sl_pct": 10,
  "time_max_bars": 15,
  "tp_pct": 12,
  "vol_confirm": true,
  "vol_spike_mult": 2.5
}
```

#### Walk-Forward (5/5)

| Fold | Test Bars | Trades | P&L | WR% | DD% | Pass |
|------|-----------|--------|-----|-----|-----|------|
| 1 | 50-184 | 7 | $280.43 | 57.1 | 12.2 | PASS |
| 2 | 184-318 | 5 | $766.00 | 100.0 | 8.1 | PASS |
| 3 | 318-452 | 5 | $429.34 | 60.0 | 8.0 | PASS |
| 4 | 452-586 | 6 | $291.44 | 50.0 | 16.4 | PASS |
| 5 | 586-721 | 9 | $973.34 | 77.8 | 13.3 | PASS |

#### Slippage Ladder

| Regime | Eff.Fee | Trades | P&L | WR% | PF | DD% | Pass |
|--------|---------|--------|-----|-----|----|-----|------|
| 1x_fees_0bps | 0.260% | 32 | $4,718.27 | 68.8 | 2.61 | 16.4 | PASS |
| 1x_fees_10bps | 0.360% | 32 | $4,307.10 | 68.8 | 2.49 | 16.8 | PASS |
| 1x_fees_20bps | 0.460% | 32 | $3,920.36 | 68.8 | 2.37 | 17.1 | PASS |
| 1x_fees_35bps | 0.610% | 32 | $3,382.99 | 68.8 | 2.20 | 17.7 | PASS |
| 2x_fees_0bps | 0.520% | 32 | $3,699.45 | 68.8 | 2.30 | 17.3 | PASS |
| 2x_fees_10bps | 0.620% | 32 | $3,348.89 | 68.8 | 2.19 | 17.7 | PASS |
| 2x_fees_20bps | 0.720% | 32 | $3,019.26 | 68.8 | 2.08 | 18.0 | PASS |
| 2x_fees_35bps | 0.870% | 32 | $2,561.42 | 68.8 | 1.93 | 18.6 | PASS |
| 3x_fees_0bps | 0.780% | 32 | $2,831.02 | 68.8 | 2.02 | 18.2 | PASS |
| 3x_fees_10bps | 0.880% | 32 | $2,532.38 | 68.8 | 1.93 | 18.6 | PASS |
| 3x_fees_20bps | 0.980% | 32 | $2,251.66 | 65.6 | 1.83 | 19.4 | PASS |
| 3x_fees_35bps | 1.130% | 32 | $1,861.91 | 65.6 | 1.70 | 20.7 | PASS |
| **1-candle-later** | 1.020% | 32 | $2,144.16 | 65.6 | 1.80 | 19.8 | PASS |

---
## Universe: LIVE_CURRENT

- Cache: `candle_cache_532.json`
- MD5: `3b1dba2eeb4d95ac68d0874b50de3d4d`
- Coins: 526 | Max bars: 721 | ~112d

### Config: C1 — [GO]
```json
{
  "exit_type": "tp_sl",
  "max_pos": 1,
  "rsi_max": 45,
  "sl_pct": 15,
  "time_max_bars": 15,
  "tp_pct": 15,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```

#### Walk-Forward (4/5)

| Fold | Test Bars | Trades | P&L | WR% | DD% | Pass |
|------|-----------|--------|-----|-----|-----|------|
| 1 | 50-184 | 6 | $-108.22 | 50.0 | 23.5 | FAIL |
| 2 | 184-318 | 5 | $664.43 | 100.0 | 10.3 | PASS |
| 3 | 318-452 | 5 | $201.38 | 40.0 | 7.7 | PASS |
| 4 | 452-586 | 6 | $328.96 | 33.3 | 10.5 | PASS |
| 5 | 586-721 | 8 | $949.37 | 87.5 | 18.1 | PASS |

#### Slippage Ladder

| Regime | Eff.Fee | Trades | P&L | WR% | PF | DD% | Pass |
|--------|---------|--------|-----|-----|----|-----|------|
| 1x_fees_0bps | 0.260% | 30 | $3,745.50 | 70.0 | 3.31 | 27.9 | PASS |
| 1x_fees_10bps | 0.360% | 30 | $3,414.81 | 70.0 | 3.10 | 28.2 | PASS |
| 1x_fees_20bps | 0.460% | 30 | $3,102.56 | 70.0 | 2.91 | 28.5 | PASS |
| 1x_fees_35bps | 0.610% | 30 | $2,666.58 | 70.0 | 2.64 | 29.0 | PASS |
| 2x_fees_0bps | 0.520% | 30 | $2,923.64 | 70.0 | 2.80 | 28.7 | PASS |
| 2x_fees_10bps | 0.620% | 30 | $2,638.83 | 70.0 | 2.62 | 29.0 | PASS |
| 2x_fees_20bps | 0.720% | 30 | $2,369.98 | 70.0 | 2.46 | 29.3 | PASS |
| 2x_fees_35bps | 0.870% | 30 | $1,994.74 | 70.0 | 2.23 | 29.8 | PASS |
| 3x_fees_0bps | 0.780% | 30 | $2,215.96 | 70.0 | 2.37 | 29.5 | PASS |
| 3x_fees_10bps | 0.880% | 30 | $1,970.86 | 66.7 | 2.22 | 29.8 | PASS |
| 3x_fees_20bps | 0.980% | 30 | $1,739.56 | 60.0 | 2.07 | 30.1 | PASS |
| 3x_fees_35bps | 1.130% | 30 | $1,416.85 | 56.7 | 1.86 | 30.6 | PASS |
| **1-candle-later** | 1.020% | 30 | $1,650.73 | 60.0 | 2.01 | 30.2 | PASS |

### Config: GRID_BEST — [SOFT-GO]
```json
{
  "exit_type": "tp_sl",
  "max_pos": 1,
  "rsi_max": 45,
  "sl_pct": 10,
  "time_max_bars": 15,
  "tp_pct": 12,
  "vol_confirm": true,
  "vol_spike_mult": 2.5
}
```

#### Walk-Forward (3/5)

| Fold | Test Bars | Trades | P&L | WR% | DD% | Pass |
|------|-----------|--------|-----|-----|-----|------|
| 1 | 50-184 | 8 | $-209.63 | 37.5 | 19.0 | FAIL |
| 2 | 184-318 | 5 | $594.76 | 100.0 | 10.3 | PASS |
| 3 | 318-452 | 6 | $591.90 | 66.7 | 6.4 | PASS |
| 4 | 452-586 | 7 | $-23.03 | 28.6 | 19.2 | FAIL |
| 5 | 586-721 | 9 | $642.05 | 77.8 | 17.6 | PASS |

#### Slippage Ladder

| Regime | Eff.Fee | Trades | P&L | WR% | PF | DD% | Pass |
|--------|---------|--------|-----|-----|----|-----|------|
| 1x_fees_0bps | 0.260% | 35 | $1,833.39 | 60.0 | 1.68 | 23.6 | PASS |
| 1x_fees_10bps | 0.360% | 35 | $1,575.18 | 60.0 | 1.59 | 24.0 | PASS |
| 1x_fees_20bps | 0.460% | 35 | $1,333.89 | 60.0 | 1.51 | 24.3 | PASS |
| 1x_fees_35bps | 0.610% | 35 | $1,001.37 | 60.0 | 1.39 | 24.8 | PASS |
| 2x_fees_0bps | 0.520% | 35 | $1,196.80 | 60.0 | 1.46 | 24.5 | PASS |
| 2x_fees_10bps | 0.620% | 35 | $980.38 | 60.0 | 1.38 | 24.8 | PASS |
| 2x_fees_20bps | 0.720% | 35 | $778.23 | 60.0 | 1.30 | 25.1 | PASS |
| 2x_fees_35bps | 0.870% | 35 | $499.74 | 60.0 | 1.20 | 25.6 | PASS |
| 3x_fees_0bps | 0.780% | 35 | $663.39 | 60.0 | 1.26 | 25.3 | PASS |
| 3x_fees_10bps | 0.880% | 35 | $482.18 | 57.1 | 1.19 | 25.6 | PASS |
| 3x_fees_20bps | 0.980% | 35 | $312.96 | 51.4 | 1.13 | 25.9 | PASS |
| 3x_fees_35bps | 1.130% | 35 | $79.96 | 48.6 | 1.03 | 26.8 | PASS |
| **1-candle-later** | 1.020% | 35 | $248.46 | 51.4 | 1.10 | 26.1 | PASS |

---
## Decision Line

**BEST LONG-TERM: TRADEABLE + GRID_BEST → GO**

```
python trading_bot/paper_backfill_v4.py --hours 168 --config grid_best
```

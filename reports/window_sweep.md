# Window Sweep - Temporal Stability Report
Generated: 2026-02-15 08:41
Dataset: candle_cache_tradeable.json | Max bars: 721
Initial capital: $2000 | Fee: 0.26%

## Window Definitions
| Window | Start Bar | End Bar | Bars | ~Days |
|--------|-----------|---------|------|-------|
| fixed_120d | 50 | 721 | 671 | 112d |
| fixed_30d | 541 | 721 | 180 | 30d |
| fixed_60d | 361 | 721 | 360 | 60d |
| fixed_90d | 181 | 721 | 540 | 90d |
| roll_1 | 50 | 230 | 180 | 30d |
| roll_2 | 230 | 410 | 180 | 30d |
| roll_3 | 410 | 590 | 180 | 30d |
| roll_4 | 590 | 721 | 131 | 22d |

## Config: C1
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

### Window Results
| Window | Trades | P&L | WR% | PF | DD% | Bars |
|--------|--------|-----|-----|----|-----|------|
| fixed_120d | 27 | +$1930 | 66.7 | 1.83 | 29.3 | 671 |
| fixed_30d | 9 | +$523 | 66.7 | 1.62 | 18.4 | 180 |
| fixed_60d | 16 | +$2020 | 68.8 | 2.45 | 18.4 | 360 |
| fixed_90d | 22 | +$3078 | 72.7 | 2.51 | 18.4 | 540 |
| roll_1 | 7 | -$387 | 57.1 | 0.49 | 29.3 | 180 |
| roll_2 | 5 | +$512 | 80.0 | 2.86 | 14.7 | 180 |
| roll_3 | 8 | +$1286 | 62.5 | 6.06 | 11.9 | 180 |
| roll_4 | 7 | +$361 | 71.4 | 1.55 | 18.4 | 131 |

### Stability Metrics
| Metric | Value |
|--------|-------|
| Verdict | **STABLE** (PASS) |
| Positive windows | 7/8 (88%) |
| Zero-trade windows | 0 |
| Worst P&L | $-387 (roll_1) |
| Max DD | 29.3% (fixed_120d) |
| Rolling mean P&L | $443 |
| Rolling CV | 1.55 |

## Config: GRID_BEST
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

### Window Results
| Window | Trades | P&L | WR% | PF | DD% | Bars |
|--------|--------|-----|-----|----|-----|------|
| fixed_120d | 32 | +$4718 | 68.8 | 2.61 | 16.4 | 671 |
| fixed_30d | 11 | +$1094 | 72.7 | 2.76 | 13.3 | 180 |
| fixed_60d | 18 | +$1800 | 66.7 | 2.56 | 16.4 | 360 |
| fixed_90d | 25 | +$3892 | 72.0 | 2.98 | 16.4 | 540 |
| roll_1 | 9 | +$377 | 66.7 | 1.55 | 14.8 | 180 |
| roll_2 | 6 | +$1084 | 83.3 | 7.63 | 8.0 | 180 |
| roll_3 | 8 | +$466 | 50.0 | 1.87 | 16.4 | 180 |
| roll_4 | 9 | +$973 | 77.8 | 3.07 | 13.3 | 131 |

### Stability Metrics
| Metric | Value |
|--------|-------|
| Verdict | **STABLE** (PASS) |
| Positive windows | 8/8 (100%) |
| Zero-trade windows | 0 |
| Worst P&L | $377 (roll_1) |
| Max DD | 16.4% (fixed_120d) |
| Rolling mean P&L | $725 |
| Rolling CV | 0.49 |

## Comparative Summary
| Config | Verdict | Pos% | Worst P&L | Max DD | Rolling CV |
|--------|---------|------|-----------|--------|------------|
| C1 | **STABLE** | 88% | $-387 | 29.3% | 1.55 |
| GRID_BEST | **STABLE** | 100% | $377 | 16.4% | 0.49 |
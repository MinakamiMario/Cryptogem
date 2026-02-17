# HF Smoke Run Results

**Date**: 2026-02-15 10:36
**Universe**: tradeable
**Data**: `candle_cache_tradeable.json`
**Total time**: 24.9s

## Hypothesis Comparison

| Hypothesis | Trades | WR% | P&L | PF | DD% | Time |
|------------|--------|-----|-----|----|-----|------|
| GRID_BEST_baseline | 32 | 68.8% | $+4,718 | 2.61 | 16.4% | 0.3s |
| H1_mean_reversion | 33 | 51.5% | $+323 | 1.18 | 28.5% | 0.2s |
| H2_momentum_burst | 24 | 66.7% | $+2,288 | 2.43 | 22.1% | 0.2s |
| H3_vol_breakout | 15 | 60.0% | $+49 | 1.05 | 28.5% | 0.2s |

## Exit Reason Breakdown

### GRID_BEST_baseline
| Reason | Count |
|--------|-------|
| PROFIT TARGET | 16 |
| TIME MAX | 11 |
| FIXED STOP | 5 |

### H1_mean_reversion
| Reason | Count |
|--------|-------|
| TIME MAX | 14 |
| PROFIT TARGET | 10 |
| FIXED STOP | 9 |

### H2_momentum_burst
| Reason | Count |
|--------|-------|
| TIME MAX | 11 |
| PROFIT TARGET | 7 |
| FIXED STOP | 6 |

### H3_vol_breakout
| Reason | Count |
|--------|-------|
| TIME MAX | 8 |
| FIXED STOP | 5 |
| PROFIT TARGET | 2 |

## Configs

**GRID_BEST_baseline**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 10, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 2.5}`

**H1_mean_reversion**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 30, "sl_pct": 6, "time_max_bars": 8, "tp_pct": 8, "vol_confirm": true, "vol_spike_mult": 2.0}`

**H2_momentum_burst**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 55, "sl_pct": 8, "time_max_bars": 12, "tp_pct": 15, "vol_confirm": true, "vol_spike_mult": 4.0}`

**H3_vol_breakout**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 10, "time_max_bars": 20, "tp_pct": 20, "vol_confirm": true, "vol_spike_mult": 5.0}`

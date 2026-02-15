# Leakage / Purge Sanity Check Report

**Generated**: 2026-02-15 08:42
**Method**: Purged Walk-Forward (embargo=2) vs No-Purge (embargo=0), 5-fold
**Leakage Threshold**: >20.0% delta triggers warning

## MD5 Verification

| Universe | MD5 | Expected | Match |
|----------|-----|----------|-------|
| LIVE_CURRENT | `3b1dba2eeb4d...` | `3b1dba2eeb4d...` | OK |
| TRADEABLE | `f6fd2ca303b6...` | `f6fd2ca303b6...` | OK |

## Summary

| Universe | Config | Purged P&L | NoPurge P&L | Delta% | Verdict |
|----------|--------|------------|-------------|--------|---------|
| LIVE_CURRENT | C1 | $2,035.92 | $2,035.92 | +0.00% | CLEAN |
| LIVE_CURRENT | GRID_BEST | $1,596.05 | $1,596.05 | +0.00% | CLEAN |
| TRADEABLE | C1 | $1,742.43 | $1,742.43 | +0.00% | CLEAN |
| TRADEABLE | GRID_BEST | $2,740.55 | $2,740.55 | +0.00% | CLEAN |

### Overall Verdict: **ALL CLEAN -- NO LEAKAGE**

## Detailed Results

### LIVE_CURRENT / C1

Config: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 15, "time_max_bars": 15, "tp_pct": 15, "vol_confirm": true, "vol_spike_mult": 3.0}`


| Metric | Purged (emb=2) | NoPurge (emb=0) |
|--------|----------------|-----------------|
| Passed Folds | 4/5 | 4/5 |
| Total Test P&L | $2,035.92 | $2,035.92 |
| Max Test DD | 23.5% | 23.5% |
| Runtime | 1.37s | 1.26s |
| **Leakage Delta** | | **+0.00%** |
| **Verdict** | | **CLEAN** |

| Fold | Purged Test P&L | NoPurge Test P&L | Delta | Purged WR | NoPurge WR |
|------|-----------------|------------------|-------|-----------|------------|
| 1 | $-108.22 | $-108.22 | +$0.00 | 50.0% | 50.0% |
| 2 | $664.43 | $664.43 | +$0.00 | 100.0% | 100.0% |
| 3 | $201.38 | $201.38 | +$0.00 | 40.0% | 40.0% |
| 4 | $328.96 | $328.96 | +$0.00 | 33.3% | 33.3% |
| 5 | $949.37 | $949.37 | +$0.00 | 87.5% | 87.5% |

### LIVE_CURRENT / GRID_BEST

Config: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 10, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 2.5}`


| Metric | Purged (emb=2) | NoPurge (emb=0) |
|--------|----------------|-----------------|
| Passed Folds | 3/5 | 3/5 |
| Total Test P&L | $1,596.05 | $1,596.05 |
| Max Test DD | 19.2% | 19.2% |
| Runtime | 1.46s | 1.68s |
| **Leakage Delta** | | **+0.00%** |
| **Verdict** | | **CLEAN** |

| Fold | Purged Test P&L | NoPurge Test P&L | Delta | Purged WR | NoPurge WR |
|------|-----------------|------------------|-------|-----------|------------|
| 1 | $-209.63 | $-209.63 | +$0.00 | 37.5% | 37.5% |
| 2 | $594.76 | $594.76 | +$0.00 | 100.0% | 100.0% |
| 3 | $591.90 | $591.90 | +$0.00 | 66.7% | 66.7% |
| 4 | $-23.03 | $-23.03 | +$0.00 | 28.6% | 28.6% |
| 5 | $642.05 | $642.05 | +$0.00 | 77.8% | 77.8% |

### TRADEABLE / C1

Config: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 15, "time_max_bars": 15, "tp_pct": 15, "vol_confirm": true, "vol_spike_mult": 3.0}`


| Metric | Purged (emb=2) | NoPurge (emb=0) |
|--------|----------------|-----------------|
| Passed Folds | 3/5 | 3/5 |
| Total Test P&L | $1,742.43 | $1,742.43 |
| Max Test DD | 25.3% | 25.3% |
| Runtime | 1.3s | 1.29s |
| **Leakage Delta** | | **+0.00%** |
| **Verdict** | | **CLEAN** |

| Fold | Purged Test P&L | NoPurge Test P&L | Delta | Purged WR | NoPurge WR |
|------|-----------------|------------------|-------|-----------|------------|
| 1 | $-451.89 | $-451.89 | +$0.00 | 40.0% | 40.0% |
| 2 | $840.26 | $840.26 | +$0.00 | 100.0% | 100.0% |
| 3 | $-161.50 | $-161.50 | +$0.00 | 25.0% | 25.0% |
| 4 | $1,154.53 | $1,154.53 | +$0.00 | 66.7% | 66.7% |
| 5 | $361.03 | $361.03 | +$0.00 | 71.4% | 71.4% |

### TRADEABLE / GRID_BEST

Config: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 10, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 2.5}`


| Metric | Purged (emb=2) | NoPurge (emb=0) |
|--------|----------------|-----------------|
| Passed Folds | 5/5 | 5/5 |
| Total Test P&L | $2,740.55 | $2,740.55 |
| Max Test DD | 16.4% | 16.4% |
| Runtime | 1.29s | 1.15s |
| **Leakage Delta** | | **+0.00%** |
| **Verdict** | | **CLEAN** |

| Fold | Purged Test P&L | NoPurge Test P&L | Delta | Purged WR | NoPurge WR |
|------|-----------------|------------------|-------|-----------|------------|
| 1 | $280.43 | $280.43 | +$0.00 | 57.1% | 57.1% |
| 2 | $766.00 | $766.00 | +$0.00 | 100.0% | 100.0% |
| 3 | $429.34 | $429.34 | +$0.00 | 60.0% | 60.0% |
| 4 | $291.44 | $291.44 | +$0.00 | 50.0% | 50.0% |
| 5 | $973.34 | $973.34 | +$0.00 | 77.8% | 77.8% |

# Validation Summary — GRID_BEST tp_sl

**Last validated**: 2026-02-15
**Overall verdict**: **GO** (TRADEABLE + GRID_BEST)
**Best long-term**: TRADEABLE + GRID_BEST

---

## Validated Configs

### GRID_BEST
```json
{"exit_type":"tp_sl","max_pos":1,"rsi_max":45,"sl_pct":10,"time_max_bars":15,"tp_pct":12,"vol_confirm":true,"vol_spike_mult":2.5}
```

### C1
```json
{"exit_type":"tp_sl","max_pos":1,"rsi_max":45,"sl_pct":15,"time_max_bars":15,"tp_pct":15,"vol_confirm":true,"vol_spike_mult":3.0}
```

---

## Test Results

### 1. Leakage Check — CLEAN
**Verdict**: ALL CLEAN, no leakage detected
**Command**: `python3 trading_bot/leakage_check.py`
**Report**: `reports/leakage_check.json` + `.md`

| Universe | Config | Purged P&L | NoPurge P&L | Delta | Verdict |
|----------|--------|------------|-------------|-------|---------|
| LIVE_CURRENT | C1 | $1,824.59 | $1,824.59 | 0.00% | CLEAN |
| LIVE_CURRENT | GRID_BEST | $2,636.66 | $2,636.66 | 0.00% | CLEAN |
| TRADEABLE | C1 | $1,310.37 | $1,310.37 | 0.00% | CLEAN |
| TRADEABLE | GRID_BEST | $3,270.69 | $3,270.69 | 0.00% | CLEAN |

Method: Purged walk-forward (5-fold, embargo=2) vs no-purge (embargo=0). Threshold: >20% delta = warning.

---

### 2. Nested Holdout — 36/36 PASS OOS
**Verdict**: Strategy family is robust (all 36 grid configs pass OOS gates)
**Command**: `python3 trading_bot/nested_holdout.py`
**Report**: `reports/nested_holdout.json` + `.md`

- Outer split: holdout bars [586,721) = 135 bars; dev [50,586) = 536 bars
- Inner: 4-fold purged WF on dev set, 36 configs grid
- OOS gates: P&L > -$200, DD < 40%, trades >= 3
- Result: 36/36 configs pass OOS

---

### 3. Window Sweep — GRID_BEST STABLE
**Verdict**: GRID_BEST 8/8 positive windows, CV=0.49
**Command**: `python3 trading_bot/window_sweep.py`
**Report**: `reports/window_sweep.json` + `.md`
**Universe**: TRADEABLE only

| Config | Positive | CV | Worst P&L | Max DD | Verdict |
|--------|----------|-----|-----------|--------|---------|
| C1 | 7/8 (88%) | 1.55 | -$387 | 29.3% | UNSTABLE |
| GRID_BEST | 8/8 (100%) | 0.49 | +$377 | 22.1% | **STABLE** |

Thresholds: >=75% positive AND no window >30% DD AND worst > -$500.

---

### 4. Slippage Regimes — GO
**Verdict**: All 4 combos = GO
**Command**: `python3 trading_bot/slippage_regimes.py`
**Report**: `reports/slippage_regimes.json` + `.md`

| Universe | Config | Verdict | BE (2x fees) | P&L @baseline | P&L @2x+20bps | P&L @1-candle |
|----------|--------|---------|--------------|---------------|---------------|---------------|
| TRADEABLE | C1 | GO | 95 bps | $1,930 | $1,397 | $1,068 |
| TRADEABLE | GRID_BEST | GO | **162 bps** | $4,718 | $3,650 | $2,968 |
| LIVE_CURRENT | C1 | GO | 78 bps | $3,746 | $2,788 | $2,152 |
| LIVE_CURRENT | GRID_BEST | GO | 66 bps | $3,393 | $2,399 | $1,750 |

13 regimes tested: fee x[1,2,3] x slippage [0,10,20,35]bps + 1-candle-later (2x+50bps). All 52 PASS.

---

### 5. Long Horizon Max — TRAD/GRID = GO
**Verdict**: TRADEABLE + GRID_BEST = GO
**Command**: `python3 trading_bot/long_horizon_max.py`
**Report**: `reports/long_horizon_max.json` + `.md`

Full battery per universe x config:
- Baseline + WF (5-fold purged, embargo=2) + Slippage ladder + Jitter (50 variants) + MC Ruin (1000 shuffles) + Top1/Top3 share

| Universe | Config | Trades | P&L | WF | Fric>0 | 1c>0 | DD | Top1 | Jitter | MC Ruin | Verdict |
|----------|--------|--------|-----|-----|--------|------|-----|------|--------|---------|---------|
| TRADEABLE | GRID_BEST | 32 | $4,718 | 5/5 | Y | Y | 22.1% | 9.0% | 94.0% | 0.0% | **GO** |
| LIVE_CURRENT | C1 | 30 | $3,746 | 4/5 | Y | Y | 24.3% | 13.3% | 90.0% | 0.0% | **GO** |
| TRADEABLE | C1 | 27 | $1,930 | 3/5 | Y | Y | 29.3% | 17.1% | 82.0% | 0.0% | SOFT-GO |
| LIVE_CURRENT | GRID_BEST | 35 | $3,393 | 3/5 | Y | Y | 22.8% | 11.3% | 88.0% | 0.0% | SOFT-GO |

GO thresholds: WF>=4/5, fric>$0, candle>$0, DD<40%, Top1<40%.

---

### 6. Rolling Regime Sweep — TRAD/GRID 100% STABLE
**Verdict**: TRADEABLE + GRID_BEST = STABLE (100% windows positive)
**Command**: `python3 trading_bot/rolling_regime_sweep.py`
**Report**: `reports/rolling_regime_sweep.json` + `.md`

6 rolling windows (~18d each) x 3 fee regimes (baseline, 2x+20bps, 1-candle-later).

| Universe | Config | Pos% (base) | Pos% (fric) | Pos% (1c) | CV | Verdict |
|----------|--------|-------------|-------------|-----------|-----|---------|
| TRADEABLE | GRID_BEST | **100%** | 100% | 100% | 0.71 | **STABLE** |
| LIVE_CURRENT | C1 | **100%** | 100% | 67% | 0.55 | STABLE |
| TRADEABLE | C1 | 50% | 33% | 33% | 2.31 | UNSTABLE |
| LIVE_CURRENT | GRID_BEST | 67% | 67% | 50% | 1.27 | UNSTABLE |

Stable threshold: >=70% windows positive.

---

## Data Integrity

| Cache | MD5 | Coins | Bars |
|-------|-----|-------|------|
| candle_cache_tradeable.json | `f6fd2ca303b677fe67ceede4a6b8f7ba` | 425 | 721 |
| candle_cache_532.json | `3b1dba2eeb4d95ac68d0874b50de3d4d` | 526 | ~660 |

## Reproduction

All tests reproducible via:
```bash
make check                              # 66 regression tests
make robustness                         # Full GO/NO-GO harness
python3 trading_bot/leakage_check.py    # Leakage sanity
python3 trading_bot/nested_holdout.py   # Nested holdout
python3 trading_bot/window_sweep.py     # Window sweep
python3 trading_bot/slippage_regimes.py # Slippage stress
python3 trading_bot/long_horizon_max.py # Long horizon battery
python3 trading_bot/rolling_regime_sweep.py  # Rolling regimes
```

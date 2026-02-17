# Part 2 DD Killer: Drawdown Reduction Experiments

**Date**: 2026-02-16 01:28
**Commit**: 427d5e0
**Universe**: T1(96) + T2(199) = 295 coins (excl 21 net-negative)
**Signal**: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)
**Cost**: MEXC Market (T1=12.5bps, T2=23.5bps)
**Stress**: 2x (T1=25.0bps, T2=47.0bps)
**Runtime**: 34.3s

## Gate Thresholds (STRICT)

| Gate | Metric | Threshold |
|------|--------|-----------|
| G1 | trades/week | >= 10 |
| G2 | max gap | <= 2.5 days |
| G3 | exp/week | > $0 |
| G4 | exp/week (stress 2x) | > $0 |
| G5 | max DD | <= 20% |
| G6 | WF positive folds | >= 4/5 |
| G8 | fold concentration | < 35% |

## Summary: All Variants

| Section | Label | Trades | PF | P&L | Exp/Wk | DD%% | WF | FC | Gap | Gates |
|---------|-------|--------|----|------|--------|------|----|----|-----|-------|
| SL/TP | baseline (sl5/tp8) | 56 | 2.834 | $3272 | $762.44 | 8.6 | 4/5 | 0.34 | 1.5 | **ALL** |
| SL/TP | sl3/tp6 (tight) | 58 | 2.427 | $1889 | $440.22 | 16.4 | 4/5 | 0.43 | 1.5 | 6/7 |
| SL/TP | sl3/tp8 | 58 | 2.749 | $2725 | $634.92 | 15.2 | 4/5 | 0.40 | 1.5 | 6/7 |
| SL/TP | sl4/tp8 | 58 | 2.538 | $3003 | $699.71 | 12.4 | 4/5 | 0.36 | 1.5 | 6/7 |
| SL/TP | sl5/tp6 (tight tp) | 56 | 2.650 | $2288 | $533.15 | 9.1 | 4/5 | 0.37 | 1.5 | 6/7 |
| SL/TP | sl5/tp10 (wide tp) | 55 | 2.831 | $3148 | $733.42 | 9.1 | 4/5 | 0.37 | 1.5 | 6/7 |
| SL/TP | sl7/tp8 | 55 | 2.715 | $3196 | $744.61 | 9.8 | 5/5 | 0.33 | 1.5 | **ALL** |
| SL/TP | sl7/tp10 | 54 | 2.712 | $3064 | $713.99 | 9.5 | 5/5 | 0.36 | 1.5 | 6/7 |
| Cooldown | cd0/cas0 (no cooldown) | 57 | 2.941 | $3509 | $817.59 | 8.6 | 4/5 | 0.38 | 1.5 | 6/7 |
| Cooldown | cd4/cas8 (baseline) | 56 | 2.834 | $3272 | $762.44 | 8.6 | 4/5 | 0.34 | 1.5 | **ALL** |
| Cooldown | cd4/cas12 | 56 | 2.834 | $3272 | $762.44 | 8.6 | 4/5 | 0.34 | 1.5 | **ALL** |
| Cooldown | cd8/cas12 | 56 | 2.834 | $3272 | $762.44 | 8.6 | 4/5 | 0.34 | 1.5 | **ALL** |
| Cooldown | cd8/cas24 (1 day) | 56 | 2.834 | $3272 | $762.44 | 8.6 | 4/5 | 0.34 | 1.5 | **ALL** |
| Cooldown | cd12/cas24 | 56 | 2.834 | $3272 | $762.44 | 8.6 | 4/5 | 0.34 | 1.5 | **ALL** |
| VolFilter | no vol filter | 56 | 2.834 | $3272 | $762.44 | 8.6 | 4/5 | 0.34 | 1.5 | **ALL** |
| VolFilter | atr_ratio<1.5 | 48 | 2.568 | $1937 | $451.39 | 16.8 | 4/5 | 0.44 | 1.5 | 6/7 |
| VolFilter | atr_ratio<2.0 | 51 | 2.892 | $2446 | $569.96 | 9.7 | 5/5 | 0.40 | 1.5 | 6/7 |
| VolFilter | atr_ratio<2.5 | 53 | 3.284 | $3036 | $707.43 | 9.2 | 5/5 | 0.41 | 1.5 | 6/7 |
| VolFilter | atr_ratio<3.0 | 53 | 3.284 | $3036 | $707.43 | 9.2 | 5/5 | 0.41 | 1.5 | 6/7 |
| Combined | COMBO: sl5/tp8 cd4/cas8 atr<off | 56 | 2.834 | $3272 | $762.44 | 8.6 | 4/5 | 0.34 | 1.5 | **ALL** |
| MaxDDKill | MAX_DD_KILL: sl3/tp6 cd12/cas24 atr<1.5 | 50 | 1.726 | $868 | $202.22 | 22.6 | 3/5 | 0.44 | 1.5 | 4/7 |

**Variants passing ALL gates**: 9/21
**Best overall**: baseline (sl5/tp8)

## Experiment 1: SL/TP Retune

Baseline SL/TP = sl5/tp8. Testing tighter stops, tighter/wider targets.

| Label | SL | TP | Trades | PF | Exp/Wk | DD%% | WF | G1 | G2 | G3 | G4 | G5 | G6 | G8 |
|-------|----|----|--------|----|--------|------|----|----|----|----|----|----|----|-----|
| baseline (sl5/tp8) | 5 | 8 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | P | P | P | P | P | P | P |
| sl3/tp6 (tight) | 3 | 6 | 58 | 2.427 | $440.22 | 16.4 | 4/5 | P | P | P | P | P | P | F |
| sl3/tp8 | 3 | 8 | 58 | 2.749 | $634.92 | 15.2 | 4/5 | P | P | P | P | P | P | F |
| sl4/tp8 | 4 | 8 | 58 | 2.538 | $699.71 | 12.4 | 4/5 | P | P | P | P | P | P | F |
| sl5/tp6 (tight tp) | 5 | 6 | 56 | 2.650 | $533.15 | 9.1 | 4/5 | P | P | P | P | P | P | F |
| sl5/tp10 (wide tp) | 5 | 10 | 55 | 2.831 | $733.42 | 9.1 | 4/5 | P | P | P | P | P | P | F |
| sl7/tp8 | 7 | 8 | 55 | 2.715 | $744.61 | 9.8 | 5/5 | P | P | P | P | P | P | P |
| sl7/tp10 | 7 | 10 | 54 | 2.712 | $713.99 | 9.5 | 5/5 | P | P | P | P | P | P | F |

**Best SL/TP**: baseline (sl5/tp8)

## Experiment 2: Cooldown After Loss

Testing longer cooldown periods after stops to reduce revenge trading.

| Label | CD | CAS | Trades | PF | Exp/Wk | DD%% | WF | G1 | G2 | G3 | G4 | G5 | G6 | G8 |
|-------|----|-----|--------|----|--------|------|----|----|----|----|----|----|----|-----|
| cd0/cas0 (no cooldown) | 0 | 0 | 57 | 2.941 | $817.59 | 8.6 | 4/5 | P | P | P | P | P | P | F |
| cd4/cas8 (baseline) | 4 | 8 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | P | P | P | P | P | P | P |
| cd4/cas12 | 4 | 12 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | P | P | P | P | P | P | P |
| cd8/cas12 | 8 | 12 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | P | P | P | P | P | P | P |
| cd8/cas24 (1 day) | 8 | 24 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | P | P | P | P | P | P | P |
| cd12/cas24 | 12 | 24 | 56 | 2.834 | $762.44 | 8.6 | 4/5 | P | P | P | P | P | P | P |

**Best Cooldown**: cd4/cas8 (baseline)

## Experiment 3: Volatility Filter

Skip entries when ATR_ratio (current ATR / SMA of ATR) exceeds threshold.

| Label | Threshold | Trades | PF | Exp/Wk | DD%% | WF | G1 | G2 | G3 | G4 | G5 | G6 | G8 |
|-------|-----------|--------|----|--------|------|----|----|----|----|----|----|----|-----|
| no vol filter | None | 56 | 2.834 | $762.44 | 8.6 | 4/5 | P | P | P | P | P | P | P |
| atr_ratio<1.5 | 1.5 | 48 | 2.568 | $451.39 | 16.8 | 4/5 | P | P | P | P | P | P | F |
| atr_ratio<2.0 | 2.0 | 51 | 2.892 | $569.96 | 9.7 | 5/5 | P | P | P | P | P | P | F |
| atr_ratio<2.5 | 2.5 | 53 | 3.284 | $707.43 | 9.2 | 5/5 | P | P | P | P | P | P | F |
| atr_ratio<3.0 | 3.0 | 53 | 3.284 | $707.43 | 9.2 | 5/5 | P | P | P | P | P | P | F |

**Best Vol Filter**: no vol filter

## Experiment 4: Combined Best

Combines best individual findings:
- SL/TP: baseline (sl5/tp8)
- Cooldown: cd4/cas8 (baseline)
- Vol filter: no vol filter

### Combined: COMBO: sl5/tp8 cd4/cas8 atr<off

| Metric | Value |
|--------|-------|
| Trades | 56 |
| PF | 2.834 |
| P&L | $3272 |
| Exp/Week | $762.44 |
| DD% | 8.6% |
| WF | 4/5 |
| Fold Conc | 0.34 |
| Max Gap | 1.5 days |
| Stress PF | 2.306 |
| Stress Exp/Wk | $571.41 |
| **Gates** | **ALL PASS** |

| Gate | Value | Threshold | Pass |
|------|-------|-----------|------|
| G1 | 13.05 | >= 10 | PASS |
| G2 | 1.5 | <= 2.5 | PASS |
| G3 | 762.4382 | > $0 | PASS |
| G4 | 571.413 | > $0 | PASS |
| G5 | 8.63 | <= 20% | PASS |
| G6 | 4 | >= 4/5 | PASS |
| G8 | 0.3418 | < 0.35 | PASS |

### Max DD Kill: MAX_DD_KILL: sl3/tp6 cd12/cas24 atr<1.5

| Metric | Value |
|--------|-------|
| Trades | 50 |
| PF | 1.726 |
| P&L | $868 |
| Exp/Week | $202.22 |
| DD% | 22.6% |
| WF | 3/5 |
| Fold Conc | 0.44 |
| Max Gap | 1.5 days |
| Stress PF | 1.302 |
| Stress Exp/Wk | $93.83 |
| **Gates** | **4/7** |

| Gate | Value | Threshold | Pass |
|------|-------|-----------|------|
| G1 | 11.65 | >= 10 | PASS |
| G2 | 1.5 | <= 2.5 | PASS |
| G3 | 202.2171 | > $0 | PASS |
| G4 | 93.828 | > $0 | PASS |
| G5 | 22.55 | <= 20% | FAIL |
| G6 | 3 | >= 4/5 | FAIL |
| G8 | 0.4399 | < 0.35 | FAIL |

## Verdict

**9 variant(s) pass ALL strict gates.**

Best overall: **baseline (sl5/tp8)**

### Key Findings

- **sl3/tp6 (tight)** increases DD by 7.7% (8.6% -> 16.4%)
- **sl3/tp8** increases DD by 6.6% (8.6% -> 15.2%)
- **sl4/tp8** increases DD by 3.8% (8.6% -> 12.4%)
- **sl7/tp8** increases DD by 1.2% (8.6% -> 9.8%)
- **sl7/tp10** increases DD by 0.9% (8.6% -> 9.5%)

---
*Generated by strategies/hf/screening/run_part2_dd_killer_001.py at 2026-02-16 01:28*
# HF Per-Tier Validation Report -- 4H Variant Research (Sprint 2.3)

> **Key question**: Which tiers pass all 5 hard gates under tier-specific friction?

**Date**: 2026-02-15 14:01
**Universe**: tradeable
**Data**: `candle_cache_tradeable.json`
**Total coins**: 425
**Tier source**: `universe_tiering_001.json`
**Runtime**: 367.7s

## 1. Summary Matrix

| Config | Tier | Coins | Fee (bps) | Verdict | G1 | G2 | G3 | G4 | G5 |
|--------|------|-------|-----------|---------|----|----|----|----|-----|
| Champion_H2 | Tier 1 (Liquid) | 100 | 31.0 | **INSUFFICIENT_SAMPLE** | INSUF | FAIL | PASS | FAIL | FAIL |
| Champion_H2 | Tier 2 (Mid) | 216 | 56.0 | **GO** | PASS | PASS | PASS | PASS | PASS |
| Champion_H2 | Tier 3 (Illiquid) | 109 | 101.0 | **INSUFFICIENT_SAMPLE** | INSUF | FAIL | FAIL | FAIL | PASS |
| Champion_H2 | Tier 1+2 (Live) | 316 | 56.0 | **GO** | PASS | PASS | PASS | PASS | PASS |
| GRID_BEST | Tier 1 (Liquid) | 100 | 31.0 | **INSUFFICIENT_SAMPLE** | INSUF | FAIL | PASS | PASS | FAIL |
| GRID_BEST | Tier 2 (Mid) | 216 | 56.0 | **SOFT-GO** | PASS | FAIL | PASS | PASS | PASS |
| GRID_BEST | Tier 3 (Illiquid) | 109 | 101.0 | **INSUFFICIENT_SAMPLE** | INSUF | FAIL | FAIL | FAIL | PASS |
| GRID_BEST | Tier 1+2 (Live) | 316 | 56.0 | **GO** | PASS | PASS | PASS | PASS | PASS |

---

## 2. Detail: Champion_H2

**Config**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 8, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 3.0}`

### Tier 1 (Liquid) (100 coins, fee=31.0bps)

**Verdict**: **INSUFFICIENT_SAMPLE** -- Only 17 trades (need >= 20)

- **G1 Trade Sufficiency**: 17 trades (min=20) -> **INSUFFICIENT_SAMPLE**
- **G2 Walk-Forward**: 2/5 positive folds, 2/5 PF>1 -> **FAIL**

  | Fold | Bars | Trades | P&L | PF | WR% | Positive |
  |------|------|--------|-----|----|-----|----------|
  | 1 | 50-184 | 6 | $-525 | 0.3 | 16.7% | NO |
  | 2 | 184-318 | 3 | $+525 | 99.0 | 100.0% | YES |
  | 3 | 318-452 | 1 | $-80 | 0.0 | 0.0% | NO |
  | 4 | 452-586 | 1 | $-40 | 0.0 | 0.0% | NO |
  | 5 | 586-721 | 6 | $+108 | 1.23 | 50.0% | YES |

- **G3 Rolling Windows**: 3/4 positive (75%, gate >= 70%) -> **PASS**
- **G4 Friction Stress**: 1.5x (46.5bps): $-100 | 2.0x (62.0bps): $-198 -> **FAIL**
- **G5 Concentration**: top1=32.0% (< 40%), top3=71.4% (< 70%) -> **FAIL**

### Tier 2 (Mid) (216 coins, fee=56.0bps)

**Verdict**: **GO** -- All 5 hard gates passed

- **G1 Trade Sufficiency**: 23 trades (min=20) -> **PASS**
- **G2 Walk-Forward**: 4/5 positive folds, 4/5 PF>1 -> **PASS**

  | Fold | Bars | Trades | P&L | PF | WR% | Positive |
  |------|------|--------|-----|----|-----|----------|
  | 1 | 50-184 | 5 | $-195 | 0.65 | 40.0% | NO |
  | 2 | 184-318 | 4 | $+420 | 99.0 | 100.0% | YES |
  | 3 | 318-452 | 3 | $+144 | 1.79 | 66.7% | YES |
  | 4 | 452-586 | 5 | $+296 | 1.77 | 60.0% | YES |
  | 5 | 586-721 | 6 | $+329 | 1.92 | 66.7% | YES |

- **G3 Rolling Windows**: 3/4 positive (75%, gate >= 70%) -> **PASS**
- **G4 Friction Stress**: 1.5x (84.0bps): $+832 | 2.0x (112.0bps): $+488 -> **PASS**
- **G5 Concentration**: top1=19.2% (< 40%), top3=40.0% (< 70%) -> **PASS**

### Tier 3 (Illiquid) (109 coins, fee=101.0bps)

**Verdict**: **INSUFFICIENT_SAMPLE** -- Only 16 trades (need >= 20)

- **G1 Trade Sufficiency**: 16 trades (min=20) -> **INSUFFICIENT_SAMPLE**
- **G2 Walk-Forward**: 2/5 positive folds, 2/5 PF>1 -> **FAIL**

  | Fold | Bars | Trades | P&L | PF | WR% | Positive |
  |------|------|--------|-----|----|-----|----------|
  | 1 | 50-184 | 4 | $-42 | 0.9 | 50.0% | NO |
  | 2 | 184-318 | 4 | $+396 | 27.16 | 50.0% | YES |
  | 3 | 318-452 | 2 | $-58 | 0.42 | 50.0% | NO |
  | 4 | 452-586 | 2 | $-203 | 0.0 | 0.0% | NO |
  | 5 | 586-721 | 4 | $+73 | 1.36 | 75.0% | YES |

- **G3 Rolling Windows**: 2/4 positive (50%, gate >= 70%) -> **FAIL**
- **G4 Friction Stress**: 1.5x (151.5bps): $-200 | 2.0x (202.0bps): $-475 -> **FAIL**
- **G5 Concentration**: top1=18.7% (< 40%), top3=53.4% (< 70%) -> **PASS**

### Tier 1+2 (Live) (316 coins, fee=56.0bps)

**Verdict**: **GO** -- All 5 hard gates passed

- **G1 Trade Sufficiency**: 30 trades (min=20) -> **PASS**
- **G2 Walk-Forward**: 4/5 positive folds, 4/5 PF>1 -> **PASS**

  | Fold | Bars | Trades | P&L | PF | WR% | Positive |
  |------|------|--------|-----|----|-----|----------|
  | 1 | 50-184 | 7 | $-416 | 0.49 | 28.6% | NO |
  | 2 | 184-318 | 4 | $+420 | 99.0 | 100.0% | YES |
  | 3 | 318-452 | 4 | $+48 | 1.17 | 50.0% | YES |
  | 4 | 452-586 | 6 | $+544 | 2.28 | 66.7% | YES |
  | 5 | 586-721 | 9 | $+601 | 2.09 | 66.7% | YES |

- **G3 Rolling Windows**: 3/4 positive (75%, gate >= 70%) -> **PASS**
- **G4 Friction Stress**: 1.5x (84.0bps): $+1,067 | 2.0x (112.0bps): $+590 -> **PASS**
- **G5 Concentration**: top1=13.2% (< 40%), top3=30.7% (< 70%) -> **PASS**

---

## 2. Detail: GRID_BEST

**Config**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 10, "time_max_bars": 15, "tp_pct": 12, "vol_confirm": true, "vol_spike_mult": 2.5}`

### Tier 1 (Liquid) (100 coins, fee=31.0bps)

**Verdict**: **INSUFFICIENT_SAMPLE** -- Only 18 trades (need >= 20)

- **G1 Trade Sufficiency**: 18 trades (min=20) -> **INSUFFICIENT_SAMPLE**
- **G2 Walk-Forward**: 2/5 positive folds, 2/5 PF>1 -> **FAIL**

  | Fold | Bars | Trades | P&L | PF | WR% | Positive |
  |------|------|--------|-----|----|-----|----------|
  | 1 | 50-184 | 5 | $-119 | 0.78 | 40.0% | NO |
  | 2 | 184-318 | 3 | $+525 | 99.0 | 100.0% | YES |
  | 3 | 318-452 | 1 | $-80 | 0.0 | 0.0% | NO |
  | 4 | 452-586 | 2 | $-248 | 0.0 | 0.0% | NO |
  | 5 | 586-721 | 7 | $+70 | 1.12 | 57.1% | YES |

- **G3 Rolling Windows**: 3/4 positive (75%, gate >= 70%) -> **PASS**
- **G4 Friction Stress**: 1.5x (46.5bps): $+121 | 2.0x (62.0bps): $+5 -> **PASS**
- **G5 Concentration**: top1=41.2% (< 40%), top3=71.5% (< 70%) -> **FAIL**

### Tier 2 (Mid) (216 coins, fee=56.0bps)

**Verdict**: **SOFT-GO** -- WF 3/5 folds (soft pass at 3/5), all other gates pass

- **G1 Trade Sufficiency**: 22 trades (min=20) -> **PASS**
- **G2 Walk-Forward**: 3/5 positive folds, 3/5 PF>1 -> **FAIL**

  | Fold | Bars | Trades | P&L | PF | WR% | Positive |
  |------|------|--------|-----|----|-----|----------|
  | 1 | 50-184 | 4 | $-101 | 0.79 | 50.0% | NO |
  | 2 | 184-318 | 4 | $+420 | 99.0 | 100.0% | YES |
  | 3 | 318-452 | 3 | $+217 | 2.83 | 66.7% | YES |
  | 4 | 452-586 | 5 | $-5 | 0.99 | 40.0% | NO |
  | 5 | 586-721 | 6 | $+545 | 3.38 | 83.3% | YES |

- **G3 Rolling Windows**: 3/4 positive (75%, gate >= 70%) -> **PASS**
- **G4 Friction Stress**: 1.5x (84.0bps): $+944 | 2.0x (112.0bps): $+601 -> **PASS**
- **G5 Concentration**: top1=21.1% (< 40%), top3=42.6% (< 70%) -> **PASS**

### Tier 3 (Illiquid) (109 coins, fee=101.0bps)

**Verdict**: **INSUFFICIENT_SAMPLE** -- Only 17 trades (need >= 20)

- **G1 Trade Sufficiency**: 17 trades (min=20) -> **INSUFFICIENT_SAMPLE**
- **G2 Walk-Forward**: 3/5 positive folds, 3/5 PF>1 -> **FAIL**

  | Fold | Bars | Trades | P&L | PF | WR% | Positive |
  |------|------|--------|-----|----|-----|----------|
  | 1 | 50-184 | 4 | $-69 | 0.85 | 50.0% | NO |
  | 2 | 184-318 | 4 | $+396 | 27.16 | 50.0% | YES |
  | 3 | 318-452 | 3 | $+133 | 2.21 | 66.7% | YES |
  | 4 | 452-586 | 2 | $-242 | 0.0 | 0.0% | NO |
  | 5 | 586-721 | 4 | $+28 | 1.11 | 75.0% | YES |

- **G3 Rolling Windows**: 2/4 positive (50%, gate >= 70%) -> **FAIL**
- **G4 Friction Stress**: 1.5x (151.5bps): $-154 | 2.0x (202.0bps): $-452 -> **FAIL**
- **G5 Concentration**: top1=16.8% (< 40%), top3=46.6% (< 70%) -> **PASS**

### Tier 1+2 (Live) (316 coins, fee=56.0bps)

**Verdict**: **GO** -- All 5 hard gates passed

- **G1 Trade Sufficiency**: 29 trades (min=20) -> **PASS**
- **G2 Walk-Forward**: 5/5 positive folds, 5/5 PF>1 -> **PASS**

  | Fold | Bars | Trades | P&L | PF | WR% | Positive |
  |------|------|--------|-----|----|-----|----------|
  | 1 | 50-184 | 6 | $+32 | 1.05 | 50.0% | YES |
  | 2 | 184-318 | 4 | $+420 | 99.0 | 100.0% | YES |
  | 3 | 318-452 | 4 | $+118 | 1.54 | 50.0% | YES |
  | 4 | 452-586 | 6 | $+211 | 1.46 | 50.0% | YES |
  | 5 | 586-721 | 9 | $+434 | 1.64 | 66.7% | YES |

- **G3 Rolling Windows**: 4/4 positive (100%, gate >= 70%) -> **PASS**
- **G4 Friction Stress**: 1.5x (84.0bps): $+1,328 | 2.0x (112.0bps): $+827 -> **PASS**
- **G5 Concentration**: top1=14.2% (< 40%), top3=35.4% (< 70%) -> **PASS**

---

## 3. Key Findings

### Champion_H2

**Passing tiers**: Tier 2 (Mid), Tier 1+2 (Live)
**Insufficient sample**: Tier 1 (Liquid), Tier 3 (Illiquid)

### GRID_BEST

**Passing tiers**: Tier 2 (Mid) (SOFT-GO), Tier 1+2 (Live)
**Insufficient sample**: Tier 1 (Liquid), Tier 3 (Illiquid)

---

## 4. Live Eligibility Assessment

> Does **Tier 1+2** at conservative fees (T2=56.0bps) pass all gates?

| Config | Tier 1+2 Verdict | Live Eligible? |
|--------|-----------------|----------------|
| Champion_H2 | **GO** | **YES** |
| GRID_BEST | **GO** | **YES** |

**Recommendation**: Both configs pass gates on the live universe (Tier 1+2) 
under conservative per-tier friction. The strategy is eligible for live trading 
on the tradeable universe defined in `UNIVERSE_POLICY.md`.

---

## Gate Thresholds (per GATES.md)

| Gate | Threshold |
|------|-----------|
| G1 Trade Sufficiency | >= 20 trades |
| G2 Walk-Forward | >= 4/5 folds positive (or PF>1) |
| G3 Rolling Windows | >= 70% positive P&L |
| G4 Friction Stress | P&L > $0 at tier_fee*1.5 AND tier_fee*2.0 |
| G5 Concentration | top1 < 40%, top3 < 70% |

## Fee Model

| Tier | Base Fee | Per-Side | 1.5x Stress | 2.0x Stress |
|------|----------|----------|-------------|-------------|
| Tier 1 (Liquid) | 26.0 bps | 31.0 bps | 46.5 bps | 62.0 bps |
| Tier 2 (Mid) | 26.0 bps | 56.0 bps | 84.0 bps | 112.0 bps |
| Tier 3 (Illiquid) | 26.0 bps | 101.0 bps | 151.5 bps | 202.0 bps |
| Tier 1+2 (Live) | 26.0 bps | 56.0 bps | 84.0 bps | 112.0 bps |

## Verdict Logic

- `INSUFFICIENT_SAMPLE`: trades < 20
- `GO`: all 5 hard gates pass
- `SOFT-GO`: WF 3/5 and all other gates pass
- `NO-GO`: any gate fails (beyond soft WF)

*Generated by hf_validate_per_tier.py at 2026-02-15 14:01 -- 4H variant research*
# MEXC Risk Wrapper Sweep — Sprint4_041 DD Reduction

**Date**: 2026-02-18
**Git**: `9a606d9`
**Config**: Sprint4_041 (H4S4-G05) vol_mult=3.5, rsi_max=35
**Universe**: Top 200 by volume, >=2160 bars (200 coins)
**Full range**: ~467 days, 2853 bars
**Fee**: MEXC 10bps
**Sizing**: Fixed $2,000/trade (no compounding)

## Baseline

| Metric | Value |
|--------|------:|
| Trades | 330 |
| PF | 1.3628 |
| P&L | $+8,696.59 |
| DD | 52.6% |
| WR | 53.9% |
| EV/trade | $26.35 |
| Trades/day | 0.76 |
| Capped returns | 1 |

## Methodology

Post-hoc risk wrappers applied to fixed-notional ($2000/trade) trade list.
Entry and exit logic UNCHANGED. Only sizing or trade admission modified.

### Wrapper Strategies
1. **DD Throttle** (15 combos): Scale position size when DD > threshold
2. **Vol Scaling** (9 combos): Size inversely proportional to ATR (capped 0.25x-2.0x)
3. **Adaptive MaxPos** (4 combos): Reduce max concurrent positions by DD level
4. **Cooldown Extension** (5 combos): Extend post-stop cooldown beyond default 8 bars
5. **Combined** (top-2 x top-2 cross-category): Size-based + skip-based

**Total combos**: 49

### Scoring Function
```
score = dd_improvement * 0.5 + pf_retention * 0.3 + trade_retention * 0.2
Hard gate: PF < 1.0 => score = 0
```

## Top-10 Leaderboard

| # | Score | PF | DD% | Trades | P&L | WR% | DD Reduction | Category | Label |
|---|------:|---:|----:|-------:|----:|----:|------------:|----------|-------|
| 1 | 0.8286 | 1.50 | 16.2% | 250 | $+3,050 | 56.0% | +69.3% | combined | COMBO(dd_throttle(dd>5%,scale=0.25) + adaptive_max **DEPLOY** |
| 2 | 0.8106 | 1.46 | 20.3% | 301 | $+3,415 | 54.5% | +61.4% | combined | COMBO(dd_throttle(dd>5%,scale=0.25) + adaptive_max **DEPLOY** |
| 3 | 0.8028 | 1.46 | 16.5% | 228 | $+3,161 | 55.7% | +68.7% | combined | COMBO(dd_throttle(dd>10%,scale=0.25) + adaptive_ma **DEPLOY** |
| 4 | 0.8001 | 1.40 | 21.9% | 330 | $+3,193 | 53.9% | +58.4% | dd_throttle | dd_throttle(dd>5%,scale=0.25) **DEPLOY** |
| 5 | 0.8001 | 1.40 | 21.9% | 330 | $+3,193 | 53.9% | +58.4% | combined | COMBO(dd_throttle(dd>5%,scale=0.25) + cooldown_ext **DEPLOY** |
| 6 | 0.8001 | 1.40 | 21.9% | 330 | $+3,193 | 53.9% | +58.4% | combined | COMBO(dd_throttle(dd>5%,scale=0.25) + cooldown_ext **DEPLOY** |
| 7 | 0.7757 | 1.37 | 20.7% | 281 | $+3,228 | 55.5% | +60.7% | combined | COMBO(dd_throttle(dd>10%,scale=0.25) + adaptive_ma **DEPLOY** |
| 8 | 0.7459 | 1.65 | 27.6% | 244 | $+10,797 | 57.0% | +47.6% | adaptive_maxpos | adaptive_maxpos(2/1/1) **DEPLOY** |
| 9 | 0.7048 | 1.29 | 29.3% | 330 | $+2,787 | 53.9% | +44.4% | dd_throttle | dd_throttle(dd>10%,scale=0.25) **DEPLOY** |
| 10 | 0.7048 | 1.29 | 29.3% | 330 | $+2,787 | 53.9% | +44.4% | combined | COMBO(dd_throttle(dd>10%,scale=0.25) + cooldown_ex **DEPLOY** |

## Per-Category Best

| Category | Score | PF | DD% | Trades | P&L | Label |
|----------|------:|---:|----:|-------:|----:|-------|
| dd_throttle | 0.8001 | 1.40 | 21.9% | 330 | $+3,193 | dd_throttle(dd>5%,scale=0.25) |
| vol_scale | 0.4738 | 1.24 | 141.7% | 330 | $+9,181 | vol_scale(atr7,pctl=75) |
| adaptive_maxpos | 0.7459 | 1.65 | 27.6% | 244 | $+10,797 | adaptive_maxpos(2/1/1) |
| cooldown_ext | 0.5000 | 1.36 | 52.6% | 330 | $+8,697 | cooldown_ext(cd=8bars) |
| combined | 0.8286 | 1.50 | 16.2% | 250 | $+3,050 | COMBO(dd_throttle(dd>5%,scale=0.25) + adaptiv |

## Deploy Candidates (PF>=1.15, DD<35%, Trades>200)

| # | Category | PF | DD% | Trades | P&L | Score | Label |
|---|----------|---:|----:|-------:|----:|------:|-------|
| 1 | combined | 1.50 | 16.2% | 250 | $+3,050 | 0.8286 | COMBO(dd_throttle(dd>5%,scale=0.25) + adaptive_max |
| 2 | combined | 1.46 | 20.3% | 301 | $+3,415 | 0.8106 | COMBO(dd_throttle(dd>5%,scale=0.25) + adaptive_max |
| 3 | combined | 1.46 | 16.5% | 228 | $+3,161 | 0.8028 | COMBO(dd_throttle(dd>10%,scale=0.25) + adaptive_ma |
| 4 | dd_throttle | 1.40 | 21.9% | 330 | $+3,193 | 0.8001 | dd_throttle(dd>5%,scale=0.25) |
| 5 | combined | 1.40 | 21.9% | 330 | $+3,193 | 0.8001 | COMBO(dd_throttle(dd>5%,scale=0.25) + cooldown_ext |
| 6 | combined | 1.40 | 21.9% | 330 | $+3,193 | 0.8001 | COMBO(dd_throttle(dd>5%,scale=0.25) + cooldown_ext |
| 7 | combined | 1.37 | 20.7% | 281 | $+3,228 | 0.7757 | COMBO(dd_throttle(dd>10%,scale=0.25) + adaptive_ma |
| 8 | adaptive_maxpos | 1.65 | 27.6% | 244 | $+10,797 | 0.7459 | adaptive_maxpos(2/1/1) |
| 9 | dd_throttle | 1.29 | 29.3% | 330 | $+2,787 | 0.7048 | dd_throttle(dd>10%,scale=0.25) |
| 10 | combined | 1.29 | 29.3% | 330 | $+2,787 | 0.7048 | COMBO(dd_throttle(dd>10%,scale=0.25) + cooldown_ex |
| 11 | combined | 1.29 | 29.3% | 330 | $+2,787 | 0.7048 | COMBO(dd_throttle(dd>10%,scale=0.25) + cooldown_ex |
| 12 | dd_throttle | 1.17 | 33.2% | 330 | $+1,689 | 0.6404 | dd_throttle(dd>15%,scale=0.25) |

## All Results by Category

### Dd Throttle (15 combos)

| # | Score | PF | DD% | Trades | P&L | DD red | Label |
|---|------:|---:|----:|-------:|----:|-------:|-------|
| 1 | 0.8001 | 1.40 | 21.9% | 330 | $+3,193 | +58.4% | dd_throttle(dd>5%,scale=0.25) |
| 2 | 0.7048 | 1.29 | 29.3% | 330 | $+2,787 | +44.4% | dd_throttle(dd>10%,scale=0.25) |
| 3 | 0.6404 | 1.17 | 33.2% | 330 | $+1,689 | +36.8% | dd_throttle(dd>15%,scale=0.25) |
| 4 | 0.6374 | 1.31 | 36.9% | 330 | $+4,452 | +29.9% | dd_throttle(dd>5%,scale=0.5) |
| 5 | 0.6211 | 1.23 | 36.9% | 330 | $+3,676 | +29.9% | dd_throttle(dd>10%,scale=0.5) |
| 6 | 0.5903 | 1.21 | 39.6% | 330 | $+4,103 | +24.7% | dd_throttle(dd>20%,scale=0.5) |
| 7 | 0.5645 | 1.20 | 41.9% | 330 | $+3,334 | +20.2% | dd_throttle(dd>15%,scale=0.5) |
| 8 | 0.5620 | 1.33 | 45.2% | 330 | $+6,399 | +14.1% | dd_throttle(dd>5%,scale=0.75) |
| 9 | 0.5620 | 1.13 | 40.6% | 330 | $+1,291 | +22.7% | dd_throttle(dd>20%,scale=0.25) |
| 10 | 0.5590 | 1.31 | 45.2% | 330 | $+6,512 | +14.1% | dd_throttle(dd>10%,scale=0.75) |
| 11 | 0.5569 | 1.35 | 46.3% | 330 | $+8,028 | +11.9% | dd_throttle(dd>20%,scale=0.75) |
| 12 | 0.5421 | 1.15 | 43.2% | 330 | $+2,106 | +17.9% | dd_throttle(dd>25%,scale=0.25) |
| 13 | 0.5279 | 1.23 | 46.5% | 330 | $+4,774 | +11.5% | dd_throttle(dd>25%,scale=0.5) |
| 14 | 0.5233 | 1.34 | 49.7% | 330 | $+7,969 | +5.5% | dd_throttle(dd>25%,scale=0.75) |
| 15 | 0.5200 | 1.30 | 49.0% | 330 | $+6,577 | +6.8% | dd_throttle(dd>15%,scale=0.75) |

### Vol Scale (9 combos)

| # | Score | PF | DD% | Trades | P&L | DD red | Label |
|---|------:|---:|----:|-------:|----:|-------:|-------|
| 1 | 0.4738 | 1.24 | 141.7% | 330 | $+9,181 | -169.6% | vol_scale(atr7,pctl=75) |
| 2 | 0.4738 | 1.24 | 141.7% | 330 | $+9,181 | -169.6% | vol_scale(atr14,pctl=75) |
| 3 | 0.4738 | 1.24 | 141.7% | 330 | $+9,181 | -169.6% | vol_scale(atr21,pctl=75) |
| 4 | 0.4614 | 1.19 | 82.4% | 330 | $+3,697 | -56.6% | vol_scale(atr7,pctl=25) |
| 5 | 0.4614 | 1.19 | 82.4% | 330 | $+3,697 | -56.6% | vol_scale(atr14,pctl=25) |
| 6 | 0.4614 | 1.19 | 82.4% | 330 | $+3,697 | -56.6% | vol_scale(atr21,pctl=25) |
| 7 | 0.4524 | 1.15 | 102.3% | 330 | $+4,195 | -94.6% | vol_scale(atr7,pctl=50) |
| 8 | 0.4524 | 1.15 | 102.3% | 330 | $+4,195 | -94.6% | vol_scale(atr14,pctl=50) |
| 9 | 0.4524 | 1.15 | 102.3% | 330 | $+4,195 | -94.6% | vol_scale(atr21,pctl=50) |

### Adaptive Maxpos (4 combos)

| # | Score | PF | DD% | Trades | P&L | DD red | Label |
|---|------:|---:|----:|-------:|----:|-------:|-------|
| 1 | 0.7459 | 1.65 | 27.6% | 244 | $+10,797 | +47.6% | adaptive_maxpos(2/1/1) |
| 2 | 0.6100 | 1.51 | 42.7% | 304 | $+10,735 | +18.7% | adaptive_maxpos(3/2/1) |
| 3 | 0.5882 | 1.40 | 42.7% | 308 | $+9,027 | +18.7% | adaptive_maxpos(3/3/1) |
| 4 | 0.5841 | 1.52 | 42.7% | 258 | $+9,501 | +18.7% | adaptive_maxpos(2/2/1) |

### Cooldown Ext (5 combos)

| # | Score | PF | DD% | Trades | P&L | DD red | Label |
|---|------:|---:|----:|-------:|----:|-------:|-------|
| 1 | 0.5000 | 1.36 | 52.6% | 330 | $+8,697 | +0.0% | cooldown_ext(cd=8bars) |
| 2 | 0.5000 | 1.36 | 52.6% | 330 | $+8,697 | +0.0% | cooldown_ext(cd=12bars) |
| 3 | 0.5000 | 1.36 | 52.6% | 330 | $+8,697 | +0.0% | cooldown_ext(cd=16bars) |
| 4 | 0.5000 | 1.36 | 52.6% | 330 | $+8,697 | +0.0% | cooldown_ext(cd=20bars) |
| 5 | 0.5000 | 1.36 | 52.6% | 330 | $+8,697 | +0.0% | cooldown_ext(cd=24bars) |

### Combined (16 combos)

| # | Score | PF | DD% | Trades | P&L | DD red | Label |
|---|------:|---:|----:|-------:|----:|-------:|-------|
| 1 | 0.8286 | 1.50 | 16.2% | 250 | $+3,050 | +69.3% | COMBO(dd_throttle(dd>5%,scale=0.25) + adaptiv |
| 2 | 0.8106 | 1.46 | 20.3% | 301 | $+3,415 | +61.4% | COMBO(dd_throttle(dd>5%,scale=0.25) + adaptiv |
| 3 | 0.8028 | 1.46 | 16.5% | 228 | $+3,161 | +68.7% | COMBO(dd_throttle(dd>10%,scale=0.25) + adapti |
| 4 | 0.8001 | 1.40 | 21.9% | 330 | $+3,193 | +58.4% | COMBO(dd_throttle(dd>5%,scale=0.25) + cooldow |
| 5 | 0.8001 | 1.40 | 21.9% | 330 | $+3,193 | +58.4% | COMBO(dd_throttle(dd>5%,scale=0.25) + cooldow |
| 6 | 0.7757 | 1.37 | 20.7% | 281 | $+3,228 | +60.7% | COMBO(dd_throttle(dd>10%,scale=0.25) + adapti |
| 7 | 0.7048 | 1.29 | 29.3% | 330 | $+2,787 | +44.4% | COMBO(dd_throttle(dd>10%,scale=0.25) + cooldo |
| 8 | 0.7048 | 1.29 | 29.3% | 330 | $+2,787 | +44.4% | COMBO(dd_throttle(dd>10%,scale=0.25) + cooldo |
| 9 | 0.4759 | 1.43 | 52.0% | 258 | $+12,367 | +1.1% | COMBO(vol_scale(atr7,pctl=75) + adaptive_maxp |
| 10 | 0.4759 | 1.43 | 52.0% | 258 | $+12,367 | +1.1% | COMBO(vol_scale(atr14,pctl=75) + adaptive_max |
| 11 | 0.4738 | 1.24 | 141.7% | 330 | $+9,181 | -169.6% | COMBO(vol_scale(atr7,pctl=75) + cooldown_ext( |
| 12 | 0.4738 | 1.24 | 141.7% | 330 | $+9,181 | -169.6% | COMBO(vol_scale(atr7,pctl=75) + cooldown_ext( |
| 13 | 0.4738 | 1.24 | 141.7% | 330 | $+9,181 | -169.6% | COMBO(vol_scale(atr14,pctl=75) + cooldown_ext |
| 14 | 0.4738 | 1.24 | 141.7% | 330 | $+9,181 | -169.6% | COMBO(vol_scale(atr14,pctl=75) + cooldown_ext |
| 15 | 0.4623 | 1.50 | 52.0% | 211 | $+11,829 | +1.1% | COMBO(vol_scale(atr7,pctl=75) + adaptive_maxp |
| 16 | 0.4623 | 1.50 | 52.0% | 211 | $+11,829 | +1.1% | COMBO(vol_scale(atr14,pctl=75) + adaptive_max |

## Recommendation

**Recommended deploy candidate**: COMBO(dd_throttle(dd>5%,scale=0.25) + adaptive_maxpos(2/1/1))
- PF: 1.50 (baseline: 1.36)
- DD: 16.2% (baseline: 52.6%)
- Trades: 250 (baseline: 330)
- P&L: $+3,050.29 (baseline: $+8,696.59)
- Score: 0.8286


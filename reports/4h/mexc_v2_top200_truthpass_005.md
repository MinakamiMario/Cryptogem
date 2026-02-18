# MEXC v2 Top-200 Truth-Pass (Fixed Notional)

**Date**: 2026-02-18
**Git**: `9a606d9`
**Universe**: Top 200 by volume, ≥2160 bars (200 coins)
**Full range**: ~467 days, 2853 bars
**Fee**: MEXC 10bps
**Sizing**: Fixed $2,000/trade (no compounding)

## Verdict Summary

| Config | Verdict | PF | P&L | Trades | DD | WR | Window | WF | Bootstrap |
|--------|---------|---:|----:|-------:|---:|---:|-------:|---:|----------:|
| Vol 3.5x RSI 35 (primary) | **VERIFIED** | 1.36 | $+8,697 | 330 | 52.6% | 53.9% | PASS (3/3) | PASS | PASS (P5=1.04, 96%) |
| Vol 4.0x RSI 40 (secondary) | **VERIFIED** | 1.31 | $+7,297 | 304 | 50.3% | 54.0% | PASS (3/3) | PASS | PASS (P5=0.98, 93%) |

## Vol 3.5x RSI 35 (primary)

**Full range**: 330 trades, PF=1.36, P&L=$+8,696.59, DD=52.6%, WR=53.9%, 0.71 trades/day

### Window Split

| Window | Trades | PF | P&L |
|--------|-------:|---:|----:|
| early | 157 | 1.32 | $+3,923 |
| mid | 96 | 1.40 | $+2,668 |
| late | 77 | 1.34 | $+1,707 |

**3/3 PASS**

### Walk-Forward

- **Split A (cal=early, test=mid+late)** [PASS]: cal=157tr PF=1.32, test=173tr PF=1.37
- **Split B (cal=early+mid, test=late)** [PASS]: cal=253tr PF=1.37, test=77tr PF=1.34

### Bootstrap

- P5 PF: 1.04, Median PF: 1.35
- % Profitable: 96.5%
- **PASS**

### Determinism: **PASS**

## Vol 4.0x RSI 40 (secondary)

**Full range**: 304 trades, PF=1.31, P&L=$+7,296.72, DD=50.3%, WR=54.0%, 0.65 trades/day

### Window Split

| Window | Trades | PF | P&L |
|--------|-------:|---:|----:|
| early | 151 | 1.16 | $+2,077 |
| mid | 86 | 1.31 | $+2,017 |
| late | 67 | 1.74 | $+2,875 |

**3/3 PASS**

### Walk-Forward

- **Split A (cal=early, test=mid+late)** [PASS]: cal=151tr PF=1.16, test=153tr PF=1.46
- **Split B (cal=early+mid, test=late)** [PASS]: cal=237tr PF=1.23, test=67tr PF=1.74

### Bootstrap

- P5 PF: 0.98, Median PF: 1.30
- % Profitable: 93.0%
- **PASS**

### Determinism: **PASS**

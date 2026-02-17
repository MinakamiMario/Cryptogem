# Regime Filter Results — SMA50 Slope Gate

**Date**: 2026-02-17
**Config**: hnotrl_msp20 (max_pos=2, rsi42, msp20, tm20)
**Filter**: Only enter when per-coin SMA50 slope <= threshold

## Impact Table

| Window | Slope Gate | Tr | WR% | P&L | PF | DD% | EV/trade | Verdict |
|--------|------------|---:|----:|----:|---:|----:|---------:|---------|
| EARLY | none | 15 | 60.0 | +$4 | 1.01 | 18.5 | +$0.3 | NO-GO |
| EARLY | ≤-6% | 7 | 57.1 | -$45 | 0.87 | 16.7 | -$6.4 | INSUF |
| EARLY | ≤-8% | 4 | 50.0 | -$132 | 0.55 | 16.7 | -$33.1 | INSUF |
| EARLY | ≤-10% | 3 | 33.3 | -$212 | 0.27 | 16.7 | -$70.7 | INSUF |
| | | | | | | | | |
| LATE | none | 20 | 85.0 | +$3,514 | 9.40 | 12.0 | +$176 | GO |
| LATE | ≤-6% | 11 | 90.9 | +$3,010 | 14.89 | 11.1 | +$274 | INSUF |
| LATE | ≤-8% | 9 | 88.9 | +$2,920 | 14.63 | 11.0 | +$325 | INSUF |
| LATE | ≤-10% | 7 | 100.0 | +$2,985 | ∞ | 2.1 | +$427 | INSUF |
| | | | | | | | | |
| FULL | none | 43 | 72.1 | +$3,331 | 3.61 | 22.8 | +$78 | GO |
| FULL | ≤-6% | 21 | 71.4 | +$3,315 | 6.82 | 16.7 | +$158 | NO-GO |
| FULL | ≤-8% | 16 | 68.8 | +$2,986 | 6.95 | 17.3 | +$187 | NO-GO |
| FULL | ≤-10% | 13 | 69.2 | +$2,491 | 8.71 | 16.7 | +$192 | INSUF |

## Key Findings

### 1. Regime filter VERBETERT kwaliteit maar VERLAAGT trade count

Op FULL window:
- **≤-6%**: Halveert trades (43→21), maar behoudt 99.5% van de P&L (+$3,315 vs +$3,331)!
  PF stijgt van 3.61→6.82, DD daalt van 22.8%→16.7%, EV verdubbelt (+$78→+$158)
- **≤-8%**: Nog selectiever (43→16), P&L -10% maar PF bijna verdubbeld (6.95)
- **≤-10%**: Te streng — onder G1 drempel (13 trades < 15)

### 2. De filter doet EXACT wat verwacht: hij blokkeert EARLY trades

EARLY zonder filter: 15 trades, break-even (+$4). Met ≤-6%: slechts 7 trades, -$45.
Dit bevestigt: de EARLY trades die overblijven na filtering zijn NIET beter — ze zijn zelfs slechter.
De EARLY window heeft simpelweg geen edge, regime filter of niet.

### 3. LATE trades worden nauwelijks beïnvloed

LATE ≤-6% behoudt 11/20 trades en 86% van P&L. De 9 gefilterde trades waren
kleine winnaars — de grote winners (RSI Recovery) vallen allemaal in diep-bearish regime.

### 4. Het dilemma: kwaliteit vs sample size

| Threshold | FULL trades | PF | P&L retained | Gate verdict |
|-----------|-------------|-----|-------------|--------------|
| none | 43 | 3.61 | 100% | **GO** |
| ≤-6% | 21 | 6.82 | 99.5% | NO-GO (G5) |
| ≤-8% | 16 | 6.95 | 89.6% | NO-GO (G5) |
| ≤-10% | 13 | 8.71 | 74.8% | INSUFFICIENT |

De filter verbetert PF dramatisch maar verlaagt trades onder G1/G5 drempels.
**Met 120 dagen data is er niet genoeg sample size om een regime filter te valideren.**

## Verdict

**De SMA50 slope filter is DIAGNOSTISCH WAARDEVOL maar NIET deployeerbaar met huidige data.**

De filter bevestigt dat:
1. De edge zit in diep-bearish regime (SMA50 slope < -8%)
2. Buiten dat regime is de strategie break-even
3. Maar met slechts 120 dagen data levert filtering te weinig trades op

### Aanbeveling

1. **NIET implementeren als hard gate** — te weinig trades na filtering
2. **WEL gebruiken als informatief signaal** — "trade met meer vertrouwen wanneer slope < -8%"
3. **Meer data nodig** (360+ dagen) om regime filter statistisch te valideren
4. **hnotrl_msp20 zonder filter blijft de productie-kandidaat** — 43 trades, PF 3.61, GO op FULL+LATE

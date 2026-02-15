# V5 KANDIDATEN RAPPORT
**Datum:** 13 februari 2026, 05:30 UTC (bijgewerkt)
**Testperiode:** 60 dagen bear market (285 coins, Kraken)
**Totaal geteste configuraties:** 250+

---

## V4 BASELINE (huidige strategie)
```
12 trades | WR 83.3% | P&L $+4,553 | PF 78.07 | DD 1.9% | AvgBars 6.3
```
**Entry:** DualConfirm (Donchian+BB) | RSI<40 | VolSpike>2x | VolConfirm>1x
**Exit:** ATR 2.0x trailing | BE+3% | TimeMax 10 bars
**Portfolio:** 1x$2000 all-in | Volume ranking

---

## V5 WINNAAR: RSI Recovery Exit

### Wat is het?
Een extra exit-regel die de trade sluit zodra de RSI herstelt naar een neutraal niveau. De logica: we kopen in oversold (RSI<40), dus als RSI herstelt naar ~45-47 is het ergste voorbij en pakken we winst.

### Beste configuratie
```
V5 = V4 + RSI Recovery Exit (target=47, min_bars=2)
12 trades | WR 91.7% | P&L $+4,711 | PF 107.81 | DD 1.8% | AvgBars 6.1
```

**vs V4:** +$158 meer P&L | +8.4% hoger WR | +38% hogere PF | -0.1% minder DD

### Impact analyse
De RSI Recovery exit verandert precies 1 verliezende trade in een winnaar:
- **ACA/USD:** Was TimeMax exit na 9 bars met -$15 verlies -> Nu RSI Recovery exit na 6 bars met +$143 winst
- **Verschil:** $158 extra P&L, 1 minder verlies

### Robustheid
RSI Recovery is **zeer robuust**:
- target=42 tot 47: Allemaal 91.7% WR, PF >106
- target=42-43: $+4,665 (identiek)
- target=44: $+4,663
- target=45: $+4,666
- target=46: $+4,673
- target=47: $+4,711 (best)
- target=48+: valt terug naar V4 baseline (RSI bereikt 48 niet meer voor TimeMax)
- min_bars 1-6: Geen verschil (identieke resultaten)

**Cliff edge bij 48:** Target=47 is de hoogste die nog effect heeft. Target=48 levert baseline.

### Trade details (V5 met RSI Recovery target=47)
```
 TANSSI/USD   | $0.0106 -> $0.0114 | P&L $+134.51 |  9b | TIME MAX (RSI bleef <47)
 LCX/USD      | $0.0571 -> $0.0604 | P&L $+103.51 |  5b | RSI RECOVERY
 ACA/USD      | $0.0087 -> $0.0094 | P&L $+142.69 |  6b | RSI RECOVERY *** was -$15 verlies in V4!
 EWT/USD      | $0.7510 -> $0.7730 | P&L  $+48.04 |  9b | TIME MAX
 BICO/USD     | $0.0433 -> $0.0446 | P&L  $+49.49 |  6b | DC TARGET
 AI3/USD      | $0.0189 -> $0.0186 | P&L  $-44.10 |  9b | TIME MAX (enige verliezer)
 HBAR/USD     | $0.1031 -> $0.1070 | P&L  $+63.88 |  7b | DC TARGET
 BERA/USD     | $0.5890 -> $0.6082 | P&L  $+54.63 |  7b | DC TARGET
 ZEUS/USD     | $0.0071 -> $0.0190 | P&L $+3333.0 |  6b | RSI RECOVERY
 XRP/USD      | $1.2117 -> $1.5120 | P&L $+484.02 |  4b | DC TARGET
 B3/USD       | $0.0005 -> $0.0006 | P&L $+309.10 |  3b | RSI RECOVERY
 ESPORTS/USD  | $0.3969 -> $0.4053 | P&L  $+31.82 |  2b | DC TARGET
```

---

## ANDERE GETESTE VERBETERINGEN

### Entry filters
| Filter | Trades | WR | P&L | PF | Verdict |
|--------|--------|-----|------|-----|---------|
| ADX > 15-25 | 7-12 | 57-78% | -$390 tot -$3900 | 4-44 | SLECHTER - filtert goede trades weg |
| RSI < 35 | 10 | 90% | $+4,530 | 104 | Iets beter WR, maar verliest 2 trades |
| RSI < 30 | 8 | 87.5% | $+1,062 | 25 | Te restrictief |
| VolSpike > 1.5x | 14 | 85.7% | $+4,592 | 32 | Meer trades maar lager PF |
| VolSpike > 2.5-3.0x | 11 | 81.8% | $+4,499 | 77 | Nauwelijks verschil |
| Higher Low | 0 | - | - | - | Filtert ALLES weg |
| BB Squeeze | 0-6 | - | - | - | Niet compatibel |
| Consec Red candles | varies | - | - | - | Schadelijk |

### Exit verbeteringen
| Tweak | Trades | WR | P&L | PF | Verdict |
|-------|--------|-----|------|-----|---------|
| **RSI Recovery (47,2b)** | **12** | **91.7%** | **$+4,711** | **108** | **WINNAAR** |
| RSI Recovery (45,2b) | 12 | 91.7% | $+4,666 | 107 | Runner-up |
| DynTimeMax (+4b RSI>40) | 12 | 83.3% | $+4,622 | 79 | Klein voordeel |
| TimeMax = OFF | 12 | 91.7% | $+4,595 | 52 | Goed WR maar lager PF |
| TimeMax = 12 | 12 | 83.3% | $+4,576 | 47 | Minimaal beter |
| Adaptive ATR | 12 | 83.3% | $+4,553 | 78 | Geen effect |
| StepTrail | 12 | 83.3% | $+4,553 | 78 | Geen effect |
| BE trigger variaties | 12 | 83.3% | $+4,553 | 78 | Geen effect |
| Profit target <15% | 12 | varies | -$238+ | varies | Schadelijk (capt ZEUS outlier) |

### Period variaties
| Config | Trades | WR | P&L | PF | Verdict |
|--------|--------|-----|------|-----|---------|
| DC=10 BB=20 | 12 | 91.7% | $+4,399 | 101 | Hogere WR maar lager P&L |
| DC=15 BB=20 | 12 | 91.7% | $+4,404 | 101 | Idem |
| DC=20 BB=20 (V4) | 12 | 83.3% | $+4,553 | 78 | Baseline |
| DC=25/30 | 10-11 | 80-82% | -$334+ | 70-73 | Slechter |
| BB dev=2.0 (V4) | 12 | 83.3% | $+4,553 | 78 | Optimaal |
| BB dev <2.0 | 19-41 | 39-53% | -$1000+ | 1.8-5.5 | Veel slechter |

### Nieuwe entry filters (final sweep)
| Filter | Trades | WR | P&L | PF | Verdict |
|--------|--------|-----|------|-----|---------|
| Body/wick ratio > 0.2-0.6 | 4-9 | 40-57% | $+188 tot $+717 | 1.9-4.0 | Schadelijk - filtert ZEUS weg |
| Vol acceleration 2-4 bars | 2-10 | 80-100% | $+210 tot $+1,037 | 19-INF | Te weinig trades |
| Min ATR% > 3% | 6 | 83.3% | $+4,016 | 269 | Interessant: 100% WR (excl ZEUS), maar halveert trades |
| BB distance < 2-10% | 12 | 83.3% | $+4,295-4,553 | 74-78 | Geen of licht schadelijk effect |
| Bounce strength > 30-70% | 9-12 | 64-70% | $+510 tot $+4,145 | 2.9-16 | Schadelijk |
| EMA20/50/100/200 below | 12 | 83.3% | $+4,553 | 78 | GEEN effect (alles al onder EMA in bear) |

### V5 + nieuwe filters
| Combo | Trades | WR | P&L | PF | Verdict |
|-------|--------|-----|------|-----|---------|
| V5 + MinATR>3% | 6 | 100% | $+4,174 | INF | 0% DD maar halveert P&L |
| V5 + MinATR>2% | 11 | 90.9% | $+4,585 | 49 | Klein voordeel maar lager PF |
| V5 + BBdist<5% | 12 | 91.7% | $+4,711 | 108 | IDENTIEK (filter doet niets) |
| V5 + EMA50/200 | 12 | 91.7% | $+4,711 | 108 | IDENTIEK (bear market) |

### Overige
- **Cooldown variaties:** Geen enkel effect (alle 12 varianten identiek)
- **RSI sell threshold:** Geen effect (50-80 identiek)
- **ATR multiplier:** 1.8-3.5x identiek; <1.8x slechter (meer stops)
- **Step-trail exit:** Geen effect (trades exiten al voor steps bereikt)
- **Profit target:** Alles boven 15% geen effect; <15% schadelijk (capt ZEUS)

---

## CONCLUSIE & AANBEVELING

### V5 = V4 + RSI Recovery Exit (target=47, min_bars=2)

**Verandering:** Eenvoudige toevoeging van 1 exit-regel:
> Als RSI >= 47 EN minstens 2 bars in trade -> exit met "RSI RECOVERY"

**Waarom target=47 en niet 45?**
- 47 laat trades iets langer lopen -> meer winst (TANSSI, EWT krijgen TimeMax i.p.v. vroege RSI exit)
- Maar het vangt wel ACA op die bij V4 als verliezer eindigde
- Edge case: 48 werkt niet meer (AI3 bereikt nooit RSI 48 binnen TimeMax)

**Risico-inschatting:**
- LAAG risico: identieke entry logica, alleen exit wordt slimmer
- Robuust: werkt consistent van target 42-47
- Ergste geval: sommige trades sluiten iets eerder (minder winst maar ook minder risico)
- ZEUS trade ongewijzigd: $+3,333 P&L blijft intact

**Implementatie:** 3 regels code toevoegen aan strategy.py (exit check na min_bars)

**Overweging target=47 vs 45:**
- target=45 is "veiliger" (meer marge tot cliff edge bij 48)
- target=47 levert $45 meer P&L ($4,711 vs $4,666)
- Aanbeveling: **target=45** voor productie (meer marge, kleiner overfitting risico)

---

## SAMENVATTING NACHTWERK

**4 test-scripts geschreven en gedraaid:**
1. `backtest_v5_experiments.py` - 74 configuraties (exit, ATR, periodes, entry, combos)
2. `backtest_v5_deep_dive.py` - RSI Recovery tuning, ADX anomalie, DC periodes
3. `backtest_v5_precision.py` - Fine-tuning sweep RSI Recovery 42-47
4. `backtest_v5_final_sweep.py` - Body/wick, vol accel, ATR%, bounce, EMA filters

**Belangrijkste inzichten:**
1. V4 is al bijna optimaal - de meeste tweaks hebben letterlijk GEEN effect
2. RSI Recovery Exit is de enige echte verbetering: +$158 P&L, WR 83%->92%
3. ADX filter is schadelijk met VolConfirm aan (tegengesteld aan eerdere test zonder VolConfirm)
4. ZEUS ($+3,333) is 71% van totale P&L - elke filter die ZEUS wegfiltert vernietigt de strategie
5. Alle EMA filters hebben 0 effect omdat alle coins al onder EMA zitten in bear market
6. Veel parameters zijn cliff-edges: BB dev=2.0 (1.8 of 2.2 = dramatisch slechter)

---

## STATUS PAPER TRADER (05:06 UTC)
- Running: V4 (zonder RSI Recovery) op paper_backfill_v4.py
- Checks voltooid: #1 (12:00), #2 (16:00), #3 (01:02), #4 (05:02) - 0 trades
- Volgende check: 08:02 UTC
- Resterend: 163.5 uur van 168 uur totaal
- Output: paper_trades_v4_live.xlsx + paper_state_v4_live.json

---

## NEXT STEPS (voor als je wakker wordt)
1. **Besluit:** V5 met RSI Recovery target=45 of 47 activeren?
2. **Paper trader:** Draait nog ~6.5 dagen op V4 - eventueel V5 paper trader ernaast starten
3. **Bull strategy:** Geparkeerd tot marktcondities veranderen
4. **Cycle detector:** Geparkeerd, later implementeren

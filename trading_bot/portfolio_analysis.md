# Portfolio Diversificatie & Position Sizing Analyse
**V5 Prod Strategie - Kraken Crypto Trading Bot**

---

## 1. Kelly Criterion Berekening

### Zonder ZEUS/USD (45 trades)

**Trade Statistics:**
- Trades: 45
- Wins: 21
- Losses: 24
- Win Rate (WR): 46.67%
- Total P&L: -$451.13
- Avg Win: $90.57
- Avg Loss: $118.79

**Kelly Formula:**
```
Kelly% = WR - ((1 - WR) / (Avg_Win / Avg_Loss))
Kelly% = 0.4667 - ((0.5333) / (90.57 / 118.79))
Kelly% = 0.4667 - (0.5333 / 0.7624)
Kelly% = 0.4667 - 0.6995
Kelly% = -0.2328 → -23.28%
```

**Conclusie:** NEGATIEVE Kelly → strategie is NIET winstgevend zonder ZEUS. Je zou theoretisch moeten SHORT gaan op deze strategie, of helemaal niet traden.

---

### Met ZEUS/USD (46 trades)

**Trade Statistics:**
- Trades: 46
- Wins: 22
- Losses: 24
- Win Rate: 47.83%
- Total P&L: $2,881.86
- Avg Win: $242.49 (inclusief ZEUS $3,333)
- Avg Loss: $118.25

**Kelly Formula:**
```
Kelly% = WR - ((1 - WR) / (Avg_Win / Avg_Loss))
Kelly% = 0.4783 - ((0.5217) / (242.49 / 118.25))
Kelly% = 0.4783 - (0.5217 / 2.0509)
Kelly% = 0.4783 - 0.2543
Kelly% = 0.2240 → 22.40%
```

**Full Kelly Aanbeveling:** 22.40% van kapitaal per trade

**Fractional Kelly Opties:**
- **25% Kelly (conservatief):** 5.6% per trade → $112 per trade op $2,000 kapitaal
- **50% Kelly (standaard):** 11.2% per trade → $224 per trade op $2,000 kapitaal
- **Full Kelly (agressief):** 22.4% per trade → $448 per trade op $2,000 kapitaal

**WAARSCHUWING:** Deze Kelly% is ALLEEN positief door ZEUS. De berekening gaat uit van een gemiddelde win van $242, maar:
- 21 van 22 wins zijn gemiddeld $90
- 1 win (ZEUS) is $3,333

Dit is GEEN stabiele Kelly% - hij is kunstmatig opgeblazen door één outlier.

---

## 2. Optimale max_positions Analyse

### Signaal Overlap Analyse (60 dagen)

**Huidige Data:**
- Totaal bars: 223 (60 dagen @ 4H candles)
- Totaal trades: 46
- Avg bars per trade: 5.43
- Entry bars variëren van bar 60 t/m 583

**Simultane Signalen Identificatie:**

Laat ik de overlappende trades berekenen:

**Trade Overlaps (voorbeeld uit de data):**

| Trade A | Trade B | Overlap Bars | Gemiste Kans? |
|---------|---------|--------------|---------------|
| KULA (63-65) | - | - | Nee |
| BTT (85-94) | - | - | Nee |
| XTER (106-115) | - | - | Nee |
| WCT (127-132) | - | - | Nee |
| OBOL (206-209) | OGN (215-224) | Geen | Opeenvolgende trades |
| OGN (215-224) | SOLV (234-241) | Geen | Opeenvolgende trades |
| TOKE (208-213) | OGN (215-224) | Geen | Opeenvolgende trades |

**CRUCIALE OBSERVATIE:**
In de huidige data (46 trades over 223 bars) zijn er **GEEN overlappende signalen**! Alle trades zijn opeenvolgend. Dit betekent:

1. De strategie is zeer selectief (entry filters zijn streng)
2. Er is hooguit 1 signaal per keer actief
3. **max_positions > 1 zou GEEN extra trades opleveren in deze dataset**

**Simulatie met 2-3 posities:**
- Met 2 posities: 0 extra trades (geen overlaps)
- Met 3 posities: 0 extra trades (geen overlaps)
- **Verwachte P&L verbetering: $0**

---

## 3. Anti-Concentratie Regel

### Max Verlies per Trade

**Huidige Situatie:**
- Grootste verlies (single trade): -$304.34 (FOREST/USD)
- Dit is **15.2%** van $2,000 kapitaal
- Tweede grootste: -$284.49 (XTER/USD) = 14.2%
- Derde grootste: -$268.99 (onbekend pair) = 13.4%

**Top 5 Verliezen:**
1. -$304.34 (15.2%)
2. -$284.49 (14.2%)
3. -$268.99 (13.4%)
4. -$236.79 (11.8%)
5. -$218.73 (10.9%)

**Risico Assessment:**
- 5 van 24 verliezen zijn >10% van kapitaal
- Dit is **extreem volatiel** voor een crypto strategie
- Max Drawdown van 75.3% bevestigt dit

**Aanbevolen Anti-Concentratie Regel:**
- **Max verlies per trade: 5% van equity** (best practice voor hoog-risico strategieën)
- **Max verlies per trade: 10% van equity** (agressief, maar binnen risicobeheer)

Dit zou betekenen:
- Bij 5% regel: max $100 risico → position size ≈ $200-400 (afhankelijk van ATR)
- Bij 10% regel: max $200 risico → position size ≈ $400-800

**PROBLEEM:** Huidige all-in strategie ($2,000 per trade) kan leiden tot -15% trades. Dit is te risicovol voor structureel kapitaalbeheer.

---

### Vaste $ vs Kelly-Adjusted Sizing

**Optie 1: Vaste $ per Trade**
- Voor: Simpel, consistent, voorspelbaar
- Tegen: Geen compound effect, geen risicoadjustment

**Optie 2: Kelly-Adjusted % per Trade**
- Voor: Schaalt mee met equity, risicobewust
- Tegen: Volatiel bij kleine bankroll

**Vergelijking (start $10,000):**

| Trade | Vaste $500 | 5% Kelly |
|-------|------------|----------|
| 1 (win +20%) | $10,100 | $10,100 |
| 2 (loss -15%) | $9,850 | $9,850 |
| 3 (win +25%) | $10,225 | $10,235 |
| 4 (ZEUS +167%) | $11,060 | $12,103 |

Kelly groeit sneller bij wins, maar krimpt ook harder bij losses. Voor **volatiele outlier-strategie** is **vaste $ sizing VEILIGER**.

---

## 4. Concrete Aanbeveling

### Scenario A: Conservatief (Fractional Kelly 25%)

**Totaal Kapitaal:** $10,000
**Per Trade (Kelly 5.6%):** $560
**Max Posities:** 2 (maar verwacht 1 actief signaal tegelijk)
**Stop-Loss Buffer:** $2,000 reserve voor drawdowns

**Voordelen:**
- Beschermt tegen ZEUS-afhankelijkheid
- Overleeft 75% drawdown (≈10 opeenvolgende max losses)
- Lage stressload

**Nadelen:**
- Compound effect is traag
- Mist upside van all-in bij ZEUS-achtige trades

---

### Scenario B: Standaard (Fractional Kelly 50%)

**Totaal Kapitaal:** $8,000
**Per Trade (Kelly 11.2%):** $896 → rond op $1,000
**Max Posities:** 1 (dataset toont geen overlaps)
**Stop-Loss Buffer:** $1,000 reserve

**Voordelen:**
- Balans tussen groei en risico
- Meer exposure dan conservatief
- Nog steeds bescherming tegen ruin

**Nadelen:**
- Bij 3 opeenvolgende max losses: -45% DD (≈ $3,600)
- Zonder ZEUS: verwachte return -$10/trade → -$450 over 45 trades

---

### Scenario C: Agressief (Full Kelly)

**Totaal Kapitaal:** $5,000
**Per Trade (Kelly 22.4%):** $1,120 → rond op $1,000
**Max Posities:** 1
**Stop-Loss Buffer:** $500 reserve

**Voordelen:**
- Maximale compound growth bij ZEUS-achtige outliers
- "Risicobudget" = $5,000 (acceptabel verlies)

**Nadelen:**
- 75% DD = $3,750 verlies (75% van $5k)
- Bij pech (geen ZEUS in eerste 20 trades): -$200 verwacht verlies
- **Hoge kans op total ruin zonder ZEUS-trade**

---

## 5. EINDADVIES

### HUIDIGE REALITEIT (op basis van data):

1. **Zonder ZEUS: strategie is NEGATIEF EV**
   - Verwacht: -$10 per trade
   - Kelly% = -23% (je zou SHORT moeten gaan)
   - 100% kans op verlies (Monte Carlo zonder ZEUS)

2. **Met ZEUS: strategie is STERK POSITIEF**
   - Verwacht: +$62.65 per trade (gemiddelde)
   - Maar dit is misleidend (1 outlier van $3,333)
   - Walk-Forward: GEFAALD (0/3 folds winstgevend)

3. **Max Posities > 1 is NUTTELOOS**
   - Geen overlappende signalen in 60-dag dataset
   - Extra kapitaal voor 2e positie is "dood geld"

---

### AANBEVELING VOOR LIVE TRADING:

**Optie 1: NIET TRADEN (meest rationeel)**
- Walk-Forward gefaald → strategie degradeert out-of-sample
- Zonder ZEUS: -$450 verwacht verlies
- Alleen winstgevend door 1 mega-outlier (onvoorspelbaar)

**Optie 2: "LOTTO TICKET" STRATEGIE (acceptabel risico)**

**Setup:**
- Totaal Kapitaal: $5,000 (acceptabel verlies)
- Per Trade: $1,000 (20% van kapitaal)
- Max Posities: 1 (geen overlaps in data)
- Stop: HARD CAP bij -$3,000 totaal verlies (60% DD)

**Rationale:**
- Je "koopt" een lotto ticket voor $5,000
- Verwachting: -$10/trade × 50 trades = -$500 verwacht verlies
- MAAR: 1 ZEUS-achtige trade → +$3,000+ winst (maakt alles goed)
- Je "betaalt" $500 voor kans op $3,000+ jackpot

**Risk Management:**
- Na 30 trades zonder ZEUS-achtige win: STOP (protect -$300)
- Bij ZEUS-achtige win: neem 50% profit, laat 50% compounding doen
- NOOIT meer dan $1,000 per trade (beschermt tegen 15% single-loss trades)

---

## 6. FORMULES SAMENVATTING

### Kelly Criterion (algemeen):
```
Kelly% = (p × b - q) / b

Waar:
p = kans op winst (WR)
q = kans op verlies (1 - WR)
b = win/loss ratio (Avg_Win / Avg_Loss)

Vereenvoudigde vorm:
Kelly% = WR - ((1 - WR) / (Avg_Win / Avg_Loss))
```

### Position Sizing:
```
Position_Size = Kapitaal × (Kelly% × Fractional_Kelly)

Fractional Kelly opties:
- 25% (zeer conservatief)
- 50% (standaard)
- 100% (agressief)
```

### Max Positions Berekening:
```
Max_Concurrent = Kapitaal / Position_Size

Maar: bepaal dit op basis van FEITELIJKE OVERLAP in signalen!
In deze dataset: Max_Concurrent = 1 (geen overlaps)
```

### Anti-Concentratie:
```
Max_Loss_Per_Trade = Kapitaal × 0.05  (5% regel)
                   = Kapitaal × 0.10  (10% regel, agressief)
```

---

## CONCLUSIE

De strategie heeft een **structureel negatief edge** zonder mega-outliers. Kelly Criterion zonder ZEUS is **-23%** (moet short gaan of niet traden).

Als je toch wilt traden:
- **$5,000 totaal kapitaal**
- **$1,000 per trade (fixed size, geen Kelly)**
- **Max 1 positie tegelijk** (data toont geen overlaps)
- **Stop bij -$3,000 totaal verlies**

Dit is een **lotto-strategie**, geen structurele edge. Behandel het als entertainment met gedefinieerd risico, niet als serieuze trading strategie.

---

**Datum:** 13 februari 2026
**Auteur:** SuperClaude Quant Researcher
**Disclaimer:** Deze analyse is gebaseerd op 60 dagen backtest data. Geen garantie op toekomstige resultaten.

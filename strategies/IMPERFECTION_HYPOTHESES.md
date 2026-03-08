# Marktimperfectie Hypotheses — Ontwerpfase Q1 2026

> **Methodiek**: ADR-LAB-001 — marktimperfecties eerst, goedkoopste test eerst, stoppen bij falen.
> **Context**: MEXC SPOT, $10-25K account, 0% maker fee, bestaande infra (4H + 1m).
> **Datum**: 2026-03-07

---

## Tier 1 — Testbaar met bestaande data (≤2 uur per hypothese)

### H1: Weekend-momentum op ms_018

**Mechanisme**: Institutionele market makers verminderen activiteit in het weekend. Minder liquidity → momentum persisteert langer → dips zijn dieper en bounces sterker. Academisch bewijs (2025): altcoin dagrendement weekend 0.0041 vs weekdag 0.0019 (2.15x verschil).

**Wanneer het werkt**: Bull- en zijwaartse markten. Effect zwakker in diepe bear markets. Sterkst voor altcoins (niet BTC).

**Goedkoopste falsificatie**: Split bestaande ms_018 backtest-trades per dag-van-de-week. Bereken PF weekend (vr 20:00 – zo 24:00 UTC) vs doordeweeks. Als PF-weekend ≤ PF-doordeweeks → verwerpen, stoppen. Geschatte effort: 1 uur code, 0 nieuwe data.

**Wat we al weten**: Sprint 2 testte cross-sectional momentum als standalone entry (PF=0.81), maar als FILTER op ms_018 is het niet getest.

---

### H2: Time-of-day entry kwaliteit

**Mechanisme**: Crypto vertoont uitgesproken intraday patronen ondanks 24/7 markt. Piek volume/volatiliteit 16:00-17:00 UTC (US+EU overlap). Bid-side imbalance verdubbelt in de tweede 12 uur (+1.54% vs +3.18%). Limit buys in Aziatische sessie krijgen betere fills.

**Wanneer het werkt**: Altijd — gedreven door wereldwijde tijdzone-verschillen en institutionele handelsuren. Structureel.

**Goedkoopste falsificatie**: Split ms_018 trades per 4H candle starttijd (00, 04, 08, 12, 16, 20 UTC). Vergelijk PF per venster. Als PF vlak over alle vensters → verwerpen. Effort: 1 uur, bestaande data.

---

### H3: Liquiditeits-quintiel amplificatie

**Mechanisme**: Academisch bewijs (2025): 13/14 crypto-anomalieën produceren hogere rendementen in lage-liquiditeitsgroepen. 9/14 statistisch significant. Minder liquide coins hebben grotere mispricings die langer duren (minder arbitrage-druk).

**Wanneer het werkt**: Coins met laag gemiddeld dagvolume. Tradeoff: meer edge per trade maar lagere capaciteit. Met $10-25K account ben je klein genoeg om dit te exploiteren.

**Goedkoopste falsificatie**: Stratificeer ms_018 resultaten per coin naar gemiddeld dagvolume (5 quintielen). Als PF monotoon dalend van laag-volume naar hoog-volume → effect aanwezig. Als vlak → verwerpen. Effort: 2 uur, bestaande data.

**Wat we al weten**: ms_018 draait op 487 coins (Kraken). MEXC universe is 3000+. Liquiditeitseffect zou verklaren waarom meer coins soms helpt en soms niet.

---

### H4: Volatility-clustering positie-sizing (vol_scale op ms_018)

**Mechanisme**: Crypto volatiliteit is sterk persistent (GARCH beta >0.7). Na een rustige periode kan je grotere posities nemen (lager risico per unit). Na een vol-shock moet je krimpen. Dit genereert geen entries maar sizet ze correct.

**Wanneer het werkt**: Altijd — wiskundige eigenschap van financiële rendementen, geen gedragsedge. Niet afhankelijk van marktregime.

**Goedkoopste falsificatie**: Pas bestaande Sprint 4 vol_scale wrapper (ATR14, pctl=25) toe op ms_018 raw trades. Vergelijk DD-reductie vs PF-impact. Infra bestaat al. Effort: 2 uur. Als DD niet daalt OF PF daalt >20% → verwerpen.

**Wat we al weten**: Op Sprint 4 config 042: DD 31.8%→20.3%, PF behouden. Op config 041: vol_scale degradeerde bootstrap (0.92→0.83). Effect is config-afhankelijk — moet apart getest worden op ms_018.

---

## Tier 2 — Nieuwe data nodig, bestaande infra (½-1 dag per hypothese)

### H5: Post-liquidatie cascade bounce

**Mechanisme**: Leveraged liquidaties op futures duwen spot-prijs onder fundamentele waarde. Geforceerde verkoop creëert tijdelijke supply/demand imbalance. Wanneer de cascade uitgeput raakt (OI daalt >15%, funding flipt negatief), revert de prijs. Voorbeeld: oktober 2025 crash — $19B OI geliquideerd in 36 uur, $3.21B in 60 seconden.

**Wanneer het werkt**: Na grote liquidatie-events (>$500M/24h). Herstel over uren tot weken, past bij 4H timeframe. NIET bij regime-veranderingen (crypto winter).

**Goedkoopste falsificatie**: Pull historische liquidatie-data via CoinGlass API (gratis). Definieer "cascade events" (magnitude >$500M/24h OF >$200M/4h). Meet spot-rendementen op T+1h, T+4h, T+24h, T+72h na cascade-piek. Vergelijk met random entry. Als post-cascade rendementen niet significant beter → verwerpen. Effort: ½ dag (nieuwe API, eenvoudige analyse).

**Waarom interessant**: Maps direct naar bestaande 4H spot infra. Signal (liquidatie magnitude) is gratis. Entry (spot limit buy op MEXC, 0% maker) is goedkoop. Tijdframe (4H-dagelijks) past bij ms_018 infrastructure.

---

### H6: Funding rate als regime-filter

**Mechanisme**: Wanneer perpetual funding rates extreem positief zijn (longs betalen shorts), signaleert dit overleveraged longs. Voorspelbare deleveraging-druk volgt: longs worden gesqueezed, cascading liquidations duwen spot naar beneden, daarna reversal. Je tradedt niet futures — je gebruikt funding rate als SIGNAL om spot entries te timen.

**Wanneer het werkt**: Funding rate >0.1% per 8h op Binance/Bybit perps, gecombineerd met OI op lokale highs. Sterkst voor mid-cap altcoins.

**Goedkoopste falsificatie**: Collect funding rate data (CoinGlass/Binance API, gratis). Definieer "extreme funding" events (top 5% van 8h rates). Als forward 4H-72H returns na extreme funding niet significant verschillen van random → verwerpen. Effort: ½ dag.

**Relatie tot H5**: H5 en H6 meten hetzelfde fenomeen (leverage unwind) vanuit twee invalshoeken. Als H5 faalt, faalt H6 waarschijnlijk ook.

---

## Tier 3 — Nieuwe infra nodig (1-2 dagen per hypothese)

### H7: On-chain whale accumulatie regime-filter

**Mechanisme**: Whales (10-10.000 BTC equivalent) accumuleren voordat prijzen bewegen. Late 2025: whales accumuleerden 56.227 BTC terwijl retail verkocht. Divergentie tussen whale accumulatie en retail selling is een leading indicator.

**Wanneer het werkt**: Wanneer whale accumulatie in top kwartiel EN retail sentiment negatief (Fear & Greed <30). Setup voor mean reversion na retail capitulatie.

**Goedkoopste falsificatie**: CryptoQuant free tier. Definieer "whale accumulation" events (netto instroom >2σ boven gemiddelde). Meet forward 7/14/30d rendementen. Als niet significant beter dan baseline → verwerpen. Effort: 1 dag (nieuwe API + analyse).

**Bruikbaarheid**: Niet als entry-signal. Als macro regime-filter of positie-sizing input: "meer risico nemen wanneer whales accumuleren, minder wanneer ze distribueren."

---

### H8: Cross-sectional momentum als filter op ms_018

**Mechanisme**: Momentum (koop winnaars, vermijd verliezers over afgelopen 2 weken) is een van de sterkste anomalieën in crypto. Sharpe >1 over 500+ coins. Sterker in lage-liquiditeitsgroepen. ms_018 IS al een momentum-signal (BoS bevestigt trendshift), maar cross-sectional ranking zou noise-coins kunnen wegfilteren.

**Wanneer het werkt**: Coins die al in opwaartse trend zitten vóór het ms_018 signal. Filtert false signals in coins die structureel dalen.

**Goedkoopste falsificatie**: Bereken 14-daags momentum per coin. Neem alleen ms_018 entries in top 50% momentum-quintiel. Vergelijk PF met ongefilterd. Effort: ½ dag (herbruikbare Sprint 2 infra: `strategies/4h/sprint2/market_context.py`).

**Wat we al weten**: Sprint 2 testte momentum als ENTRY (PF=0.81, NO-GO). Maar als FILTER op een sterkere entry is het niet getest.

---

## Testplan — Volgorde per ADR-LAB-001

| # | Hypothese | Data | Effort | Falsificatie-criterium |
|---|-----------|------|--------|------------------------|
| 1 | H1: Weekend filter | Bestaand | 1 uur | PF-weekend ≤ PF-doordeweeks |
| 2 | H2: Time-of-day | Bestaand | 1 uur | PF vlak over alle 4H vensters |
| 3 | H3: Liquiditeits-quintiel | Bestaand | 2 uur | PF vlak over volume-quintielen |
| 4 | H4: Vol_scale ms_018 | Bestaand | 2 uur | DD niet lager OF PF daalt >20% |
| 5 | H5: Cascade bounce | Nieuwe API | ½ dag | Post-cascade returns = random |
| 6 | H8: Momentum filter | Hergebruik | ½ dag | Gefilterd PF ≤ ongefilterd PF |
| 7 | H6: Funding rate | Nieuwe API | ½ dag | Post-extreme returns = random |
| 8 | H7: Whale accumulatie | Nieuwe API | 1 dag | Accumulatie-events = baseline |

**Stopcriterium**: Elk item dat de falsificatie niet overleeft → stoppen, door naar volgende. Items die overleven → combinatie-test (H1+H2+H3 als multi-filter op ms_018).

**Totale effort Tier 1**: ~6 uur. Tier 2: ~1.5 dag. Tier 3: ~2 dagen.

---

## Wat NIET in scope is

- **Futures/leverage**: Niet beschikbaar, account te klein voor risico
- **Memecoin listing trading**: Niet systematisch backtestbaar, insider-edge nodig
- **OBI microstructure (sub-second)**: Te hoog-frequent voor huidige infra
- **Social sentiment signals**: Data te duur/beperkt voor robuuste backtest

## Relatie tot bestaande strategieën

- **ms_018 (LIVE)**: H1-H4 en H8 zijn FILTERS/OVERLAYS op ms_018, geen vervanging
- **Scalp FVG (LIVE)**: H2 (time-of-day) zou ook op scalp getest kunnen worden
- **DualConfirm (Kraken)**: H5/H6 (cascade/funding) zijn onafhankelijke entry-signals

## Bronnen

Gebaseerd op academisch onderzoek 2024-2025:
- Weekend momentum: ACR Journal 2025
- Liquiditeits-amplificatie: ScienceDirect 2022 (crypto anomalies + liquidity)
- Cascade mechanica: SSRN 5611392 (Oct 2025 crash anatomy)
- Intraday patronen: Amberdata 2025 (rhythm of liquidity)
- Volatility clustering: Springer 2025 (GARCH-family crypto)
- Momentum anomalie: ScienceDirect 2024 (lasso-type factor model)

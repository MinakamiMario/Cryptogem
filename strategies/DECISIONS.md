# ADR-LAB-001: Research Integrity Principles

**Datum**: 2026-03-06
**Status**: ACCEPTED
**Aanleiding**: MS-018 post-mortem — strategie live gedeployed die bij grondige toetsing 0/5 tests passeerde

---

## Principes

### 1. Elke strategie moet falsifieerbaar zijn
Een strategie die niet weerlegd kán worden, is geen strategie. Definieer vooraf welk bewijs de strategie zou ontkrachten.

### 2. Edge moet out-of-sample aantoonbaar zijn
In-sample performance bewijst niets. Winst moet reproduceerbaar zijn op data die niet gebruikt is bij het ontwerp.

### 3. Coin-selectie moet voorspellend zijn
Als een strategie niet blind werkt en coin-selectie vereist, moet die selectie aantoonbaar persistent zijn: coins die je vandaag selecteert moeten morgen ook winnen.

### 4. Goedkoopste test eerst
De snelste, goedkoopste test die een strategie kan falsificeren, hoort als eerste te draaien — niet als laatste.

### 5. Valideer op de exchange waarop je tradedt
Backtest-resultaten op exchange A zijn geen bewijs voor performance op exchange B. Data, fees, en microstructuur moeten matchen.

---

## Toepassing

Deze principes geven richting aan het bewijs dat nodig is voor een GO-beslissing. Ze schrijven geen vaste volgorde of methode voor — het team bepaalt per strategie welke toetsen het meest informatief zijn, zolang de principes gedekt worden.

## Context

Zie `reports/lab/strategy_review_001_ms018_verdict.md` voor het volledige MS-018 dossier.

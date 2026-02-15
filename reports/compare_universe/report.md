# Universe Comparison: ALL vs HALAL
Generated: 2026-02-14 23:56 CET
ALL universe: 884 coins (hash: `0bd301f2488b`)
HALAL universe: 281 coins (hash: `0bd301f2488b`)

## Side-by-Side Summary

| Config | Universe | Tr | P&L | WR | DD | PF | WF | Fric 2x+20 | MC ruin | Jitter | Univ | Top1% | Verdict |
|--------|----------|-----|------|-----|-----|-----|-----|------------|---------|--------|------|-------|---------|
| C1_TPSL_RSI45 | ALL (884c) | 34 | $1192 | 58.8% | 32.2% | 1.39 | 4/5 | $332 | 4.4% | 82.0% | 3/4 | 10% | 🟢 GO |
| C1_TPSL_RSI45 | HALAL (281c) | 19 | $712 | 57.9% | 23.4% | 1.57 | 4/5 | $276 | 0.0% | 96.0% | 4/4 | 18% | 🟢 GO |

## Delta Analysis (ALL vs HALAL)

| Config | Metric | ALL | HALAL | Delta | Impact |
|--------|--------|-----|-------|-------|--------|
| C1_TPSL_RSI45 | Trades | 34 | 19 | +15 | meer sample |
| | P&L | $1192 | $712 | $+480 | beter |
| | WR | 58.8% | 57.9% | +0.9% | beter |
| | DD | 32.2% | 23.4% | +8.8% | meer risico |
| | WF | 4/5 | 4/5 | | gelijk |
| | Verdict | GO | GO | | ✅ consistent |

## Conclusie

- **C1_TPSL_RSI45**: 🟢 GO op beide universes — strategie is universe-agnostisch

## Interpretatie

De strategie presteert consistent op zowel het volledige (ALL) als het halal-gefilterde universum. Dit wijst op **generaliseerbaarheid**: de edge is niet afhankelijk van een specifieke coinset.

Mismatch risico: backtest op ALL terwijl live HALAL draait kan leiden tot 
overschatting. Als HALAL-only resultaten significant afwijken, overweeg 
de backtest te herdraaien met `--universe halal` als primary validation.
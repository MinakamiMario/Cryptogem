# Cache Comparison: RESEARCH_ALL vs LIVE_CURRENT
Generated: 2026-02-15 00:50 CET
RESEARCH_ALL: 2086 coins (hash: `a68399c0da2e`)
LIVE_CURRENT: 523 coins (hash: `3b1dba2eeb4d`)

## Side-by-Side Summary

| Config | Universe | Tr | P&L | WR | DD | PF | WF | Fric 2x+20 | MC ruin | Jitter | Univ | Top1% | Verdict |
|--------|----------|-----|------|-----|-----|-----|-----|------------|---------|--------|------|-------|---------|
| C1_TPSL_RSI45 | RESEARCH_ALL (2086c) | 45 | $529 | 51.1% | 40.8% | 1.14 | 3/5 | $-334 | 37.5% | 26.0% | 2/4 | 12% | 🔴 NO-GO |
| C1_TPSL_RSI45 | LIVE_CURRENT (523c) | 30 | $3746 | 70.0% | 27.9% | 3.31 | 4/5 | $2370 | 0.0% | 98.0% | 4/4 | 17% | 🟢 GO |

## Delta Analysis

| Config | Metric | RESEARCH_ALL | LIVE_CURRENT | Delta | Impact |
|--------|--------|-----|------|-------|--------|
| C1_TPSL_RSI45 | Trades | 45 | 30 | +15 | meer sample |
| | P&L | $529 | $3746 | $-3217 | slechter |
| | WR | 51.1% | 70.0% | -18.9% | slechter |
| | DD | 40.8% | 27.9% | +12.9% | meer risico |
| | WF | 3/5 | 4/5 | | verschil! |
| | Verdict | NO-GO | GO | | VERSCHIL! |

## Conclusie

- **C1_TPSL_RSI45**: NO-GO op RESEARCH_ALL maar GO op LIVE_CURRENT — extra coins in RESEARCH_ALL verwateren performance

## Interpretatie

Er zijn **verschillen** tussen RESEARCH_ALL en LIVE_CURRENT resultaten. Check per config welke cache de edge levert en of de universes aansluiten.

RESEARCH_ALL en LIVE_CURRENT bevatten mogelijk verschillende coinsets. 
Als RESEARCH_ALL significant beter presteert, overweeg de LIVE_CURRENT pool uit te breiden. 
Als LIVE_CURRENT beter presteert, verwateren de extra coins in RESEARCH_ALL de edge.
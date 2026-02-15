# Coin Attribution Analysis

**Config C1**: `{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45, "sl_pct": 15, "time_max_bars": 15, "tp_pct": 15, "vol_confirm": true, "vol_spike_mult": 3.0}`
**Runtime**: 402.9s

## RESEARCH_ALL Universe

- **Total coins**: 2090
- **Coins with trades**: 44
- **Positive coins**: 22 | **Negative coins**: 22
- **Backtest**: 45 trades | P&L $+529 | WR 51.1% | DD 40.8% | PF 1.14

### Top 10 Winners
| # | Coin | Trades | Total P&L | WR% | Avg P&L | MEXC-only? |
|---|------|--------|-----------|-----|---------|------------|
| 1 | MF/USD | 2 | $+552.32 | 100.0% | $+276.16 | no |
| 2 | CHESS/USD | 1 | $+325.83 | 100.0% | $+325.83 | YES |
| 3 | ZEUS/USD | 1 | $+325.74 | 100.0% | $+325.74 | no |
| 4 | CLUB/USD | 1 | $+319.65 | 100.0% | $+319.65 | YES |
| 5 | HMND/USD | 1 | $+315.16 | 100.0% | $+315.16 | YES |
| 6 | B3/USD | 1 | $+315.07 | 100.0% | $+315.07 | no |
| 7 | WCT/USD | 1 | $+301.46 | 100.0% | $+301.46 | no |
| 8 | GHIBLI/USD | 1 | $+282.41 | 100.0% | $+282.41 | YES |
| 9 | LOCK/USD | 1 | $+279.32 | 100.0% | $+279.32 | YES |
| 10 | DYM/USD | 1 | $+246.77 | 100.0% | $+246.77 | no |

### Top 10 Destroyers (most negative first)
| # | Coin | Trades | Total P&L | WR% | Avg P&L | MEXC-only? |
|---|------|--------|-----------|-----|---------|------------|
| 1 | SNIFT/USD | 1 | $-413.28 | 0.0% | $-413.28 | YES |
| 2 | MOCHI/USD | 1 | $-399.74 | 0.0% | $-399.74 | YES |
| 3 | COQ/USD | 1 | $-399.63 | 0.0% | $-399.63 | YES |
| 4 | MASA/USD | 1 | $-382.87 | 0.0% | $-382.87 | YES |
| 5 | BERA/USD | 1 | $-379.33 | 0.0% | $-379.33 | no |
| 6 | AKE/USD | 1 | $-366.61 | 0.0% | $-366.61 | no |
| 7 | HAIO/USD | 1 | $-323.60 | 0.0% | $-323.60 | YES |
| 8 | EAT/USD | 1 | $-313.00 | 0.0% | $-313.00 | no |
| 9 | MORE/USD | 1 | $-309.85 | 0.0% | $-309.85 | YES |
| 10 | AI3/USD | 1 | $-146.10 | 0.0% | $-146.10 | no |

### Exclusion Test Results
| Scenario | Trades | P&L | WR% | DD% | PF |
|----------|--------|-----|-----|-----|-----|
| Full RESEARCH_ALL | 45 | $+529 | 51.1% | 40.8% | 1.14 |
| Excl. top 10 destroyers | 41 | $+7,459 | 61.0% | 17.9% | 4.64 |
| Excl. top 25 destroyers | 40 | $+7,741 | 70.0% | 27.8% | 3.80 |

**Exclusion impact**:
- Excl. 10: P&L delta $+6,930, WR delta +9.9pp
- Excl. 25: P&L delta $+7,213, WR delta +18.9pp
- **Does excluding destroyers restore edge?** JA (WR>60%: JA, P&L significantly higher: JA)

## LIVE_CURRENT Universe

- **Total coins**: 526
- **Coins with trades**: 28
- **Backtest**: 30 trades | P&L $+3,746 | WR 70.0% | DD 27.9%
- **Top 1 coin share**: MF/USD = 16.9% of profit
- **Top 3 coins share**: 43.0% of total profit

### Leave-One-Out (Top 5 coins)
| Coin | Coin P&L | Without P&L | Delta | Without Trades | Without WR% |
|------|----------|-------------|-------|----------------|-------------|
| MF/USD | $+907.53 | $+1,708 | $-2,038 | 29 | 65.5% |
| B3/USD | $+786.47 | $+3,412 | $-333 | 29 | 69.0% |
| XCN/USD | $+616.68 | $+3,664 | $-82 | 29 | 69.0% |
| ZEUS/USD | $+538.87 | $+3,020 | $-725 | 29 | 69.0% |
| DYM/USD | $+475.96 | $+3,262 | $-483 | 29 | 72.4% |

## Venue Breakdown
| Venue | Coins w/ Trades | Winners | Destroyers | Total P&L | Trades | Avg P&L/trade |
|-------|-----------------|---------|------------|-----------|--------|---------------|
| MEXC-only | 26 | 12 | 14 | $-213 | 26 | $-8.18 |
| Kraken | 18 | 10 | 8 | $+741 | 19 | $+39.00 |

## Conclusie

**MEXC long-tail verwatert edge door strategie-mismatch? JA**

MEXC P&L: $-213 (26tr avg$-8.18), Kraken P&L: $+741 (19tr avg$+39.00)

De MEXC-only coins dragen negatief bij aan het totaalresultaat.
De strategie presteert beter op Kraken-coins dan op de MEXC long-tail.
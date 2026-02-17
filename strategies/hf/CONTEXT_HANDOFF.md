> **🔒 PROJECT CLOSED** (2026-02-17) — This document is frozen.
> Closure: MEXC validated; Bybit real-VWAP definitive NO-GO; portability disproven.
> Tag: `hf-part2-closed-v1`

# HF Part 2 — Context Handoff voor Nieuwe Sessie

## Executive Summary
- Signal: H20 VWAP_DEVIATION v5 (dev=2.0, tp=8, sl=5, tl=10)
- Alternative: sl7 (sl=7) — iets robuuster bij taker costs
- Strategy universe: 295 coins (96 T1 + 199 T2, excl 21 net-negative)
- OB sampling set: 42 coins (20 T1 + 20 T2 + BTC + ETH) — cost regimes gemeten, toegepast op 295
- Exchange: MEXC SPOT
- Execution: MAKER LIMIT ORDERS (bevestigd via 19,500 live OB snapshots)
- Status: CONDITIONAL GO (ADR-HF-034) | PROJECT CLOSED (2026-02-17)

## ⚠️ Fee Structuur — EXACTE WAARDEN

### MEXC SPOT fees (bron: mexc.com/fee + VIP screenshot)
| Product | Maker | Taker | Bron |
|---------|-------|-------|------|
| SPOT (standaard per VIP screenshot) | **0%** | **0.05% = 5 bps** | User-geverifieerd |
| SPOT (met MX token holding) | **0%** | **0.04% = 4 bps** | User-geverifieerd |
| SPOT (in costs_mexc_v2.py code) | 0 bps | **10 bps** | Code-hardcoded |

**DISCREPANTIE**: Code gebruikt 10bps taker, werkelijk is 4-5bps (afhankelijk van MX token holding). De backtests zijn CONSERVATIEF — werkelijke kosten zijn 2-2.5x lager. Dit is bewust niet aangepast (veiligheidsmarge).

### Kostendecompositie: exchange_fee vs total_per_side_bps
| Component | Definitie | Voorbeeld (taker_p50, T1) |
|-----------|-----------|---------------------------|
| `exchange_fee_bps` | Fee-only (naar exchange) | 10.0 bps |
| `spread_bps` | Half-spread (half van bid-ask) | 5.2 bps |
| `slippage_bps` | Book walk impact ($200 notional) | 16.7 bps |
| `adverse_selection_bps` | (alleen maker: spread × 0.3) | 0 (taker) |
| **`total_per_side_bps`** | **ALL-IN → dit gaat naar harness** | **31.9 bps** |

**Cruciale regel**: Harness ontvangt ALLEEN `total_per_side_bps / 10000` als `fee`. Geen aparte componenten. Geen double-counting.

## Universe vs Sampling Set

| Concept | Omvang | Doel |
|---------|--------|------|
| **Strategy universe** | 295 coins (96 T1 + 199 T2) | Backtests draaien op alle 295 |
| **OB sampling set** | 42 coins (20 T1 + 20 T2 + BTC + ETH) | Orderbook data verzamelen om cost regimes te meten |
| **Regime toepassing** | 295 coins | Gemeten T1/T2 regimes worden PER TIER toegepast op alle 295 coins |

Sampling logica: 10 alphabetisch + 10 random(seed=42) per tier. BTC/ETH als referentie.

## Gemeten Orderbook Kosten (19,500 snapshots, ~2.5h)

| Regime | Exec Mode | T1 total_bps | T2 total_bps | Status |
|--------|-----------|--------------|--------------|--------|
| maker_p50 | limit | 3.1 | 4.1 | ✅ ALL PASS |
| maker_p90 | limit | 29.2 | 11.4 | ✅ ALL PASS |
| taker_p50 | market | 31.9 | 29.9 | ⚠️ sl7 passes, v5 borderline |
| taker_p90 | market | 214.2 | 100.2 | ❌ CATASTROPHAAL |

## 24-Backtest Matrix (14/24 PASS)
- Alle 12 maker combinaties PASS (PF=2.86-3.38, DD≤9.5%, WF=5/5)
- Taker P50 marginaal (sl7 passes $200/$500, v5 fails G8 op $200)
- Taker P90 catastrophaal (PF<1.0, negatieve verwachting)

### Fill model assumption
In de rerun is de maker fill-model NIET penaliserend — bar-structure toont 100% fill bij deze lage kosten. **Dit is een assumption, NIET een live-garantie.** Live fill tracking (queue positie, adverse selection) is een open punt voor paper trading.

## STRICT Gates (7 gates — G7 excluded)

| Gate | Metric | Threshold | Waarom |
|------|--------|-----------|--------|
| G1 | Trades/week | ≥ 10 | Throughput minimum |
| G2 | Max gap | ≤ 2.5 dagen | Continuïteit |
| G3 | Exp/week (market) | > $0 | Winstgevendheid |
| G4 | Exp/week (stress 2x) | > $0 | Stressbestendigheid |
| G5 | Max drawdown | ≤ 20% | Risicolimiet |
| G6 | Walk-forward folds | ≥ 4/5 positief | OOS validatie |
| G8 | Top-1 fold concentratie | < 35% | Geen outlier-afhankelijkheid |

**G7** (neighbor stability ≥ 8/12) zit in de scoreboard maar is NIET in de STRICT runner (`evaluate_gates_strict()`). Daarom rapporteert de 24-combo runner "7/7", niet "8/8".

## Known Gotchas / Data Quality

### MEXC OB data (mexc_sanity_001.md)
- **39/42 coins** aanwezig (3 missen — dynamisch geselecteerd via alphabetisch+random, exacte 3 niet gespecificeerd in rapport). Non-blocking.
- T1 depth ($8K) < T2 depth ($12K) — inversie, tier ≠ depth ranking. Non-blocking.
- T1 slippage non-monotoon ($200 > $500) door survivorship bias: 20.46% None-rate bij $2000 (depth shortfall). Non-blocking.
- Extreme spreads: 3.49% van snapshots (outliers, niet structureel).
- BTC referentie: median 0.05 bps, P90 0.82 bps — zeer schoon.

### Slippage verificatie (mexc_slippage_verification_001.md)
- 9/9 handmatige book walks: **0.00 bps delta** (exacte match).
- Synthetisch orderbook test: exact match (100.25 bps).

### Anti-double-counting (regime_decomposition_001.json)
- 12/12 component sums match (delta = 0.0).
- register_regime() assertions werken correct.

## Sleutelbestanden

### Part 2 Infrastructuur (strategies/hf/screening/)
| Bestand | Functie |
|---------|---------|
| orderbook_collector.py | Live OB snapshot daemon (CCXT, enableRateLimit=True, 50ms sleep tussen coins) |
| orderbook_analysis.py | Distributions + regime builder (CLI: --input, --output-dir, --label) |
| fill_model_v3.py | Bar-structure fill model — pure filtering, NOOIT cost deduction |
| test_fill_model_v3.py | 16 unit tests |
| run_part2_measured_cost_rerun.py | 24-combo runner (CLI: --config, --measured-report, --dry-run) |
| costs_mexc_v2.py | MEXC cost model + register_regime() met anti-double-count asserts |
| harness.py | **READ-ONLY** — screening backtest engine |

### Part 2 Tracking (reports/hf/)
| Bestand | Functie |
|---------|---------|
| part2_scoreboard.md | Gate status per kandidaat (8/8 gates incl G7, vs 7/7 STRICT) |
| part2_backlog.md | Priority queue + completed cycles 1-10 |
| part2_teamlog.md | Cycle-by-cycle execution log |

### Part 2 ADRs (in strategies/hf/DECISIONS.md)
| ADR | Titel | Status |
|-----|-------|--------|
| HF-030 | GO/NO-GO throughput validation | CONDITIONAL GO |
| HF-031 | Full 316-coin universe | CONDITIONAL HALT |
| HF-032 | Universe reduction 295 coins | APPROVED |
| HF-033 | P0 data assembly audit + cost measurement | GO MAINTAINED |
| HF-034 | Measured OB 24-backtest rerun | GO MAINTAINED (maker) |

### Part 2 Rapportages (reports/hf/)
- part2_measured_cost_rerun_001.{json,md} — LATEST: 24-combo resultaten
- mexc_orderbook_costs_001.{json,md} — OB spread/slippage analyse
- mexc_sanity_001.md — data quality checks
- mexc_slippage_verification_001.md — slippage walk verificatie
- regime_decomposition_001.json — anti-double-count bewijs
- 50+ eerdere part2_*.{json,md} rapporten van Cycles 1-9

## Architectuur

### Measurement Pipeline
```
orderbook_collector.py → mexc_orderbook_001.jsonl (JSONL, gitignored)
  ↓
orderbook_analysis.py → compute_distributions() → build_measured_regimes()
  ↓
costs_mexc_v2.py::register_regime() → anti-double-count assert
  ↓
run_part2_measured_cost_rerun.py → 24 backtests → reports/hf/part2_measured_cost_rerun_001.{json,md}
```

### Key Constraints
- harness.py is READ-ONLY — fee formula: `fees = pos.size_usd * fee + (pos.size_usd + gross) * fee`
- signal_fn protocol: returns {stop_price, target_price, time_limit, strength}
- BTC/USD MUST be in market context coin list
- Kraken is structureel niet-winstgevend voor 1H (ADR-HF-027)
- Part 2 code mag NIET gemixed worden met trading_bot/ (4H DualConfirm)

## Multi-Exchange Exploratie — Volgende Stap

> **CANCELLED** (ADR-HF-035/036/037): Bybit validation proved signal is NOT portable.
> Remaining exchanges deprioritized. Infrastructure reusable if new signal family emerges.

### Doel
Test H20 VWAP_DEVIATION op exchanges met:
- Meer coins (>500), meer volume/liquiditeit
- Vergelijkbare of betere fee-structuren
- Coins hoeven NIET te matchen tussen exchanges — maximale coverage per exchange

### Sampling Policy (KRITIEK voor schaalbare collectie)

| Categorie | Coins | Interval | Rationale |
|-----------|-------|----------|-----------|
| Top 100 op volume | 100 | 10s | Hoge liquiditeit, primaire universum |
| Top 101-300 | 200 | 30s | Mid-cap, voldoende granulariteit |
| Long tail (301+) | rest | 60-180s round-robin | Coverage zonder rate-limit druk |

**Rate-limit veiligheid**:
- CCXT `enableRateLimit=True` als basis
- Extra politeness sleep (50-100ms per request)
- Exchange-specifieke limits opzoeken vóór collectie start
- Coverage report genereren: coins per uur, gaps, None-rates
- Exponential backoff bij errors (1s → 2s → 4s, max 30s)

### Methodologie Template (per exchange)
1. **Fee research**: Werkelijke fee per VIP level + bron vastleggen
2. **Coin universe**: Alle SPOT pairs ophalen, filteren op volume/coverage
3. **Tiering**: T1/T2/T3 op basis van volume, capacity, coverage
4. **Data collectie**: Aangepaste collector met tiered sampling policy
5. **OB analyse**: orderbook_analysis.py (exchange-agnostisch)
6. **Cost model**: Schrijf costs_{exchange}_v1.py met register_regime() asserts
7. **Backtest**: run_part2_measured_cost_rerun.py met exchange-specifieke regimes
8. **Gate evaluatie**: 7 STRICT gates, zelfde thresholds
9. **ADR**: Documenteer resultaat + vergelijking met MEXC

### Kandidaat Exchanges
| Exchange | Spot Maker | Spot Taker | Coin Count | Notities |
|----------|-----------|-----------|------------|----------|
| Binance | 10bps (of lager met BNB) | 10bps | ~600+ | Grootste volume |
| Bybit | 10bps | 10bps | ~400+ | Goede liquiditeit |
| OKX | 8bps | 10bps | ~300+ | Altcoin dekking |
| Gate.io | 9bps | 9bps | ~1700+ | Meeste coins |
| Bitget | 10bps | 10bps | ~800+ | Groeiend |

**NB**: Exacte fees opzoeken per exchange vóór implementatie. Bovenstaande zijn benaderingen.

### Herbruikbare Code
| Script | Exchange-agnostisch? | Aanpassing nodig |
|--------|---------------------|------------------|
| orderbook_collector.py | ❌ | EXCHANGE_ID, COIN_LIST, sampling tiers |
| orderbook_analysis.py | ✅ | Alleen input path |
| fill_model_v3.py | ✅ | Geen |
| run_part2_measured_cost_rerun.py | ⚠️ | Regime import, candle cache path |
| harness.py | ✅ | Fee is input parameter |

## Quick Start Commands
```bash
# Tests draaien
/opt/homebrew/bin/python3 -m pytest strategies/hf/screening/ -q

# Collector starten (MEXC, dry-run)
python strategies/hf/screening/orderbook_collector.py --duration-hours 24 --dry-run

# Orderbook analyse
python strategies/hf/screening/orderbook_analysis.py --input data/orderbook_snapshots/FILE.jsonl --label EXCHANGE_001

# 24-combo rerun (dry-run)
python strategies/hf/screening/run_part2_measured_cost_rerun.py --config both --dry-run

# Git status
git log --oneline -5 hf-part2
```

## Git Branch
- Branch: `hf-part2`
- Laatste commit: `e913d99` (P0 measured orderbook validation)
- Remote: up to date met `origin/hf-part2`

# Archive Manifest

**Datum**: 2026-02-22
**Reden**: Root directory opschoning — organisch gegroeide bestanden georganiseerd
**Regel**: Niets verwijderd, alles gearchiveerd. Code is intact en functioneel.

---

## Overzicht

| Categorie | Aantal bestanden | Locatie |
|-----------|:----------------:|---------|
| 4H Strategy iteraties | 22 | `legacy_strategies/4h/` |
| 1H Strategy iteraties | 50 | `legacy_strategies/1h/` |
| PineScript indicatoren | 8 | `pinescripts/` |
| Legacy scripts | 6 | `legacy_scripts/` |
| Legacy data (CSV) | 2 | `legacy_data/` |
| Backtest Engine v2.0 | 12 (map) | `backtest_engine_v2.0/` |
| **Totaal** | **100** | |

---

## legacy_strategies/4h/ — 4H Timeframe Strategies (v1-v22)

Iteratieve ontwikkeling van TradingView-style strategieën op 4H BTC/crypto data.
Vervangen door `trading_bot/strategy.py` (DualConfirmStrategy) als productie-implementatie.

| Bestand | Strategie | Beschrijving |
|---------|-----------|--------------|
| `strategy_v1.py` | CycleMACrossover | MA crossover met cycle detection |
| `strategy_v2.py` | CycleMeanReversion | Mean reversion met cycle timing |
| `strategy_v3.py` | CycleDPOStochastic | DPO + Stochastic combo |
| `strategy_v4.py` | AdaptiveCycleComposite | Adaptieve multi-indicator |
| `strategy_v5.py` | CycleEMAWithATRStop | EMA + ATR trailing stop |
| `strategy_v6.py` | CycleEMARSIMomentum | EMA + RSI momentum filter |
| `strategy_v7.py` | MultiCycleVolRegime | Multi-cycle met volume regime |
| `strategy_v8.py` | UltimateCycleRider | All-in cycle strategy |
| `strategy_v9.py` | ShortCycleRSI | Kort-termijn RSI cycle |
| `strategy_v10.py` | StochCycleSwing | Stochastic swing trading |
| `strategy_v11.py` | EMAPullbackCycle | EMA pullback entries |
| `strategy_v12.py` | KeltnerCycleBreakout | Keltner channel breakout |
| `strategy_v13.py` | KeltnerOptimizedStops | Keltner met geoptimaliseerde stops |
| `strategy_v14.py` | KeltnerRSIMomentum | Keltner + RSI momentum |
| `strategy_v15.py` | KeltnerVolRegime | Keltner + volume regime |
| `strategy_v16.py` | RSISnapBack | RSI snap-back reversal |
| `strategy_v17.py` | InsideBarBreakout | Inside bar breakout pattern |
| `strategy_v18.py` | ThreeBarMomentum | 3-bar momentum pattern |
| `strategy_v19.py` | WilliamsRScalper | Williams %R scalping |
| `strategy_v20.py` | InsideBarRSI | Inside bar + RSI combo |
| `strategy_v21.py` | KeltnerMicroBreakout | Keltner micro-breakout |
| `strategy_v22.py` | ComboShortTerm | Combinatie korte termijn |

## legacy_strategies/1h/ — 1H Timeframe Strategies (v23-v72)

50 iteraties van 1H strategieën. Ontwikkeld voor TradingView backtesting.
Dit onderzoek leidde uiteindelijk tot het HF 1H VWAP_DEVIATION signaal in `strategies/hf/`.

| Range | Thema | Voorbeelden |
|-------|-------|-------------|
| v23-v34 | Keltner Channel varianten | Keltner1H, RSI1HScalper, BBSqueeze1H, DualKeltnerVol1H |
| v35-v52 | Momentum + trend following | PureTrendFollower, UltraWideMomentum (v1-v5), ADX varianten |
| v53-v72 | VWAP + volume indicatoren | VWAPTrend, VWAPChaikin, Supertrend, Ichimoku, Chaikin |

Volledige lijst: `strategy_1h_v23.py` t/m `strategy_1h_v72.py`

## pinescripts/ — TradingView PineScript Indicatoren (8 bestanden)

Visuele TradingView implementaties van beste strategieën, gebruikt voor handmatige validatie.

| Bestand | Gebaseerd op |
|---------|-------------|
| `BEST_STRATEGY_V13_PineScript.pine` | 4H Keltner Optimized (v13) |
| `BEST_STRATEGY_V21_ShortTerm_PineScript.pine` | 4H Keltner Micro Breakout (v21) |
| `BEST_1H_STRATEGY_V49_PineScript.pine` | 1H UltraWide Momentum ADX (v49) |
| `BEST_1H_STRATEGY_V55_PineScript.pine` | 1H VWAP Trend (v55) |
| `BEST_1H_STRATEGY_V69_SAFE_PineScript.pine` | 1H VWAP Chaikin Safe (v69) |
| `BEST_BEAR_BOUNCE_V4_PineScript.pine` | 4H DualConfirm Bear Bounce (v4) |
| `CHAMPION_TP_SL_V31_PineScript.pine` | Champion TP/SL (v31) |
| `CHAMPION_TP_SL_V31_Aligned_PineScript.pine` | Champion TP/SL Aligned (v31) |

## legacy_scripts/ — Standalone Runner Scripts (6 bestanden)

Scripts die de legacy strategies aanstuurden. Vervangen door `agent_team_v3.py` en sprint runners.

| Bestand | Functie |
|---------|---------|
| `fetch_data.py` | Kraken 4H data ophalen (vervangen door `scripts/download_kraken_4h_native.py`) |
| `fetch_data_1h.py` | Kraken 1H data ophalen (vervangen door `scripts/build_hf_cache.py`) |
| `run_backtests.py` | Runner voor 4H strategies v1-v22 |
| `run_backtests_1h.py` | Runner voor 1H strategies v23-v72 |
| `paper_trade_sim.py` | Paper trader voor v55/v69 (vervangen door `paper_backfill_v4.py`) |
| `paper_trade_compare.py` | Vergelijking paper trade resultaten |

## legacy_data/ — Historische CSV Bestanden (2 bestanden)

BTC price data gebruikt door de oudste strategy iteraties. Huidige data pipeline gebruikt JSON caches in `~/CryptogemData/`.

| Bestand | Grootte | Beschrijving |
|---------|---------|--------------|
| `btc_usd_1d.csv` | 414 KB | BTC/USD 1D candles |
| `btc_usd_1h.csv` | 1.4 MB | BTC/USD 1H candles |

## backtest_engine_v2.0/ — Legacy Backtest Framework (complete map)

Standalone backtest engine met eigen strategy implementaties.
Vervangen door de huidige `trading_bot/agent_team_v3.py` + `strategies/` architectuur.

| Onderdeel | Bestanden | Beschrijving |
|-----------|-----------|--------------|
| `engine/` | `backtest.py`, `analyzers.py`, `data_loader.py`, `report.py` | Core engine |
| `strategies/` | `bear_mean_reversion.py`, `bear_optimized.py`, `v13_keltner_optimized.py`, `v21_keltner_micro.py`, `v55_vwap_trend.py`, `v69_vwap_chaikin.py` | 6 strategy implementaties |
| Root scripts | `run.py`, `run_ai_coins.py`, `run_bear_analysis.py`, `run_bear_period.py` | Runners |

---

## Waarom Gearchiveerd

Deze bestanden representeren de **exploratiefase** van het project (feb 2026):
- 72 strategy iteraties waren nodig om de DualConfirm bounce strategie te ontdekken
- PineScript bestanden valideerden visueel op TradingView
- backtest_engine_v2.0 was een tussenstap naar de huidige modulaire architectuur

De actieve codebase is nu:
- **4H DualConfirm**: `trading_bot/strategy.py` + `trading_bot/agent_team_v3.py`
- **4H Research**: `strategies/4h/sprint1-4/`
- **HF 1H VWAP**: `strategies/hf/` + `trading_bot/paper_hf_1h.py`
- **MEXC 4H Deploy**: `trading_bot/paper_mexc_4h.py`

## Herstel

Alle bestanden zijn intact en functioneel. Om een gearchiveerd bestand te herstellen:
```bash
git mv archive/legacy_strategies/4h/strategy_v13.py strategy_v13.py
```

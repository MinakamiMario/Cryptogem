# Cryptogem Backtest Engine v2.0

BTC/USD trading strategy backtester en paper trade simulator.

## Structuur

```
backtest_engine_v2.0/
├── run.py                  # CLI runner
├── requirements.txt        # Dependencies
├── data/                   # Marktdata (CSV)
│   ├── BTC_1h.csv
│   └── BTC_1d.csv
├── engine/                 # Core engine
│   ├── __init__.py
│   ├── backtest.py         # Backtest & paper trade runner
│   ├── analyzers.py        # Trade loggers
│   ├── data_loader.py      # Multi-coin data fetcher
│   └── report.py           # Resultaat rapportage
├── strategies/             # Trading strategieen
│   ├── __init__.py
│   ├── v55_vwap_trend.py   # Best return (+53.4%)
│   ├── v69_vwap_chaikin.py # Best risk-adjusted (PF 1.35)
│   ├── v13_keltner_optimized.py  # 1D Keltner
│   └── v21_keltner_micro.py      # 1D Keltner Micro
├── pinescripts/            # TradingView Pine Scripts
│   ├── v55_vwap_trend.pine
│   └── v69_vwap_chaikin.pine
└── results/                # Backtest output
```

## Installatie

```bash
pip install -r requirements.txt
```

## Gebruik

```bash
# Backtest
python run.py backtest                        # Alle strategieen BTC 1H
python run.py backtest --coin ETH             # Op ETH
python run.py backtest --timeframe 1d         # Op 1D timeframe
python run.py backtest --strategy v55         # Enkele strategie

# Paper trade
python run.py paper                           # Alle strategieen, 1 jaar, EUR 1000
python run.py paper --days 30                 # Laatste 30 dagen
python run.py paper --capital 500             # EUR 500 startkapitaal
python run.py paper --strategy v69            # Enkele strategie

# Vergelijking
python run.py compare                         # 1H vs 1D side-by-side

# Data
python run.py fetch                           # Download data alle coins
python run.py fetch --coin SOL                # Alleen SOL
python run.py list                            # Beschikbare data
```

## Strategieen

| Strategie | Timeframe | Return | MaxDD | PF | Trades | WR |
|-----------|-----------|--------|-------|-----|--------|-----|
| V55 VWAP Trend | 1H | +53.4% | ~28% | 1.28 | 73 | 42% |
| V69 VWAP+Chaikin | 1H | +41.3% | 20.2% | 1.35 | 62 | 44% |
| V13 Keltner | 1D | +9490% | 42.8% | - | 73 | - |
| V21 Keltner Micro | 1D | varies | varies | - | ~150 | - |

## Regels

- Long only (geen shorting)
- Geen leverage
- 0.1% commissie per trade
- 95% positiegrootte

## Coins

Ondersteund via Yahoo Finance: BTC, ETH, SOL, BNB

# CRYPTOGEM TRADING BOT — VOLLEDIGE SESSIE SAMENVATTING
**Laatste update:** 13 februari 2026
**Doel:** Context-overdracht naar nieuwe chat sessie

---

## 1. PROJECT OVERZICHT

### Wat is het?
Een geautomatiseerde cryptocurrency trading bot die draait op **Kraken**, gefocust op **bear market bounce** strategie. De bot scant 532+ coins op 4-uurs candles, zoekt oversold bounces via Donchian Channels + Bollinger Bands dual confirmation, en handelt met $2000 all-in per trade.

### Kerngegevens
- **Exchange:** Kraken (primair), MEXC (voorbereid, wacht op API keys)
- **Coins:** 532 dynamisch ontdekt via Kraken API (was 289 hardcoded)
- **Timeframe:** 4-uurs candles
- **Strategie:** V5 DualConfirm met RSI Recovery Exit
- **Portfolio:** 1x$2000 all-in, volume-based ranking
- **Marktfocus:** Bear market (bull strategie uitgesteld)

### Gebruiker
- **Taal:** Nederlands
- **Voorkeur:** Simpele, evidence-based verbeteringen
- **Operatie:** Bot draait 's nachts door terwijl gebruiker slaapt
- **Halal filter:** Actief (geen yield/lending/staking tokens)

---

## 2. MAPPENSTRUCTUUR

### Actieve Trading Bot (`/Users/oussama/Cryptogem/trading_bot/`)

#### Core Modules
| Bestand | Grootte | Functie |
|---------|---------|---------|
| `bot.py` | 34 KB | Live Kraken trading bot met Telegram notificaties |
| `strategy.py` | 28 KB | DualConfirmStrategy class (V4/V5 logica) |
| `kraken_client.py` | 26 KB | Kraken API client met dynamische coin discovery |
| `exchange_manager.py` | 17 KB | Multi-exchange abstractielaag (Kraken + MEXC) |
| `paper_backfill_v4.py` | 39 KB | Paper trading met 168-uur historische backfill |
| `coin_scanner.py` | 23 KB | Multi-source coin discovery (Kraken + MEXC + DEX) |
| `dex_manager.py` | 42 KB | DEX liquidity/pool management (Solana/BSC) |
| `halal_filter.py` | 26 KB | Sharia-compliant coin filtering |

#### Backtest Suite (21 bestanden)
| Bestand | Functie | Status |
|---------|---------|--------|
| `backtest_mega_compare.py` (43 KB) | **30 strategieën vergelijken op 532 coins** | ✅ Laatste run |
| `backtest_532_coins.py` (23 KB) | 532 vs 289 coins vergelijking | ✅ Compleet |
| `backtest_combined_winner.py` (29 KB) | Hoofd backtest engine (289 coins) | ✅ Compleet |
| `backtest_v5_experiments.py` (35 KB) | 74-config experiment suite | ✅ Compleet |
| `backtest_v5_deep_dive.py` (24 KB) | RSI Recovery + ADX deep analysis | ✅ Compleet |
| `backtest_v5_precision.py` (18 KB) | Fine-tuning RSI targets 42-47 | ✅ Compleet |
| `backtest_v5_final_sweep.py` (19 KB) | Filter efficiency testing | ✅ Compleet |
| `backtest_v5_capital_sim.py` (15 KB) | Capital allocation simulatie | ✅ Compleet |
| `backtest_v5_portfolio_compare.py` (27 KB) | Multi-portfolio vergelijking | ✅ Compleet |
| `backtest_v6_price_structure.py` (28 KB) | Price action structure analyse | ✅ Compleet |
| `backtest_portfolio_optimization.py` (46 KB) | Capital optimalisatie | ✅ Compleet |
| `backtest_entry_optimization.py` (39 KB) | Entry filter optimalisatie | ✅ Compleet |
| `backtest_exit_optimization.py` (34 KB) | Exit strategie optimalisatie | ✅ Compleet |
| `backtest_extra_filters.py` (35 KB) | Extra filter testen | ✅ Compleet |
| Overige: `backtest_all.py`, `backtest_compare.py`, `backtest_improved.py`, `backtest_stoploss.py`, `backtest_timeframe_test.py`, `backtest_universal.py`, `backtest_universal_portfolio.py`, `filter_backtest.py` | Diverse eerdere tests | ✅ Compleet |

#### Data & Cache
| Bestand | Grootte | Inhoud |
|---------|---------|--------|
| `candle_cache_532.json` | 47.6 MB | 526 coins, 60 dagen 4H data (meest recent) |
| `candle_cache_60d.json` | 14.4 MB | 60-dagen cache (289 coins) |
| `candle_cache_240m_60d.json` | 13.9 MB | Alternatief 4H formaat |
| `candle_cache.json` | 13.1 MB | Originele cache |
| Overige caches | ~30 MB | 30-dag, 14-dag, 1-uur varianten |

#### PineScript (TradingView)
| Bestand | Versie |
|---------|--------|
| `pinescript_dual_confirm_v5.pine` (18 KB) | V5 met RSI Recovery exit (LAATSTE) |
| `pinescript_dual_confirm_v4.pine` (16 KB) | V4 baseline |
| `pinescript_dual_confirm_optimized.pine` (12 KB) | Eerdere optimalisatie |

#### Configuratie
| Bestand | Inhoud |
|---------|--------|
| `.env` | KRAKEN_API_KEY, KRAKEN_PRIVATE_KEY, COINS, STRATEGY, CAPITAL_PER_TRADE, MAX_OPEN_POSITIONS, MAX_DAILY_LOSS_PCT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID |
| `V5_RAPPORT.md` | Uitgebreid V5 bevindingen rapport (Nederlands) |

#### Paper Trading Status
| Bestand | Status |
|---------|--------|
| `paper_trades_v4_live.xlsx` | Actieve V4 paper trades |
| `paper_state_v4_live.json` | V4 paper trader state |
| `paper_trades_2x1000.xlsx` | 2-positie test |
| `paper_trades_3x700.xlsx` | 3-positie test |

### Root Directory (`/Users/oussama/Cryptogem/`)
- 72 legacy strategie-versies (`strategy_v1.py` t/m `strategy_1h_v72.py`)
- 6 legacy PineScript versies
- `backtest_engine_v2.0/` subdirectory met oudere engine
- BTC data CSV bestanden

---

## 3. STRATEGIE-EVOLUTIE (V1 → V5)

### V1-V2: Basis Bounce Strategie
- Simpele Donchian Channel bounce
- RSI < 35 entry filter
- ATR trailing stop

### V3: Volume Spike Filter
- **Toevoeging:** Volume spike > 2x gemiddelde als entry filter
- **Effect:** Filterde ruis-signalen, verhoogde winstgevendheid
- **Break-even stop:** Toegevoegd (+3% trigger)
- **Time max:** 10 bars (40 uur) force exit

### V4: DualConfirm (Productie)
**De huidige productie-strategie met dual confirmation:**

#### Entry Condities (ALLE moeten waar zijn):
1. **Donchian Bounce:** `low <= vorige_donchian_low` (prijs raakt DC bodem)
2. **Bollinger Bounce:** `close <= bb_lower` (prijs raakt BB onderband)
3. **RSI Oversold:** `RSI < 40`
4. **Price Bounce:** `close > vorige_close` (bounce bevestigd)
5. **Volume Spike:** `volume >= 2.0x 20-bar gemiddelde` (V2)
6. **Volume Confirm:** `volume >= 1.0x vorige bar` (V4 nieuw)
7. **Base Volume:** `volume >= 0.5x 20-bar gemiddelde`
8. **Cooldown:** Minimaal 4 bars na normale exit, 8 bars na stop loss

#### Exit Condities (eerste die triggert):
1. **Hard Stop:** `close < entry × 0.85` (max 15% verlies)
2. **Time Max:** Na 10 bars (40 uur) → force exit
3. **DC Target:** `close >= donchian_midchannel`
4. **BB Target:** `close >= bollinger_mid`
5. **RSI Overbought:** `RSI > 70`
6. **Trailing Stop:** `close < stop_price` (ATR × 2.0 trail)

#### Trailing Stop Management:
- **Initieel:** `stop = close - (ATR × 2.0)`, max 15% onder entry
- **Update per bar:** `stop = highest_since_entry - (ATR × 2.0)`
- **Break-even:** Bij ≥3% winst → stop minimaal op `entry × 1.006` (+0.6% fee buffer)

#### V4 Backtest Resultaten (289 coins, 60 dagen):
```
12 trades | WR 83.3% | P&L $+4,553 | PF 78.07 | DD 1.9%
```

### V5: RSI Recovery Exit (Aanbevolen)
**Toevoeging:** Extra exit-regel die trade sluit zodra RSI herstelt.

#### Logica:
```
ALS RSI >= target (45 of 47) EN minstens 2 bars in trade → EXIT met "RSI RECOVERY"
```

#### Waarom werkt het:
- We kopen in oversold (RSI < 40)
- Als RSI herstelt naar ~45-47 is het ergste voorbij
- Pakt winst voordat RSI terugvalt
- Converteert verliezende TimeMax-trades naar winnaars

#### Kritieke trade: ACA/USD
- **V4:** TimeMax exit na 9 bars → -$15 verlies
- **V5:** RSI Recovery exit na 6 bars → +$143 winst
- **Verschil:** $158 extra P&L

#### V5 Backtest Resultaten (289 coins, 60 dagen):
```
target=47: 12tr | WR 91.7% | P&L $+4,711 | PF 108 | DD 1.8%
target=45: 12tr | WR 91.7% | P&L $+4,666 | PF 107 | DD 1.8%
```

#### Robustheid:
- **target=42 t/m 47:** Allemaal 91.7% WR, PF >106 (zeer stabiel)
- **Cliff bij 48:** Target ≥48 valt terug naar V4 baseline (RSI bereikt 48 niet meer)
- **Productie-aanbeveling:** target=45 (meer marge tot cliff edge)

---

## 4. STRATEGIE PARAMETERS — COMPLETE REFERENTIE

### DualConfirmStrategy (strategy.py)
```python
# INDICATORS
donchian_period = 20          # Donchian lookback bars
bb_period = 20                # Bollinger Bands lookback bars
bb_dev = 2.0                  # BB standaard deviatie multiplier ⚠️ CLIFF: 1.8 of 2.2 = dramatisch slechter
rsi_period = 14               # RSI lookback bars
rsi_dc_max = 40               # RSI threshold voor Donchian entry
rsi_bb_max = 40               # RSI threshold voor BB entry
rsi_sell = 70                 # RSI threshold voor profit exit
atr_period = 14               # ATR lookback bars
atr_stop_mult = 2.0           # Trailing stop = close - (ATR × 2.0)

# RISK MANAGEMENT
cooldown_bars = 4             # Cooldown na normale exit (16 uur)
cooldown_after_stop = 8       # Cooldown na stop loss (32 uur)
max_stop_loss_pct = 15.0      # Harde max verlies cap

# V2 OPTIMALISATIES
volume_spike_filter = True    # Volume spike filter aan
volume_spike_mult = 2.0       # Volume moet ≥2.0x gemiddelde zijn
volume_min_pct = 0.5          # Basis volume minimum (50% van avg)
breakeven_stop = True         # Break-even stop aan
breakeven_trigger_pct = 3.0   # Na +3% winst → stop naar BE + 0.6%

# V3 OPTIMALISATIE
time_max_bars = 10            # Force exit na 10 bars (40 uur)

# V4 OPTIMALISATIE
vol_confirm = True            # Volume bar-to-bar confirmatie
vol_confirm_mult = 1.0        # Huidige bar ≥ 1.0x vorige bar

# V5 OPTIMALISATIE (RSI Recovery)
rsi_recovery = True           # RSI Recovery exit aan
rsi_recovery_target = 45      # Exit als RSI >= 45 (productie-aanbeveling)
rsi_recovery_min_bars = 2     # Minimaal 2 bars in trade voor RSI exit
```

### Indicator Berekeningen
| Indicator | Formule | Gebruik |
|-----------|---------|---------|
| **RSI** | 100 - (100 / (1 + avg_gain / avg_loss)), period=14 | Entry filter (< 40) + Exit (> 70) + RSI Recovery |
| **ATR** | Gemiddelde van True Range over 14 bars | Trailing stop berekening |
| **Donchian** | Highest High / Lowest Low over 20 bars | Entry (low touch) + Exit (mid target) |
| **Bollinger** | SMA(20) ± 2.0 × StdDev | Entry (lower touch) + Exit (mid target) |
| **ADX** | Directional Index (14 bars) | Getested maar VERWORPEN (schadelijk met VolConfirm) |

### Signal Quality Score
```python
rsi_score = max(0, (40 - rsi) / 40)              # 0-1 op basis van RSI afstand
vol_score = min(1, current_volume / (avg × 3))     # 0-1, capt op 3x volume
confidence = max(0.80, rsi_score × 0.5 + vol_score × 0.5)
```

---

## 5. DYNAMISCHE COIN DISCOVERY

### Probleem
Oorspronkelijk 289 coins hardcoded in `PAIR_MAP` in `kraken_client.py`. Dit miste nieuwe Kraken listings en was handmatig onderhoud.

### Oplossing: Dynamische Discovery via Kraken API
**Methode:** `discover_all_usd_pairs()` in `kraken_client.py`

#### Hoe het werkt:
1. **API Call:** Kraken `AssetPairs` endpoint → alle actieve paren ophalen
2. **Filtering:**
   - Alleen `ZUSD`/`USD` quote currency
   - Skip darkpool paren (`.d`)
   - Skip offline paren
   - Exclusielijst: 112+ tokens uitgefilterd
3. **Normalisatie:** Kraken naming (XBT→BTC, XXRP→XRP, etc.)
4. **Merge:** Combineer met hardcoded PAIR_MAP als fallback
5. **Cache:** 1 uur TTL, `force_refresh=True` om te forceren

#### Exclusielijst (112+ tokens):
| Categorie | Voorbeelden | Reden |
|-----------|-------------|-------|
| **Stablecoins** (23) | USDT, USDC, DAI, TUSD, BUSD, PYUSD, FDUSD, RLUSD | Geen volatiliteit |
| **Fiat** (12) | EUR, GBP, AUD, CAD, JPY, EURQ, TGBP, AUDX | Geen crypto |
| **Wrapped/Pegged** (15) | WBTC, WETH, STETH, CBETH, CMETH, LSETH, TBTC | Volgt onderliggende asset |
| **Yield/Lending** (27) | AAVE, COMP, MKR, CRV, LDO, LQTY, SPELL, PENDLE, ONDO, SNX | Haram (rente-gerelateerd) |
| **Memecoins** (47) | DOGE, SHIB, PEPE, FLOKI, FARTCOIN, RETARDIO, TITCOIN, GHIBLI | Te volatiel/geen fundamentals |
| **Gambling** (3) | ROLLBIT, FUN, WINR | Haram |

#### Resultaat: 532 coins (was 289)

#### Integratie in codebase:
```python
# bot.py, paper_backfill_v4.py — zelfde patroon:
coins_str = os.getenv('COINS', '')
if coins_str:
    coins = [c.strip() for c in coins_str.split(',')]  # .env fallback
else:
    coins = client.get_all_tradeable_pairs()            # Dynamische discovery
```

### Survivorship Bias Analyse
- **289 oude coins:** Handmatig geselecteerd (deels op basis van historische performance) → **biased**
- **243 nieuwe coins:** Nooit eerder getest → meer representatief voor toekomst
- **Backtest 243 nieuwe coins only:** 36 trades, 30.6% WR, $-1,717 → aanzienlijk slechter
- **Conclusie:** De 289 oude coins zijn cherry-picked. ZEUS ($+3,333) domineert 71% van P&L. Meer coins = meer kans op de volgende ZEUS, maar ook meer verliezende trades.

---

## 6. MEGA STRATEGIE VERGELIJKING — 30 STRATEGIEËN OP 532 COINS

### Test Setup
- **Script:** `backtest_mega_compare.py`
- **Data:** 526 coins met data, ~60 dagen, 4H candles
- **Fee:** 0.26% per trade (in + out)
- **Scoring:** Composite Score = P&L 35% + PF 20% + WR 15% + DD-penalty 20% + Trades 10%

### ConfigurableStrategy Parameters (backtest_mega_compare.py)
```python
# ENTRY
dc_period = 20           # Donchian lookback
bb_period = 20           # BB lookback
bb_dev = 2.0             # BB std dev
rsi_period = 14          # RSI lookback
rsi_max = 40             # RSI entry threshold
atr_period = 14          # ATR lookback
vol_min_pct = 0.5        # Base volume min

# FILTERS
vol_spike = False        # Volume spike filter
vol_spike_mult = 2.0     # Volume spike multiplier
vol_confirm = False      # Volume bar-to-bar confirm
vol_confirm_mult = 1.0   # Vol confirm threshold
adx_filter = False       # ADX trend filter
adx_max = 25             # ADX maximum

# EXIT
atr_mult = 2.0           # Trailing stop multiplier
max_stop_pct = 15.0      # Max stop loss %
breakeven = False        # Break-even stop
be_trigger = 3.0         # BE trigger %
time_max = False         # Time limit
time_max_bars = 10       # Max bars in trade
rsi_sell = 70            # RSI sell threshold
rsi_recovery = False     # RSI Recovery exit
rsi_rec_target = 47      # RSI Recovery target
rsi_rec_min_bars = 2     # Min bars voor RSI exit

# COOLDOWN
cooldown_bars = 4        # Normale cooldown
cooldown_stop = 8        # Stop loss cooldown

# PORTFOLIO
max_pos = 1              # Max gelijktijdige posities
pos_size = 2000          # Positie grootte in USD
```

### Alle 30 Configuraties

#### Baseline & V3 Varianten
| # | Naam | Wijziging t.o.v. V4 | max_pos | pos_size |
|---|------|---------------------|---------|----------|
| 1 | V3 BASELINE | RSI<35, ATR 3.0x, geen vol, geen BE, geen TMax | 2 | $1000 |
| 2 | V3 + VolSpike | V3 + vol_spike=2x | 2 | $1000 |
| 3 | V3 + BE stop | V3 + breakeven=3% | 2 | $1000 |

#### V4 Varianten
| # | Naam | Wijziging t.o.v. V4 | max_pos | pos_size |
|---|------|---------------------|---------|----------|
| 4 | V4 DUALCONFIRM | Baseline V4 (RSI<40, vol_spike=2x, vol_confirm=1x, BE=3%, TMax=10) | 1 | $2000 |
| 5 | V4 ZONDER VOL | vol_spike=OFF, vol_confirm=OFF | 1 | $2000 |
| 6 | V4 + ADX<25 | + adx_filter=True, adx_max=25 | 1 | $2000 |
| 7 | V4 + RSI<35 | rsi_max=35 (strenger) | 1 | $2000 |

#### V5 RSI Recovery Varianten
| # | Naam | rsi_rec_target | Overig |
|---|------|----------------|--------|
| 8 | V5 RSI REC 47 | 47 | Standaard V5 |
| 9 | V5 RSI REC 45 ★ | 45 | **PRODUCTIE** |
| 10 | V5 RSI REC 42 | 42 | Conservatief |
| 11 | V5 RSI REC 50 | 50 | Agressief |

#### ATR Multiplier Sweep
| # | Naam | atr_mult | Basis |
|---|------|----------|-------|
| 12 | V5 + ATR 1.5x | 1.5 | V5 RSI45 |
| 13 | V5 + ATR 2.5x | 2.5 | V5 RSI45 |
| 14 | V5 + ATR 3.0x | 3.0 | V5 RSI45 |

#### Donchian Period Sweep
| # | Naam | dc_period | Basis |
|---|------|-----------|-------|
| 15 | V5 + DC=15 | 15 | V5 RSI45 |
| 16 | V5 + DC=25 | 25 | V5 RSI45 |

#### Time Max Sweep
| # | Naam | time_max_bars | Basis |
|---|------|---------------|-------|
| 17 | V5 + TMax 6 | 6 (24h) | V5 RSI45 |
| 18 | V5 + TMax 16 | 16 (64h) | V5 RSI45 |
| 19 | V5 GEEN TMax | OFF | V5 RSI45 |

#### Bollinger Deviation Sweep
| # | Naam | bb_dev | Basis |
|---|------|--------|-------|
| 20 | V5 + BB 1.8 | 1.8 | V5 RSI45 |
| 21 | V5 + BB 2.2 | 2.2 | V5 RSI45 |

#### Volume Spike Sweep
| # | Naam | vol_spike_mult | Basis |
|---|------|----------------|-------|
| 22 | V5 + VolSpk 1.5x | 1.5 | V5 RSI45 |
| 23 | V5 + VolSpk 3.0x | 3.0 | V5 RSI45 |

#### Portfolio Sizing
| # | Naam | max_pos | pos_size | Basis |
|---|------|---------|----------|-------|
| 24 | V5 + 2x$1000 | 2 | $1000 | V5 RSI45 |
| 25 | V5 + 3x$667 | 3 | $667 | V5 RSI45 |

#### Break-Even Variaties
| # | Naam | be_trigger | breakeven | Basis |
|---|------|------------|-----------|-------|
| 26 | V5 + BE 2% | 2% | ON | V5 RSI45 |
| 27 | V5 + BE 5% | 5% | ON | V5 RSI45 |
| 28 | V5 GEEN BE | - | OFF | V5 RSI45 |

#### Cooldown Variaties
| # | Naam | cooldown_bars | cooldown_stop | Basis |
|---|------|---------------|---------------|-------|
| 29 | V5 + CD 2/4 | 2 | 4 | V5 RSI45 |
| 30 | V5 + CD 6/12 | 6 | 12 | V5 RSI45 |

### Volledige Resultaten (op 532 coins)

```
  #    STRATEGIE                    |  #TR |   W-  L |     WR |        P&L |     PF |     DD | SCORE
  ------------------------------------------------------------------------------------------------
  🥇  V5 + VolSpk 3.0x             |   40 |  22- 18 |  55.0% | $  +3,820 |   3.0 |  31.4% |  54.4
  🥈  V3 + VolSpike                |   71 |  39- 32 |  54.9% | $  +2,022 |   1.9 |  25.3% |  48.6
  🥉  V5 + BE 5%                   |   45 |  24- 21 |  53.3% | $  +3,293 |   2.3 |  54.7% |  43.8
  #4  V5 GEEN BE                   |   45 |  24- 21 |  53.3% | $  +3,293 |   2.3 |  54.7% |  43.8
  #5  V5 + ATR 1.5x                |   50 |  23- 27 |  46.0% | $  +3,145 |   2.1 |  68.3% |  42.9
  #6  V5 + DC=15                   |   46 |  22- 24 |  47.8% | $  +3,103 |   2.2 |  64.3% |  42.3
  #7  V5 + BE 2%                   |   46 |  22- 24 |  47.8% | $  +3,029 |   2.2 |  67.9% |  41.9
  #8  V5 RSI REC 47                |   46 |  22- 24 |  47.8% | $  +2,917 |   2.1 |  73.6% |  41.2
  #9  V5 RSI REC 45 ★ (PRODUCTIE) |   46 |  22- 24 |  47.8% | $  +2,882 |   2.1 |  75.3% |  41.0
  #10 V5 + CD 2/4                  |   46 |  22- 24 |  47.8% | $  +2,882 |   2.1 |  75.3% |  41.0
  #11 V5 + CD 6/12                 |   46 |  22- 24 |  47.8% | $  +2,882 |   2.1 |  75.3% |  41.0
  #12 V5 + ATR 3.0x                |   43 |  21- 22 |  48.8% | $  +2,863 |   2.0 |  76.2% |  40.4
  #13 V5 RSI REC 42                |   46 |  22- 24 |  47.8% | $  +2,765 |   2.0 |  81.2% |  40.4
  #14 V5 + BB 1.8                  |   61 |  30- 31 |  49.2% | $  +2,654 |   1.7 |  87.1% |  40.3
  #15 V5 + ATR 2.5x                |   45 |  22- 23 |  48.9% | $  +2,769 |   2.0 |  80.9% |  40.3
  #16 V4 DUALCONFIRM               |   46 |  21- 25 |  45.7% | $  +2,759 |   2.0 |  81.4% |  40.0
  #17 V5 RSI REC 50                |   46 |  21- 25 |  45.7% | $  +2,759 |   2.0 |  81.4% |  40.0
  #18 V5 + DC=25                   |   44 |  21- 23 |  47.7% | $  +2,662 |   2.0 |  69.1% |  39.5
  #19 V4 + RSI<35                  |   44 |  20- 24 |  45.5% | $  +2,742 |   2.0 |  82.3% |  39.5
  #20 V5 + TMax 16                 |   43 |  19- 24 |  44.2% | $  +2,594 |   1.9 |  71.3% |  38.4
  #21 V5 GEEN TMax                 |   43 |  19- 24 |  44.2% | $  +2,594 |   1.9 |  71.3% |  38.4
  #22 V3 + BE stop                 |   55 |  24- 31 |  43.6% | $  +1,194 |   1.6 |  43.4% |  35.5
  #23 V5 + 3x$667                  |   86 |  40- 46 |  46.5% | $    +850 |   1.5 |  43.8% |  34.0
  #24 V5 + 2x$1000                 |   72 |  33- 39 |  45.8% | $  +1,224 |   1.5 |  56.6% |  33.2
  #25 V3 BASELINE                  |   51 |  26- 25 |  51.0% | $    -399 |   0.8 |  37.8% |  30.2
  #26 V4 ZONDER VOL                |   73 |  29- 44 |  39.7% | $    +897 |   1.2 | 142.5% |  30.0
  #27 V4 + ADX<25                  |   14 |   6-  8 |  42.9% | $    -132 |   0.9 |  27.6% |  27.1
  #28 V5 + TMax 6                  |   49 |  20- 29 |  40.8% | $    -459 |   0.8 |  78.8% |  23.4
  #29 V5 + VolSpk 1.5x             |   47 |  21- 26 |  44.7% | $    -753 |   0.7 |  72.8% |  22.0
  #30 V5 + BB 2.2                  |   27 |  10- 17 |  37.0% | $    -925 |   0.5 |  72.2% |  15.7
```

### Top 5 Gedetailleerd

#### 🥇 V5 + VolSpk 3.0x (Score 54.4)
```
40 trades | WR 55.0% | P&L $+3,820 | PF 3.0 | DD 31.4%
Avg Win: $+261 | Avg Loss: $-107 | Avg Bars: 5.7 (23h)

Exit Reasons:
  TRAIL STOP       12x | WR   0.0% | P&L $-1,409
  TIME MAX         10x | WR  40.0% | P&L $  -368
  DC TARGET         9x | WR 100.0% | P&L $  +977
  RSI RECOVERY      8x | WR 100.0% | P&L $+4,581
  END               1x | WR 100.0% | P&L $   +40

Top trades:
  ✅ ZEUS/USD       | $+3,333 | RSI RECOVERY
  ✅ XCN/USD        | $+344   | RSI RECOVERY
  ✅ B3/USD         | $+309   | RSI RECOVERY
  ✅ STRD/USD       | $+284   | DC TARGET
  ✅ MF/USD         | $+172   | RSI RECOVERY
```

#### 🥈 V3 + VolSpike (Score 48.6)
```
71 trades | WR 54.9% | P&L $+2,022 | PF 1.9 | DD 25.3% (LAAGSTE DD!)
2x$1000 portfolio | Avg Win: $+113 | Avg Loss: $-74

Exit Reasons:
  DC TARGET        28x | WR  92.9% | P&L $+3,269
  TRAIL STOP       22x | WR   0.0% | P&L $-1,726
  BB TARGET        16x | WR  75.0% | P&L $  +850
```

#### 🥉 V5 + BE 5% / V5 GEEN BE (Score 43.8 — IDENTIEK!)
```
45 trades | WR 53.3% | P&L $+3,293 | PF 2.3 | DD 54.7%
Bewijs dat break-even stop NULEFFECT heeft op 532 coins
```

### Parameter Sensitivity Analyse

#### RSI Recovery Target
```
target=42 | 46tr | WR  47.8% | P&L $+2,765 | PF 2.0 | DD 81.2%
target=45 | 46tr | WR  47.8% | P&L $+2,882 | PF 2.1 | DD 75.3%
target=47 | 46tr | WR  47.8% | P&L $+2,917 | PF 2.1 | DD 73.6%
target=50 | 46tr | WR  45.7% | P&L $+2,759 | PF 2.0 | DD 81.4%
→ Sweet spot: 45-47, minimaal verschil
```

#### ATR Multiplier
```
ATR 1.5x | 50tr | WR  46.0% | P&L $+3,145 | PF 2.1 | DD 68.3%  ← Meer trades & P&L maar hogere DD
ATR 2.0x | 46tr | WR  47.8% | P&L $+2,882 | PF 2.1 | DD 75.3%  ← Productie
ATR 2.5x | 45tr | WR  48.9% | P&L $+2,769 | PF 2.0 | DD 80.9%
ATR 3.0x | 43tr | WR  48.8% | P&L $+2,863 | PF 2.0 | DD 76.2%
→ Weinig verschil, 2.0x is goed
```

#### Bollinger Deviation
```
BB 1.8 | 61tr | WR  49.2% | P&L $+2,654 | PF 1.7 | DD 87.1%  ← Meer trades maar lager PF
BB 2.0 | 46tr | WR  47.8% | P&L $+2,882 | PF 2.1 | DD 75.3%  ← Productie
BB 2.2 | 27tr | WR  37.0% | P&L $  -925 | PF 0.5 | DD 72.2%  ← ⚠️ CLIFF! VERLIEZEN!
→ BB 2.0 is de enige goede waarde
```

#### Portfolio Sizing
```
1x$2000 | 46tr | P&L $+2,882 | PF 2.1 | DD 75.3%  ← Hoogste P&L
2x$1000 | 72tr | P&L $+1,224 | PF 1.5 | DD 56.6%  ← Lagere DD
3x$667  | 86tr | P&L $  +850 | PF 1.5 | DD 43.8%  ← Laagste DD, laagste P&L
→ 1x$2000 all-in is optimaal voor maximale P&L
```

---

## 7. KRITIEKE BEVINDINGEN & LESSEN

### Parametereffecten Samenvatting
| Parameter | Effect op 532 coins | Aanbeveling |
|-----------|---------------------|-------------|
| **VolSpk 3.0x** | +$938 vs 2.0x, WR 55% vs 48%, DD 31% vs 75% | ✅ Upgrade overwegen |
| **Break-even stop** | NULEFFECT (BE 5% = GEEN BE, identiek) | ❌ Kan verwijderd worden |
| **Cooldowns** | NULEFFECT (2/4 = 4/8 = 6/12, identiek) | – Maakt niet uit |
| **BB dev=2.2** | CLIFF: $-925 verlies | ⚠️ NOOIT wijzigen van 2.0 |
| **VolSpk 1.5x** | $-753 verlies | ⚠️ Nooit verlagen |
| **TMax 6** | $-459 verlies, WR 41% | ⚠️ Niet te kort |
| **TMax 16 = GEEN TMax** | Identiek ($+2,594) | – 16 en geen limiet zijn gelijk |
| **ADX filter** | $-132 verlies, filtert te veel weg | ❌ Verworpen |
| **RSI Recovery** | +$158 op 289 coins, +$35 op 532 coins | ✅ Behouden |
| **1x$2000 all-in** | Hoogste P&L van alle portfolio varianten | ✅ Behouden |

### Fundamentele Inzichten
1. **ZEUS Dominantie:** ZEUS/USD ($+3,333) = 71% van totale P&L in bijna elke strategie. Elke filter die ZEUS eruit filtert vernietigt de strategie
2. **Survivorship Bias:** De 289 originele coins zijn cherry-picked. De 243 nieuwe coins presteren significant slechter (30.6% WR, $-1,717). Meer coins = meer kans op de volgende ZEUS
3. **RSI Recovery exits zijn topperformers:** 100% WR op RSI Recovery exits met $+4,581 totaal in de winnende strategie
4. **Volume is essentieel:** Zonder volume filters (V4 ZONDER VOL) daalt WR naar 39.7% en DD stijgt naar 142.5%
5. **De meeste tweaks doen NIETS:** Van 250+ geteste configuraties hebben <10 daadwerkelijk effect
6. **EMA filters = no-op in bear market:** Alle coins zitten al onder alle EMA's in een bear market
7. **Cliff edges zijn gevaarlijk:** BB dev (2.0 → 2.2 = cliff), RSI Recovery target (47 → 48 = cliff)

---

## 8. MULTI-EXCHANGE ARCHITECTUUR

### Huidige Status
| Exchange | Status | Coins | Fee |
|----------|--------|-------|-----|
| **Kraken** | ✅ Actief | 532 dynamisch | 0.26% |
| **MEXC** | ⏳ Wacht op API keys | ~2000+ USDT paren | 0% maker |
| **DEX Solana** | 🔧 Voorbereid | Via GeckoTerminal | 0.3% |
| **DEX BSC** | 🔧 Voorbereid | Via GeckoTerminal | 0.3% |

### Architectuur
```
bot.py
  ├── CoinScanner (coin_scanner.py)
  │   ├── KrakenExchangeClient (exchange_manager.py)
  │   │   └── KrakenClient (kraken_client.py) ← discover_all_usd_pairs()
  │   ├── MEXCExchangeClient (exchange_manager.py)
  │   │   └── CCXT library
  │   └── DEXManager (dex_manager.py)
  │       ├── GeckoTerminal API (Solana pools)
  │       └── GeckoTerminal API (BSC pools)
  │
  ├── DualConfirmStrategy (strategy.py)
  │   └── Indicators: RSI, ATR, Donchian, Bollinger
  │
  ├── HalalFilter (halal_filter.py)
  │   └── Filtert yield/lending/gambling/etc.
  │
  └── Telegram Notificaties
```

### Coin Loading Flow
```
1. Check .env COINS → als gevuld, gebruik die (backward compat)
2. Als leeg → KrakenClient.get_all_tradeable_pairs()
   a. discover_all_usd_pairs() via Kraken AssetPairs API
   b. Filter: stablecoins, fiat, wrapped, yield, meme, gambling
   c. Cache: 1 uur TTL
   d. Merge met PAIR_MAP fallback
   e. Return: gesorteerde lijst van ~532 'BASE/USD' strings
3. Optional: CoinScanner.scan_all() voor multi-exchange
   a. Kraken coins ophalen
   b. MEXC coins ophalen (als API keys beschikbaar)
   c. DEX coins ophalen (Solana/BSC via GeckoTerminal)
   d. Deduplicatie (skip coins al op Kraken)
   e. Halal filter toepassen
```

---

## 9. PAPER TRADER STATUS

### Actieve Configuratie
- **Script:** `paper_backfill_v4.py --hours 168`
- **Strategie:** V4 DualConfirm (ZONDER RSI Recovery)
- **Start:** 12 februari 2026
- **Outputs:**
  - `paper_trades_v4_live.xlsx` — Trade log
  - `paper_state_v4_live.json` — State snapshot
  - `logs/paper_v4_live_*.log` — Activity log
- **Check interval:** Elke 4 uur (UTC 00:00, 04:00, 08:00, etc.)

### State Structuur
```json
{
  "positions": {"PAIR/USD": {"entry_price": 0.0, "volume": 0.0, "stop": 0.0, ...}},
  "total_pnl": 0.0,
  "wins": 0,
  "losses": 0,
  "closed_trades": 0,
  "checks": 0,
  "backfill_done": true
}
```

---

## 10. OPENSTAANDE BESLISSINGEN

### Strategie Upgrade
De data wijst naar **V5 + VolSpk 3.0x** als optimale configuratie:
| Metric | Huidige (V5 RSI45, VolSpk 2.0x) | Beste (V5 RSI45, VolSpk 3.0x) | Verschil |
|--------|----------------------------------|-------------------------------|----------|
| P&L | $+2,882 | $+3,820 | +$938 |
| PF | 2.1 | 3.0 | +0.9 |
| WR | 47.8% | 55.0% | +7.2% |
| DD | 75.3% | 31.4% | -43.9% |
| Trades | 46 | 40 | -6 |

**Trade-off:** 6 minder trades, maar significant betere kwaliteit.

### Nog te beslissen:
1. VolSpk 3.0x activeren in productie? (sterk bewijs)
2. Break-even stop verwijderen? (bewezen nuleffect)
3. MEXC API keys invoeren voor multi-exchange?
4. V5 paper trader naast V4 starten?
5. Bull strategy ontwikkelen? (geparkeerd)
6. Cycle detector implementeren? (geparkeerd)

---

## 11. COMPOSITE SCORE FORMULE

```python
# Normaliseer naar 0-1 range
pnl_n = min(1, max(0, (total_pnl + 2000) / 8000))      # P&L: -2000 tot +6000 → 0 tot 1
pf_n  = min(1, max(0, (pf - 0.5) / 9.5))               # PF: 0.5 tot 10 → 0 tot 1
wr_n  = wr / 100                                        # WR: 0-100% → 0 tot 1
dd_p  = max(0, 1 - max_dd / 50)                         # DD: 0% = 1, 50%+ = 0 (penalty)
tr_n  = min(1, len(trades) / 50)                        # Trades: 0-50 → 0 tot 1

# Gewogen composite score (max 100)
score = pnl_n * 35 + pf_n * 20 + wr_n * 15 + dd_p * 20 + tr_n * 10
```

---

## 12. V5 RAPPORT SAMENVATTING (250+ GETESTE CONFIGS)

### Uit het nachtwerk (4 scripts, 250+ configs):

#### Entry Filters — Meestal schadelijk
- ADX filter: SLECHTER (filtert goede trades weg met VolConfirm aan)
- RSI < 35: Iets betere WR maar verliest trades
- RSI < 30: Te restrictief
- Higher Low filter: Filtert ALLES weg
- BB Squeeze: Niet compatibel
- Body/wick ratio: Filtert ZEUS weg
- Vol acceleration: Te weinig trades
- EMA filters: NULEFFECT in bear market

#### Exit Verbeteringen — Alleen RSI Recovery werkt
- RSI Recovery (47,2b): **WINNAAR** → +$158 P&L, WR 83%→92%
- Adaptive ATR: Geen effect
- StepTrail: Geen effect
- BE trigger variaties: Geen effect
- Profit target <15%: SCHADELIJK (capt ZEUS outlier)

#### Period Variaties — BB 2.0 is heilig
- DC=10-15: Hogere WR maar lager P&L
- DC=25-30: Slechter
- BB dev <2.0 of >2.0: Dramatisch slechter (cliff edges)

---

## 13. QUICK START VOOR NIEUWE SESSIE

### Belangrijkste bestanden om te lezen:
1. `strategy.py` — DualConfirmStrategy class (V4/V5 logica)
2. `kraken_client.py` — Dynamic coin discovery + Kraken API
3. `backtest_mega_compare.py` — ConfigurableStrategy + 30 configs
4. `bot.py` — Live bot architectuur
5. `V5_RAPPORT.md` — Uitgebreid testrapport

### Huidige productie-configuratie (V5):
```
Entry: DC+BB dual confirm | RSI<40 | VolSpike>2x | VolConfirm>1x
Exit: ATR 2.0x trail | BE+3% | TMax 10 bars | RSI Recovery target=45, min_bars=2
Portfolio: 1x$2000 all-in | Volume ranking
Coins: 532 dynamisch ontdekt via Kraken API
```

### Potentiële upgrade (bewezen door mega-backtest):
```
Wijziging: vol_spike_mult 2.0 → 3.0
Effect: +$938 P&L, +7.2% WR, -43.9% DD, PF 2.1→3.0
Trade-off: 6 minder trades (40 vs 46)
```

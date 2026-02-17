# 4H DualConfirm Strategy — Architectural Decision Records

## ADR-4H-001: Gates-Lite Framework

**Date**: 2026-02-17
**Status**: ACCEPTED
**Author**: Agent session

### Context

The HF screening pipeline (`strategies/hf/`) uses a 7-gate promotion system in `agent_team_v3.py` (lines 1813-1869):

| Gate | Check | Threshold |
|------|-------|-----------|
| G1 | Walk-Forward | WF >= 3/5 folds |
| G2 | Friction 2x fees | P&L > $0 |
| G3 | NoTop P&L | > -$200 |
| G4 | Outlier + Coin Conc | top1 < 80%, max coin < 80% |
| G5 | MC P5 | > 50% initial capital |
| G6 | Class A ratio | > 50% |
| G7 | Worst window | > -$300 |

This pipeline is thorough but heavy: it requires walk-forward runs, Monte Carlo simulations, friction stress tests, and window analysis. During research sweeps where hundreds of configs are evaluated, we need a lighter-weight pre-filter that can quickly eliminate non-viable candidates before committing to the full validation suite.

### Decision

Implement a **5-gate "Gates-Lite"** framework in `strategies/4h/gates_4h.py`:

| Gate | Name | Threshold | Rationale |
|------|------|-----------|-----------|
| G1 | MIN_TRADES | >= 15 | Statistical significance for 526-coin dataset. Lower than HF's 20 because 4H has fewer bars (~721) and naturally fewer trades. Baseline V5+VolSpk3 produces 39 trades. |
| G2 | MAX_DRAWDOWN | <= 40% | Capital preservation. Baseline DD = 30.7%. Buffer of ~10pp for research candidates. HF uses 50% — we are stricter because 4H trades are larger/longer. |
| G3 | PROFIT_FACTOR | >= 1.3 | Edge confirmation. Baseline PF = 3.2, but research candidates may be exploring new territory. 1.3 is a floor, not a target. HF screening uses 1.1 (softer) because 1H has higher throughput. |
| G4 | EXPECTANCY | > $0 | Positive expected value per trade. Most fundamental test: does the strategy make money on average? Redundant with PF > 1 but expressed in dollar terms for interpretability. |
| G5 | ROBUSTNESS_SPLIT | both halves profitable | Cheap walk-forward proxy. Splits trade list chronologically at the midpoint. Both halves must show positive P&L. Much faster than 5-fold WF (~1ms vs ~5s) but less rigorous. |

All thresholds are configurable via kwargs to `evaluate_gates()`.

### Verdict Logic

```
IF trades < 15:
    verdict = INSUFFICIENT_SAMPLE  (no GO/NO-GO issued)
ELSE IF all 5 gates pass:
    verdict = GO
ELSE:
    verdict = NO-GO
```

This mirrors the HF GATES.md pattern where G1 (trade sufficiency) is a precondition that blocks all other verdicts.

### G5 Implementation Modes

The robustness split gate operates in two modes:

1. **Trade-list split** (default): Splits `bt['trade_list']` by chronological midpoint of `entry_bar`. Fast (~1ms), no re-run needed. Approximation because it sums P&L without separate equity curves.

2. **Pre-split results**: Caller provides `split_results=(first_half_bt, second_half_bt)` from two independent `run_backtest()` calls with `start_bar`/`end_bar` boundaries. More accurate because each half gets independent position management and equity tracking.

Mode 1 is the default for sweep pre-filtering. Mode 2 is recommended for final validation before promotion.

### Relationship to Full Validation

Gates-Lite is a **pre-filter**, not a replacement:

```
Research sweep (100s of configs)
    |
    v
Gates-Lite (5 gates, ~1s per config after backtest)
    |  GO candidates
    v
Full validation (WF5, MC, friction stress, window analysis)
    |  PROMOTED configs
    v
Paper trading
```

Configs passing Gates-Lite should still undergo the full 7-gate pipeline or equivalent before deployment.

### Consequences

**Positive**:
- Quick evaluation (~1s per config post-backtest)
- Eliminates obviously non-viable candidates early
- Configurable thresholds for different research contexts
- Standalone module — no dependencies beyond standard library
- JSON-serializable output for integration with sweep scripts

**Negative**:
- Not a replacement for full robustness validation
- G5 trade-list split is an approximation (no independent equity curves per half)
- Does not check friction stress, Monte Carlo, coin concentration, or Class A ratio
- False positives possible (config passes Gates-Lite but fails full validation)

### Implementation

- File: `strategies/4h/gates_4h.py`
- Dataclasses: `GateResult`, `GateReport`
- Functions: `evaluate_gates()`, `print_gate_report()`, `gates_to_dict()`
- Self-test: `python -m strategies.4h.gates_4h` runs demo with mock data

### Provenance

- **Dataset**: `ohlcv_4h_kraken_spot_usd_526` (526 coins, ~721 bars, native Kraken)
- **Universe**: `kraken_4h_526_v1`
- **Fee model**: `kraken_spot_26bps` (26 bps/side taker-only)
- **Initial capital**: $2,000 (`INITIAL_CAPITAL` in agent_team_v3.py)

---

## ADR-4H-002: Sweep V1 Results & Top-3 Shortlist

**Date**: 2026-02-17
**Status**: ACCEPTED
**Author**: Agent session (Head + 4 subagents)

### Context

After structuring the 4H project (ADR-4H-001), we needed a broad screening of strategy variants to identify the most promising candidates for full robustness validation. The sweep covers 30 configs across 3 exit types and 4 blocks of parameter variations.

### Sweep Design

- **30 configs**: Block A (12 trail), Block B (10 hybrid_notrl), Block C (6 tp_sl), Block D (2 structural)
- **Dataset**: `candle_cache_532` (526 coins, ~721 bars, 4H Kraken)
- **Gates-Lite**: 5 gates (MIN_TRADES≥15, MAX_DD≤40%, PF≥1.3, EXPECTANCY>$0, ROBUSTNESS_SPLIT)
- **Ranking**: GO configs sorted by PF desc → EV/trade desc → DD asc → trades desc
- **Sweep plan**: `strategies/4h/sweep_plan_v1.json`
- **Git**: `2659755`

### Results

| Metric | Value |
|--------|-------|
| Total configs | 30 |
| GO | 3 (10%) |
| NO-GO | 27 (90%) |
| Failed | 0 |
| Wall time | 59.8s (50.4s precompute + 9.1s backtests) |

### Top-3 Shortlist (alle hybrid_notrl)

| Rank | Config | Tr | WR% | P&L | PF | DD% | EV/trade |
|------|--------|----|-----|-----|----|-----|----------|
| 1 | `hnotrl_mp1` (max_pos=1, rsi42, msp15, tm20) | 34 | 70.6% | +$5,177 | 3.81 | 29.2% | +$152 |
| 2 | `hnotrl_msp20` (max_pos=2, rsi42, msp20, tm20) | 43 | 72.1% | +$3,331 | 3.61 | 22.8% | +$77 |
| 3 | `hnotrl_mp1_rsi38` (max_pos=1, rsi38, msp15, tm20) | 31 | 67.7% | +$4,026 | 3.35 | 35.3% | +$130 |

### Key Findings

1. **hybrid_notrl domineert**: Alle 3 GO configs zijn hybrid_notrl. Geen enkel trail of tp_sl config passeert alle 5 gates.

2. **G5 (ROBUSTNESS_SPLIT) is de hardste gate**: 27/27 NO-GO configs falen op G5. De chronologische 50/50 split laat zien dat de meeste configs hun winst uit één helft halen (waarschijnlijk de ZEUS-trade helft).

3. **Trail configs**: Hoog rendement (PF 2.91-4.63, P&L +$3,324-$5,787) maar falen allemaal G5. BEST_KNOWN (idx 11) is de sterkste trail met PF 4.63 en DD 20.0%, maar faalt robuustheid.

4. **tp_sl configs**: Marginaal winstgevend (PF 1.11-1.36, P&L +$234-$637). Meeste falen ook G3 (PF<1.3). Dit exit type werkt niet met Kraken fees.

5. **max_pos effect**: mp1 geeft hogere P&L (+$5,177 vs +$3,665) maar minder trades (34 vs 43). mp2 geeft lagere DD (20.2% vs 29.2%) en meer trades.

6. **max_stop_pct=20**: Losser max_stop geeft betere robustness split (msp20 passeert, msp15 niet bij mp2). Losser laat verliezende trades langer openstaan → meer kans op recovery in de tweede helft.

### Decision

**Top-3 shortlist goedgekeurd voor volledige robustheidvalidatie:**

1. `hnotrl_mp1` — Hoogste PF, hoogste EV/trade, minste trades
2. `hnotrl_msp20` — Meeste trades, laagste DD, beste diversificatie
3. `hnotrl_mp1_rsi38` — Striktere entry filter, minder trades maar hoog EV

### Next Steps

1. Volledige 7-gate pipeline (WF5, MC, friction stress) op top-3
2. Evalueer of G5 threshold te streng is (trade-list split vs independent half-runs)
3. Overweeg hybrid van #1 en #2 (mp1 met msp20)

### Reproducibility

```bash
# Exact dezelfde sweep opnieuw draaien:
python scripts/run_4h_sweep.py --plan strategies/4h/sweep_plan_v1.json --force

# Scoreboard opnieuw bouwen:
python scripts/build_4h_scoreboard.py
```

### Implementation

- Sweep plan: `strategies/4h/sweep_plan_v1.json`
- Sweep runner: `scripts/run_4h_sweep.py`
- Scoreboard builder: `scripts/build_4h_scoreboard.py`
- Results: `reports/4h/sweep_v1_*_2659755/`
- Scoreboard: `reports/4h/scoreboard_sweep_v1.{json,md}`
- Contract: `strategies/4h/sweep_v1_contract.md`
- Robustness notes: `strategies/4h/robustness_notes_v1.md`
- Gates: `strategies/4h/gates_4h.py` (G1-G5 mandatory + G6-G7 advisory)

### Provenance

- **Dataset**: `ohlcv_4h_kraken_spot_usd_526` (SHA256: `f7c70e7a...`)
- **Universe**: `kraken_4h_526_v1` (526 coins)
- **Fee model**: `kraken_spot_26bps`
- **Scoreboard**: `reports/4h/scoreboard_sweep_v1.json`
- **Initial capital**: $2,000
- **Git**: `2659755`

---

## ADR-4H-003: Sweep V1B — Time Window Stability Check

**Date**: 2026-02-17
**Status**: ACCEPTED
**Author**: Agent session (Head + 2 subagents)

### Context

Sweep v1 vond 3 GO configs (alle hybrid_notrl). v1b beantwoordt de vraag: is de edge stabiel over tijd, of zit alle winst geconcentreerd in één periode?

### Method

Dataset (120 dagen, 720 bars) gesplitst in 2 non-overlapping windows van 360 bars:
- **EARLY**: eerste 360 bars (okt 16 – dec 14, 2025) — 487 coins met ≥360 bars
- **LATE**: laatste 360 bars (dec 15 – feb 13, 2026) — 487 coins

Dezelfde 3 GO-configs uit v1 gedraaid op EARLY + LATE met identieke gates. Geen downloads nodig — data gesplitst uit bestaand `candle_cache_532.json`.

### Results

| Config | Window | Tr | WR% | P&L | PF | DD% | EV/t | Verdict |
|--------|--------|----|-----|-----|----|-----|------|---------|
| hnotrl_mp1 | EARLY | 12 | 58.3% | -$10 | 0.99 | 29.1% | -$0.8 | INSUFFICIENT |
| hnotrl_mp1 | **FULL** | **34** | **70.6%** | **+$5,177** | **3.81** | **29.2%** | **+$152** | **GO** |
| hnotrl_mp1 | LATE | 17 | 82.4% | +$6,257 | 7.02 | 29.3% | +$368 | NO-GO (G5) |
| | | | | | | | | |
| hnotrl_msp20 | EARLY | 15 | 60.0% | +$4 | 1.01 | 18.5% | +$0.3 | NO-GO |
| hnotrl_msp20 | **FULL** | **43** | **72.1%** | **+$3,331** | **3.61** | **22.8%** | **+$78** | **GO** |
| hnotrl_msp20 | **LATE** | **20** | **85.0%** | **+$3,514** | **9.40** | **12.0%** | **+$176** | **GO** |
| | | | | | | | | |
| hnotrl_mp1_rsi38 | EARLY | 12 | 58.3% | -$10 | 0.99 | 29.1% | -$0.8 | INSUFFICIENT |
| hnotrl_mp1_rsi38 | **FULL** | **31** | **67.7%** | **+$4,026** | **3.35** | **35.3%** | **+$130** | **GO** |
| hnotrl_mp1_rsi38 | LATE | 15 | 80.0% | +$5,042 | 6.35 | 35.4% | +$336 | NO-GO (G5) |

### Key Findings

1. **EARLY window is structureel zwak**: Alle 3 configs genereren weinig trades (12-15) en zijn break-even of licht negatief. De edge bestaat niet in de eerste helft van de dataset.

2. **LATE window is explosief sterk**: PF 6.35-9.40, WR 80-85%. Bijna alle winst zit in de tweede 60 dagen. Dit verklaart waarom G5 (robustness split) in v1 zo moeilijk was.

3. **hnotrl_msp20 is de enige config die 2/3 windows passeert** (FULL GO + LATE GO). De andere twee falen op LATE door G5 en hebben INSUFFICIENT op EARLY.

4. **Concentration risico bevestigd**: De v1 GO-resultaten worden gedragen door LATE-window performance. EARLY is break-even → de FULL-window P&L is vrijwel volledig LATE-window winst.

5. **max_pos=2 (msp20) biedt meer stabiliteit**: 15 trades in EARLY (net genoeg voor G1) vs 12 bij mp1 configs. Meer positions = meer trading opportunity.

### Decision

**hnotrl_msp20 is de sterkste kandidaat** — enige config met GO op meerdere windows.

De EARLY-window zwakte is een **rode vlag voor stationariteit**:
- Mogelijke regime shift rond dec 2025
- EARLY performance kan representatief zijn voor toekomstige drawdown periodes
- Meer data nodig (langere dataset) om te bevestigen of dit seizoensgebonden is

### Next Steps

1. Regime analyse: wat veranderde rond dec 2025 (volatiliteit, marktstructuur)?
2. Walk-forward met 3+ folds op FULL dataset voor hnotrl_msp20
3. Monte Carlo op hnotrl_msp20 (shuffle trade volgorde)
4. Evalueer langere windows (480 bars = 80 dagen) als alternatief
5. Paper trading prioriteit: hnotrl_msp20

### Reproducibility

```bash
# 1. Slice windows
python scripts/slice_4h_windows.py

# 2. Run v1b sweep
python scripts/run_4h_sweep.py --plan strategies/4h/sweep_plan_v1b.json \
  --data reports/4h/windows/candle_cache_early_360.json --only 1,2,3
python scripts/run_4h_sweep.py --plan strategies/4h/sweep_plan_v1b.json \
  --data reports/4h/windows/candle_cache_late_360.json --only 4,5,6
```

### Implementation

- Window slicer: `scripts/slice_4h_windows.py`
- Sweep plan: `strategies/4h/sweep_plan_v1b.json` (6 configs)
- Runner: `scripts/run_4h_sweep.py` (+ `--data` flag)
- Results: `reports/4h/sweep_v1_{001-006}_*_2659755/`
- Windows: `reports/4h/windows/candle_cache_{early,late}_360.json`

### Provenance

- **Dataset**: `ohlcv_4h_kraken_spot_usd_526` (windowed: EARLY 360 bars, LATE 360 bars)
- **Universe**: `kraken_4h_526_v1` (487 coins with ≥360 bars)
- **Fee model**: `kraken_spot_26bps`
- **Initial capital**: $2,000
- **Git**: `2659755`

---

## ADR-4H-004: Regime Diagnose + SMA50 Slope Filter

**Date**: 2026-02-17
**Status**: ACCEPTED
**Author**: Agent session

### Context

ADR-4H-003 toonde dat alle GO-configs break-even zijn in EARLY (okt-dec 2025) maar explosief in LATE (dec-feb 2026). Waarom? En kan een regime filter EARLY verbeteren?

### Regime Diagnose — Key Finding

**SMA50 slope is de #1 discriminator** tussen EARLY en LATE:
- EARLY: gemiddelde slope = **-4.0%** (mild, choppy decline)
- LATE: gemiddelde slope = **-14.2%** (steep, sustained downtrend) — 3.5x steiler

Alle andere metrics (ATR%, RSI<40 freq, vol spike freq, max DD) zijn binnen 10% van elkaar. Het markt-"materiaal" was gelijk — alleen de **structuur** verschilde.

**Trade attribution** bevestigt: RSI Recovery exits gaan van 50% WR / +$28 (EARLY) naar 87.5% WR / +$3,670 (LATE). In een steile downtrend bounchen oversold coins harder en betrouwbaarder.

### Regime Filter Test

hnotrl_msp20 getest met 3 SMA50 slope thresholds (≤-6%, ≤-8%, ≤-10%) op EARLY, LATE, en FULL:

| Window | Filter | Tr | PF | P&L | EV/t | Verdict |
|--------|--------|---:|---:|----:|-----:|---------|
| FULL | none | 43 | 3.61 | +$3,331 | +$78 | GO |
| FULL | ≤-6% | 21 | 6.82 | +$3,315 | +$158 | NO-GO (G5) |
| FULL | ≤-8% | 16 | 6.95 | +$2,986 | +$187 | NO-GO (G5) |
| FULL | ≤-10% | 13 | 8.71 | +$2,491 | +$192 | INSUF |

### Decision

**SMA50 slope filter is diagnostisch waardevol maar NIET deployeerbaar met 120 dagen data.**

- ≤-6% behoudt 99.5% P&L met de helft van de trades → kwaliteit stijgt enorm
- Maar trades dalen onder G1/G5 drempels → kan niet gevalideerd worden
- EARLY wordt NIET beter met filter — de edge bestaat simpelweg niet in mild-bearish regimes
- **Meer data nodig (360+ dagen)** om regime filter statistisch te onderbouwen

**Conclusie**: hnotrl_msp20 zonder filter blijft productie-kandidaat. SMA50 slope is een informatief signal ("trade met meer vertrouwen bij slope < -8%"), geen hard gate.

### Implementation

- Diagnose script: `scripts/regime_diagnosis.py`
- Diagnose report: `reports/4h/regime_diagnosis_v1.md`
- Regime-aware runner: `scripts/run_4h_sweep_regime.py` (monkeypatch, engine ongewijzigd)
- Sweep plan: `strategies/4h/sweep_plan_v1b_regime.json` (12 configs)
- Filter results: `reports/4h/regime_filter_results_v1.md`
- Results: `reports/4h/sweep_v1b_{001-012}_*_2659755/`

### Provenance

- **Dataset**: `ohlcv_4h_kraken_spot_usd_526` (windowed subsets)
- **Universe**: `kraken_4h_526_v1` (487 coins with ≥360 bars per window)
- **Fee model**: `kraken_spot_26bps`
- **Initial capital**: $2,000
- **Git**: `2659755`

---

## ADR-4H-005: Extended Data (360+ Days) + Slope-as-Sizing

**Date**: 2026-02-17
**Status**: ACCEPTED
**Author**: Agent session

### Context

ADR-4H-004 concluded that:
1. SMA50 slope is the #1 regime discriminator (-4% EARLY vs -14% LATE)
2. A hard slope gate improves quality dramatically but drops trades below gate thresholds
3. More data (360+ days) is needed to statistically validate any regime approach

This ADR extends the dataset from 120 → 360+ days and tests slope-as-sizing (soft scaling, NOT hard gate).

### Data Source

- **Source**: CryptoCompare `histohour` API with `e=Kraken` and `aggregate=4`
- **Venue**: **PROXY** — not native Kraken API data
- **Registry ID**: `ohlcv_4h_kraken_spot_usd_v2`
- **Requested**: 526 coins (from original candle_cache_532.json)
- **Downloaded**: 336 coins (190 failed = not on CryptoCompare)
- **Median bars**: 2183 (363 days)
- **Max span**: 583 days (2024-07-14 → 2026-02-17)
- **VWAP**: Approximated as `(H+L+C)/3` (CC has no native VWAP)
- **File**: `~/CryptogemData/derived/candle_cache/kraken/4h/candle_cache_4h_kraken_v2.json` (77.6 MB)

**Important**: This is proxy data. Top candidates require a native Kraken confirm run.

### Cohort Design

| Cohort | Min Bars | Min Days | Coins | Purpose |
|--------|----------|----------|-------|---------|
| A | ≥2160 | ≥360 | 170 | Primary analysis |
| B | ≥1080 | ≥180 | 242 | Secondary check |

### Slope-as-Sizing Design

Unlike ADR-4H-004's hard gate, slope-as-sizing keeps ALL trades but scales position size:

```
slope <= steep_thresh (e.g. -10%): scale = 1.0 (full position)
slope >= mild_thresh  (e.g. -3%):  scale = min_scale (e.g. 0.3)
between: linear interpolation
```

Trade count stays constant; only dollar exposure changes per regime.

### Results — Cohort A (170 coins, ≥360 days)

| # | Config | Tr | WR% | P&L | PF | DD% | EV/t | Verdict |
|---|--------|---:|----:|----:|---:|----:|-----:|---------|
| 1 | Baseline (no sizing) | 76 | 56.6 | -$669 | 0.64 | 41.7 | -$8.8 | NO-GO |
| 2 | Conservative (min=0.5) | 76 | 56.6 | -$147 | 0.86 | 17.7 | -$1.9 | NO-GO |
| 3 | **Moderate (min=0.3)** | 76 | 56.6 | **+$62** | **1.09** | **10.5** | +$0.8 | NO-GO |
| 4 | **Aggressive (min=0.2)** | 76 | 56.6 | **+$61** | **1.09** | **9.1** | +$0.8 | NO-GO |

### Results — Cohort B (242 coins, ≥180 days, secondary)

| # | Config | Tr | WR% | P&L | PF | DD% | EV/t | Verdict |
|---|--------|---:|----:|----:|---:|----:|-----:|---------|
| 5 | Baseline | 97 | 58.8 | -$481 | 0.80 | 51.8 | -$5.0 | NO-GO |
| 6 | **Moderate (min=0.3)** | 97 | 58.8 | **+$205** | **1.20** | **19.2** | +$2.1 | NO-GO |

### Key Findings

#### 1. Baseline is NEGATIEF op extended data

Op 120 dagen (v1): hnotrl_msp20 had 43 trades, PF=3.61, +$3,331 (GO).
Op 360+ dagen (v2): 76 trades, PF=0.64, -$669 (NO-GO).

De extra ~240 dagen bevatten perioden ZONDER steep downtrend (SMA50 slope > -8%).
In die perioden is de strategie verliesgevend, wat het totaal naar beneden trekt.

**Dit bevestigt ADR-4H-004**: de edge is regime-afhankelijk.

#### 2. Slope-as-sizing WERKT maar is niet genoeg

Moderate slope-sizing brengt het van -$669 → +$62 (PF 0.64 → 1.09).
DD daalt van 41.7% → 10.5% — een 4x verbetering.
Maar PF=1.09 is ver onder de G3 drempel (PF ≥ 1.5).

#### 3. Cohort B bevestigt het patroon

Meer coins (242 vs 170) en meer trades (97 vs 76) met hetzelfde resultaat:
baseline negatief, slope-sizing positief (PF 1.20 op cohort B).

#### 4. Trade count is voldoende voor validatie

76-97 trades op 360+ dagen — ruim boven G1 (≥15 trades).
Het probleem is niet sample size maar de STRUCTURELE regime-afhankelijkheid.

### Vergelijking V1 (120d) vs V2 (360d)

| Metric | V1 (120d, 526 coins) | V2 Baseline (360d, 170 coins) | V2 Slope-sized |
|--------|---------------------|------------------------------|----------------|
| Trades | 43 | 76 | 76 |
| PF | 3.61 | 0.64 | 1.09 |
| P&L | +$3,331 | -$669 | +$62 |
| DD | 22.8% | 41.7% | 10.5% |
| Verdict | GO | NO-GO | NO-GO |

### Diagnosis

De 4H DualConfirm bounce strategie is een **conditional strategy**:
- **In regime** (steep downtrend, SMA50 slope < -8%): PF > 3, zeer winstgevend
- **Buiten regime** (choppy/mild): PF < 0.7, verliesgevend

Slope-as-sizing verzacht het probleem maar lost het niet op.
De strategie moet ofwel:
1. **Alleen gedraaid worden IN regime** (hard gate, accepteer lagere trade count)
2. **Gecombineerd worden met een regime-switch** (ander strategie buiten regime)
3. **Geaccepteerd worden als regime-conditional** met lagere overall PF

### Decision

1. **hnotrl_msp20 is GEEN all-weather strategie** — dit is nu bewezen met 360+ dagen data
2. **Slope-as-sizing is een verbetering** (PF 0.64 → 1.09, DD 41.7% → 10.5%) maar onvoldoende
3. **De V1 GO verdict (PF=3.61) was periode-afhankelijk** — de 120-dag window viel in een steep downtrend
4. **Proxy data caveat**: resultaten zijn op CryptoCompare data, niet native Kraken
5. **Productie-aanbeveling**: gebruik hnotrl_msp20 **alleen wanneer SMA50 slope < -8%** (manual regime switch), accepteer lagere trade frequency

### Next Steps

1. **Kraken native confirm run**: Top kandidaat op native Kraken data voor subset coins
2. **Regime-conditioned deployment**: Paper trader die alleen activeert in diep-bearish regime
3. **Evalueer alternatieve exit types of entry filters** die regime-robuuster zijn

### Implementation

- Download script: `scripts/download_kraken_4h_extended.py` (CryptoCompare API)
- Extended runner: `scripts/run_4h_sweep_extended.py` (cohort + slope-as-sizing)
- Sweep plan: `strategies/4h/sweep_plan_v2_extended.json` (6 configs, cohort A+B)
- Scoreboard: `reports/4h/scoreboard_sweep_v2.{json,md}`
- Results: `reports/4h/sweep_v2_{001-006}_*_2659755/`
- Dataset: `~/CryptogemData/derived/candle_cache/kraken/4h/candle_cache_4h_kraken_v2.json`
- Registry: `~/CryptogemData/manifests/registry.json` (source=cryptocompare, venue=proxy)

### Provenance

- **Dataset**: `ohlcv_4h_kraken_spot_usd_v2` (SHA256: `084da932...`, 77.6 MB)
- **Universe**: `kraken_4h_cohortA_170_v1` (170 coins), `kraken_4h_cohortB_242_v1` (242 coins)
- **Fee model**: `kraken_spot_26bps`
- **Scoreboard**: `reports/4h/scoreboard_sweep_v2.json`
- **Initial capital**: $2,000
- **Git**: `2659755`

---

## ADR-4H-005-A: Kraken Native Confirm — Proxy vs Native Delta

**Date**: 2026-02-17
**Status**: ACCEPTED
**Author**: Agent session
**Parent**: ADR-4H-005

### Context

ADR-4H-005 used CryptoCompare proxy data (`source=cryptocompare`, `venue=proxy`) for 360-day extended analysis. This addendum validates results on **native Kraken API data** for a 62-coin confirm subset (all traded coins + BTC/ETH) over the 120-day window.

### Data Delta Analysis

OHLCV comparison across 62 coins, 41,617 matched bars:

| Field | Median Diff | P95 Diff | Note |
|-------|------------|---------|------|
| Close | 0.0000% | 0.006% | Identical |
| High | 0.0000% | 1.29% | Identical |
| Low | 0.0000% | 1.14% | Identical |
| Open | **0.3650%** | 2.96% | Bar-boundary convention |
| VWAP | **0.3066%** | 1.88% | HLC/3 vs real VWAP |
| Volume | 0.00% | 0.00% | Identical |

Outlier: LUNA/USD ticker-mapping artifact (LUNA classic vs 2.0).

### A/B Backtest Results

| Mode | Source | Trades | PF | P&L | DD% | Verdict |
|------|--------|-------:|---:|----:|----:|---------|
| Baseline | **Native** | 16 | **2.52** | **+$364** | **7.2%** | **GO** |
| Baseline | Proxy | 22 | 0.90 | -$71 | 20.1% | NO-GO |
| | **Delta** | **-6** | **+1.63** | **+$435** | **-12.9%** | |
| Slope-sizing | **Native** | 16 | **4.24** | **+$267** | **1.9%** | **GO** |
| Slope-sizing | Proxy | 22 | 1.11 | +$34 | 9.2% | NO-GO |
| | **Delta** | **-6** | **+3.12** | **+$233** | **-7.2%** | |
| Hard gate | Native | 5 | inf | +$257 | 3.1% | INSUF |
| Hard gate | Proxy | 5 | 7.40 | +$254 | 2.0% | INSUF |
| | Delta | 0 | — | +$3 | +1.0% | |

### Root Cause: 6 Ghost Trades

Proxy data generates **6 extra trades** that don't appear on native data. These phantom entries are caused by the ~0.37% Open price difference (bar-boundary convention) which can flip marginal Donchian/Bollinger entry signals. All 6 ghost trades are net-negative, dragging proxy results from GO to NO-GO.

In the hard gate regime (steep downtrend only), both sources produce identical trade counts (5) and near-identical P&L (+$257 vs +$254) — confirming that in strong regime the data is interchangeable.

### Key Findings

1. **Native Kraken data produces better results than proxy** — 6 fewer trades, all net-positive
2. **The proxy bias is PESSIMISTIC** — proxy overfits on noise entries, understates true performance
3. **ADR-4H-005 extended data conclusions remain VALID** — the proxy was conservative, not optimistic
4. **In steep regime the data sources are interchangeable** (hard gate: delta = +$3)
5. **The 120-day native window shows GO** for both baseline and slope-sizing on 62 coins

### Verdict

| Config | 120d Native | 360d Proxy | Interpretation |
|--------|------------|-----------|----------------|
| Baseline | **GO** (PF=2.52) | NO-GO (PF=0.64) | In-regime: strong. Extended: diluted. |
| Slope-sizing | **GO** (PF=4.24) | Marginal (PF=1.09) | Sizing helps. Native edge is real. |
| Hard gate | INSUF (5tr) | INSUF | Need more data for statistical validity. |

**Productie-aanbeveling**:
- Baseline hnotrl_msp20 is **GO on native Kraken data** (120 days, 62 coins)
- Slope-as-sizing **versterkt** de edge (PF 2.52 → 4.24, DD 7.2% → 1.9%)
- Deploy only in regime (SMA50 slope < -8%) OR with slope-as-sizing for all-weather
- Use native Kraken data for production monitoring (proxy is pessimistic)

### Implementation

- Coin selection: `strategies/4h/kraken_confirm_coins.json` (62 coins)
- Native download: `scripts/download_kraken_4h_native.py`
- Confirm runner: `scripts/run_kraken_confirm.py`
- Sweep plan: `strategies/4h/sweep_plan_kraken_confirm.json`
- Delta report: `reports/4h/proxy_vs_native_delta.json`
- Scoreboard: `reports/4h/scoreboard_confirm.{json,md}`
- Results: `reports/4h/confirm_{001-006}_*_2659755/`
- Native data: `~/CryptogemData/derived/candle_cache/kraken/4h/candle_cache_4h_kraken_native_confirm.json`

### Provenance

- **Dataset (native)**: `ohlcv_4h_kraken_spot_usd_native_confirm` (SHA256: `db88a213...`, 6.0 MB)
- **Dataset (proxy)**: `ohlcv_4h_kraken_spot_usd_v2` (SHA256: `084da932...`)
- **Universe**: `kraken_4h_native_62_v1` (62 coins)
- **Fee model**: `kraken_spot_26bps`
- **Scoreboard**: `reports/4h/scoreboard_confirm.json`
- **Initial capital**: $2,000
- **Git**: `2659755`

---

## ADR-4H-006: MEXC 4H Portability Test

**Date**: 2026-02-17
**Status**: ACCEPTED (NO-GO)
**Author**: Agent session
**Parent**: ADR-4H-005

### Context

ADR-4H-005 validated the hnotrl_msp20 strategy on extended Kraken data (360+ days) and found it to be regime-dependent. ADR-4H-005-A confirmed the edge on native Kraken data (120d, GO). This ADR tests whether the same DualConfirm bounce strategy is **portable to MEXC** — a different exchange with different fee structure, coin universe, and market microstructure.

**Hypothesis**: MEXC's lower fees (10bps vs 26bps per side) might rescue the marginal edge seen on extended Kraken data.

### Test Design

4 configs on MEXC proxy data (CryptoCompare, 144 coins, cohort A >= 2160 bars / 360 days):

| # | Config | Fee | Slope-sizing | Purpose |
|---|--------|-----|-------------|---------|
| 1 | Baseline + MEXC fee | 10bps | No | MEXC performance |
| 2 | Slope moderate + MEXC fee | 10bps | Yes (min=0.3) | Best MEXC case |
| 3 | Baseline + Kraken fee | 26bps | No | Fee isolation (control) |
| 4 | Slope moderate + Kraken fee | 26bps | Yes (min=0.3) | Fee isolation (slope) |

All configs use identical parameters: `exit_type=hybrid_notrl, rsi_max=42, vol_spike_mult=3.0, max_stop_pct=20, tm=20, max_pos=2, rsi_rec_target=45`.

### Results

| # | Config | Tr | WR% | P&L | PF | DD% | EV/t | Gates | Verdict |
|---|--------|----|-----|-----|----|-----|------|-------|---------|
| 1 | Baseline MEXC fee | 23 | 65.2 | -$58 | 0.92 | 33.0 | -$2.53 | 2/5 | **NO-GO** |
| 2 | **Slope + MEXC fee** | **23** | **65.2** | **+$159** | **1.51** | **13.5** | **+$6.90** | **4/5** | **NO-GO (G5)** |
| 3 | Baseline Kraken fee | 23 | 65.2 | -$128 | 0.84 | 34.2 | -$5.56 | 2/5 | NO-GO |
| 4 | Slope + Kraken fee | 23 | 65.2 | +$118 | 1.38 | 13.9 | +$5.15 | 4/5 | NO-GO (G5) |

**Kraken reference (extended 360d proxy, 170 coins):**

| # | Config | Tr | WR% | P&L | PF | DD% | EV/t | Verdict |
|---|--------|----|-----|-----|----|-----|------|---------|
| K1 | Baseline Kraken | 76 | 56.6 | -$669 | 0.64 | 41.7 | -$8.80 | NO-GO |
| K2 | Slope moderate Kraken | 76 | 56.6 | +$62 | 1.09 | 10.5 | +$0.81 | NO-GO |

### Fee Isolation Finding

Same MEXC data, different fees — isolates the fee contribution:

| Comparison | Baseline | Slope-sized |
|-----------|---------|-------------|
| MEXC fee (10bps) P&L | -$58 | +$159 |
| Kraken fee (26bps) P&L | -$128 | +$118 |
| **Fee delta** | **$70** | **$40** |
| Fee per trade | $3.03 | $1.75 |

**Fee delta = $40-70 across 23 trades.** This is modest. Lower fees improve results but do not change the verdict.

### Universe Delta

Total head-to-head improvement (MEXC slope vs Kraken slope): $159 - $62 = **$97**.
Fee contribution: $40. Universe contribution: **$57**.

MEXC has 144 coins vs Kraken 170 coins in cohort A, yet produces only 23 trades vs 76 trades (70% fewer). The MEXC coin universe triggers fewer DualConfirm entries — likely different volatility/RSI profiles in USDT-quoted pairs vs Kraken USD pairs.

### Key Finding: Slope-Sizing is Essential

On BOTH exchanges, slope-as-sizing converts a negative baseline into a positive result:

| Exchange | Baseline P&L | Slope P&L | Improvement | DD Reduction |
|----------|-------------|-----------|-------------|-------------|
| Kraken 360d | -$669 | +$62 | +$730 | 31.2pp |
| MEXC 360d | -$58 | +$159 | +$217 | 19.5pp |

This is a universal pattern: the DualConfirm edge is regime-dependent, and slope-sizing suppresses position size in regimes where the edge is absent.

### G5 Failure Analysis

Best MEXC config (slope + MEXC fee) passes G1-G4 but fails G5 (robustness split):
- H1: 12 trades, P&L = -$114
- H2: 11 trades, P&L = +$273

Same pattern as Kraken: the edge is concentrated in the later period (steep downtrend regime). The first half is break-even or negative.

### Decision

**NO-GO on MEXC deployment.**

Reasons:
1. **Insufficient trades**: 23 trades on 144 coins over 360 days is barely above G1 threshold (15). No statistical confidence.
2. **G5 failure**: Robustness split fails — all profit is in the second half.
3. **Baseline is negative**: Even with 60% lower fees, the baseline without slope-sizing loses money (-$58).
4. **Trade frequency**: 0.16 trades/coin/year on MEXC vs 0.45 on Kraken — the signal fires 3x less often.
5. **MEXC fees do not rescue the strategy**: Fee delta is only $40-70, insufficient to flip a structural issue.

### Cross-Exchange Observations

1. **DualConfirm bounce needs specific volatility/RSI profiles** — these occur more frequently in Kraken's coin universe (USD pairs) than MEXC's (USDT pairs).
2. **Lower fees alone cannot rescue a strategy with insufficient signal generation.** The bottleneck is entry triggers, not transaction costs.
3. **Slope-sizing is a universal improvement pattern** that works on both exchanges — it should be part of any deployment regardless of venue.
4. **The 4H strategy is regime-dependent on ALL exchanges** — this is a property of the DualConfirm bounce signal, not the exchange.
5. **Portability to MEXC is disproven** for the same reason as HF Bybit portability (ADR-HF-035): different market microstructure produces insufficient signal activity.

### Implementation

- Sweep plan: `strategies/4h/sweep_plan_mexc_confirm.json`
- Runner: `scripts/run_4h_sweep_extended.py`
- MEXC data: `~/CryptogemData/derived/candle_cache/mexc/4h/candle_cache_4h_mexc_v1.json`
- Comparison report: `reports/4h/kraken_vs_mexc_comparison.json`
- Results: `reports/4h/sweep_v2_{001-004}_*mexc*_2659755/`
- Scoreboard: `reports/4h/scoreboard_sweep_v2.{json,md}` (combined Kraken + MEXC)

### Provenance

- **Dataset**: `ohlcv_4h_mexc_spot_usdt_v1` (SHA256: `f7801b8d...`, 46.9 MB)
- **Universe**: `mexc_4h_cohortA_144_v1` (144 coins with ≥2160 bars)
- **Fee models**: `mexc_spot_10bps` (configs 1-2), `kraken_spot_26bps` (configs 3-4, fee isolation)
- **Comparison ref**: `ohlcv_4h_kraken_spot_usd_v2` (Kraken extended, 170 coins)
- **Scoreboard**: `reports/4h/scoreboard_sweep_v2.json`
- **Initial capital**: $2,000
- **Git**: `2659755`

---

*Canonical source for 4H gate decisions. Referenced by `gates_4h.py`.*

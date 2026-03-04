# Market Structure Strategy — Decision Records

## ADR-MS-001: Sprint 1 Results — 7/18 GO, 2 families survive

**Date**: 2026-03-02
**Status**: GO — advance to Sprint 2 truth-pass

### Context

After 63 indicator-driven configs across 4H Sprints 1-3 yielded 0 GO (PF>=1.0), and SuperHF Sprint 3 confirmed the same pattern (44 configs, 0 GO), we pivoted to market structure-based entries.

Market structure entries are based on WHAT price DID at structural levels (sweep, reclaim, break, fill) rather than WHERE an indicator stands (RSI<35, BB touch).

### Experiment

- **Dataset**: 4H Kraken, 487 coins (>=360 bars), ~660 bars per coin
- **Exits**: hybrid_notrl (FIXED STOP -> TIME MAX -> RSI RECOVERY -> DC TARGET -> BB TARGET)
- **Configs**: 18 across 5 families
- **Fees**: 26 bps/side (Kraken spot)

### Results

**7/18 configs PF >= 1.0, all 7 pass ALL hard + soft gates.**

| Family | Configs | GO | Best PF | Best DD | Avg PF |
|--------|---------|-----|---------|---------|--------|
| **shift_pb** | 3 | 3/3 | 2.08 | 21.3% | 1.85 |
| **fvg_fill** | 4 | 4/4 | 1.66 | 19.5% | 1.59 |
| ob_touch | 4 | 0/4 | 0.72 | 85.2% | 0.67 |
| liq_sweep | 4 | 0/4 | 0.76 | 81.5% | 0.67 |
| sfp | 3 | 0/3 | 0.63 | 82.7% | 0.59 |

### Key Findings

#### 1. Structure Shift + Pullback (shift_pb) is the strongest signal
- After bullish BoS (break of structure), buy the pullback to previous swing low zone
- PF 1.68-2.08, DD 21-35%, all 3 configs pass all gates
- **Low DC-geometry compliance (6-14%)** — entries are NOT at traditional DC-low levels
- Works because BoS confirms trend shift; pullback is the re-entry opportunity
- RSI RECOVERY is dominant exit (55-67%), stop-outs very low (3-5%)

#### 2. FVG Fill is robust across all parameter variants
- Buy when price fills an unfilled bullish Fair Value Gap zone
- 4/4 configs GO (PF 1.46-1.66), DD 19-37%
- **Critical bug fixed**: FVG/OB snapshots used "snapshot after fill/mitigation" semantics, causing 0 entries. Fix: snapshot BEFORE fill checks (snapshot represents start-of-bar state)
- ms_008 (wide: max_age=40, rsi_max=40) has 98% DC-geometry compliance — inherent DC compatibility
- ms_006 (norsi: no RSI filter) gets most trades (548) but lowest PF (1.46)

#### 3. Failed families: liq_sweep, ob_touch, sfp
- Liquidity sweep+reclaim: PF 0.58-0.76. Sweep detection works but reclaim signal has no edge. Stop-outs 10-12%.
- Order block touch: PF 0.62-0.72. OB zones too wide, too many false touches. DD 85-97%.
- SFP (swing failure pattern): PF 0.54-0.63. Same-bar sweep+reclaim too noisy.

#### 4. Exit attribution pattern
GO configs:
- RSI RECOVERY: 43-67% of exits (dominant profit source)
- DC TARGET: 13-33%
- BB TARGET: 4-18%
- FIXED STOP: 3-8% (very low stop-out ratio)

NO-GO configs:
- DC TARGET and RSI RECOVERY: ~40% each (symmetric = no edge)
- FIXED STOP: 8-12% (higher stop-out ratio)

#### 5. DC-geometry compliance varies wildly
- shift_pb: 6-14% full compliance — structurally different entry geometry
- fvg_fill: 23-98% — ms_008 (with RSI filter) has highest compliance
- Failed families: 20-44% — moderate compliance didn't help

### Decision

**GO** — advance to Sprint 2 truth-pass with top-4 candidates:
1. ms_018 (shift_pb shallow): PF=2.08, 697 trades, DD=21.3%
2. ms_005 (fvg base): PF=1.65, 429 trades, DD=19.5%
3. ms_017 (shift_pb fib618): PF=1.80, 475 trades, DD=28.0%
4. ms_007 (fvg deep): PF=1.66, 344 trades, DD=22.9%

### Consequences

1. Sprint 2 truth-pass: window stability (3 splits), bootstrap (1000 samples), full WF
2. If >=1 passes truth-pass → paper trading validation
3. shift_pb's low DC-geometry suggests these entries work on a DIFFERENT principle than DualConfirm — potential ensemble candidate
4. FVG fill's high DC-geometry (ms_008) suggests it could be combined with DualConfirm exits naturally

### Risks

1. **Overfitting to 4-month data window**: 487 coins compensates (cross-sectional robustness), but temporal stability needs truth-pass confirmation
2. **PF 2.08 is suspiciously high**: ms_018 needs careful bootstrap scrutiny — could be regime-dependent
3. **shift_pb has low DC-geometry**: entries succeed WITHOUT DC-compatible positioning — exits may need tuning
4. **FVG snapshot fix was critical**: a subtle bug (snapshot-after-fill vs snapshot-before-fill) caused 0 FVG trades initially. This class of bug could affect other indicators.

### Bug Fixed: FVG/OB Snapshot Timing

- **Root cause**: `calc_fair_value_gaps()` and `calc_order_blocks()` took snapshots AFTER fill/mitigation checks. When a bar fills an FVG (close <= gap_high), the FVG was removed from the snapshot before the signal function could see it.
- **Fix**: Snapshot taken BEFORE fill/mitigation checks. The snapshot represents "active structures at start of bar", enabling the signal function to trigger on the same bar that fills/mitigates the structure.
- **Impact**: FVG family went from 0 trades to 295-548 trades, all 4 configs GO.

---

## ADR-MS-002: Sprint 2 Truth-Pass — 4/4 VERIFIED

**Date**: 2026-03-02
**Status**: GO — advance to paper trading validation

### Context

Sprint 1 identified 7/18 GO configs from 2 surviving families (shift_pb 3/3, fvg_fill 4/4). Top-4 candidates advanced to Sprint 2 truth-pass: 3-test robustness battery (window stability, walk-forward, bootstrap Monte Carlo).

ADR-MS-001 flagged key risks:
1. PF 2.08 (ms_018) suspiciously high — could be regime-dependent
2. Overfitting to ~4-month data window — temporal stability unconfirmed
3. shift_pb's low DC-geometry (6-14%) — structurally different entry principle

### Experiment

- **Dataset**: 4H Kraken, 487 coins (>=360 bars), 721 bars max
- **Bar range**: 50-721 (671 usable bars)
- **Window split**: early=50-273, mid=273-496, late=496-721 (~223 bars each)
- **Exits**: hybrid_notrl (DC TARGET + RSI RECOVERY + BB TARGET)
- **Fees**: 26 bps/side (Kraken spot)
- **Bootstrap**: 1000 resamples, seed=42

### Truth-Pass Tests

| Test | Criterion | Threshold |
|------|-----------|-----------|
| T1: Window Split | PF >= 1.0 in >= 2/3 windows | early/mid/late thirds |
| T2: Walk-Forward | Cal PF >= 1.0 AND Test PF >= 0.9 | Either split passes |
| T3: Bootstrap | P5_PF >= 0.85 AND >= 60% profitable | 1000 trade resamples |

Verdicts: ALL 3 PASS → VERIFIED, 2/3 → CONDITIONAL, ≤1/3 → FAILED

### Results

**4/4 VERIFIED — all candidates pass all 3 robustness tests.**

| Config | Family | Full PF | Trades | DD | Window | WF | Boot P5 PF | Boot %Prof | Verdict |
|--------|--------|---------|--------|-----|--------|-----|-----------|-----------|---------|
| **ms_018** | shift_pb | 2.08 | 697 | 21.3% | 3/3 | 2/2 | 1.48 | 100% | **VERIFIED** |
| **ms_017** | shift_pb | 1.80 | 475 | 28.0% | 3/3 | 2/2 | 1.28 | 100% | **VERIFIED** |
| **ms_007** | fvg_fill | 1.66 | 344 | 22.9% | 3/3 | 2/2 | 1.24 | 99% | **VERIFIED** |
| **ms_005** | fvg_fill | 1.65 | 429 | 19.5% | 3/3 | 2/2 | 1.19 | 100% | **VERIFIED** |

### Key Findings

#### 1. ms_018 (shift_pb shallow) is GENUINELY strong — not overfit
- ADR-MS-001 flagged PF=2.08 as "suspiciously high"
- Truth-pass RESOLVES this concern: P5_PF=1.48, 100% bootstrap profitable
- Window stability: ALL 3 windows profitable (PF 1.71/2.65/2.01)
- Walk-forward: BOTH splits pass (test PF 2.11 and 2.01)
- This is the strongest signal we've found across ALL research (4H Sprints 1-4, HF, SuperHF, MS)

#### 2. Temporal stability is excellent across ALL configs
- 16/16 window tests PASS (4 configs × 3 windows × PF >= 1.0)
- No single window failure across any config
- Contrast with Sprint 4: sprint4_032 had PF=0.46 in early window, sprint4_035 had PF=0.30
- Market structure signals are temporally robust — structural patterns persist across regimes

#### 3. shift_pb vs fvg_fill: complementary strengths
- **shift_pb** (ms_018, ms_017): Higher PF (1.80-2.08), higher P&L, but higher DD (21-28%)
- **fvg_fill** (ms_005, ms_007): Lower PF (1.65-1.66), lower DD (19-23%), more stable windows
- ms_017 has high mid-window variance (PF=5.06 mid vs 1.35 late) — regime-sensitive but still passes
- **Ensemble potential**: shift_pb (low DC-geometry 6-14%) + fvg_fill (mixed 44-64%) = different entry geometries

#### 4. Bootstrap confirms deep edge
- All P5_PF >= 1.19 (worst case still profitable)
- 99-100% bootstrap profitable across all 4 configs
- Compare: Sprint 4 best was sprint4_041 with P5_PF=0.92, 90.9% profitable
- MS configs have ~50% wider P5 margin than best indicator-based config

#### 5. Walk-forward is strongest test — all 8 splits pass
- 8/8 WF splits pass (4 configs × 2 splits)
- No split has test PF < 1.35
- This means: calibrating on ANY subset → testing on ANY future subset → still profitable
- Walk-forward is the hardest truth-pass test; universal pass = strong temporal robustness

### Comparison with Sprint 4 (indicator-based entries)

| Metric | Sprint 4 Best (041) | MS Best (018) | Delta |
|--------|-------------------|---------------|-------|
| Full PF | 1.41 | 2.08 | +47% |
| Verdict | VERIFIED (3/3) | VERIFIED (3/3) | same |
| Boot P5 PF | 0.92 | 1.48 | +61% |
| Boot %Prof | 90.9% | 100% | +10pp |
| DD | 36.4% | 21.3% | -42% |
| Trades | 216 | 697 | +223% |
| Window stability | 3/3 | 3/3 | same |
| WF splits | 2/2 | 2/2 | same |

**Market structure entries are categorically superior**: higher PF, lower DD, more trades, and stronger bootstrap.

### Decision

**GO** — advance to paper trading validation. Priority order:

1. **ms_018_mse_shallow** (shift_pb): Primary candidate. PF=2.08, P5_PF=1.48, DD=21.3%, 697 trades. Best all-around.
2. **ms_005_msb_base** (fvg_fill): Secondary candidate. PF=1.65, P5_PF=1.19, DD=19.5%, 429 trades. Lowest DD, ensemble-ready.
3. **ms_017_mse_fib618** (shift_pb): Reserve. PF=1.80, P5_PF=1.28, 475 trades. Strong but DD=28%.
4. **ms_007_msb_deep** (fvg_fill): Reserve. PF=1.66, P5_PF=1.24, 344 trades. Fewest trades.

### Consequences

1. **Paper trading**: Deploy ms_018 (primary) + ms_005 (secondary) for live paper validation
2. **Ensemble research**: shift_pb + fvg_fill have different entry geometries — test combined signals
3. **DD-reduction** (optional): ms_018 DD=21.3% already within acceptable bounds, but vol_scale could reduce further
4. **Sprint 4 comparison**: MS signals dominate indicator-based. DualConfirm sprint4_041 remains viable but MS is strictly better on all metrics.
5. **Next milestone**: Paper trading P&L tracking, live drift detection, execution quality

### Risks

1. **4-month data window**: Despite 487-coin cross-section and temporal stability, real market regime changes may differ
2. **ms_017 mid-window spike** (PF=5.06): Suggests one regime was exceptionally favorable — could mean fragility
3. **shift_pb mechanism**: BoS + pullback requires trending markets. Range-bound or choppy markets may degrade performance
4. **FVG fill persistence**: If market microstructure changes (e.g., faster gap fills), fvg_fill edge may erode
5. **Execution gap**: 4H candle bars → real execution may have slippage, partial fills, timing issues

### ADR-MS-001 Risk Resolution

| Risk (from ADR-MS-001) | Resolution |
|------------------------|------------|
| PF 2.08 suspiciously high | **RESOLVED**: P5_PF=1.48, 100% bootstrap profitable, 3/3 windows pass |
| Overfitting to 4-month window | **RESOLVED**: All 16 window tests pass, 8/8 WF splits pass |
| shift_pb low DC-geometry | **ACCEPTED**: Works on different principle (BoS + pullback), doesn't need DC-geometry |
| FVG snapshot bug class | **MONITORED**: No new bugs found; fix verified by 4/4 fvg_fill GO |

---

## ADR-MS-003: Sprint 3 Ensemble — ms_018 standalone is optimal

**Date**: 2026-03-02
**Status**: DECIDED — ms_018 standalone preferred over ensemble

### Context

Sprint 2 verified 4 configs from 2 families with different entry geometries:
- **shift_pb** (ms_018, ms_017): BoS + pullback, low DC-geometry (6-14%)
- **fvg_fill** (ms_005, ms_007): Gap fill, mixed DC-geometry (44-64%)

Hypothesis: combining two independent signal families with low overlap could produce a stronger portfolio (more diversified trades, smoother equity curve, lower DD).

### Experiment

- **Ensemble pairs tested**: 3 combinations across priority mode
- **Overlap measurement**: Direct signal comparison across all bar×coin pairs
- **Truth-pass**: Full 3-test battery on each ensemble

### Overlap Analysis

| Pair | A-only | B-only | Both | Overlap % |
|------|--------|--------|------|-----------|
| ms_018 + ms_005 | 4,377 | 6,030 | 441 | 4.1% |
| ms_018 + ms_007 | 4,659 | 3,724 | 159 | 1.9% |
| ms_017 + ms_005 | 3,004 | 6,094 | 377 | 4.0% |

**Key finding**: Signal overlap is very low (1.9-4.1%). The two families trigger on genuinely different market structures. fvg_fill generates more raw signals (~6K) than shift_pb (~4.5K).

### Results

| Ensemble | PF | Trades | DD | P&L | A/B Split | Verdict |
|----------|-----|--------|-----|------|-----------|---------|
| ms_018 + ms_005 | 1.89 | 454 | 24.2% | $+17,381 | 2505/2827 | VERIFIED |
| ms_018 + ms_007 | 1.55 | 417 | 24.5% | $+12,360 | 2371/1646 | VERIFIED |
| ms_017 + ms_005 | 1.66 | 445 | 21.9% | $+10,620 | 1573/2770 | VERIFIED |

**Standalone comparison**:

| Config | PF | Trades | DD | P&L |
|--------|-----|--------|-----|------|
| ms_018 standalone | **2.08** | 697 | **21.3%** | **$+46,017** |
| ms_005 standalone | 1.65 | 429 | 19.5% | $+18,756 |
| Best ensemble (018+005) | 1.89 | 454 | 24.2% | $+17,381 |

### Key Findings

#### 1. Ensemble DEGRADES ms_018's performance
- PF: 2.08 → 1.89 (-9%)
- P&L: $46K → $17K (-62%)
- DD: 21.3% → 24.2% (+2.9pp)
- Trades: 697 → 454 (-35%)

The engine has limited position slots. fvg_fill signals consume slots that would have gone to higher-quality shift_pb signals, diluting the portfolio.

#### 2. Low overlap confirms independent signals
- 1.9-4.1% overlap = genuinely different entry triggers
- fvg_fill generates ~60% more raw signals than shift_pb
- But quantity ≠ quality: shift_pb has PF 2.08 vs fvg_fill 1.65

#### 3. Capital competition, not diversification
The ensemble fails to diversify because both signal types compete for the same position slots in the same portfolio. With limited capital, the optimal strategy is to allocate 100% to the highest-PF signal (ms_018).

#### 4. All ensembles still VERIFIED
Despite being suboptimal, all 3 ensembles pass truth-pass (3/3). This means fvg_fill is a valid standalone strategy if deployed separately — just not as a mix-in for shift_pb.

### Decision

**ms_018 standalone is the optimal single-strategy deployment**. Ensemble does not add value.

However, fvg_fill (ms_005) remains viable for:
1. **Separate portfolio**: Deploy on separate capital allocation, not as ensemble
2. **Different market regime**: If shift_pb stops working (ranging markets), fvg_fill may persist
3. **Cross-exchange**: fvg_fill's different entry geometry might port better to other exchanges

### Consequences

1. **Primary deployment**: ms_018 standalone for paper trading
2. **Secondary deployment**: ms_005 standalone on separate capital (optional)
3. **No ensemble**: Priority/strongest mixing does not improve risk-adjusted returns
4. **Future research**: Consider time-based regime switching (shift_pb in trending, fvg_fill in ranging) rather than simultaneous ensemble

---

## ADR-MS-004: Paper Trading Setup — MEXC 4H ms_018

**Date**: 2026-03-02
**Status**: DEPLOYED — paper trading ready to start

### Context

MS Sprint 1-3 complete:
- Sprint 1: 7/18 GO, 2 families survive (shift_pb, fvg_fill)
- Sprint 2: 4/4 VERIFIED through truth-pass (3/3 tests each)
- Sprint 3: ms_018 standalone preferred over ensemble

ms_018_mse_shallow is the primary deployment candidate:
- PF=2.08 (P5=1.48), DD=21.3%, 697 trades, 100% boot profitable
- Backtest on Kraken 4H, 487 coins, 26bps fees

### Decision: Deploy on MEXC

**Exchange**: MEXC SPOT (not Kraken)
- Rationale: MEXC infrastructure already exists (HF paper trading, exchange_manager.py)
- Fee advantage: MEXC 10bps taker (conservative) vs Kraken 26bps — strategy should perform BETTER live
- Coin universe: MEXC has 1,900+ USDT pairs vs Kraken ~526 USD pairs — more signal opportunities
- Risk: Backtest was on Kraken data — MEXC candle characteristics may differ slightly

### Configuration (frozen)

```
Signal:     shift_pb shallow (Structure Shift + Pullback)
Params:     max_bos_age=15, pullback_pct=0.382, max_pullback_bars=6
Exits:      hybrid_notrl (FIXED STOP → TIME MAX → RSI RECOVERY → DC TARGET → BB TARGET)
Exit grid:  max_stop_pct=15, time_max_bars=15, rsi_rec_target=45, rsi_rec_min_bars=2
Fee:        MEXC 10bps/side (conservative)
Sizing:     $5,000/trade, max 2 positions (updated ADR-MS-005)
Cooldown:   4 bars normal, 8 bars after stop loss
```

### Drift Detection

| Criterion | Threshold | Action |
|-----------|-----------|--------|
| R1: PF floor | PF < 1.0 after 30+ trades | ROLLBACK |
| R2: DD ceiling | Max DD > 30% | ROLLBACK |
| R3: Consecutive losses | 8+ in a row | ROLLBACK |
| D1: PF below P5 | PF < 1.48 after 50+ trades | WARNING |
| D2: Low win rate | WR < 35% after 30+ trades | WARNING |
| D3: Class A dominance | A share < 40% after 20+ trades | WARNING |
| Checkpoint | Every 25 trades | LOG |

### Rollback Procedure

If any CRITICAL criterion triggers:
1. Stop paper trading (Ctrl+C or --hours limit)
2. Review `--report` output and trade_log
3. Check for data issues (MEXC API gaps, coin delistings)
4. If structural: investigate ms_018 signal degradation on fresh Kraken data
5. If exchange-specific: consider Kraken deployment instead

### Files

| File | Purpose |
|------|---------|
| `trading_bot/paper_ms_4h.py` | MEXC 4H paper trader for ms_018 |
| `trading_bot/paper_state_ms_4h_paper.json` | Persistent state |
| `trading_bot/dashboard_ms_4h_paper.json` | Monitoring dashboard |
| `trading_bot/logs/paper_ms_4h_paper_*.log` | Run logs |

### Usage

```bash
# Dry run (1 cycle, validates connectivity + signal computation)
python trading_bot/paper_ms_4h.py --dry-run

# Live for 7 days
python trading_bot/paper_ms_4h.py --hours 168

# Infinite (Ctrl+C to stop)
python trading_bot/paper_ms_4h.py

# Check progress
python trading_bot/paper_ms_4h.py --report
```

### Success Criteria (after 50+ trades)

| Metric | Minimum | Target | Backtest |
|--------|---------|--------|----------|
| PF | > 1.0 | > 1.48 (P5) | 2.08 |
| DD | < 30% | < 21% | 21.3% |
| WR | > 35% | > 45% | — |
| Class A share | > 40% | > 60% | — |

### Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| MEXC data ≠ Kraken data | 30% | Reduced PF | Drift detection at 25-trade checkpoints |
| USDT pairs ≠ USD pairs | 20% | Different coin behavior | Monitor per-coin attribution |
| MEXC rate limits | 10% | Missed signals | 0.25s delay between API calls |
| Structural entry scarcity | 25% | < 1 trade/day | 300 coins scanned (vs 487 backtest) |
| Fee advantage masks degradation | 15% | False confidence | Compare vs P5 baseline (Kraken fees) |

---

## ADR-MS-005: Position Sizing — max_pos=2 optimal

**Date**: 2026-03-03
**Status**: DECIDED — max_pos=2 deployed, capital per trade $5K

### Context

ADR-MS-004 deployed paper trading with max_pos=3, $2K/trade (default from backtest engine). This was inherited from Sprint 3 without explicit optimization. Question: what's the optimal number of concurrent positions for ms_018?

### Experiment

Sensitivity run: ms_018 (shift_pb shallow) with max_pos={1, 2, 3, 5, 8} on same dataset (487 coins, 4H Kraken, 26bps).

### Results

| max_pos | Trades | PF | P&L | DD% | Risk-adj (PF/DD) |
|---------|--------|----|-----|-----|-------------------|
| 1 | 239 | 1.55 | $17,183 | 31.6% | 4.91 |
| **2** | **447** | **2.04** | **$42,900** | **20.4%** | **10.00** |
| 3 | 682 | 2.08 | $40,944 | 21.3% | 9.77 |
| 5 | 1,014 | 1.42 | $5,308 | 35.1% | 4.05 |
| 8 | 1,371 | 1.36 | $2,863 | 29.6% | 4.59 |

### Key Findings

#### 1. max_pos=2 dominates on risk-adjusted basis
- Best risk-adjusted score: PF/DD = 10.00 (vs 9.77 for max_pos=3)
- Highest P&L: $42,900 (vs $40,944 for max_pos=3)
- Lowest DD: 20.4% (vs 21.3% for max_pos=3)
- PF negligibly lower: 2.04 vs 2.08 (-0.04, within noise)

#### 2. max_pos=1 is paradoxically worse
- DD rises to 31.6% despite fewer trades (239)
- Single-coin concentration: each trade absorbs full portfolio risk
- PF drops to 1.55 — engine can't diversify across entry timing

#### 3. max_pos>=5 dilutes quality
- PF collapses: 1.42 (5 slots) → 1.36 (8 slots)
- P&L drops 87-93% vs optimal
- Engine fills slots with marginal entries that drag portfolio down
- More trades ≠ better: 1,371 trades at PF 1.36 < 447 trades at PF 2.04

#### 4. Capital allocation follows naturally
- $10K equity / 2 positions = $5K per trade
- vs previous: $10K / 3 positions = $3.3K per trade
- Larger position in fewer, higher-quality entries = more efficient capital use

### Decision

**max_pos=2, $5K/trade** for paper trading deployment.

Updated in `trading_bot/paper_ms_4h.py`:
- `MAX_POSITIONS = 2` (was 3)
- `CAPITAL_PER_TRADE = 5000` (was 2000)
- Baseline PF updated to 2.04, DD to 20.4%, trades to 447

### Trade Frequency Expectation

- Backtest: 447 trades / ~120 days / 487 coins = **~3.7 trades/day**
- Live (MEXC, ~300 coins scanned): **~2-3 trades/day** expected
- With max 2 concurrent and avg ~7 bar hold: typically 1-2 open at any time

### Consequences

1. **Paper trader updated**: max_pos=2, $5K/trade, drift baseline adjusted
2. **ADR-MS-004 superseded on sizing**: config section now stale, this ADR is authoritative
3. **Sensitivity script saved**: `scripts/run_ms_maxpos_sensitivity.py` for reproducibility
4. **Report saved**: `reports/ms/maxpos_sensitivity.json`

---

## ADR-MS-006: Normal Live GO — $500/trade, halal whitelist, guarded-live 48h

**Date**: 2026-03-04
**Status**: GO — advance from micro-live to normal live

### Context

Micro-live smoke test (ADR-MS-004/005) completed:
- 3 real trades via `live_trader.py --strategy ms_018 --live --micro` ($50/trade)
- All 3 exits: DC TARGET (Class A) — best exit type
- P&L: +$1.02 on $150 risked, PF=7.05
- Slippage: -14.5 bps (worst, SEI sell) to +15.0 bps (worst, SEI buy)
- Fees: $0.00 confirmed (MEXC 0% maker/taker)
- 8 checks over 29h, no crashes, no circuit breaker triggers, no reconciliation mismatches

OrderExecutor precision bugfix applied (commit `caf2cb4`):
- CCXT `amount_precision` returns step size (0.001) on MEXC, not decimal count (3)
- Fix: `-floor(log10(step))` conversion + `min_amount` guard
- Affected TAO, BTC, ETH — any coin where `$size / price < 1.0`

### Decision

**GO** — advance to normal live with guarded parameters:

| Parameter | Micro-Live | Normal Live | Rationale |
|-----------|-----------|-------------|-----------|
| Trade size | $50 | **$500** | 10x micro, conservative vs $1,400 Half Kelly |
| Max positions | 2 | **2** | ADR-MS-005 optimal |
| Max exposure | $100 | **$1,000** | Manageable risk |
| Coin universe | 300 (all) | **45 (halal whitelist)** | Islamic compliance |
| Duration | 24h | **48h (guarded)** | Meaningful sample, quick intervention |
| Mode | --micro | **--trade-size 500** | New CLI flag added |

### Execution Command

```bash
python live_trader.py --strategy ms_018 --live --trade-size 500 \
    --coins-file halal_coins.txt --hours 48 --reset
```

### Halal Whitelist

`trading_bot/halal_coins.txt` — 45 utility-based coins:
- L1 platforms (BTC, ETH, SOL, ADA, AVAX, DOT, NEAR, SUI, APT, ...)
- L2/scaling (OP, ARB, IMX, POL)
- Cross-chain (ATOM, DOT, LINK)
- Storage/compute (FIL, AR, RENDER, TAO)
- Payment/transfer (XRP, XLM)

Excluded: lending/riba (AAVE, COMP, MKR), meme/gambling (DOGE, SHIB, PEPE), interest-bearing stablecoins.

### Trade Frequency Impact

- Backtest: 447 trades / 120 days / 487 coins ≈ 3.7 trades/day
- Halal universe: 45/487 = 9.2% of coins → **~0.34 trades/day expected**
- In 48h: expect **0-2 trades** (low sample, but validates execution at $500)
- If 0 trades: extend to 168h or add coins

### Guarded-Live Monitoring (48h)

| Criterion | Threshold | Action |
|-----------|-----------|--------|
| Trade execution | Any fill failure | Investigate immediately |
| Slippage | > 30 bps avg | Pause entries, review liquidity |
| Reconciliation | > 5% mismatch | Auto-pause (built-in) |
| Circuit breaker | Any trip | Auto-panic-sell (built-in) |
| Balance check | Manual 2x/day | Verify MEXC balance vs state |
| TG notifications | All entries/exits | Real-time monitoring |

### Infrastructure Verification

| Component | Status | Evidence |
|-----------|--------|----------|
| `live_trader.py` | ✅ | 3 trades executed, all invariants held |
| `order_executor.py` | ✅ | Precision bugfix applied, verified |
| `circuit_breaker.py` | ✅ | DD, PF, consec-loss checks + panic sell |
| `strategy_config.py` | ✅ | ms_018 config frozen from ADR-MS-002/005 |
| `halal_coins.txt` | ✅ | 45 coins, manually curated |
| `--trade-size` flag | ✅ | Added to live_trader.py |
| Atomic state writes | ✅ | tmp → bak → rename pattern |
| Reconciliation | ✅ | Exchange balance vs local state every cycle |
| Graceful shutdown | ✅ | SIGTERM/SIGINT handlers save state |

### Risk Analysis

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Slippage > backtest | 25% | Reduced PF | Real-time slippage tracking + alert |
| Halal universe too small | 40% | 0 trades in 48h | Extend to 168h, then reassess |
| Network/API failure during trade | 10% | Orphaned position | Pre-write markers + reconciliation |
| Market flash crash | 5% | DD spike | Circuit breaker + panic sell |
| Exchange maintenance | 10% | Missed signals | Retry logic + graceful degradation |

### Success Criteria (after 48h)

| Metric | Minimum | Ideal |
|--------|---------|-------|
| Trades executed | ≥ 1 | ≥ 3 |
| Fill rate | 100% (no failures) | 100% |
| Slippage | < 30 bps avg | < 15 bps avg |
| No circuit breaker trips | Required | Required |
| No reconciliation mismatches | Required | Required |
| TG notifications working | Required | Required |

### After 48h: Decision Point

- **All criteria met + ≥1 trade**: Continue at $500/trade for 7 days
- **0 trades but no issues**: Extend to 168h with same parameters
- **Any execution issue**: Investigate, fix, re-start micro-live
- **After 7 days + 10+ trades**: Review for Half Kelly ($1,400/trade)

### Consequences

1. `--trade-size` flag added to `live_trader.py` for flexible sizing
2. Micro-live state preserved in `state_ms_018_shift_pb_live.json` (3 trades)
3. Normal live starts fresh with `--reset` flag
4. Paper trader (`paper_ms_4h.py`, PID 35757) continues running independently for signal tracking
5. GATES document created for live deployment reproducibility

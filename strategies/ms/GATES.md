# MS Sprint 1 — Gate Definitions

## Hard Gates (KILL)

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| G0: TRADES | >= 80 | Minimum statistical significance |
| G1: PF | >= 1.0 | Positive expectancy after fees (26bps Kraken) |

**KILL condition**: 0/18 configs pass G1 → MS Sprint 1 CLOSED.

## Soft Gates (Advance to truth-pass)

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| G2: PF_ADVANCE | >= 1.10 | Buffer above breakeven for truth-pass |
| S1: DD | <= 50% | Drawdown within acceptable bounds |
| S2: WF | 2/3 folds PF >= 0.9 | Walk-forward stability (3 temporal folds) |
| S3: CONC | top1 coin < 30% trades | No single-coin concentration |
| S4: DC_GEO | informational | % entries satisfying close<dc_mid AND close<bb_mid AND rsi<40 |

## Sprint 1 Results (2026-03-02)

**7/18 GO** — 2 families survived:

| Family | GO | Best PF | Avg PF | DC-Geometry |
|--------|-----|---------|--------|-------------|
| shift_pb | 3/3 | 2.08 | 1.85 | Low (6-14%) |
| fvg_fill | 4/4 | 1.66 | 1.59 | Mixed (23-98%) |
| ob_touch | 0/4 | 0.72 | 0.67 | Low (20-24%) |
| liq_sweep | 0/4 | 0.76 | 0.67 | Medium (38-43%) |
| sfp | 0/3 | 0.63 | 0.59 | Medium (36-44%) |

## Walk-Forward (S2) Detail

All 7 GO configs pass S2 (3/3 folds PF >= 0.9):

| Config | F1 | F2 | F3 | Status |
|--------|-----|-----|-----|--------|
| ms_018 (shift_pb shallow) | 1.66 | 2.55 | 2.04 | 3/3 |
| ms_017 (shift_pb fib618) | 1.58 | 4.71 | 1.41 | 3/3 |
| ms_016 (shift_pb base) | 1.26 | 2.71 | 1.56 | 3/3 |
| ms_007 (fvg deep) | 1.61 | 1.29 | 1.91 | 3/3 |
| ms_005 (fvg base) | 1.86 | 2.06 | 1.52 | 3/3 |
| ms_008 (fvg wide) | 1.49 | 1.45 | 1.79 | 3/3 |
| ms_006 (fvg norsi) | 1.25 | 1.29 | 1.66 | 3/3 |

## Sprint 2 Truth-Pass Results (2026-03-02)

**4/4 VERIFIED** — all candidates pass all 3 robustness tests.

### Truth-Pass Gates

| Test | Criterion | Threshold |
|------|-----------|-----------|
| T1: Window Split | PF >= 1.0 in >= 2/3 windows | early/mid/late thirds |
| T2: Walk-Forward | Cal PF >= 1.0 AND Test PF >= 0.9 | Either split passes |
| T3: Bootstrap | P5_PF >= 0.85 AND >= 60% profitable | 1000 trade resamples |

Verdicts: ALL 3 PASS → VERIFIED, 2/3 → CONDITIONAL, ≤1/3 → FAILED

### Window Split Detail (T1)

| Config | Early PF | Mid PF | Late PF | Windows OK | Status |
|--------|----------|--------|---------|------------|--------|
| ms_018 (shift_pb shallow) | 1.71 | 2.65 | 2.01 | 3/3 | PASS |
| ms_005 (fvg base) | 2.05 | 2.21 | 1.56 | 3/3 | PASS |
| ms_017 (shift_pb fib618) | 1.62 | 5.06 | 1.35 | 3/3 | PASS |
| ms_007 (fvg deep) | 1.78 | 1.40 | 1.95 | 3/3 | PASS |

### Walk-Forward Detail (T2)

| Config | Split A (cal→test) | Split B (cal→test) | Status |
|--------|-------------------|-------------------|--------|
| ms_018 | 1.71→2.11 | 2.32→2.01 | 2/2 PASS |
| ms_005 | 2.05→1.62 | 2.01→1.56 | 2/2 PASS |
| ms_017 | 1.62→1.82 | 3.73→1.35 | 2/2 PASS |
| ms_007 | 1.78→1.68 | 1.51→1.95 | 2/2 PASS |

### Bootstrap Detail (T3)

| Config | Median PF | P5 PF | P95 PF | % Profitable | Status |
|--------|-----------|-------|--------|-------------|--------|
| ms_018 | 2.08 | 1.48 | 2.91 | 100% | PASS |
| ms_005 | 1.65 | 1.19 | 2.26 | 100% | PASS |
| ms_017 | 1.83 | 1.28 | 2.56 | 100% | PASS |
| ms_007 | 1.65 | 1.24 | 2.24 | 99% | PASS |

### Combined Verdicts

| Config | Family | Full PF | DD | T1 | T2 | T3 | Verdict |
|--------|--------|---------|-----|-----|-----|-----|---------|
| **ms_018** | shift_pb | 2.08 | 21.3% | PASS | PASS | PASS | **VERIFIED** |
| **ms_005** | fvg_fill | 1.65 | 19.5% | PASS | PASS | PASS | **VERIFIED** |
| **ms_017** | shift_pb | 1.80 | 28.0% | PASS | PASS | PASS | **VERIFIED** |
| **ms_007** | fvg_fill | 1.66 | 22.9% | PASS | PASS | PASS | **VERIFIED** |

## Position Sizing Sensitivity (ADR-MS-005)

ms_018 tested at max_pos={1, 2, 3, 5, 8}:

| max_pos | Trades | PF | P&L | DD% | Risk-adj |
|---------|--------|----|-----|-----|----------|
| 1 | 239 | 1.55 | $17,183 | 31.6% | 4.91 |
| **2** | **447** | **2.04** | **$42,900** | **20.4%** | **10.00** |
| 3 | 682 | 2.08 | $40,944 | 21.3% | 9.77 |
| 5 | 1,014 | 1.42 | $5,308 | 35.1% | 4.05 |
| 8 | 1,371 | 1.36 | $2,863 | 29.6% | 4.59 |

**Decision**: max_pos=2 optimal. Risk-adjusted score 10.00, best P&L, lowest DD.

## Deployment Config (Paper Trading)

```
Exchange:       MEXC SPOT (10bps/side)
Signal:         ms_018 shift_pb shallow
Max positions:  2 (ADR-MS-005)
Capital/trade:  $5,000
Equity:         $10,000
Cooldown:       4 bars (8 after stop)
Est. frequency: ~2-3 trades/day
```

## Priority Order

1. **ms_018** (shift_pb shallow): PRIMARY — PF=2.04 @max_pos=2, P5_PF=1.48, DD=20.4%, 447 trades
2. **ms_005** (fvg base): Secondary — PF=1.65, P5_PF=1.19, DD=19.5%, 429 trades
3. **ms_017** (shift_pb fib618): Reserve — PF=1.80, P5_PF=1.28, DD=28.0%
4. **ms_007** (fvg deep): Reserve — PF=1.66, P5_PF=1.24, DD=22.9%

---

## Live Deployment Gates (ADR-MS-006)

### Pre-Deployment Checklist

| # | Gate | Criterion | Status |
|---|------|-----------|--------|
| G0 | Strategy verified | Truth-pass 3/3 | ✅ ADR-MS-002 |
| G1 | Position sizing | Sensitivity analysis | ✅ ADR-MS-005 |
| G2 | Ensemble ruled out | Standalone > ensemble | ✅ ADR-MS-003 |
| G3 | Micro-live smoke | ≥1 real trade, no failures | ✅ ADR-MS-006: 3/3 trades |
| G4 | Precision verified | All price ranges handled | ✅ Bugfix caf2cb4 |
| G5 | Halal whitelist | Curated ≥30 coins | ✅ 45 coins |
| G6 | Tests green | make check passes | ✅ 66 tests |

### Runtime Gates (automated in live_trader.py)

#### Hard — Circuit Breaker Trip (panic sell + halt)
| Gate | Threshold | Active After |
|------|-----------|-------------|
| R1 | DD ≥ 25% of peak | Always |
| R2 | PF < 1.0 | 30+ trades |
| R3 | 8+ consecutive losses | Always |

#### Soft — Entry Pause (24h)
| Gate | Threshold | Active After |
|------|-----------|-------------|
| D1 | Daily loss > 5% of peak | Always |

#### Warning — TG Alert (no action)
| Gate | Threshold | Active After |
|------|-----------|-------------|
| W1 | PF < 1.48 (P5 baseline) | 50+ trades |
| W2 | WR < 35% | 30+ trades |
| W3 | Avg slippage > 20 bps | 20+ fills |

#### Integrity — Every Cycle
| Gate | Description | On Violation |
|------|-------------|-------------|
| I1 | Reconciliation (exchange vs state) | >5% → pause 24h |
| I2 | Liquidity (24h volume ≥ $500K) | Skip that coin |
| I3 | Atomic writes (tmp → bak → rename) | Recovery from .bak |

### Frozen Parameters

```yaml
# Signal: shift_pb shallow (ms_018)
max_bos_age: 15
pullback_pct: 0.382
max_pullback_bars: 6

# Exits: hybrid_notrl
max_stop_pct: 15.0
time_max_bars: 15
rsi_recovery: true
rsi_rec_target: 45.0
rsi_rec_min_bars: 2

# Sizing: normal live (ADR-MS-006)
capital_per_trade: 500.0
max_positions: 2
fee_rate: 0.0010  # conservative

# Execution
min_volume_24h: 500000
cooldown_bars: 4
cooldown_after_stop: 8
min_candles: 120
```

### Escalation Path

| Stage | Trade Size | Criterion to Advance |
|-------|-----------|---------------------|
| ~~Micro-live~~ | ~~$50~~ | ~~✅ 3 trades, all OK~~ |
| **Normal live** | **$500** | **48h guarded monitoring** |
| Full live | $1,400 (Half Kelly) | PF > 1.0, slippage < 20bps |
| Scale up | $2,800+ | PF > 1.48, DD < 25%, 50+ trades |

### Deployment Command

```bash
# Normal live ($500/trade, halal whitelist, 48h)
python live_trader.py --strategy ms_018 --live --trade-size 500 \
    --coins-file halal_coins.txt --hours 48 --reset
```

### Reproducibility Artifacts

| Artifact | Location |
|----------|----------|
| Strategy config | `trading_bot/strategies/ms_018.py` |
| Live trader | `trading_bot/live_trader.py` |
| Order executor | `trading_bot/order_executor.py` |
| Circuit breaker | `trading_bot/circuit_breaker.py` |
| Halal whitelist | `trading_bot/halal_coins.txt` |
| State (live) | `trading_bot/state_ms_018_shift_pb_live.json` |
| Logs | `trading_bot/logs/live_ms_018_shift_pb_*.log` |
| ADR chain | `strategies/ms/DECISIONS.md` (MS-001 → MS-006) |
| Gate canon | this file |

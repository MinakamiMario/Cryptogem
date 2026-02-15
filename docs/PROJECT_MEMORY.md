# Project Memory — Cryptogem Trading Bot

## Project Overview
- **Exchange**: Kraken (526 tradeable coins)
- **Timeframe**: 4H candles
- **Strategy**: DualConfirm bounce (bear market)
- **Dataset**: candle_cache_tradeable.json (425 coins, 721 bars, ~112 days)
- **Live dataset**: candle_cache_532.json (526 coins, ~660 bars)
- **Capital**: $2,000 initial, 100% per trade, max_pos=1

## Architecture

### Agent Team V3 (current)
- **4 agents**: Auditor (data checks), Scout (config search), Validator (WF/MC/friction), Orchestrator (budget)
- **MetaLearner**: helper for stable params + exit class analysis
- **Blackboard communication**, precomputed indicators (30x faster)
- **7-gate promotion pipeline**: WF>=3/5, Friction>$0, NoTop>-$200, Top1<80%, CoinConc<80%, ClassA>50%, WorstWindow>-$300
- **Runtime-based budget**: seconds, not config-count

### Backtest Engine
- `agent_team_v3.py` → `run_backtest()`, `precompute_all()`, `normalize_cfg()`
- `strategy.py` → `calc_rsi()`, `calc_atr()`, `calc_donchian()`, `calc_bollinger()`, `DualConfirmStrategy`
- `robustness_harness.py` → `purged_walk_forward()`, `monte_carlo_*()`, `run_candidate()`

## Validated Configs

### GRID_BEST (tp_sl) — GO
```json
{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45,
 "sl_pct": 10, "time_max_bars": 15, "tp_pct": 12,
 "vol_confirm": true, "vol_spike_mult": 2.5}
```
- TRADEABLE: 32 trades, $4718 P&L, 68.8% WR, WF 5/5, BE 162bps
- Verdict: **GO** (all 6 robustness tests passed)

### C1 (tp_sl) — GO (on LIVE_CURRENT)
```json
{"exit_type": "tp_sl", "max_pos": 1, "rsi_max": 45,
 "sl_pct": 15, "time_max_bars": 15, "tp_pct": 15,
 "vol_confirm": true, "vol_spike_mult": 3.0}
```
- LIVE_CURRENT: 30 trades, $3746 P&L, 66.7% WR, WF 4/5, BE 78bps

### Entry Logic (all configs)
1. Donchian low touch (prev bar DC lower) + RSI < rsi_max + close > prev close
2. Bollinger lower touch (close <= BB lower) — BOTH required (DualConfirm)
3. Volume spike >= vol_spike_mult x 20-bar avg
4. Volume confirm: current vol >= previous vol

### Exit Logic (tp_sl mode)
1. FIXED STOP: low <= entry * (1 - sl_pct/100)
2. PROFIT TARGET: high >= entry * (1 + tp_pct/100)
3. TIME MAX: bars_in >= time_max_bars

## Key Learnings
- **VolSpike 3.0x** filters losing trail stops, keeps winners (+$938 vs 2.0x)
- **Positive profit attribution** fix: share metrics must use `sum(max(0,pnl))` as denominator, never `abs(total_pnl)`
- **Trail stops** are 100% losing but DC/RSI Recovery compensate (in trail exit mode)
- **tp_sl exit mode** outperforms trail on robustness (WF 5/5 vs 3/5)
- **Random neighbor search is useless** after good sweep: 26K+ variants, 0 improvements
- **Precomputed indicators essential**: 30x speedup

## Data Hashes (MD5)
| Cache | MD5 | Coins |
|-------|-----|-------|
| candle_cache_tradeable.json | `f6fd2ca303b677fe67ceede4a6b8f7ba` | 425 |
| candle_cache_532.json | `3b1dba2eeb4d95ac68d0874b50de3d4d` | 526 |

## Schema Invariants
- `time_max_bars` = canonical key, `tm_bars` = legacy alias
- `normalize_cfg()` called at `run_backtest()` entry + `save/load_champion()`
- `PARAMS_BY_EXIT` = source of truth for exit-type param grids
- 66 regression tests must stay green (`make check`)

## File Map

### Active Scripts
| File | Purpose |
|------|---------|
| `agent_team_v3.py` | Backtest engine + 4-agent orchestrator |
| `strategy.py` | DualConfirmStrategy + indicator functions |
| `robustness_harness.py` | GO/NO-GO validation harness |
| `bot.py` | Live Kraken trading bot |
| `paper_backfill_v4.py` | Paper trader with backfill |
| `overnight_optimizer.py` | Realistic equity sweep + Monte Carlo |
| `DualConfirm_GRID_BEST.pine` | TradingView PineScript (GRID_BEST tp_sl) |

### Validation Scripts
| File | Purpose |
|------|---------|
| `leakage_check.py` | Purged vs no-purge walk-forward |
| `nested_holdout.py` | Inner WF + outer holdout |
| `window_sweep.py` | Temporal stability (fixed + rolling windows) |
| `slippage_regimes.py` | Fee/slippage stress test |
| `long_horizon_max.py` | Full battery: WF + slippage + jitter + MC ruin |
| `rolling_regime_sweep.py` | Rolling windows x fee regimes |

### Tests
| File | Tests | Makefile |
|------|-------|---------|
| `test_param_sensitivity.py` | 66 | `make tests` |
| `test_robustness_harness.py` | ~10 | `make robustness-tests` |

### Deprecated
All in `trading_bot/deprecated/` — v1/v2 agents, v5-v9 experiments.

## HF Research (1H Screening)

### Scope
- **Timeframe**: 1H candles (separate from 4H DualConfirm)
- **Universe**: T1 (98 coins, 31bps/side) + T2 (216 coins, 56bps/side) = 316 coins
- **Dataset**: candle_cache_1h.json (1903 coins, 721 bars)
- **Engine**: standalone harness in `strategies/hf/screening/harness.py` (READ-ONLY, engine fee parity with `agent_team_v3.py`)

### Signal Protocol
```
signal_fn(candles, bar, indicators, params) -> {stop_price, target_price, time_limit, strength}
```
- Cross-coin context injected via `params['__market__']`
- Per-coin identity via `indicators['__coin__']`

### Research Summary
- 5 sprints, 25 hypothesis families, 150+ configs tested
- **All negative at Kraken fees**
- Sprint 4: 15 hypotheses (mean_reversion, momentum, volume, price_action, multi_indicator) -- 0/90 survivors
- Sprint 5: 10 hypotheses (microstructure, market_state, cross_sectional) -- 0/60 survivors
- Reality Check: H20 VWAP_DEVIATION v5 flips positive at MEXC fees (PF=1.25, +$143/wk)

### Current Baseline
- **Signal**: H20 VWAP_DEVIATION v5 (dev_thresh=2.0, tp_pct=8, sl_pct=5)
- **Exchange**: MEXC (0% maker, 10bps taker) -- market execution
- **Result**: PF=1.25, +$143/wk, survives P95 stress (PF=1.07)
- **Status**: CONDITIONAL GO (ADR-HF-029) -- needs paper trading validation

### Key Learnings
- 1H crypto at Kraken fees (T2=56bps/side) is structurally unprofitable
- Fee structure is the bottleneck, not signal quality
- MEXC cost advantage (60-92% cheaper) is necessary for positive expectancy

### Key Files
| Location | Purpose |
|----------|---------|
| `strategies/hf/DECISIONS.md` | 29 ADRs (HF-001 through HF-029) |
| `strategies/hf/screening/` | All screening code (harness, hypotheses, screener) |
| `reports/hf/` | All experiment reports (JSON + MD pairs) |
| `strategies/hf/GATES.md` | 4H gate canon |
| `strategies/hf/GATES_SCREENING.md` | 1H screening gates |
| `strategies/hf/UNIVERSE_POLICY.md` | Tier definitions and inclusion criteria |

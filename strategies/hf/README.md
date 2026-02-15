# HF Strategy — High-Frequency Hypothesis Testing

Research folder for alternative DualConfirm parameter regimes.

## Status: Phase 1 — Smoke Run

## Hypotheses

### H1: LTF Mean Reversion
Tight RSI oversold bounce (RSI<30) with small TP/SL (tp8/sl6, tm8).
Rationale: GRID_BEST uses RSI<45 which is loose. Tighter RSI should
filter for deeper oversold conditions with faster mean-reversion payoff.

### H2: Momentum Burst
High volume spike (>4x avg) with relaxed RSI (RSI<55, tp15/sl8, tm12).
Rationale: Extreme volume events signal institutional interest. Relaxed
RSI allows entry at less oversold levels if volume conviction is high.

### H3: Vol Breakout
Extreme volume filter (5x avg) with wide TP target (tp20/sl10, tm20).
Rationale: BB-lower touches with explosive volume may signal regime
shifts worth holding longer for larger moves.

### Baseline: GRID_BEST
tp12/sl10/vs2.5/rsi45/tm15 — the validated production config for comparison.

## Usage

```bash
# Smoke run (all hypotheses + GRID_BEST baseline)
python strategies/hf/run_backtest.py

# With specific universe
python strategies/hf/run_backtest.py --universe tradeable   # default
python strategies/hf/run_backtest.py --universe live         # 526 coins

# Check existing tests still pass
make check
```

## Outputs

```
reports/hf/smoke.json   # Raw results (trades, WR, P&L, PF, DD per hypothesis)
reports/hf/smoke.md     # Human-readable comparison table
```

## Architecture

HF imports the shared backtest engine read-only from `trading_bot/`:

```python
from agent_team_v3 import precompute_all, run_backtest, normalize_cfg
```

No files in `trading_bot/` are modified. All HF code lives under `strategies/hf/`.

### Files

| File | Purpose |
|------|---------|
| `hf_strategy.py` | Hypothesis configs (H1/H2/H3) + GRID_BEST reference |
| `run_backtest.py` | Smoke-run script: backtest all hypotheses, write reports |
| `config.json` | Module metadata |
| `README.md` | This file |

## Isolation Rules

- HF changes MUST NOT modify files in `trading_bot/`
- GRID_BEST-critical files are read-only (locked at `v0.2-grid-best-locked`)
- All reports go to `reports/hf/`
- `make check` must stay green

## Phases

1. **Skeleton + Smoke** (current): Interface, smoke run, baseline comparison
2. **Hypothesis Refinement**: Grid sweeps within each hypothesis family
3. **Validation**: Walk-forward, slippage stress, Monte Carlo on winners

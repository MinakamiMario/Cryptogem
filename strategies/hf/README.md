# HF Strategy — High-Frequency Hypothesis Testing

Research folder for alternative DualConfirm parameter regimes.

## Status: Phase 2 — H2 Momentum Burst Sweep

## Setup (worktree)

Data files are gitignored. In a worktree, symlink them from the main repo:

```bash
# From worktree root:
ln -sf /Users/oussama/Cryptogem/trading_bot/candle_cache_532.json trading_bot/candle_cache_532.json
mkdir -p data
ln -sf /Users/oussama/Cryptogem/data/candle_cache_tradeable.json data/candle_cache_tradeable.json
```

## Hypotheses

### H1: LTF Mean Reversion
Tight RSI oversold bounce (RSI<30) with small TP/SL (tp8/sl6, tm8).
Result: weak (WR 51.5%, PF 1.18). Tight RSI kills win rate.

### H2: Momentum Burst (active)
High volume spike (>4x avg) with relaxed RSI (RSI<55, tp15/sl8, tm12).
Result: promising (WR 66.7%, PF 2.43, P&L $2,288). Grid sweep in Phase 2.

### H3: Vol Breakout
Extreme volume filter (5x avg) with wide TP target (tp20/sl10, tm20).
Result: too few trades (15), PF 1.05. Extreme filter kills trade count.

### Baseline: GRID_BEST
tp12/sl10/vs2.5/rsi45/tm15 — the validated production config ($4,718 P&L).

## HF Gates

All candidate configs must pass:

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| Min trades | >= 20 | Statistical significance on 721 bars |
| Profit Factor | >= 1.6 | Edge must be meaningful |
| Max Drawdown | <= 30% | Risk management |
| Friction 2x+20bps | P&L > $0 | Survives realistic trading costs |
| Friction 1-candle | P&L > $0 | Survives delayed fill scenario |

Friction model: Kraken fee = 0.26% per side. 2x+20bps = 0.72% eff. fee.
1-candle-later = 2x fees + 50bps gap = 1.02% eff. fee.

## Usage

```bash
# Phase 1: Smoke run
python strategies/hf/run_backtest.py

# Phase 2: H2 grid sweep (1280 configs, ~5 min)
python strategies/hf/h2_sweep.py

# With specific universe
python strategies/hf/h2_sweep.py --universe tradeable   # default (425 coins)
python strategies/hf/h2_sweep.py --universe live         # 526 coins

# Verify shared engine tests
make check
```

## Outputs

```
reports/hf/smoke.json       # Phase 1: all hypotheses baseline
reports/hf/smoke.md
reports/hf/h2_sweep.json    # Phase 2: H2 grid sweep + champion
reports/hf/h2_sweep.md
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
| `h2_sweep.py` | H2 grid sweep with HF gates + friction stress |
| `config.json` | Module metadata + champion-candidate |
| `README.md` | This file |

## Isolation Rules

- HF changes MUST NOT modify files in `trading_bot/`
- GRID_BEST-critical files are read-only (locked at `v0.2-grid-best-locked`)
- All reports go to `reports/hf/`
- `make check` must stay green

## Phases

1. **Skeleton + Smoke** (done): Interface, smoke run, baseline comparison
2. **H2 Sweep** (current): Grid sweep around H2, apply HF gates, select champion
3. **Validation**: Walk-forward, slippage stress, Monte Carlo on champion

# Fill Model Report — Reality Check Sprint

**Task**: fill_model_design
**Date**: 2026-02-15
**Commit**: 566d686

---

## Summary

Three fill regimes for MEXC spot trading, modelling the transition from
the current Kraken-fee backtest assumptions to realistic MEXC execution.

The harness (`harness.py`) currently uses a flat per-side fee (31 bps T1,
56 bps T2 for Kraken). MEXC offers 0/0 maker/taker fees for spot, so
the dominant costs shift to spread, slippage, and adverse selection.

---

## Mode Definitions

### Mode 1: MARKET (taker)

| Component | Tier 1 | Tier 2 |
|-----------|--------|--------|
| Exchange fee | 0 bps | 0 bps |
| Half-spread | 4 bps | 15 bps |
| Slippage ($500) | 2 bps | 10 bps |
| Adverse selection | 0 bps | 0 bps |
| **Total per side** | **6 bps** | **25 bps** |
| Fill rate | 100% | 100% |

Market orders always fill. Costs come entirely from spread crossing and
market impact. T1 coins (high liquidity) have tight spreads; T2 coins
(lower liquidity) have wider spreads and more slippage.

### Mode 2: LIMIT_OPTIMISTIC (passive maker)

| Component | Tier 1 | Tier 2 |
|-----------|--------|--------|
| Exchange fee | 0 bps | 0 bps |
| Half-spread | 0 bps | 0 bps |
| Slippage | 0 bps | 0 bps |
| Adverse selection | 3 bps | 3 bps |
| **Total per side** | **3 bps** | **3 bps** |
| Fill rate | 80% | 80% |

Limit orders avoid spread and slippage costs. The trade-off is a 20%
miss rate (signals that never fill) and a mild 3 bps adverse selection
(fills that execute tend to be slightly worse than average).

### Mode 3: LIMIT_REALISTIC (passive maker, conservative)

| Component | Tier 1 | Tier 2 |
|-----------|--------|--------|
| Exchange fee | 0 bps | 0 bps |
| Half-spread | 0 bps | 0 bps |
| Slippage | 0 bps | 0 bps |
| Adverse selection | 8 bps | 8 bps |
| **Total per side** | **8 bps** | **8 bps** |
| Fill rate | 55% | 55% |

Conservative limit model. Only 55% of signals fill. Critically, the
missed 45% are the strongest momentum signals (price ran away before the
limit order filled). This is the "winner's curse" -- you only get filled
when the market comes to you, which means momentum was against your entry.
The 8 bps adverse selection penalises surviving fills.

---

## Comparison vs Kraken (Current Harness)

| Metric | Kraken T1 | Kraken T2 | MEXC Market T1 | MEXC Market T2 | MEXC Limit-Opt T1 | MEXC Limit-Real T1 |
|--------|-----------|-----------|----------------|----------------|--------------------|--------------------|
| Per-side cost (bps) | 31 | 56 | 6 | 25 | 3 | 8 |
| Round-trip cost (bps) | 62 | 112 | 12 | 50 | 6 | 16 |
| Fill rate | 100% | 100% | 100% | 100% | 80% | 55% |
| Adverse bias | No | No | No | No | No | Yes |

**Key takeaway**: MEXC costs are dramatically lower than Kraken.
Even the most conservative limit model (8 bps/side) is 74% cheaper
than Kraken T1 (31 bps/side). The real question is whether the
strategy survives the fill rate penalty and adverse selection in
limit_realistic mode.

---

## Cost Reduction vs Kraken

| Mode + Tier | Cost/side | vs Kraken T1 | vs Kraken T2 |
|-------------|-----------|-------------|-------------|
| MEXC Market T1 | 6 bps | -81% | -89% |
| MEXC Market T2 | 25 bps | -19% | -55% |
| MEXC Limit-Opt T1 | 3 bps | -90% | -95% |
| MEXC Limit-Real T1 | 8 bps | -74% | -86% |

---

## Usage

The fill model is a wrapper/post-processor. It does NOT modify harness.py.

```python
from strategies.hf.screening.fill_model import (
    apply_fill_model,
    effective_cost_per_side,
    adjust_for_fill_rate,
    adjust_backtest_result,
)

# Get parameters for a fill mode
params = apply_fill_model('limit_realistic', 'tier1')
# -> {'harness_fee_decimal': 0.0008, 'fill_rate': 0.55, ...}

# Get effective cost
cost = effective_cost_per_side('market', 'tier1')
# -> 6.0 (bps per side)

# Adjust trade count for fills
effective, missed = adjust_for_fill_rate(100, 0.55, adverse_bias=True)
# -> (55, 45)

# Full adjustment of backtest result
adjusted = adjust_backtest_result(
    mode='limit_realistic',
    tier='tier1',
    n_trades=100,
    total_pnl=50.0,
    trade_list=bt_result.trade_list,
)
```

---

## File Location

Module: `strategies/hf/screening/fill_model.py`
JSON report: `reports/hf/fill_model_001.json`

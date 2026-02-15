# HF Baseline — H20 VWAP_DEVIATION v5

**Locked**: 2026-02-15
**Tag**: hf-baseline-v1
**Status**: CONDITIONAL GO (ADR-HF-029)

## Signal

| Parameter | Value |
|-----------|-------|
| Hypothesis | H20 VWAP_DEVIATION |
| Variant | v5 |
| dev_thresh | 2.0 |
| tp_pct | 8 |
| sl_pct | 5 |
| time_limit | 10 |
| Timeframe | 1H |
| Universe | T1 (98 coins) + T2 (216 coins) |

### Signal Logic

Entry is long-only VWAP mean reversion with bounce confirmation:

- Compute rolling VWAP from volume-weighted price. Skip coins without VWAP data.
- Compute ATR-normalised deviation: `(vwap - close) / ATR`. Price must be significantly below VWAP.
- Deviation must exceed `dev_thresh` (2.0 ATR units) -- filters for large dislocations only.
- Bounce confirmation: current `close > prev_close` (price recovering toward VWAP).
- On entry, set fixed TP at `close * 1.08`, SL at `close * 0.95`, time limit 10 bars.

## Execution Model

| Parameter | Value |
|-----------|-------|
| Exchange | MEXC |
| Execution | Market (taker) |
| T1 fee | 5 bps/side |
| T2 fee | 20 bps/side |
| Fill rate | 100% |

## Baseline Results

MEXC Market regime, variant v5 (dev=2.0, tp=8, sl=5):

| Metric | Value |
|--------|-------|
| Profit Factor | 1.250 |
| Exp/Trade | $8.7551 |
| Exp/Week | $142.80 |
| Max DD% | 44.6% |
| Trades | 70 |
| Win Rate | 48.6% |
| Fee Drag | 14.1% |
| Data period | 1H, T1(98)+T2(216), ~4.3 weeks |

### Stress Tests

| Stress | PF | Exp/Week |
|--------|-----|----------|
| P90 (1.5x spread+slip) | 1.155 | $89.94 |
| P95 (2.0x spread+slip) | 1.070 | $41.54 |

## Reproduce

```bash
python -m strategies.hf.screening.run_reality_check
```

Requires `data/candle_cache_1h.json` and `reports/hf/universe_tiering_001.json`.
Output: `reports/hf/reality_check_001.json` + `reports/hf/reality_check_001.md`.

## Risk Factors

1. **MEXC promotional rate risk**: 0% maker fee is promotional (active since Q4 2022). If reverted to 10bps, maker costs increase but taker mode (this baseline) is unaffected since it already includes 10bps exchange fee in the spread+slippage model.
2. **Spread/slippage model uncertainty**: Cost estimates are volume-based models, not live order book measurements. Must validate with paper trading on actual MEXC pairs.
3. **Volume authenticity**: MEXC has faced wash trading questions. If true volumes are 30-50% lower, spread and slippage increase 20-40%.
4. **Regulatory risk**: MEXC is less regulated than Kraken. Capital deployment decision.
5. **Sample size**: 70 trades across ~4.3 weeks of 1H data. Statistically marginal -- survives P95 stress but confidence intervals are wide.

## What NOT to Change

1. `harness.py` -- READ-ONLY (engine fee parity verified via `# Parity: engine line NNN` comments)
2. Do not re-screen hypotheses (25 families / 150 configs exhaustively tested across Sprints 3-5)
3. Do not use Kraken fees (structurally unprofitable at 1H -- PF=0.895 at 31/56 bps)
4. `make check` must stay 66/66 green
5. Do not modify `fill_model.py` cost regimes without re-running full reality check

# HF Part 2 — Executive Summary

**Project**: H20 VWAP_DEVIATION measured validation + multi-exchange portability (10 cycles, 37 ADRs, 2026-01 — 2026-02)

## What Worked — MEXC SPOT
- Maker execution: PF=2.86-3.38, DD≤9.5%, 14/24 combos pass 7/7 STRICT gates
- 19,500 live OB snapshots, 0.00bps slippage delta, breakeven at 5.0x fee multiplier
- Assumptions: 0% maker fee (MEXC promo), bar-structure 100% fill model, $200-$500 sizes, 295-coin universe (excl 21 net-negative)

## What Failed — Bybit SPOT
- 0/24 combos pass with H20 signal, Z-score variant, and 4 alternative signal families
- Real 1m VWAP (37.8M candles, 166 coins) produces 3 triggers vs MEXC ~150+ in same period
- Root cause: Bybit's low intra-hour volatility dispersion — 92% of coins never reach dev_thresh=2.0; bounce filter blocks 82% of rare events above threshold

## Conclusion
Signal edge is MEXC-specific (retail meme-coin microstructure), not universal alpha. Multi-exchange portability disproven.

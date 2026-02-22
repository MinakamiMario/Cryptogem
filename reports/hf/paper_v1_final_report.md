# HF Paper Trader V1 — Final Report

**Run ID**: `v1_553r_20260222`  
**Universe**: `papertrade_universe_v1.json` (17 coins)  
**Period**: 2026-02-21T22:28Z — 553 rounds (~14h)  
**Config**: MEXC SPOT, $5/order, near_ask pricing, 120s TTL

## Summary

| Metric | Value |
|--------|-------|
| Rounds | 553 |
| Fill rate | 55.1% (305/553) |
| Missed | 239 (43.2%) |
| Partial | 9 |
| Errors | 0 |
| Taker incidents | 0 |
| Stuck positions | 0 |
| RT P&L | $-0.8998 |
| Slippage median | -1.15 bps |
| Slippage mean | -0.31 bps |
| Maker-favorable | 75.0% |

## Per-Coin Results

| Coin | N | Filled | Missed | Part | Fill% | Avg Slip | v1 Fill | Verdict |
|------|--:|-------:|-------:|-----:|------:|---------:|--------:|---------|
| KAS/USDT | 31 | 30 | 1 | 0 | 97% | +5.9bp | 88% | KEEP_STRICT |
| ARB/USDT | 32 | 29 | 3 | 0 | 91% | +4.2bp | 100% | KEEP_STRICT |
| SUI/USDT | 33 | 27 | 6 | 0 | 82% | -0.5bp | 100% | KEEP_STRICT |
| XRP/USDT | 33 | 26 | 6 | 1 | 79% | -0.7bp | 100% | KEEP_STRICT |
| GRT/USDT | 33 | 24 | 9 | 0 | 73% | -1.8bp | 100% | KEEP_STRICT |
| HBAR/USDT | 33 | 22 | 11 | 0 | 67% | -0.5bp | 100% | KEEP_BALANCED |
| ADA/USDT | 33 | 21 | 12 | 0 | 64% | -1.8bp | 100% | KEEP_BALANCED |
| FET/USDT | 33 | 19 | 14 | 0 | 58% | -3.1bp | 100% | BORDERLINE |
| XLM/USDT | 33 | 19 | 14 | 0 | 58% | -3.2bp | 100% | BORDERLINE |
| AVAX/USDT | 31 | 15 | 16 | 0 | 48% | -1.7bp | 100% | BORDERLINE |
| FLOKI/USDT | 33 | 14 | 19 | 0 | 42% | +5.0bp | 100% | BORDERLINE |
| SHIB/USDT | 33 | 14 | 17 | 2 | 42% | -4.0bp | 100% | BORDERLINE |
| GALA/USDT | 33 | 13 | 19 | 1 | 39% | -6.6bp | 100% | DROP |
| PEPE/USDT | 33 | 13 | 19 | 1 | 39% | -4.2bp | 100% | DROP |
| TRX/USDT | 33 | 8 | 23 | 2 | 24% | -1.7bp | 100% | DROP |
| SEI/USDT | 31 | 7 | 22 | 2 | 23% | +2.1bp | 94% | DROP |
| ATOM/USDT | 32 | 4 | 28 | 0 | 12% | -6.5bp | 100% | DROP |

## Key Observations

1. **Execution plumbing flawless**: 0 errors, 0 taker, 0 stuck across 553 rounds
2. **Fill rate heterogeneous**: 12-97% per coin; v1 fill test (16 samples) predicted 100% for all — live continuous trading is harder
3. **Slippage 75% maker-favorable**: median -1.15 bps confirms near_ask pricing works
4. **KAS/ARB anomaly**: highest fill (91-97%) but highest adverse slippage (+4-6 bps) — wide OB, easy fill, price moves
5. **SUI/XRP ideal**: high fill (79-82%) AND low slippage (<1 bps)
6. **ATOM/TRX/SEI structurally unfillable**: 12-24% fill — remove from universe

## Universe Cut Recommendations

| Universe | Coins | Projected Fill |
|----------|------:|---------------:|
| v2_strict (fill>=70%) | 5 | 84.0% |
| v2_balanced (fill>=60%) | 7 | 78.5% |

## Artifacts

| File | SHA256 |
|------|--------|
| v1_553r_20260222_state.json | `73da2e49...933f0d` |
| v1_553r_20260222_stdout.log | `d6c96ed3...49d0c` |
| v1_553r_20260222_log_session1.log | `b552beda...98fbb` |
| v1_553r_20260222_log_session2.log | `9b9fef94...649d0` |
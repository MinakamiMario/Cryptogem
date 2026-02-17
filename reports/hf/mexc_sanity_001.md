# MEXC Orderbook Sanity Report — `mexc_orderbook_001.jsonl`

Generated: 2026-02-16 13:38 UTC  |  Records: 18821

## 1. BTC + ETH Reference

| Coin | N | Spread med | Spread P90 | Slip200 med | Slip200 P90 |
|------|---|-----------|-----------|------------|------------|
| BTC | 482 | 0.05 | 0.82 | 0.19 | 0.56 |
| ETH | 482 | 0.15 | 1.26 | 0.25 | 0.76 |

**BTC spread gate**: median < 5 bps, P90 < 10 bps → **PASS**

## 2. Anomaly Rates

- Crossed books: 0/18821 (0.0%) → **PASS** (< 0.1%)
- Extreme spread (> 200 bps): 657/18821 (3.49%)

### Depth shortfall (slippage is None)

| Tier | $200 | $500 | $2000 |
|------|------|------|-------|
| tier1 | 0 (0.0%) | 98 (1.01%) | 1976 (20.46%) |
| tier2 | 1 (0.01%) | 184 (2.01%) | 978 (10.67%) |

## 3. Tier Structure

| Tier | N | Spread med (bps) | Depth med (USD) |
|------|---|------------------|-----------------|
| tier1 | 9658 | 10.37 | 8109.08 |
| tier2 | 9163 | 13.73 | 12665.59 |

- T1 spread < T2 spread → **PASS**
- T1 depth > T2 depth → **FAIL**

## 4. Slippage Monotonicity

| Tier | Slip200 med | Slip500 med | Slip2000 med | Monotone |
|------|-----------|-----------|------------|----------|
| tier1 | 16.69 | 18.92 | 14.68 | NO |
| tier2 | 13.02 | 14.51 | 19.8 | YES |

**All tiers monotone** → **FAIL**

## 5. Coverage

- Unique coins: **39** / 42 expected → **FAIL** (>= 40)
- Unique hours: 3 ([11, 12, 13])
- Duration: 121.9 min (7313 sec)
- Snapshots: 18821 actual / 28521 expected (density=0.6599)
- Gaps > 5 min: 0 total across 0 coins

## 6. Verdict Summary

| Check | Result |
|-------|--------|
| BTC median spread < 5 bps, P90 < 10 bps | **PASS** |
| Crossed rate < 0.1% | **PASS** |
| T1 median spread < T2 median spread | **PASS** |
| T1 median depth > T2 median depth | **FAIL** |
| Slippage monotone per tier | **FAIL** |
| >= 40 of 42 coins present | **FAIL** |

**Overall: ISSUES FOUND**

# MEXC Orderbook Slippage Verification Report

**Date**: 2026-02-16
**Data file**: `data/orderbook_snapshots/mexc_orderbook_001.jsonl`
**Code under test**: `strategies/hf/screening/orderbook_collector.py :: compute_slippage_bps()`
**Total snapshots in file**: 3128

---

## 1. Raw Format Proof

Read 3 snapshots from the JSONL file. Each contains `bids_raw` and `asks_raw` as lists of `[price, amount]` pairs (top-20 levels).

### Snapshot 1: AB/USD (tier1, ts=1771241773)

| Side | Level | Price | Amount | Notional (price * amount) |
|------|-------|-------|--------|---------------------------|
| ask | 0 | 0.002511 | 0.01 | $0.0000 |
| ask | 1 | 0.002528 | 793.01 | $2.0047 |
| ask | 2 | 0.002534 | 13072.91 | $33.1268 |
| bid | 0 | 0.002509 | 438.42 | $1.1000 |
| bid | 1 | 0.002508 | 10923.42 | $27.3959 |
| bid | 2 | 0.002483 | 13774.41 | $34.2019 |

### Snapshot 2: ACH/USD (tier1, ts=1771241774)

| Side | Level | Price | Amount | Notional (price * amount) |
|------|-------|-------|--------|---------------------------|
| ask | 0 | 0.007713 | 170.15 | $1.3124 |
| ask | 1 | 0.007716 | 170.15 | $1.3129 |
| ask | 2 | 0.007719 | 200.38 | $1.5467 |
| bid | 0 | 0.007709 | 200.38 | $1.5447 |
| bid | 1 | 0.007706 | 54651.27 | $421.1427 |
| bid | 2 | 0.007698 | 597197.60 | $4597.2271 |

### Snapshot 3: ADA/USD (tier1, ts=1771241776)

| Side | Level | Price | Amount | Notional (price * amount) |
|------|-------|-------|--------|---------------------------|
| ask | 0 | 0.2816 | 68165.88 | $19195.51 |
| ask | 1 | 0.2817 | 104718.70 | $29499.26 |
| ask | 2 | 0.2818 | 131153.46 | $36959.04 |
| bid | 0 | 0.2815 | 68060.70 | $19159.09 |
| bid | 1 | 0.2814 | 85150.38 | $23961.32 |
| bid | 2 | 0.2813 | 139084.94 | $39124.59 |

**Format confirmed**: Each level is `[price, amount]`. Notional = price * amount (USD), NOT amount alone.

---

## 2. Manual Book Walk -- 3 Coins

### Coin Selection

| # | Selection Criterion | Coin | Tier | ask_depth_usd |
|---|---------------------|------|------|---------------|
| 1 | Highest ask_depth_usd (most liquid) | ADA/USD | tier1 | $1,272,369.10 |
| 2 | First tier1 alphabetically | AB/USD | tier1 | $10,082.62 |
| 3 | First tier2 alphabetically | 0G/USD | tier2 | $17,116.82 |

---

### Coin 1: ADA/USD (ts=1771243355, most liquid)

**Book**: bid1=0.2826, ask1=0.2827, **mid=0.28265**

Ask level 0 alone has $21,804.64 notional -- all three fills ($200, $500, $2000) complete within level 0.

#### Walk for $200

| Level | Price | Qty Available | Level Notional | Fill USD | Fill Qty |
|-------|-------|---------------|----------------|----------|----------|
| 0 | 0.2827 | 77,129.95 | $21,804.64 | $200.00 | 707.4637 |

- total_qty = 707.4637
- avg_price = 200 / 707.4637 = **0.28270000**
- slippage = (0.28270000 - 0.28265) / 0.28265 * 10000 = **1.77 bps**
- Stored: **1.77 bps** | Diff: **0.00 bps** | **PASS**

#### Walk for $500

Same single-level fill at price 0.2827.

- total_qty = 1768.6594, avg_price = 0.28270000
- slippage = **1.77 bps**
- Stored: **1.77 bps** | Diff: **0.00 bps** | **PASS**

#### Walk for $2000

Same single-level fill at price 0.2827.

- total_qty = 7074.6374, avg_price = 0.28270000
- slippage = **1.77 bps**
- Stored: **1.77 bps** | Diff: **0.00 bps** | **PASS**

---

### Coin 2: AB/USD (ts=1771241773, first tier1)

**Book**: bid1=0.002509, ask1=0.002511, **mid=0.002510**

This is a low-priced micro-cap. The book is thin with a very large level 4 ($9,587 notional at 0.002548).

#### Walk for $200

| Level | Price | Qty Available | Level Notional | Fill USD | Fill Qty | Cumul USD |
|-------|-------|---------------|----------------|----------|----------|-----------|
| 0 | 0.002511 | 0.01 | $0.00 | $0.00 | 0.01 | $0.00 |
| 1 | 0.002528 | 793.01 | $2.00 | $2.00 | 793.01 | $2.00 |
| 2 | 0.002534 | 13,072.91 | $33.13 | $33.13 | 13,072.91 | $35.13 |
| 3 | 0.002545 | 41,527.66 | $105.69 | $105.69 | 41,527.66 | $140.82 |
| 4 | 0.002548 | 3,762,565.58 | $9,587.02 | $59.18 | 23,226.29 | $200.00 |

- total_qty = 78,619.88
- avg_price = 200 / 78,619.88 = **0.002544**
- slippage = (0.002544 - 0.002510) / 0.002510 * 10000 = **135.00 bps**
- Stored: **135.00 bps** | Diff: **0.00 bps** | **PASS**

#### Walk for $500

Same levels 0-4, but level 4 fills $359.18 instead of $59.18.

- total_qty = 196,359.29, avg_price = 0.002546
- slippage = **144.83 bps**
- Stored: **144.83 bps** | Diff: **0.00 bps** | **PASS**

#### Walk for $2000

Same levels 0-4, level 4 fills $1,859.18.

- total_qty = 785,056.30, avg_price = 0.002548
- slippage = **149.75 bps**
- Stored: **149.75 bps** | Diff: **0.00 bps** | **PASS**

---

### Coin 3: 0G/USD (ts=1771241789, first tier2)

**Book**: bid1=0.6361, ask1=0.6371, **mid=0.6366**

Ask level 0 has $2,445.40 notional -- all three fills complete within level 0.

#### Walk for $200

| Level | Price | Qty Available | Level Notional | Fill USD | Fill Qty |
|-------|-------|---------------|----------------|----------|----------|
| 0 | 0.6371 | 3,838.33 | $2,445.40 | $200.00 | 313.92 |

- total_qty = 313.92, avg_price = 0.63710000
- slippage = (0.6371 - 0.6366) / 0.6366 * 10000 = **7.85 bps**
- Stored: **7.85 bps** | Diff: **0.00 bps** | **PASS**

#### Walk for $500

Single-level fill. slippage = **7.85 bps**. Stored: **7.85 bps**. Diff: **0.00 bps**. **PASS**

#### Walk for $2000

Single-level fill. slippage = **7.85 bps**. Stored: **7.85 bps**. Diff: **0.00 bps**. **PASS**

---

### Comparison Summary

| Coin | Tier | $200 Stored | $200 Computed | $500 Stored | $500 Computed | $2000 Stored | $2000 Computed | Verdict |
|------|------|-------------|---------------|-------------|---------------|--------------|----------------|---------|
| ADA/USD | T1 | 1.77 | 1.77 | 1.77 | 1.77 | 1.77 | 1.77 | ALL PASS |
| AB/USD | T1 | 135.00 | 135.00 | 144.83 | 144.83 | 149.75 | 149.75 | ALL PASS |
| 0G/USD | T2 | 7.85 | 7.85 | 7.85 | 7.85 | 7.85 | 7.85 | ALL PASS |

**All 9 comparisons: exact match (0.00 bps difference). Threshold: +/-0.5 bps.**

---

## 3. Depth Shortfall Proof

### Case A: slippage_2000_bps = None (insufficient depth)

**Snapshot**: BEAM/USD (tier1, ts=1771241784)

- stored `slippage_2000_bps` = **None**
- stored `slippage_200_bps` = 255.49 (not None -- partial depth)
- stored `slippage_500_bps` = 307.02 (not None -- partial depth)

Sum of asks_raw notional:

```
Level  0: 0.02416 * 1138.79 = $27.51
Level  1: 0.02424 * 165.91  = $4.02
Level  2: 0.02438 * 82.70   = $2.02
Level  3: 0.02450 * 131.50  = $3.22
Level  4: 0.02458 * 107.66  = $2.65
Level  5: 0.02463 * 174.62  = $4.30
Level  6: 0.02480 * 1727.34 = $42.84
Level  7: 0.02481 * 707.97  = $17.56
Level  8: 0.02490 * 5746.33 = $143.08
Level  9: 0.02491 * 2769.91 = $69.00
Level 10: 0.02495 * 108.23  = $2.70
Level 11: 0.02496 * 8612.63 = $214.97
Level 12: 0.02500 * 53.39   = $1.33
Level 13: 0.02532 * 806.12  = $20.41
Level 14: 0.02538 * 52.46   = $1.33
Level 15: 0.02549 * 67.90   = $1.73
Level 16: 0.02552 * 192.88  = $4.92
Level 17: 0.02561 * 48.65   = $1.25
Level 18: 0.02565 * 76.72   = $1.97
Level 19: 0.02568 * 305.79  = $7.85
------------------------------------
TOTAL:                        $574.67
```

**$574.67 < $2000** -- Depth is insufficient. `None` is correct.

Note: $574.67 > $200 and $574.67 > $500, consistent with slippage_200 and slippage_500 being non-None.

Total snapshots with `slippage_2000_bps = None`: **511 / 3128** (16.3%)

### Case B: slippage_200_bps != None (sufficient depth)

**Snapshot**: AB/USD (tier1, ts=1771241773)

- stored `slippage_200_bps` = **135.00** (not None)
- Sum of asks_raw notional: **$10,082.62**
- **$10,082.62 >= $200** -- Depth is sufficient. Non-None value is correct.

**Shortfall logic verified: None iff total_depth < target_notional.**

---

## 4. Synthetic Orderbook Test

### Test Setup

```python
asks = [[100.0, 1.0], [101.0, 2.0], [102.0, 3.0]]
#        notional: $100    $202        $306
mid = 99.5
target = $200
```

### Manual Calculation

**Level 0**: price=100.0, qty=1.0, notional=$100.00
- Fill all: fill_usd=$100, fill_qty=1.0, remaining=$100

**Level 1**: price=101.0, qty=2.0, notional=$202.00
- Partial fill: need $100 more at price 101.0
- fill_qty = $100 / 101.0 = 0.990099
- remaining = $0

**Totals**:
- total_qty = 1.0 + 0.990099 = 1.990099
- avg_price = $200 / 1.990099 = 100.497512
- slippage = (100.497512 - 99.5) / 99.5 * 10000 = **100.25 bps**

### Function Result

```python
compute_slippage_bps([[100.0, 1.0], [101.0, 2.0], [102.0, 3.0]], 200.0, 99.5, "buy")
# Returns: 100.25
```

**Manual: 100.25 bps. Function: 100.25 bps. EXACT MATCH.**

### Edge Case Tests

| Test | Input | Expected | Actual | Verdict |
|------|-------|----------|--------|---------|
| Insufficient depth | asks=[[100,0.5]], notional=200, mid=99.5 | None | None | PASS |
| Zero notional | asks=[[100,1]], notional=0, mid=99.5 | 0.0 | 0.0 | PASS |
| Exact one-level fill | asks=[[100,10]], notional=1000, mid=99.95 | 5.00 | 5.0 | PASS |

---

## 5. Algorithm Summary

The `compute_slippage_bps()` function in `orderbook_collector.py`:

1. **Depth check**: Walks all levels summing `min(remaining, price*qty)`. Returns `None` if `remaining > 0` after exhausting all levels.
2. **Fill walk**: For each level, computes `fill_usd = min(remaining, price*qty)` and accumulates `total_qty += fill_usd / price`.
3. **Average price**: `avg_price = notional_usd / total_qty`.
4. **Slippage**: `(avg_price - mid) / mid * 10000` for buy side, rounded to 2 decimal places.

Key correctness properties verified:
- **Notional = price * qty** (not qty alone) -- amounts are in base currency, not USD
- **Partial fills** handled correctly (fractional qty at the final level)
- **None returned** when book depth < target notional
- **Mid price** computed as `(bid1 + ask1) / 2` from raw level-1 prices
- **Rounding** to 2 decimal places on the final bps result

---

## 6. Verdict

| Check | Result |
|-------|--------|
| Raw format proof (3 snapshots) | PASS -- `[[price, amount], ...]`, notional = price * amount |
| Manual walk Coin 1 (ADA/USD, most liquid) | PASS -- 3/3 sizes match exactly (0.00 bps diff) |
| Manual walk Coin 2 (AB/USD, first T1) | PASS -- 3/3 sizes match exactly (0.00 bps diff) |
| Manual walk Coin 3 (0G/USD, first T2) | PASS -- 3/3 sizes match exactly (0.00 bps diff) |
| Depth shortfall -- None case | PASS -- $574.67 < $2000 |
| Depth shortfall -- non-None case | PASS -- $10,082.62 >= $200 |
| Synthetic orderbook test | PASS -- 100.25 bps manual = 100.25 bps function |
| Edge cases (insufficient, zero, exact) | PASS -- all 3 correct |

**OVERALL: ALL CHECKS PASS. The `compute_slippage_bps()` implementation is correct.**

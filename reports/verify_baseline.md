# Verify Baseline -- C1_TPSL_RSI45 on Two Universes

Generated: 2026-02-15 08:12:15
JSON: `/Users/oussama/Cryptogem/reports/verify_baseline.json`

## Config
```json
{
  "exit_type": "tp_sl",
  "max_pos": 1,
  "rsi_max": 45,
  "sl_pct": 15,
  "time_max_bars": 15,
  "tp_pct": 15,
  "vol_confirm": true,
  "vol_spike_mult": 3.0
}
```

## Settings
- KRAKEN_FEE: 0.0026
- INITIAL_CAPITAL: $2000
- START_BAR: 50

## Cache Metadata

| Property | LIVE_CURRENT | RESEARCH_ALL |
|----------|-------------|--------------|
| File | `candle_cache_532.json` | `candle_cache_research_all.json` |
| MD5 | `3b1dba2eeb4d95ac...` | `a68399c0da2ed828...` |
| Size | 48,777,273 bytes | 152,419,003 bytes |
| Coins | 523 | 2086 |
| Max Bars | 721 | 721 |
| Min Bars | 54 | 51 |

## Baseline Results

| Metric | LIVE_CURRENT | RESEARCH_ALL |
|--------|-------------|--------------|
| Trades | 30 | 45 |
| P&L | $3,745.50 | $528.52 |
| Win Rate | 70.0% | 51.1% |
| Profit Factor | 3.31 | 1.14 |
| Max DD | 27.9% | 40.8% |
| Final Equity | $5,745.50 | $2,528.52 |
| Top1 Coin | MF/USD (16.9%) | MF/USD (12.5%) |
| Top3 Share | 43.0% | 27.3% |
| NoTop P&L | $2,837.97 | $-23.80 |
| Unique Coins | 28 | 44 |

## Robustness Tests

| Test | LIVE_CURRENT | RESEARCH_ALL |
|------|-------------|--------------|
| WF (5-fold) | 4/5 (maxDD 23.5%) | 3/5 (maxDD 37.9%) |
| Friction 2x+20bps | $2369.98 (GO) | $-333.86 (NO-GO) |
| MC 1000 shuffles | ruin=0.0% win=100.0% | ruin=37.5% win=100.0% |
| Jitter (50 var) | 100.0% positive | 42.0% positive |
| Universe shift | 4/4 positive | 2/4 positive |

## Walk-Forward Fold Detail

### LIVE_CURRENT

| Fold | Test Bars | Trades | P&L | WR | DD | Pass |
|------|-----------|--------|-----|-----|-----|------|
| F1 | 50-184 | 6 | $-108.22 | 50.0% | 23.5% | FAIL |
| F2 | 184-318 | 5 | $664.43 | 100.0% | 10.3% | PASS |
| F3 | 318-452 | 5 | $201.38 | 40.0% | 7.7% | PASS |
| F4 | 452-586 | 6 | $328.96 | 33.3% | 10.5% | PASS |
| F5 | 586-721 | 8 | $949.37 | 87.5% | 18.1% | PASS |

### RESEARCH_ALL

| Fold | Test Bars | Trades | P&L | WR | DD | Pass |
|------|-----------|--------|-----|-----|-----|------|
| F1 | 50-184 | 9 | $-375.94 | 22.2% | 33.5% | FAIL |
| F2 | 184-318 | 9 | $459.18 | 66.7% | 14.6% | PASS |
| F3 | 318-452 | 9 | $10.08 | 55.6% | 28.4% | PASS |
| F4 | 452-586 | 10 | $-114.04 | 40.0% | 37.9% | FAIL |
| F5 | 586-721 | 7 | $147.23 | 71.4% | 18.1% | PASS |

## Exit Class Breakdown

### LIVE_CURRENT

| Class | Reason | Count | P&L | Wins |
|-------|--------|-------|-----|------|
| A | PROFIT TARGET | 8 | $3850.23 | 8 |
| B | FIXED STOP | 2 | $-1003.14 | 0 |
| B | TIME MAX | 20 | $898.40 | 13 |

### RESEARCH_ALL

| Class | Reason | Count | P&L | Wins |
|-------|--------|-------|-----|------|
| A | PROFIT TARGET | 12 | $3496.52 | 12 |
| B | FIXED STOP | 9 | $-3287.90 | 0 |
| B | TIME MAX | 24 | $319.91 | 11 |


## Timing

| Phase | LIVE_CURRENT | RESEARCH_ALL |
|-------|-------------|--------------|
| precompute_s | 30.6s | 85.9s |
| backtest_s | 0.4s | 9.1s |
| wf_s | 1.6s | 13.2s |
| friction_s | 4.5s | 30.7s |
| mc_s | 0.3s | 2.4s |
| jitter_s | 15.6s | 126.5s |
| universe_s | 14.1s | 110.4s |
| total_s | 67.6s | 379.7s |
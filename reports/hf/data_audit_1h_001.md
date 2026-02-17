# HF Data Audit — 1H Candles

**Date**: 2026-02-15 16:30
**Timeframe**: 1h
**Data file**: `candle_cache_1h.json`

## Summary

| Metric | Value |
|--------|-------|
| Total symbols | 1903 |
| Median bars | 500 |
| Min bars | 51 |
| Max bars | 721 |
| Full coverage % | 96.8% |
| OHLCV violations | 0 |
| Zero-volume symbols | 202 |
| Volume anomaly symbols | 458 |

## Flags (1430 total)

### Bar Count Deviation (644)

- `0G/USD`: {"bars": 721, "median": 500, "deviation_pct": 44.2}
- `1INCH/USD`: {"bars": 721, "median": 500, "deviation_pct": 44.2}
- `2Z/USD`: {"bars": 721, "median": 500, "deviation_pct": 44.2}
- `42/USD`: {"bars": 169, "median": 500, "deviation_pct": 66.2}
- `A/USD`: {"bars": 721, "median": 500, "deviation_pct": 44.2}
- `AAVE/USD`: {"bars": 721, "median": 500, "deviation_pct": 44.2}
- `AB/USD`: {"bars": 721, "median": 500, "deviation_pct": 44.2}
- `ACA/USD`: {"bars": 721, "median": 500, "deviation_pct": 44.2}
- `ACH/USD`: {"bars": 721, "median": 500, "deviation_pct": 44.2}
- `ACT/USD`: {"bars": 721, "median": 500, "deviation_pct": 44.2}
- ... and 634 more

### Consecutive Zero Volume (126)

- `ACX/USD`: {"max_consecutive_bars": 40, "starts_at_index": 83, "possible_delisting": false}
- `AGIALPHA/USD`: {"max_consecutive_bars": 43, "starts_at_index": 284, "possible_delisting": false}
- `AIN/USD`: {"max_consecutive_bars": 31, "starts_at_index": 26, "possible_delisting": false}
- `AIO/USD`: {"max_consecutive_bars": 24, "starts_at_index": 689, "possible_delisting": false}
- `ANIME/USD`: {"max_consecutive_bars": 24, "starts_at_index": 675, "possible_delisting": false}
- `ANLOG/USD`: {"max_consecutive_bars": 205, "starts_at_index": 316, "possible_delisting": true}
- `APR/USD`: {"max_consecutive_bars": 39, "starts_at_index": 661, "possible_delisting": false}
- `ART/USD`: {"max_consecutive_bars": 197, "starts_at_index": 441, "possible_delisting": true}
- `AUDX/USD`: {"max_consecutive_bars": 32, "starts_at_index": 457, "possible_delisting": false}
- `AVAAI/USD`: {"max_consecutive_bars": 40, "starts_at_index": 194, "possible_delisting": false}
- ... and 116 more

### Extreme Volume Spike (397)

- `0G/USD`: {"spike_count": 1, "vol_median": 9707.65, "threshold_mult": 100.0, "examples": [{"index": 178, "volume": 1009674.15471, "median": 9707.65, "multiple": 104.0}]}
- `1INCH/USD`: {"spike_count": 3, "vol_median": 6891.97, "threshold_mult": 100.0, "examples": [{"index": 262, "volume": 841410.66148502, "median": 6891.97, "multiple": 122.1}, {"index": 263, "volume": 1065763.68407026, "median": 6891.97, "multiple": 154.6}, {"index": 340, "volume": 1035344.39452269, "median": 6891.97, "multiple": 150.2}]}
- `2Z/USD`: {"spike_count": 3, "vol_median": 6021.66, "threshold_mult": 100.0, "examples": [{"index": 210, "volume": 646118.44066, "median": 6021.66, "multiple": 107.3}, {"index": 236, "volume": 1260687.53615, "median": 6021.66, "multiple": 209.4}, {"index": 607, "volume": 648144.26194, "median": 6021.66, "multiple": 107.6}]}
- `A/USD`: {"spike_count": 2, "vol_median": 6954.94, "threshold_mult": 100.0, "examples": [{"index": 10, "volume": 1286918.1626, "median": 6954.94, "multiple": 185.0}, {"index": 313, "volume": 803325.26545, "median": 6954.94, "multiple": 115.5}]}
- `ABOND/USD`: {"spike_count": 1, "vol_median": 27624.88, "threshold_mult": 100.0, "examples": [{"index": 338, "volume": 4154202.42, "median": 27624.88, "multiple": 150.4}]}
- `ACA/USD`: {"spike_count": 1, "vol_median": 29341.86, "threshold_mult": 100.0, "examples": [{"index": 676, "volume": 4792255.69770795, "median": 29341.86, "multiple": 163.3}]}
- `ACT/USD`: {"spike_count": 6, "vol_median": 2463.11, "threshold_mult": 100.0, "examples": [{"index": 58, "volume": 289272.97263, "median": 2463.11, "multiple": 117.4}, {"index": 75, "volume": 268818.74466, "median": 2463.11, "multiple": 109.1}, {"index": 385, "volume": 641715.19908, "median": 2463.11, "multiple": 260.5}]}
- `ADI/USD`: {"spike_count": 1, "vol_median": 2387.53, "threshold_mult": 100.0, "examples": [{"index": 341, "volume": 474585.80907, "median": 2387.53, "multiple": 198.8}]}
- `ADX/USD`: {"spike_count": 2, "vol_median": 132.65, "threshold_mult": 100.0, "examples": [{"index": 364, "volume": 34775.71892847, "median": 132.65, "multiple": 262.2}, {"index": 450, "volume": 41273.06339734, "median": 132.65, "multiple": 311.1}]}
- `AI3/USD`: {"spike_count": 1, "vol_median": 1627.95, "threshold_mult": 100.0, "examples": [{"index": 158, "volume": 330158.90556, "median": 1627.95, "multiple": 202.8}]}
- ... and 387 more

### High Zero Volume Pct (202)

- `ABOND/USD`: {"zero_vol_bars": 302, "total_bars": 500, "zero_vol_pct": 60.4}
- `ACX/USD`: {"zero_vol_bars": 518, "total_bars": 721, "zero_vol_pct": 71.8}
- `ADX/USD`: {"zero_vol_bars": 546, "total_bars": 721, "zero_vol_pct": 75.7}
- `AGIALPHA/USD`: {"zero_vol_bars": 367, "total_bars": 500, "zero_vol_pct": 73.4}
- `AIN/USD`: {"zero_vol_bars": 475, "total_bars": 721, "zero_vol_pct": 65.9}
- `AIO/USD`: {"zero_vol_bars": 486, "total_bars": 721, "zero_vol_pct": 67.4}
- `AIR/USD`: {"zero_vol_bars": 417, "total_bars": 721, "zero_vol_pct": 57.8}
- `ALMANAK/USD`: {"zero_vol_bars": 389, "total_bars": 721, "zero_vol_pct": 54.0}
- `ALT/USD`: {"zero_vol_bars": 476, "total_bars": 721, "zero_vol_pct": 66.0}
- `ANLOG/USD`: {"zero_vol_bars": 691, "total_bars": 721, "zero_vol_pct": 95.8}
- ... and 192 more

### Low Bar Count (61)

- `42/USD`: {"bars": 169, "threshold": 500}
- `AARK/USD`: {"bars": 484, "threshold": 500}
- `AKI/USD`: {"bars": 433, "threshold": 500}
- `ALEO/USD`: {"bars": 408, "threshold": 500}
- `ANOME/USD`: {"bars": 411, "threshold": 500}
- `AT/USD`: {"bars": 241, "threshold": 500}
- `AZTEC/USD`: {"bars": 79, "threshold": 500}
- `BEAT/USD`: {"bars": 51, "threshold": 500}
- `BELIEVE/USD`: {"bars": 311, "threshold": 500}
- `BGB/USD`: {"bars": 384, "threshold": 500}
- ... and 51 more

---
*Generated by `hf_data_audit_mtf.py` at 2026-02-15 16:30*
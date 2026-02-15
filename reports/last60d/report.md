# Last 60 Days Out-of-Sample Report
Generated: 2026-02-14 21:19 CET
Dataset: `candle_cache_last60d.json` (hash: `11105e429a0c`)
Seed: 42

## Summary

| Config | Tr | P&L | WR | PF | DD | WF | Fric 2x+20bps | MC ruin | Jitter | Top1% | Verdict |
|--------|-----|------|-----|-----|-----|-----|---------------|---------|--------|-------|---------|
| C1_TPSL_RSI45 | 15 | $2100 | 66.7% | 7.26 | 10.5% | 5/5 | $1579 | 0.0% | 100.0% | 25% | 🟢 GO |

## C1_TPSL_RSI45

**Baseline**: 15tr, $2100.47, WR 66.7%, PF 7.26, DD 10.5%

**Fees × Slippage Ladder**:
| Scenario | P&L | WR | DD | OK |
|----------|------|-----|-----|-----|
| 1.0x_fee+0bps | $2100 | 66.7% | 10.5% | ✅ |
| 1.0x_fee+10bps | $1982 | 66.7% | 10.5% | ✅ |
| 1.0x_fee+20bps | $1866 | 66.7% | 10.5% | ✅ |
| 1.0x_fee+35bps | $1698 | 66.7% | 10.5% | ✅ |
| 2.0x_fee+0bps | $1798 | 66.7% | 10.5% | ✅ |
| 2.0x_fee+10bps | $1687 | 66.7% | 10.5% | ✅ |
| 2.0x_fee+20bps | $1579 | 66.7% | 10.6% | ✅ |
| 2.0x_fee+35bps | $1423 | 66.7% | 10.9% | ✅ |
| 3.0x_fee+0bps | $1516 | 66.7% | 10.7% | ✅ |
| 3.0x_fee+10bps | $1413 | 66.7% | 10.9% | ✅ |
| 3.0x_fee+20bps | $1313 | 53.3% | 11.1% | ✅ |
| 3.0x_fee+35bps | $1168 | 53.3% | 11.6% | ✅ |
| 2x_fee+1candle_gap | $1274 | 53.3% | 11.2% | ✅ |

**Monte Carlo**: win% 100.0%, p95DD 11.1%, ruin 0.0%, median equity $4100

**Param Jitter**: 100.0% positief, worst $1339, median $1587

**Coin Concentratie**: top1=MF/USD 24.6%, top3 65.7%, noTop $1502

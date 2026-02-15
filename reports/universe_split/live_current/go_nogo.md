# GO/NO-GO Rapport
Datum: 2026-02-15 01:06:08
Dataset: `candle_cache_532.json` (hash: `3b1dba2eeb4d`)
Seed: 42

## GO Thresholds
```
wf_min_pass: 4
wf_soft_pass: 3
wf_max_dd: 40.0
friction_go: 2x_fee+20bps
mc_p95_dd_max: 50.0
mc_ruin_max: 5.0
jitter_min_positive_pct: 70.0
univ_min_subsets_positive: 2
univ_top1_share_max: 0.5
univ_top3_share_max: 0.8
```

## Resultaten

| Config | Tr | P&L | WR | DD | WF | Fric 2x+20bps | MC ruin% | Jitter pos% | Univ | Top1% | Verdict |
|--------|-----|------|-----|-----|-----|---------------|----------|-------------|------|-------|---------|
| C1_TPSL_RSI45 | 30 | $3745.5 | 70.0% | 27.9% | 4/5 | $2369.98 | 0.0% | 98.0% | 4/4 | 17% | 🟢 GO |

## GO Configs (aanbeveling)
### C1_TPSL_RSI45: tp_sl RSI45 (V3 champion)
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
- Baseline: 30tr, $3745.5, WR 70.0%, DD 27.9%, PF 3.31
- Purged WF: 4/5 (embargo=2)
- MC: win%=100.0%, p95DD=31.5%, ruin=0.0%
- Jitter: 98.0% positief, worst=$-3.28, median=$1530.29
- Concentratie: top1=MF/USD 16.9%, notop=$2837.97

## Kill-Switch Thresholds (micro-live)
```
max_dd_pct: 30.0
max_consecutive_losses: 6
max_loss_streak_usd: -400
min_trades_before_eval: 10
wr_floor: 40.0
```

Als een van deze drempels wordt bereikt tijdens micro-live: stop trading onmiddellijk, evalueer.
# GO/NO-GO Rapport
Datum: 2026-02-14 23:56:02
Dataset: `candle_cache_unfiltered.json` (hash: `0bd301f2488b`)
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
| C1_TPSL_RSI45 | 19 | $711.94 | 57.9% | 23.4% | 4/5 | $276.33 | 0.0% | 96.0% | 4/4 | 18% | 🟢 GO |

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
- Baseline: 19tr, $711.94, WR 57.9%, DD 23.4%, PF 1.57
- Purged WF: 4/5 (embargo=2)
- MC: win%=100.0%, p95DD=38.5%, ruin=0.0%
- Jitter: 96.0% positief, worst=$-94.2, median=$489.08
- Concentratie: top1=B3/USD 17.5%, notop=$369.73

## Kill-Switch Thresholds (micro-live)
```
max_dd_pct: 30.0
max_consecutive_losses: 6
max_loss_streak_usd: -400
min_trades_before_eval: 10
wr_floor: 40.0
```

Als een van deze drempels wordt bereikt tijdens micro-live: stop trading onmiddellijk, evalueer.
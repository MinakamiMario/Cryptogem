# GO/NO-GO Rapport
Datum: 2026-02-15 01:08:37
Dataset: `candle_cache_tradeable.json` (hash: `1e947af64862`)
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
| C1_TPSL_RSI45 | 27 | $1930.37 | 66.7% | 29.3% | 3/5 | $1067.69 | 1.0% | 100.0% | 2/4 | 17% | 🟡 SOFT-GO |

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
- Baseline: 27tr, $1930.37, WR 66.7%, DD 29.3%, PF 1.83
- Purged WF: 3/5 (embargo=2)
- MC: win%=100.0%, p95DD=43.7%, ruin=1.0%
- Jitter: 100.0% positief, worst=$449.96, median=$1197.86
- Concentratie: top1=MF/USD 17.0%, notop=$1205.42

## Kill-Switch Thresholds (micro-live)
```
max_dd_pct: 30.0
max_consecutive_losses: 6
max_loss_streak_usd: -400
min_trades_before_eval: 10
wr_floor: 40.0
```

Als een van deze drempels wordt bereikt tijdens micro-live: stop trading onmiddellijk, evalueer.
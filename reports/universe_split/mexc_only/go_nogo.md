# GO/NO-GO Rapport
Datum: 2026-02-15 01:09:46
Dataset: `temp_mexc_only.json` (hash: `47bf8fdfdbb1`)
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
| C1_TPSL_RSI45 | 30 | $1566.22 | 53.3% | 28.4% | 4/5 | $706.15 | 0.5% | 58.0% | 3/4 | 11% | 🔴 NO-GO |

## GEEN GO configs gevonden

## NO-GO Configs
- **C1_TPSL_RSI45**: Jitter 58.0% < 70.0%

## Kill-Switch Thresholds (micro-live)
```
max_dd_pct: 30.0
max_consecutive_losses: 6
max_loss_streak_usd: -400
min_trades_before_eval: 10
wr_floor: 40.0
```

Als een van deze drempels wordt bereikt tijdens micro-live: stop trading onmiddellijk, evalueer.